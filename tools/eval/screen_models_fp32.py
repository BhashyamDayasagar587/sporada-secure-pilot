#!/usr/bin/env python3
"""FP32 accuracy screen of candidate vehicle detectors on the SAME 119 frames,
family-agnostic via ultralytics predict (handles each family's decode+NMS).
Counts vehicles/frame (COCO {2,3,5,7}, conf>=0.4, imgsz 640) + predict latency."""
import glob, os
import cv2, numpy as np
from ultralytics import YOLO

VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
CONF=0.4; IMGSZ=640; TARGET=120
VEH=[2,3,5,7]
MODELS=["yolov8s.pt","yolov8m.pt","yolov8l.pt","yolo11s.pt","yolo11m.pt","yolo26s.pt"]

def frames():
    vids=sorted(glob.glob(os.path.join(VIDEO_DIR,"*","*.mp4")))
    by={}
    for v in vids: by.setdefault(os.path.basename(os.path.dirname(v)),[]).append(v)
    chosen=[next((f for f in by[d] if any(h in f for h in ("14h","11h","17h"))),by[d][0]) for d in sorted(by)]
    per=max(1,TARGET//len(chosen)); fr=[]
    for vid in chosen:
        cap=cv2.VideoCapture(vid); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for pos in np.linspace(int(n*0.05),int(n*0.95),per).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(pos)); f=None
            for _ in range(12):
                ok,x=cap.read()
                if ok: f=x
            if f is not None: fr.append(f)
        cap.release()
    return fr

def main():
    F=frames(); print(f"{len(F)} frames, conf>={CONF}, imgsz={IMGSZ}\n")
    print(f"{'model':12} {'veh/frame':>10} {'total':>7} {'ms/inf':>8}")
    rows=[]
    for m in MODELS:
        model=YOLO(m)
        tot=0; lat=0.0
        res=model.predict(F, conf=CONF, classes=VEH, imgsz=IMGSZ, verbose=False, device="cpu")
        for r in res:
            tot+=len(r.boxes); lat+=sum(r.speed.values())
        rows.append((m,tot/len(F),tot,lat/len(F)))
        print(f"{m.replace('.pt',''):12} {tot/len(F):>10.2f} {tot:>7} {lat/len(F):>8.1f}")
    base=next((x for x in rows if x[0]=='yolo26s.pt'),None)
    if base:
        print(f"\nvs yolo26s FP32 ({base[1]:.2f}/frame):")
        for m,vpf,tot,_ in sorted(rows,key=lambda x:-x[1]):
            tag=" <- baseline" if m=='yolo26s.pt' else ""
            print(f"  {m.replace('.pt',''):12}: {vpf:>5.2f}/fr  {100*(vpf-base[1])/base[1]:+6.1f}%{tag}")

if __name__=="__main__": main()
