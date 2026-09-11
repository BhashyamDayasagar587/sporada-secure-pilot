#!/usr/bin/env python3
"""Step 3 measurement: does plate deskew/rectification recover OCR accuracy on
TILTED plates? Controlled experiment on the labeled OCR test set (GT .txt):
frontal -> OCR; apply known tilt -> OCR (drops); deskew -> OCR (recovers)."""
import glob, os, math, numpy as np, cv2
import openvino as ov

MODEL="/home/admin1/traffic-pilot/models/openvino/ocr.xml"
DATA="/home/admin1/traffic-pilot/datasets/plate_ocr"
ALPHABET="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"; PAD="_"; W,H=128,64
core=ov.Core(); comp=core.compile_model(core.read_model(MODEL),"CPU"); out=comp.outputs[0]

def ocr(bgr):
    rgb=cv2.cvtColor(cv2.resize(bgr,(W,H)),cv2.COLOR_BGR2RGB)
    arr=np.expand_dims(rgb.transpose(2,0,1).astype(np.float32),0)
    logits=comp({0:arr})[out]
    idx=np.argmax(logits,axis=-1)[0]
    return "".join(ALPHABET[i] for i in idx if ALPHABET[i]!=PAD)

def tilt(img, angle, persp=0.15):
    h,w=img.shape[:2]
    M=cv2.getRotationMatrix2D((w/2,h/2),angle,1.0)
    rot=cv2.warpAffine(img,M,(w,h),borderValue=(114,114,114))
    # add mild perspective
    dx=int(w*persp)
    src=np.float32([[0,0],[w,0],[w,h],[0,h]])
    dst=np.float32([[dx,0],[w,0],[w-dx,h],[0,h]])
    P=cv2.getPerspectiveTransform(src,dst)
    return cv2.warpPerspective(rot,P,(w,h),borderValue=(114,114,114))

def deskew(bgr):
    """Estimate dominant text-line angle from binarized characters; rotate to level."""
    g=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
    th=cv2.threshold(g,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    coords=np.column_stack(np.where(th>0))
    if len(coords)<20: return bgr
    ang=cv2.minAreaRect(coords[:,::-1].astype(np.float32))[-1]
    if ang< -45: ang+=90
    if ang>45: ang-=90
    if abs(ang)<1.0: return bgr
    h,w=bgr.shape[:2]
    M=cv2.getRotationMatrix2D((w/2,h/2),ang,1.0)
    return cv2.warpAffine(bgr,M,(w,h),borderValue=(114,114,114),flags=cv2.INTER_CUBIC)

imgs=sorted(glob.glob(f"{DATA}/*.jpg"))
def gt(p):
    t=p[:-4]+".txt"
    return open(t).read().strip().upper().replace(" ","") if os.path.exists(t) else None
pairs=[(p,gt(p)) for p in imgs if gt(p)]
print(f"labeled OCR crops: {len(pairs)}")

def acc(fn):
    ok=0
    for p,g in pairs:
        im=cv2.imread(p)
        if im is None: continue
        if fn(im)==g: ok+=1
    return 100*ok/len(pairs)

base=acc(lambda im: ocr(im))
import random
random.seed(0)
angs=[random.choice([-18,-12,12,18]) for _ in pairs]
def tilted(im,i=[0]):
    a=angs[i[0]%len(angs)]; i[0]+=1; return ocr(tilt(im,a))
def rect(im,i=[0]):
    a=angs[i[0]%len(angs)]; i[0]+=1; return ocr(deskew(tilt(im,a)))
print(f"\n=== OCR exact-match accuracy ===")
print(f"  frontal (baseline)      : {base:.0f}%")
print(f"  tilted ~12-18deg+persp  : {acc(tilted):.0f}%")
print(f"  tilted + deskew (Step3) : {acc(rect):.0f}%")
