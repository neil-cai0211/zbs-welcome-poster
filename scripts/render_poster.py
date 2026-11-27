"""Render fixed-type sales welcome posters using local PSD masters."""
import argparse
import copy
import json
import math
import os
import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
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


def validate_box(box, size):
    if not isinstance(box, list) or len(box) != 4 or not all(type(n) is int for n in box):
        raise ValueError("每个框需要四个整数坐标 [左, 上, 右, 下]")
    x, y, right, bottom = box
    if not (0 <= x < right <= size[0] and 0 <= y < bottom <= size[1]):
        raise ValueError("版式框超出模板画布")
    return x, y, right, bottom


def read_layout(config, size, fields):
    rows = text_boxes(fields)
    if config.get("canvas") != list(size):
        raise ValueError("版式配置的画布尺寸与证件照 PSD 不一致")
    bounds = validate_box(config.get("photo_box"), size)
    mode = config.get("photo_mode")
    if mode not in ("cutout", "frame"):
        raise ValueError("photo_mode 需要选 cutout 或 frame")
    text = config.get("text_boxes")
    if text == "sales" and size == (1700, 1700):
        return rows, bounds, mode
    if not isinstance(text, dict) or set(text) != {r[0] for r in rows}:
        raise ValueError("请提供模板全部文字框，或明确指定已核对的 sales 文字版式")
    layout = []
    for label, value, _, _, pt, _, _ in rows:
        x, y, right, bottom = validate_box(text[label], size)
        layout.append((label, value, x, y, pt, right-x, bottom-y))
    return layout, bounds, mode


def fit_photo(path, bounds, mode):
    left, top, right, bottom = bounds
    width, height = right-left, bottom-top
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    if mode == "frame":
        if image.getchannel("A").getextrema() != (255, 255):
            raise ValueError("矩形照片框需要保留背景的完整证件人像")
        return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS), left, top
    alpha = image.getchannel("A")
    if alpha.getextrema() != (0, 255):
        raise ValueError("需要已检查的透明人像，主体内部应为实色")
    image = image.crop(alpha.getbbox())
    scale = min(width/image.width, height/image.height)
    image = image.resize(tuple(max(1, round(s*scale)) for s in image.size), Image.Resampling.LANCZOS)
    return image, left + round((width-image.width)/2), bottom-image.height


def render_variant(fields, sample, template, portrait, config, font_dir, output, stem):
    doc = PSDImage.open(template)
    if doc._record.header.depth != 8 or doc.pil_mode != "RGB":
        raise ValueError("请使用 RGB、8 位的空白 PSD 副本")
    rows, bounds, mode = read_layout(config, doc.size, fields)
    with Image.open(template) as source:
        composite = source.convert("RGBA")
    expected = {}
    for index, (label, value, x, y, size, w, h) in enumerate(rows):
        chinese = label.endswith(" CN")
        lines, pt, leading, image, (ax,ay) = fit(value, chinese, size, w, h, font_dir)
        layer = place_layer(doc, composite, image, label, x, y, index)
        layer.tagged_blocks[Tag.TYPE_TOOL_OBJECT_SETTING] = type_data(
            sample[6 if chinese else 5], lines, pt, leading, (x,y,ax,ay), image, chinese, 100+index)
        expected[label] = "\r".join(lines)
    image, px, py = fit_photo(portrait, bounds, mode)
    place_layer(doc, composite, image, "人物｜置顶", px, py, len(expected))
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
    psd, png = output/(stem+".psd"), output/(stem+".png")
    with psd.open("wb") as f:
        doc._record.write(f)
    rgb.save(png, dpi=(72, 72))
    saved = PSDImage.open(psd)
    layers = {layer.name: layer for layer in saved.descendants()}
    if any(layers[n].kind != "type" or layers[n].text != s for n, s in expected.items()):
        raise ValueError("文字层读回不一致")
    with Image.open(psd) as preview, Image.open(png) as flat:
        if saved[-1].name != "人物｜置顶" or ImageChops.difference(preview.convert("RGB"), flat.convert("RGB")).getbbox():
            raise ValueError("合成预览核对失败")


def render(args):
    fields = load_fields(args.fields)
    sample = PSDImage.open(args.sales)
    if (sample.size != (1700, 1700) or len(sample) < 7 or sample[3].kind != "type"
            or sample[3].text.upper().splitlines()[-2:] != ["SALES DPT.", "TELESALES"]
            or any(sample[n].kind != "type" for n in (5, 6))):
        raise ValueError("销售样稿及文字样式与已确认映射不符")
    id_inputs = (args.id_template, args.id_portrait, args.id_layout)
    if any(id_inputs) and not all(id_inputs):
        raise ValueError("双版输出需同时提供证件照模板、证件人像和版式配置")
    if all(id_inputs) and args.portrait.samefile(args.id_portrait):
        raise ValueError("请分别提供生活照和证件人像")
    if args.output.exists():
        raise FileExistsError("输出目录已存在，请选择新的版本目录")
    life = {"canvas": [1700, 1700], "photo_box": [1106, 391, 1671, 1187],
            "photo_mode": "cutout", "text_boxes": "sales"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as tmp:
        delivery = Path(tmp)/"delivery"
        delivery.mkdir()
        render_variant(fields, sample, args.blank, args.portrait, life, args.font_dir,
                       delivery, "欢迎海报-生活照版" if all(id_inputs) else "欢迎海报")
        if all(id_inputs):
            config = json.loads(args.id_layout.read_text(encoding="utf-8-sig"))
            render_variant(fields, sample, args.id_template, args.id_portrait, config,
                           args.font_dir, delivery, "欢迎海报-证件照版")
        delivery.rename(args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fields", required=True, type=Path)
    parser.add_argument("--portrait", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory for the verified pair")
    parser.add_argument("--id-template", type=Path, help="证件照专用的空白 PSD")
    parser.add_argument("--id-portrait", type=Path, help="同一位新人的证件人像")
    parser.add_argument("--id-layout", type=Path, help="按证件照底稿实测的框位 JSON")
    desktop = Path.home()/"Desktop"
    parser.add_argument("--blank", type=Path, default=desktop/"【交付】新人欢迎-空白.psd")
    parser.add_argument("--sales", type=Path, default=desktop/"【交付】新人欢迎-销售.psd")
    parser.add_argument("--font-dir", type=Path, default=Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts")
    render(parser.parse_args())
