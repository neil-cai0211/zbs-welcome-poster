"""Validate one local photo and extract the subject with Windows ML."""
import argparse
from array import array
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from winrt.windows.ai.machinelearning import LearningModel, LearningModelBinding, LearningModelSession, TensorFloat

ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "face": (ZOO+"face_detection_yunet/face_detection_yunet_2023mar.onnx",
             "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "person": (ZOO+"object_detection_yolox/object_detection_yolox_2022nov.onnx",
               "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"),
    "saliency": ("https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
                 "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"),
    "human": (ZOO+"human_segmentation_pphumanseg/human_segmentation_pphumanseg_2023mar.onnx",
              "552d8a984054e59b5d773d24b9b12022b22046ceb2bbc4c9aaeaceb36a9ddf24"),
}


def models(root, download):
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name,(url,checksum) in MODELS.items():
        path = root/(name+".onnx")
        if not path.exists() and download:
            with NamedTemporaryFile(dir=root, delete=False) as tmp:
                part = Path(tmp.name)
            try:
                with urlopen(url, timeout=90) as response, part.open("wb") as out:
                    while chunk := response.read(1024*1024):
                        out.write(chunk)
                if hashlib.sha256(part.read_bytes()).hexdigest() != checksum:
                    raise ValueError("模型校验失败："+name)
                os.replace(part,path)
            finally:
                part.unlink(missing_ok=True)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("本机缺少已校验模型："+name+"；运行 --setup-models")
        paths[name] = path
    return paths


def infer(path, rgb):
    model = LearningModel.load_from_file_path(str(path.resolve()))
    session = LearningModelSession(model)
    binding = LearningModelBinding(session)
    a = np.ascontiguousarray(rgb.transpose(2,0,1)[None], dtype=np.float32)
    tensor = TensorFloat.create_from_array(list(a.shape),array("f",a.ravel()))
    binding.bind(model.input_features[0].name,tensor)
    result = session.evaluate(binding,"local")
    outputs = {}
    for feature in model.output_features:
        value = result.outputs[feature.name].as_(TensorFloat)
        outputs[feature.name] = np.asarray(value.get_as_vector_view(),dtype=np.float32).reshape(tuple(value.shape))
    return outputs


def letterbox(im, fill):
    ratio = 640/max(im.size)
    small = im.resize(tuple(max(1,int(s*ratio)) for s in im.size),Image.Resampling.BILINEAR)
    canvas = Image.new("RGB",(640,640),(fill,)*3)
    canvas.paste(small,(0,0))
    return np.asarray(canvas,dtype=np.float32), ratio


def overlap(box, other):
    inter = np.prod(np.maximum(0,np.minimum(box[2:],other[2:])-np.maximum(box[:2],other[:2])))
    return inter/(np.prod(box[2:]-box[:2])+np.prod(other[2:]-other[:2])-inter+1e-8)


def people(im, model):
    canvas,ratio = letterbox(im,114)
    det = next(iter(infer(model,canvas).values()))[0]
    grids, steps = [], []
    for stride in (8,16,32):
        width = 640//stride
        gx,gy = np.meshgrid(np.arange(width),np.arange(width))
        grids.extend(np.stack((gx,gy),axis=-1).reshape(-1,2))
        steps.extend([stride]*(width*width))
    step = np.asarray(steps)[:,None]
    centers = (det[:,:2]+np.asarray(grids))*step
    sizes = np.exp(det[:,2:4])*step
    boxes = np.hstack((centers-sizes/2,centers+sizes/2))/ratio
    scores = det[:,4]*det[:,5]
    keep = []
    for idx in np.argsort(-scores):
        if scores[idx]<.24:
            break
        if all(overlap(boxes[idx],other)<.5 for other in keep):
            keep.append(boxes[idx])
    return keep


def frontal(im, model):
    canvas,_ = letterbox(im,0)
    out = infer(model,canvas[:,:,::-1])
    best_score = 0.
    best = None
    for stride in (8,16,32):
        width = 640//stride
        scores = np.sqrt(np.clip(out[f"cls_{stride}"],0,1)*np.clip(out[f"obj_{stride}"],0,1)).ravel()
        idx = int(scores.argmax())
        if scores[idx] > best_score:
            best_score = scores[idx]
            landmarks = out[f"kps_{stride}"].reshape(-1,5,2)[idx]
            best = (landmarks+np.array([idx%width,idx//width]))*stride
    if best is None or best_score < .65:
        return False
    eye_axis = best[1]-best[0]
    offset = np.dot(best[2]-best[:2].mean(axis=0),eye_axis)/max(1.,np.dot(eye_axis,eye_axis))
    return abs(offset)<=.35


def extract(im, paths):
    boxes = people(im,paths["person"])
    if len(boxes)!=1:
        raise ValueError("未能确认单人照（检测人数 %d），请核对或更换照片" % len(boxes))
    x,y,r,b = boxes[0]
    pad = .08*max(r-x,b-y)
    crop = im.crop((max(0,int(x-pad)),max(0,int(y-pad)),min(im.width,int(r+pad)),min(im.height,int(b+pad))))
    if not frontal(crop,paths["face"]):
        raise ValueError("未能确认脸部正对镜头，请核对或更换照片")
    crop.thumbnail((2200,2200),Image.Resampling.LANCZOS)
    image = np.asarray(crop.resize((320,320),Image.Resampling.LANCZOS),dtype=np.float32)/255
    image = (image-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    matte = next(iter(infer(paths["saliency"],image).values())).squeeze()
    matte = (matte-matte.min())/max(1e-6,float(np.ptp(matte)))
    image = np.asarray(crop.resize((192,192),Image.Resampling.LANCZOS),dtype=np.float32)/127.5-1
    human = next(iter(infer(paths["human"],image).values()))[0,1]
    def alpha(values,low,high):
        mask = Image.fromarray(np.uint8(255*np.clip((values-low)/(high-low),0,1)))
        return mask.resize(crop.size,Image.Resampling.BICUBIC)
    foreground = np.asarray(alpha(matte,.07,.93).filter(ImageFilter.MedianFilter(3)))
    body = np.asarray(alpha(human,.19,.84).filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(2)))
    opacity = np.minimum(foreground,body).astype(float)/255
    opacity = np.uint8(255*np.clip((opacity-.08)/.84,0,1))
    result = crop.convert("RGBA")
    result.putalpha(Image.fromarray(opacity))
    if result.getchannel("A").getextrema() != (0,255):
        raise ValueError("人像蒙版异常，需要检查原图")
    return result


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--setup-models",action="store_true")
    p.add_argument("--models",type=Path,default=Path(os.getenv("LOCALAPPDATA",Path.home()))/"zbs-welcome-poster"/"models")
    p.add_argument("--photo",type=Path)
    p.add_argument("--out",type=Path)
    args = p.parse_args()
    paths = models(args.models,args.setup_models)
    if args.photo or args.out:
        if not args.photo or not args.out:
            p.error("--photo 和 --out 需要同时提供")
        with Image.open(args.photo) as img:
            portrait = extract(ImageOps.exif_transpose(img).convert("RGB"),paths)
        with args.out.open("xb") as f:
            portrait.save(f,"PNG")
    elif not args.setup_models:
        p.error("请选择 --setup-models 或提供照片与输出路径")
