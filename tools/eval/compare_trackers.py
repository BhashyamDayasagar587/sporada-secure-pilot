#!/usr/bin/env python3
"""Step 4 measurement: CentroidTracker vs a compact OC-SORT on the SAME detection
sequence from a busy video. Proxy metrics (no GT): # unique IDs created, track
length distribution, fragmentation (short tracks). Fewer IDs + longer tracks +
fewer fragments = more stable IDs = OCR votes land on one track."""
import sys, glob, numpy as np, cv2
from scipy.optimize import linear_sum_assignment
sys.path.insert(0, "services/worker")
from pipeline.tracking import CentroidTracker
from pipeline.types import Detection

VID=glob.glob("/home/admin1/Videos/traffic_pilot_videos/03/*11h*.mp4")[0]
ONNX="models/weights/yolov8s_ultralytics_v8.1.0.onnx"
import onnxruntime as ort
sess=ort.InferenceSession(ONNX,providers=["CPUExecutionProvider"])
VEH={2,3,5,7}; CONF=0.4; N=300

def letterbox(img,n=640):
    h,w=img.shape[:2]; r=min(n/h,n/w); nh,nw=int(round(h*r)),int(round(w*r))
    c=np.full((n,n,3),114,np.uint8); t,l=(n-nh)//2,(n-nw)//2; c[t:t+nh,l:l+nw]=cv2.resize(img,(nw,nh)); return c,r,l,t
def detect(frame):
    lb,r,l,t=letterbox(frame); rgb=cv2.cvtColor(lb,cv2.COLOR_BGR2RGB).astype(np.float32)/255.0
    o=sess.run(None,{"images":rgb.transpose(2,0,1)[None]})[0]
    o=o[0].T if o.shape[1]<o.shape[2] else o[0]   # (8400,84)
    dets=[]
    for row in o:
        cls=int(np.argmax(row[4:])); sc=row[4+cls]
        if sc<CONF or cls not in VEH: continue
        cx,cy,bw,bh=row[:4]; x1=(cx-bw/2-l)/r; y1=(cy-bh/2-t)/r; x2=(cx+bw/2-l)/r; y2=(cy+bh/2-t)/r
        dets.append([x1,y1,x2,y2,float(sc),cls])
    # class-agnostic NMS
    if not dets: return []
    b=np.array([[d[0],d[1],d[2]-d[0],d[3]-d[1]] for d in dets]); s=[d[4] for d in dets]
    keep=cv2.dnn.NMSBoxes(b.tolist(),s,CONF,0.5)
    return [dets[i] for i in np.array(keep).flatten()]

# ---------- compact OC-SORT ----------
def iou(a,b):
    xx1=max(a[0],b[0]);yy1=max(a[1],b[1]);xx2=min(a[2],b[2]);yy2=min(a[3],b[3])
    iw=max(0,xx2-xx1);ih=max(0,yy2-yy1);inter=iw*ih
    ua=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/ua if ua>0 else 0
class KF:
    def __init__(s,box):
        s.x=np.array([(box[0]+box[2])/2,(box[1]+box[3])/2,box[2]-box[0],box[3]-box[1],0,0,0,0],float)
        s.P=np.eye(8)*10.
    def predict(s):
        for i in range(4): s.x[i]+=s.x[i+4]
        return s.x
    def update(s,box):
        z=np.array([(box[0]+box[2])/2,(box[1]+box[3])/2,box[2]-box[0],box[3]-box[1]])
        for i in range(4):
            s.x[i+4]=0.7*s.x[i+4]+0.3*(z[i]-s.x[i]); s.x[i]=z[i]
    def box(s):
        cx,cy,w,h=s.x[:4]; return [cx-w/2,cy-h/2,cx+w/2,cy+h/2]
class OCSort:
    def __init__(s,iou_thr=0.2,max_age=30,min_hits=3,ocm=0.2):
        s.iou_thr=iou_thr;s.max_age=max_age;s.min_hits=min_hits;s.ocm=ocm;s.tr=[];s.nid=0
    def update(s,dets):
        for t in s.tr: t["kf"].predict(); t["age"]+=1
        boxes=[d[:4] for d in dets]
        if s.tr and boxes:
            C=np.zeros((len(s.tr),len(boxes)))
            for i,t in enumerate(s.tr):
                tb=t["kf"].box(); tv=t.get("v")
                for j,b in enumerate(boxes):
                    cost=1-iou(tb,b)
                    if tv is not None:   # OCM direction consistency
                        dv=np.array([(b[0]+b[2])/2-(tb[0]+tb[2])/2,(b[1]+b[3])/2-(tb[1]+tb[3])/2])
                        n=np.linalg.norm(dv)
                        if n>1: cost+=s.ocm*(1-float(np.dot(tv,dv/n)))/2
                    C[i,j]=cost
            ri,ci=linear_sum_assignment(C); used_t,used_d=set(),set()
            for i,j in zip(ri,ci):
                if C[i,j]<=1-s.iou_thr+s.ocm:
                    t=s.tr[i]; ob=t["kf"].box(); t["kf"].update(boxes[j])
                    nb=boxes[j]; dv=np.array([(nb[0]+nb[2])/2-(ob[0]+ob[2])/2,(nb[1]+nb[3])/2-(ob[1]+ob[3])/2])
                    nn=np.linalg.norm(dv); t["v"]=dv/nn if nn>1 else t.get("v")
                    t["age"]=0;t["hits"]+=1;used_t.add(i);used_d.add(j)
            for j,b in enumerate(boxes):
                if j not in used_d:
                    s.nid+=1; s.tr.append({"id":s.nid,"kf":KF(b),"age":0,"hits":1,"v":None})
        elif boxes:
            for b in boxes:
                s.nid+=1; s.tr.append({"id":s.nid,"kf":KF(b),"age":0,"hits":1,"v":None})
        s.tr=[t for t in s.tr if t["age"]<=s.max_age]
        return [t["id"] for t in s.tr if t["hits"]>=s.min_hits and t["age"]==0]

# ---------- run both on the same detections ----------
cap=cv2.VideoCapture(VID); frames=[]
while len(frames)<N:
    ok,f=cap.read()
    if not ok: break
    frames.append(f)
cap.release()
alldets=[detect(f) for f in frames]
ntot=sum(len(d) for d in alldets)
print(f"{len(frames)} frames, {ntot} detections ({ntot/len(frames):.1f}/frame)\n")

# CentroidTracker
ct=CentroidTracker(max_disappeared=30,max_distance=160,min_iou=0.02)
ct_life={}
for dets in alldets:
    objs=[Detection(bbox=[int(x) for x in d[:4]],class_id=d[5],class_name="v",confidence=d[4],model_name="vehicle") for d in dets]
    matches=ct.update(objs)            # {det_idx: object_id}
    for oid in matches.values():
        ct_life[oid]=ct_life.get(oid,0)+1

# OC-SORT
oc=OCSort(); oc_life={}
for dets in alldets:
    ids=oc.update(dets)
    for i in ids: oc_life[i]=oc_life.get(i,0)+1

def report(name,life):
    import statistics as st
    L=list(life.values())
    frag=sum(1 for x in L if x<5)
    print(f"{name:16} unique_ids={len(L):4}  median_track_len={int(st.median(L)) if L else 0:3}  mean={st.mean(L):.1f}  short(<5f)={frag} ({100*frag/max(1,len(L)):.0f}%)")
print("=== tracker comparison (same detections; fewer IDs + longer tracks = more stable) ===")
report("CentroidTracker",ct_life)
report("OC-SORT",oc_life)
