#!/usr/bin/env python3
"""End-to-end ALPR yield on the AIPU: vehicle detect -> crop ROIs -> plate detect,
exactly like the cascade. Quantifies how many plates actually get found end-to-end
under each vehicle model, since plate detection only runs on detected vehicles.
Run on real sampled video frames (no GT -> measures detection yield, not recall).

Compares the imported yolo26n vs yolo26s as the vehicle stage, same plate model.
"""
import glob
import os

import cv2
import numpy as np
from axelera.runtime import Context

REPO = "/home/admin1/traffic-pilot"
VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
VCONF = float(os.getenv("VCONF", "0.4"))
PCONF = float(os.getenv("PCONF", "0.25"))
TARGET = int(os.getenv("SNAPS", "120"))
TOPK_ROI = 10  # cascade crops up to 10 largest vehicle ROIs/frame
VEH = {2, 3, 5, 7}

VEHICLE_MODELS = {
    "n-aipu(imported)": "/home/admin1/voyager-sdk/build/alpr-vehicle/alpr-vehicle/1/model.json",
    "s-aipu(coco)": f"{REPO}/models/aipu-compare/alpr-vehicle-s/alpr-vehicle-s/1/model.json",
    "s-aipu(mix)": f"{REPO}/models/aipu-compare/alpr-vehicle-s-mix/alpr-vehicle-s-mix/1/model.json",
}
PLATE_MODEL = "/home/admin1/voyager-sdk/build/alpr-plate/alpr-plate/1/model.json"


def letterbox(img, new):
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((new, new, 3), 114, np.uint8)
    top, left = (new - nh) // 2, (new - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh))
    return canvas, r, left, top


def _decode(iout, deq, imgsz, conf, classes=None):
    groups = {}
    for t, d in zip(iout, deq):
        up = t.unpadded_shape
        H, W, C = up[1], up[2], up[3]
        groups.setdefault((H, W), {})[("box" if C == 4 else "cls")] = d[0, :H, :W, :C]
    B, S, Cc = [], [], []
    for (H, W), g in groups.items():
        if "box" not in g or "cls" not in g:
            continue
        st = imgsz / H
        box, cls = g["box"], g["cls"]
        csig = 1/(1+np.exp(-np.clip(cls, -30, 30)))
        gx, gy = np.meshgrid(np.arange(W), np.arange(H))
        ax, ay = gx+0.5, gy+0.5
        l, t_, rr, b_ = box[...,0], box[...,1], box[...,2], box[...,3]
        x1=(ax-l)*st; y1=(ay-t_)*st; x2=(ax+rr)*st; y2=(ay+b_)*st
        sc = csig.max(-1); cl = csig.argmax(-1); mk = sc >= conf
        if mk.any():
            B.append(np.stack([x1[mk],y1[mk],x2[mk],y2[mk]],1)); S.append(sc[mk]); Cc.append(cl[mk])
    if not B:
        return []
    boxes, scores, clss = np.concatenate(B), np.concatenate(S), np.concatenate(Cc)
    keep = []
    cats = set(clss.tolist()) if classes is None else (set(clss.tolist()) & classes)
    for c in cats:
        m = clss == c
        idx = cv2.dnn.NMSBoxes([[float(a),float(b),float(cc-a),float(d-b)] for a,b,cc,d in boxes[m]],
                               scores[m].tolist(), conf, 0.5)
        for i in (np.array(idx).flatten() if len(idx) else []):
            keep.append((boxes[m][i], scores[m][i]))
    return keep


def run_model(inst, iout, info, frame, imgsz, conf, classes=None):
    lb, r, left, top = letterbox(frame, imgsz)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
    inp = (rgb.astype(np.int16)-128).astype(np.int8)[None]
    padded = np.pad(inp, info.padding, mode="constant", constant_values=info.zero_point)
    outbuf = [np.zeros(t.shape, np.int8) for t in iout]
    inst.run([np.ascontiguousarray(padded)], outbuf)
    deq = [((b.astype(np.float32)-t.zero_point)*t.scale) for t, b in zip(iout, outbuf)]
    dets = _decode(iout, deq, imgsz, conf, classes)
    out = []
    for (x1,y1,x2,y2), s in dets:
        out.append((int((x1-left)/r), int((y1-top)/r), int((x2-left)/r), int((y2-top)/r), float(s)))
    return out


def load(ctx, path):
    m = ctx.load_model(path)
    conn = ctx.device_connect(None, 1)
    inst = conn.load_model_instance(m, num_sub_devices=1, aipu_cores=1)
    return inst, m.outputs(), m.inputs()[0]


def sample_frames():
    vids = sorted(glob.glob(os.path.join(VIDEO_DIR, "*", "*.mp4")))
    by = {}
    for v in vids:
        by.setdefault(os.path.basename(os.path.dirname(v)), []).append(v)
    chosen = [next((f for f in by[d] if any(h in f for h in ("14h","11h","17h"))), by[d][0]) for d in sorted(by)]
    per = max(1, TARGET // len(chosen))
    frames = []
    for vid in chosen:
        cap = cv2.VideoCapture(vid); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for pos in np.linspace(int(n*0.05), int(n*0.95), per).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            fr = None
            for _ in range(12):
                ok, f = cap.read()
                if ok: fr = f
            if fr is not None: frames.append(fr)
        cap.release()
    return frames


def main():
    frames = sample_frames()
    print(f"end-to-end on {frames and len(frames)} frames  vconf>={VCONF} pconf>={PCONF}\n")
    rows = []
    for vname, vpath in VEHICLE_MODELS.items():
        if not os.path.exists(vpath):
            print(f"  {vname:18} SKIP (not built)"); continue
        with Context() as ctx:
            vinst, vout, vinfo = load(ctx, vpath)
            pinst, pout, pinfo = load(ctx, PLATE_MODEL)
            n_veh = n_plate = n_frame_with_plate = 0
            for fr in frames:
                vdets = run_model(vinst, vout, vinfo, fr, 640, VCONF, VEH)
                vdets = sorted(vdets, key=lambda d:-(d[2]-d[0])*(d[3]-d[1]))[:TOPK_ROI]
                n_veh += len(vdets)
                got = False
                for x1,y1,x2,y2,_ in vdets:
                    x1,y1 = max(0,x1),max(0,y1); x2,y2 = max(x1+1,x2),max(y1+1,y2)
                    crop = fr[y1:y2, x1:x2]
                    if crop.size == 0: continue
                    pdets = run_model(pinst, pout, pinfo, crop, 224, PCONF, None)
                    n_plate += len(pdets)
                    if pdets: got = True
                if got: n_frame_with_plate += 1
            rows.append((vname, n_veh, n_plate, n_frame_with_plate))
            print(f"  {vname:18} vehicles(ROI)={n_veh:4d}  plates={n_plate:4d}  frames_with_plate={n_frame_with_plate}")
    if len(rows) >= 2:
        base = next((r for r in rows if r[0].startswith("n-aipu")), rows[0])
        print(f"\nvs {base[0]} (plates end-to-end):")
        for r in rows:
            if r is base: continue
            d = r[2]-base[2]
            print(f"  {r[0]:18}: {d:+d} plates ({100*d/max(1,base[2]):+.1f}%)")


if __name__ == "__main__":
    main()
