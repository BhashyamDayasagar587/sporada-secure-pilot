#!/usr/bin/env python3
"""On-Axelera comparison: run compiled vehicle models on the Metis AIPU over the
SAME sampled frames and compare vehicle-detection counts, plus FP32 onnxruntime
references. Decodes the raw AIPU detect-head outputs (stride 8/16/32, ltrb + cls
logits) -> boxes -> conf filter -> per-class NMS, identifying box vs cls tensors
by channel count so it works for any yolo26 variant.

Models compared (edit MODELS below as builds complete):
  n-aipu     imported yolo26n on AIPU (COCO calib)         [baseline]
  s-aipu-coco stock yolo26s on AIPU (COCO calib)
  s-aipu-mix  stock yolo26s on AIPU (local+IDD calib)
FP32 refs: yolo26n, yolo26s via onnxruntime (upper bound).
"""
import glob
import os
import sys

import cv2
import numpy as np
import onnxruntime as ort
from axelera.runtime import Context

REPO = "/home/admin1/traffic-pilot"
VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
CONF = float(os.getenv("CONF", "0.4"))
IOU = 0.5
TARGET = int(os.getenv("SNAPS", "120"))
VEH = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
IMGSZ = 640

ONNX = {
    "n-fp32": f"{REPO}/models/weights/vehicle_yolo26n_640.onnx",
    "s-fp32": f"{REPO}/models/weights/vehicle_yolo26s_640.onnx",
}
AIPU = {
    "n-aipu(coco)": "/home/admin1/voyager-sdk/build/alpr-vehicle/alpr-vehicle/1/model.json",
    "s-aipu(coco)": f"{REPO}/models/aipu-compare/alpr-vehicle-s/alpr-vehicle-s/1/model.json",
    "s-aipu(mix)": f"{REPO}/models/aipu-compare/alpr-vehicle-s-mix/alpr-vehicle-s-mix/1/model.json",
}


def letterbox(img, new=IMGSZ):
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((new, new, 3), 114, np.uint8)
    top, left = (new - nh) // 2, (new - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh))
    return canvas, r, left, top


def nms_count(boxes, scores, classes, r, left, top):
    """per-class NMS in letterbox space, map back, keep vehicle classes."""
    keep = []
    for c in set(classes.tolist()):
        if c not in VEH:
            continue
        m = classes == c
        idx = cv2.dnn.NMSBoxes(
            [[float(x1), float(y1), float(x2 - x1), float(y2 - y1)]
             for x1, y1, x2, y2 in boxes[m]],
            scores[m].tolist(), CONF, IOU)
        if len(idx) == 0:
            continue
        bm = boxes[m][np.array(idx).flatten()]
        sm = scores[m][np.array(idx).flatten()]
        for (x1, y1, x2, y2), s in zip(bm, sm):
            keep.append(((x1 - left) / r, (y1 - top) / r,
                         (x2 - left) / r, (y2 - top) / r, float(s), c))
    return keep


def detect_onnx(sess, frame):
    lb, r, left, top = letterbox(frame)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    out = sess.run(None, {"images": rgb.transpose(2, 0, 1)[None]})[0][0]
    b, s, c = [], [], []
    for x1, y1, x2, y2, conf, cls in out:
        if conf >= CONF:
            b.append([x1, y1, x2, y2]); s.append(conf); c.append(int(cls))
    if not b:
        return []
    return nms_count(np.array(b), np.array(s), np.array(c), r, left, top)


def decode_aipu(out_tensors, dequant, r, left, top, num_classes):
    """Group outputs into (box=4ch, cls=Nch) by spatial size; decode ltrb."""
    groups = {}
    for t, deq in zip(out_tensors, dequant):
        up = t.unpadded_shape  # (1,H,W,C)
        H, W, C = up[1], up[2], up[3]
        sl = deq[0, :H, :W, :C]
        groups.setdefault((H, W), {})[("box" if C == 4 else "cls")] = sl
    B, S, C = [], [], []
    for (H, W), g in groups.items():
        if "box" not in g or "cls" not in g:
            continue
        st = IMGSZ / H
        box, cls = g["box"], g["cls"]
        csig = 1 / (1 + np.exp(-np.clip(cls, -30, 30)))
        gx, gy = np.meshgrid(np.arange(W), np.arange(H))
        ax, ay = gx + 0.5, gy + 0.5
        l, t_, rr, b_ = box[..., 0], box[..., 1], box[..., 2], box[..., 3]
        x1 = (ax - l) * st; y1 = (ay - t_) * st; x2 = (ax + rr) * st; y2 = (ay + b_) * st
        sc = csig.max(-1); cl = csig.argmax(-1); mk = sc >= CONF
        if mk.any():
            B.append(np.stack([x1[mk], y1[mk], x2[mk], y2[mk]], 1))
            S.append(sc[mk]); C.append(cl[mk])
    if not B:
        return []
    return nms_count(np.concatenate(B), np.concatenate(S), np.concatenate(C), r, left, top)


