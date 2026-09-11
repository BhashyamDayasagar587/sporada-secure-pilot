#!/usr/bin/env python3
"""FP32 screen of inference-size strategies for small/distant-vehicle recall, on
busy daytime frames. Strategies (vehicle count @ conf0.4, COCO {2,3,5,7}):
  A) model @ 640 letterbox          (current; 1x cost)
  B) model @ 1280 letterbox         (toward native res; ~4x cost)
  C) model @ 640 TILED 3x2 native   (break the image; ~6x cost, detail preserved)
Compares yolov8s and yolov8m. Cost is # of 640-equivalent inferences/frame."""
import glob, os, time
import cv2, numpy as np
from ultralytics import YOLO

VIDEO_DIR=os.getenv("VIDEO_DIR","/home/admin1/Videos/traffic_pilot_videos")
CONF=0.4; VEH=[2,3,5,7]; NPER=12
# busy daytime cams (where small/distant misses live)
VIDS=[f"{VIDEO_DIR}/03/RAVINDRA BHARATI_Lakdikapul Bus Stop-2026-04-24_11h00min00s000ms.mp4",
      f"{VIDEO_DIR}/02/RAVINDRA BHARATI_PCR2-2026-04-24_14h00min00s000ms.mp4",
      f"{VIDEO_DIR}/04/RAVINDRA BHARATI_PCR-2026-04-24_17h00min00s000ms.mp4"]

def frames():
    fr=[]
    for v in VIDS:
        cap=cv2.VideoCapture(v); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for pos in np.linspace(int(n*0.1),int(n*0.9),NPER).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(pos)); f=None
            for _ in range(12):
                ok,x=cap.read()
                if ok: f=x
            if f is not None: fr.append(f)
        cap.release()
    return fr

def count_simple(model,frame,imgsz):
    r=model.predict(frame,conf=CONF,classes=VEH,imgsz=imgsz,verbose=False,device="cpu")[0]
    return len(r.boxes)

def count_tiled(model,frame,rows=2,cols=3,overlap=0.12):
    H,W=frame.shape[:2]; tw,th=W//cols,H//rows
    ox,oy=int(tw*overlap),int(th*overlap)
    boxes=[];scores=[]
    for r in range(rows):
        for c in range(cols):
            x1=max(0,c*tw-ox); y1=max(0,r*th-oy)
            x2=min(W,(c+1)*tw+ox); y2=min(H,(r+1)*th+oy)
            tile=frame[y1:y2,x1:x2]
            res=model.predict(tile,conf=CONF,classes=VEH,imgsz=640,verbose=False,device="cpu")[0]
            for b in res.boxes.xyxy.cpu().numpy():
                boxes.append([b[0]+x1,b[1]+y1,b[2]+x1,b[3]+y1])
            scores+=res.boxes.conf.cpu().numpy().tolist()
    if not boxes: return 0
    idx=cv2.dnn.NMSBoxes([[x1,y1,x2-x1,y2-y1] for x1,y1,x2,y2 in boxes],scores,CONF,0.5)
    return len(idx)

def main():
    F=frames(); print(f"{len(F)} busy daytime frames, conf>={CONF}\n")
    print(f"{'model':8} {'strategy':16} {'veh/frame':>10} {'rel cost':>9}")
    for mname in ["yolov8s.pt","yolov8m.pt"]:
        m=YOLO(mname); tag=mname.replace('.pt','')
        for label,fn,cost in [
            ("A 640",        lambda f:count_simple(m,f,640), "1x"),
            ("B 1280",       lambda f:count_simple(m,f,1280),"~4x"),
            ("C tiled 3x2",  lambda f:count_tiled(m,f),       "~6x")]:
            tot=sum(fn(f) for f in F)
            print(f"{tag:8} {label:16} {tot/len(F):>10.2f} {cost:>9}")
        print()

if __name__=="__main__": main()
