"""Render a single fixed-type ZBS sales welcome poster using local PSD masters."""
import argparse
import copy
import json
import math
import os
import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw, ImageFont
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer
from psd_tools.constants import Compression, Resource, Tag
from psd_tools.psd import engine_data as E


def load_fields(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    keys = ("name_cn", "name_en", "department", "movie_cn", "movie_en",
            "hobby_cn", "hobby_en", "motto_cn", "motto_en")
    for key in keys:
        value = data.get(key)
        if not isinstance(value, str) or value.strip() in ("", "-", "—", "--"):
            raise ValueError(f"缺少海报字段 {key}")
        data[key] = value.strip().upper()
    if data["department"] != "销售线":
        raise ValueError("遇到新部门，请先确认中英文部门和岗位映射")
    if len(data["name_en"].split()) < 2:
        raise ValueError("姓名栏需要英文名和已确认的姓氏拼写")
    return data


def wrap(text, font, width, chinese):
    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            continue
        tokens = list(paragraph) if chinese else paragraph.split()
        current = ""
        for token in tokens:
            sep = "" if chinese or not current else " "
            candidate = current + sep + token
            if current and font.getlength(candidate) > width:
                if chinese and token in "，。！？；：、）》”’":
                    lines.append(current + token)
                    current = ""
                else:
                    lines.append(current)
                    current = token
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def fit(text, chinese, size, width, height, font_dir):
    for pt in range(size, 17, -1):
        font = ImageFont.truetype(str(font_dir / ("msyhbd.ttc" if chinese else "bahnschrift.ttf")), pt)
        if not chinese:
            font.set_variation_by_name("Bold")
        lines = wrap(text, font, width, chinese)
        leading = round(pt * (1.22 if chinese else 1.1))
        boxes = [font.getbbox(line, anchor="ls") for line in lines]
        left = min(b[0] for b in boxes)
        right = max(b[2] for b in boxes)
        top = min(b[1] + i * leading for i, b in enumerate(boxes))
        bottom = max(b[3] + i * leading for i, b in enumerate(boxes))
        if right - left <= width and bottom - top <= height:
            canvas = Image.new("RGBA", (right-left+6, bottom-top+6))
            draw = ImageDraw.Draw(canvas)
            for i, line in enumerate(lines):
                draw.text((3-left, 3-top+i*leading), line, font=font, fill="white", anchor="ls")
            box = canvas.getchannel("A").getbbox()
            if not box:
                break
            return lines, pt, leading, canvas.crop(box), (3-left-box[0], 3-top-box[1])
    raise ValueError("原文按可读字号无法完整放入栏目，请确认是否精简")


def type_data(prototype, lines, pt, leading, anchor, image, chinese, index):
    block = copy.deepcopy(prototype.tagged_blocks[Tag.TYPE_TOOL_OBJECT_SETTING])
    ty = block.data
    text = "\r".join(lines)
    ty.text_data[b"Txt "].value = text
    engine = ty.text_data[b"EngineData"].value
    ed = engine["EngineDict"]
    ed["Editor"]["Text"].value = text + "\r"
    for key in ("ResourceDict", "DocumentResources"):
        engine[key]["FontSet"][0]["Name"].value = "MicrosoftYaHei-Bold" if chinese else "Bahnschrift-Bold"
    style = copy.deepcopy(ed["StyleRun"]["RunArray"][0])
    settings = style["StyleSheet"]["StyleSheetData"]
    settings["FontSize"] = E.Float(pt)
    settings["Leading"] = E.Float(leading)
    settings["Tracking"] = E.Integer(0)
    settings["FontCaps"] = E.Integer(0)
    settings["AutoLeading"] = E.Bool(False)
    ed["StyleRun"]["RunArray"] = E.List([style])
    length = lambda s: len(s.encode("utf-16-be")) // 2
    ed["StyleRun"]["RunLengthArray"] = E.List([E.Integer(length(text)+1)])
    paragraph = copy.deepcopy(ed["ParagraphRun"]["RunArray"][0])
    paragraph["ParagraphSheet"]["Properties"]["Justification"] = E.Integer(0)
    ed["ParagraphRun"]["RunArray"] = E.List([copy.deepcopy(paragraph) for _ in lines])
    ed["ParagraphRun"]["RunLengthArray"] = E.List([E.Integer(length(s)+1) for s in lines])
    x, y, ax, ay = anchor
    ty.transform = (1., 0., 0., 1., float(x+ax), float(y+ay))
    ty.text_data[b"TextIndex"].value = index
    for key in (b"bounds", b"boundingBox"):
        for field, val in zip((b"Left", b"Top ", b"Rght", b"Btom"), (-ax,-ay,image.width-ax,image.height-ay)):
            ty.text_data[key][field].value = float(val)
    return block


def text_boxes(v):
    # Coordinates and maxima are measured on the 1700 px, 72 ppi sales sample.
    return [
        ("栏目 电影 EN","FAVORITE\nMOVIE",74,240,43,250,89),
        ("栏目 电影 CN","最爱的电影",367,239,35,179,40),
        ("栏目 爱好 EN","HOBBY",74,591,43,200,35),
        ("栏目 爱好 CN","爱好",472,591,35,75,40),
        ("栏目 座右铭 EN","MOTTO",74,1032,43,200,35),
        ("栏目 座右铭 CN","座右铭",436,1031,35,110,40),
        ("电影 EN",v["movie_en"],73,356,43,510,63),
        ("电影 CN",v["movie_cn"],73,428,35,510,75),
        ("爱好 EN",v["hobby_en"],74,676,43,510,74),
        ("爱好 CN",v["hobby_cn"],73,760,35,510,174),
        ("座右铭 EN",v["motto_en"],73,1112,39,510,133),
        ("座右铭 CN",v["motto_cn"],73,1270,36,510,113),
        ("姓名 EN",v["name_en"],1169,1234,53,452,48),
        ("部门 EN","SALES DPT.",1169,1303,51,450,45),
        ("岗位 EN","TELESALES",1169,1371,51,445,45),
        ("姓名 CN",v["name_cn"],1171,1449,36,430,40),
        ("部门和岗位 CN","销售线     初级销售代表",1171,1500,35,460,40),
    ]


def place_layer(doc, composite, image, label, x, y, index):
    record, channels = PixelLayer._build_layer_record_and_channels(image, "Poster", x, y, Compression.RLE)
    layer = PixelLayer(doc, record, channels)
    doc.append(layer)
    layer.name = label
    layer.tagged_blocks.set_data(Tag.LAYER_ID, 2000+index)
    composite.alpha_composite(image, (x,y))
    return layer


def render(args):
    v = load_fields(args.fields)
    doc = PSDImage.open(args.blank)
    sample = PSDImage.open(args.sales)
    if doc.size != (1700,1700) or sample.size != doc.size or len(sample) < 7:
        raise ValueError("需要已确认的 1700 × 1700 原版 PSD")
    if sample[3].kind != "type" or sample[3].text.upper().splitlines()[-2:] != ["SALES DPT.","TELESALES"]:
        raise ValueError("销售样稿版式与已确认映射不符")
    if any(layer.kind != "type" for layer in (sample[5], sample[6])):
        raise ValueError("销售样稿缺少文字样式层")
    portrait = Image.open(args.portrait).convert("RGBA")
    alpha = portrait.getchannel("A")
    if alpha.getextrema() != (0,255):
        raise ValueError("需要已检查的透明人像，主体内部应为实色")
    bbox = alpha.getbbox()
    portrait = portrait.crop(bbox)
    composite = Image.open(args.blank).convert("RGBA")
    expected = {}
    for index, (label, value, x, y, size, w, h) in enumerate(text_boxes(v)):
        chinese = label.endswith(" CN")
        lines, pt, leading, image, (ax,ay) = fit(value, chinese, size, w, h, args.font_dir)
        layer = place_layer(doc, composite, image, label, x, y, index)
        layer.tagged_blocks[Tag.TYPE_TOOL_OBJECT_SETTING] = type_data(
            sample[6 if chinese else 5], lines, pt, leading, (x,y,ax,ay), image, chinese, 100+index)
        expected[label] = "\r".join(lines)
    scale = min(565/portrait.width, 796/portrait.height)
    portrait = portrait.resize(tuple(max(1,round(z*scale)) for z in portrait.size), Image.Resampling.LANCZOS)
    place_layer(doc, composite, portrait, "人物｜置顶", round(1388-portrait.width/2),1187-portrait.height,len(expected))
    doc._update_record()
    rgb = composite.convert("RGB")
    doc._record.image_data.set_data([b.tobytes() for b in rgb.split()], doc._record.header)
    thumb = doc.image_resources.get_data(Resource.THUMBNAIL_RESOURCE)
    if thumb:
        buf = BytesIO()
        rgb.resize((thumb.width,thumb.height), Image.Resampling.LANCZOS).save(buf, "JPEG",quality=88)
        thumb.data = buf.getvalue()
    extra = doc._record.layer_and_mask_information.tagged_blocks
    if extra and Tag.TEXT_ENGINE_DATA in extra:
        del extra[Tag.TEXT_ENGINE_DATA]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as temp:
        work = Path(temp)
        psd, png = work/"欢迎海报.psd", work/"欢迎海报.png"
        with psd.open("wb") as f:
            doc._record.write(f)
        rgb.save(png,dpi=(72,72))
        saved = PSDImage.open(psd)
        layers = {l.name:l for l in saved.descendants()}
        if any(layers[n].kind != "type" or layers[n].text != s for n,s in expected.items()):
            raise ValueError("文字层读回不一致")
        if saved[-1].name != "人物｜置顶" or ImageChops.difference(Image.open(psd).convert("RGB"),Image.open(png).convert("RGB")).getbbox():
            raise ValueError("合成预览核对失败")
        # Publish the verified pair as one new directory on the same filesystem.
        delivery = work/"delivery"
        delivery.mkdir()
        psd.rename(delivery/psd.name)
        png.rename(delivery/png.name)
        if args.output.exists():
            raise FileExistsError("输出目录已存在，请选择新的版本目录")
        delivery.rename(args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fields", required=True, type=Path)
    parser.add_argument("--portrait", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory for the verified pair")
    desktop = Path.home()/"Desktop"
    parser.add_argument("--blank", type=Path, default=desktop/"【交付】新人欢迎-空白.psd")
    parser.add_argument("--sales", type=Path, default=desktop/"【交付】新人欢迎-销售.psd")
    parser.add_argument("--font-dir", type=Path, default=Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts")
    render(parser.parse_args())
