#!/usr/bin/env python3
"""Render yolov8s detections under 640 / 1280 / tiled-3x2 on busy frames so the
EXTRA detections can be eyeballed (real vehicles vs FPs / tile-border dupes)."""
import os, cv2, numpy as np
from ultralytics import YOLO

VIDEO_DIR="/home/admin1/Videos/traffic_pilot_videos"
OUT="/home/admin1/traffic-pilot/tmp/strategy_verify"; os.makedirs(OUT,exist_ok=True)
CONF=0.4; VEH=[2,3,5,7]
m=YOLO("yolov8s.pt")
SHOTS=[("cam01",f"{VIDEO_DIR}/03/RAVINDRA BHARATI_Lakdikapul Bus Stop-2026-04-24_11h00min00s000ms.mp4",0.45),
       ("cam03",f"{VIDEO_DIR}/04/RAVINDRA BHARATI_PCR-2026-04-24_17h00min00s000ms.mp4",0.55)]

def draw(img,boxes,confs,tag,grid=None):
    a=img.copy()
    for (x1,y1,x2,y2),c in zip(boxes,confs):
        cv2.rectangle(a,(int(x1),int(y1)),(int(x2),int(y2)),(0,255,0),2)
        cv2.putText(a,f"{c:.2f}",(int(x1),max(0,int(y1)-4)),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,255,0),1,cv2.LINE_AA)
    if grid:
        for gx in grid[0]: cv2.line(a,(gx,0),(gx,a.shape[0]),(0,128,255),1)
        for gy in grid[1]: cv2.line(a,(0,gy),(a.shape[1],gy),(0,128,255),1)
    cv2.putText(a,f"{tag}: {len(boxes)} veh",(10,34),cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,255,255),2,cv2.LINE_AA)
    return a

def simple(frame,imgsz):
    r=m.predict(frame,conf=CONF,classes=VEH,imgsz=imgsz,verbose=False,device="cpu")[0]
    return r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()

def tiled(frame,rows=2,cols=3,overlap=0.12):
    H,W=frame.shape[:2]; tw,th=W//cols,H//rows; ox,oy=int(tw*overlap),int(th*overlap)
    B=[];S=[]
    for r in range(rows):
        for c in range(cols):
            x1=max(0,c*tw-ox);y1=max(0,r*th-oy);x2=min(W,(c+1)*tw+ox);y2=min(H,(r+1)*th+oy)
            res=m.predict(frame[y1:y2,x1:x2],conf=CONF,classes=VEH,imgsz=640,verbose=False,device="cpu")[0]
            for b in res.boxes.xyxy.cpu().numpy(): B.append([b[0]+x1,b[1]+y1,b[2]+x1,b[3]+y1])
            S+=res.boxes.conf.cpu().numpy().tolist()
    if not B: return np.empty((0,4)),[],([],[])
    idx=cv2.dnn.NMSBoxes([[x1,y1,x2-x1,y2-y1] for x1,y1,x2,y2 in B],S,CONF,0.5)
    keep=np.array(idx).flatten()
    grid=([c*tw for c in range(1,cols)],[r*th for r in range(1,rows)])
    return np.array(B)[keep], [S[i] for i in keep], grid

def main():
    for name,vid,pos in SHOTS:
        cap=cv2.VideoCapture(vid); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES,int(n*pos)); f=None
        for _ in range(12):
            ok,x=cap.read()
            if ok: f=x
        cap.release()
        b6,c6=simple(f,640);   cv2.imwrite(f"{OUT}/{name}_A640.jpg",draw(f,b6,c6,f"{name} 640"))
        b12,c12=simple(f,1280);cv2.imwrite(f"{OUT}/{name}_B1280.jpg",draw(f,b12,c12,f"{name} 1280"))
        bt,ct,grid=tiled(f);   cv2.imwrite(f"{OUT}/{name}_C_tiled.jpg",draw(f,bt,ct,f"{name} tiled",grid))
        print(f"{name}: 640={len(b6)}  1280={len(b12)}  tiled={len(bt)}")
    print("saved to",OUT)

if __name__=="__main__": main()