def run_aipu_model(path, frames):
    counts = []
    with Context() as ctx:
        m = ctx.load_model(path)
        iin, iout = m.inputs(), m.outputs()
        info = iin[0]
        conn = ctx.device_connect(None, 1)
        inst = conn.load_model_instance(m, num_sub_devices=1, aipu_cores=1)
        for frame in frames:
            lb, r, left, top = letterbox(frame)
            rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
            inp = (rgb.astype(np.int16) - 128).astype(np.int8)[None]  # NHWC int8
            padded = np.pad(inp, info.padding, mode="constant", constant_values=info.zero_point)
            inbuf = [np.ascontiguousarray(padded)]
            outbuf = [np.zeros(t.shape, np.int8) for t in iout]
            inst.run(inbuf, outbuf)
            deq = [((buf.astype(np.float32) - t.zero_point) * t.scale) for t, buf in zip(iout, outbuf)]
            dets = decode_aipu(iout, deq, r, left, top, 80)
            counts.append(len(dets))
    return counts


def pick_videos():
    vids = sorted(glob.glob(os.path.join(VIDEO_DIR, "*", "*.mp4")))
    by = {}
    for v in vids:
        by.setdefault(os.path.basename(os.path.dirname(v)), []).append(v)
    out = []
    for d in sorted(by):
        fs = by[d]
        out.append(next((f for f in fs if "14h" in f or "11h" in f or "17h" in f), fs[0]))
    return out


def main():
    videos = pick_videos()
    per = max(1, TARGET // len(videos))
    frames, cams = [], []
    for vid in videos:
        cam = os.path.basename(os.path.dirname(vid))
        cap = cv2.VideoCapture(vid)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for pos in np.linspace(int(n * 0.05), int(n * 0.95), per).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            fr = None
            for _ in range(12):
                ok, f = cap.read()
                if ok:
                    fr = f
            if fr is not None:
                frames.append(fr); cams.append(cam)
        cap.release()
    print(f"cached {len(frames)} frames, conf>={CONF}\n")

    results = {}  # model -> list[count]
    for name, path in ONNX.items():
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        results[name] = [len(detect_onnx(sess, f)) for f in frames]
        print(f"  {name:14} done")
    for name, path in AIPU.items():
        if not os.path.exists(path):
            print(f"  {name:14} SKIP (not compiled yet: {path})")
            continue
        try:
            results[name] = run_aipu_model(path, frames)
            print(f"  {name:14} done")
        except Exception as e:
            print(f"  {name:14} FAILED: {repr(e)[:140]}")

    order = [k for k in ["n-fp32", "s-fp32", "n-aipu(coco)", "s-aipu(coco)", "s-aipu(mix)"] if k in results]
    cam_set = sorted(set(cams))
    print(f"\n{'cam':>5} | " + " | ".join(f"{k:>13}" for k in order))
    for cam in cam_set:
        idxs = [i for i, c in enumerate(cams) if c == cam]
        cells = [f"{sum(results[k][i] for i in idxs):>13}" for k in order]
        print(f"{cam:>5} | " + " | ".join(cells))
    print("-" * (8 + 16 * len(order)))
    tot = {k: sum(results[k]) for k in order}
    print(f"{'TOTAL':>5} | " + " | ".join(f"{tot[k]:>13}" for k in order))
    print(f"{'/frame':>5} | " + " | ".join(f"{tot[k]/len(frames):>13.2f}" for k in order))
    base = tot.get("n-aipu(coco)")
    if base:
        print("\nvs imported n-aipu(coco) baseline:")
        for k in order:
            if k == "n-aipu(coco)":
                continue
            print(f"  {k:14}: {tot[k]-base:+d} vehicles ({100*(tot[k]-base)/base:+.1f}%)")


if __name__ == "__main__":
    main()
