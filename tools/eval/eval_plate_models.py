#!/usr/bin/env python3
"""Plate-detector accuracy: FP32 onnxruntime vs Metis AIPU on the labeled plate
set (~/.cache/axelera/data/alpr_plate, 100 imgs w/ YOLO GT boxes). Reports
recall@IoU0.5, false positives, and mean confidence — to quantify how much INT8
quantization costs the plate model and whether a re-calibrated build recovers it.

AIPU model.json paths can be added to AIPU dict as new plate builds land.
"""
import glob
import os

import cv2
import numpy as np
import onnxruntime as ort
from axelera.runtime import Context

REPO = "/home/admin1/traffic-pilot"
DATA = "/home/admin1/.cache/axelera/data/alpr_plate"
CONF = float(os.getenv("CONF", "0.25"))
IOU_MATCH = 0.5
IMGSZ = 224

ONNX = {"plate-fp32": f"{REPO}/models/weights/plate_yolo26n_224.onnx"}
AIPU = {
    "plate-aipu(orig)": "/home/admin1/voyager-sdk/build/alpr-plate/alpr-plate/1/model.json",
    "plate-aipu(domain)": f"{REPO}/models/aipu-compare/alpr-plate-mix/alpr-plate-mix/1/model.json",
}


def letterbox(img, new=IMGSZ):
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((new, new, 3), 114, np.uint8)
    top, left = (new - nh) // 2, (new - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh))
    return canvas, r, left, top


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0


def load_gt(img_path, w, h):
    lp = img_path.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
    boxes = []
    if os.path.exists(lp):
        for line in open(lp):
            p = line.split()
            if len(p) >= 5:
                cx, cy, bw, bh = (float(x) for x in p[1:5])
                boxes.append([(cx-bw/2)*w, (cy-bh/2)*h, (cx+bw/2)*w, (cy+bh/2)*h])
    return boxes


def preds_onnx(sess, frame):
    lb, r, left, top = letterbox(frame)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    out = sess.run(None, {"images": rgb.transpose(2, 0, 1)[None]})[0][0]
    res = []
    for x1, y1, x2, y2, conf, cls in out:
        if conf >= CONF:
            res.append(((x1-left)/r, (y1-top)/r, (x2-left)/r, (y2-top)/r, float(conf)))
    return res


def preds_aipu(inst, iout, info, frame):
    lb, r, left, top = letterbox(frame)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
    inp = (rgb.astype(np.int16) - 128).astype(np.int8)[None]
    padded = np.pad(inp, info.padding, mode="constant", constant_values=info.zero_point)
    outbuf = [np.zeros(t.shape, np.int8) for t in iout]
    inst.run([np.ascontiguousarray(padded)], outbuf)
    deq = [((b.astype(np.float32) - t.zero_point) * t.scale) for t, b in zip(iout, outbuf)]
    groups = {}
    for t, d in zip(iout, deq):
        up = t.unpadded_shape
        H, W, C = up[1], up[2], up[3]
        groups.setdefault((H, W), {})[("box" if C == 4 else "cls")] = d[0, :H, :W, :C]
    B, S = [], []
    for (H, W), g in groups.items():
        if "box" not in g or "cls" not in g:
            continue
        st = IMGSZ / H
        box, cls = g["box"], g["cls"]
        csig = 1/(1+np.exp(-np.clip(cls, -30, 30)))
        gx, gy = np.meshgrid(np.arange(W), np.arange(H))
        ax, ay = gx+0.5, gy+0.5
        l, t_, rr, b_ = box[...,0], box[...,1], box[...,2], box[...,3]
        x1=(ax-l)*st; y1=(ay-t_)*st; x2=(ax+rr)*st; y2=(ay+b_)*st
        sc = csig.max(-1); mk = sc >= CONF
        if mk.any():
            B.append(np.stack([x1[mk],y1[mk],x2[mk],y2[mk]],1)); S.append(sc[mk])
    if not B:
        return []
    boxes = np.concatenate(B); scores = np.concatenate(S)
    idx = cv2.dnn.NMSBoxes([[float(a),float(b),float(c-a),float(d-b)] for a,b,c,d in boxes],
                           scores.tolist(), CONF, 0.5)
    if len(idx) == 0:
        return []
    out = []
    for i in np.array(idx).flatten():
        x1,y1,x2,y2 = boxes[i]
        out.append(((x1-left)/r,(y1-top)/r,(x2-left)/r,(y2-top)/r,float(scores[i])))
    return out


def score(name, predfn, imgs):
    tp = fp = gt_total = 0
    confs = []
    for ip in imgs:
        frame = cv2.imread(ip)
        if frame is None:
            continue
        h, w = frame.shape[:2]
        gts = load_gt(ip, w, h)
        gt_total += len(gts)
        preds = predfn(frame)
        matched = set()
        for *box, conf in sorted(preds, key=lambda p: -p[4]):
            best, bi = 0, -1
            for j, g in enumerate(gts):
                if j in matched:
                    continue
                v = iou(box, g)
                if v > best:
                    best, bi = v, j
            if best >= IOU_MATCH:
                tp += 1; matched.add(bi); confs.append(conf)
            else:
                fp += 1
    recall = tp / gt_total if gt_total else 0
    print(f"  {name:20} recall={recall:.3f} ({tp}/{gt_total})  FP={fp}  "
          f"mean_conf={np.mean(confs):.3f}" if confs else
          f"  {name:20} recall={recall:.3f} ({tp}/{gt_total})  FP={fp}")
    return recall


def main():
    imgs = sorted(glob.glob(f"{DATA}/images/*"))
    print(f"plate eval on {len(imgs)} labeled images, conf>={CONF}, IoU>={IOU_MATCH}\n")
    for name, path in ONNX.items():
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        score(name, lambda f, s=sess: preds_onnx(s, f), imgs)
    for name, path in AIPU.items():
        if not os.path.exists(path):
            print(f"  {name:20} SKIP (not built: {path})")
            continue
        with Context() as ctx:
            m = ctx.load_model(path); iout = m.outputs(); info = m.inputs()[0]
            conn = ctx.device_connect(None, 1)
            inst = conn.load_model_instance(m, num_sub_devices=1, aipu_cores=1)
            score(name, lambda f, i=inst, o=iout, n=info: preds_aipu(i, o, n, f), imgs)


if __name__ == "__main__":
    main()
