#!/usr/bin/env python3
"""Head-to-head: yolo26n vs yolo26s vehicle detection (FP32 onnxruntime, identical
preprocessing/threshold). Same sampled frames for both models. Saves side-by-side
annotated snapshots (n=left, s=right) and prints per-cam + overall stats.

Class map is COCO for both (2 car / 3 motorcycle / 5 bus / 7 truck) — verified
from each ONNX's metadata, so the comparison is apples-to-apples.
"""
import glob
import os

import cv2
import numpy as np
import onnxruntime as ort

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = {
    "n": os.path.join(REPO, "models/weights/vehicle_yolo26n_640.onnx"),
    "s": os.path.join(REPO, "models/weights/vehicle_yolo26s_640.onnx"),
}
VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
OUT_DIR = os.path.join(REPO, "tmp/vehicle_compare")
CONF = float(os.getenv("CONF", "0.4"))
TARGET = int(os.getenv("SNAPS", "120"))
VEH = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
IMGSZ = 640


def letterbox(img, new=IMGSZ):
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((new, new, 3), 114, np.uint8)
    top, left = (new - nh) // 2, (new - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh))
    return canvas, r, left, top


def detect(sess, frame):
    lb, r, left, top = letterbox(frame)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    out = sess.run(None, {"images": rgb.transpose(2, 0, 1)[None]})[0][0]
    dets = []
    for x1, y1, x2, y2, conf, cls in out:
        if conf < CONF or int(cls) not in VEH:
            continue
        dets.append(((x1 - left) / r, (y1 - top) / r,
                     (x2 - left) / r, (y2 - top) / r, float(conf), int(cls)))
    return dets


def draw(frame, dets, tag):
    a = frame.copy()
    for x1, y1, x2, y2, conf, cls in dets:
        cv2.rectangle(a, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
        cv2.putText(a, f"{VEH[cls]} {conf:.2f}", (int(x1), max(0, int(y1) - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(a, f"{tag}: {len(dets)} veh", (10, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
    return a


def pick_videos():
    vids = sorted(glob.glob(os.path.join(VIDEO_DIR, "*", "*.mp4")))
    by_dir = {}
    for v in vids:
        by_dir.setdefault(os.path.basename(os.path.dirname(v)), []).append(v)
    out = []
    for d in sorted(by_dir):
        files = by_dir[d]
        out.append(next((f for f in files if "14h" in f or "11h" in f or "17h" in f), files[0]))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(OUT_DIR, "*")):
        os.remove(f)
    sess = {k: ort.InferenceSession(p, providers=["CPUExecutionProvider"]) for k, p in MODELS.items()}
    videos = pick_videos()
    per = max(1, TARGET // len(videos))

    agg = {k: {"veh": 0, "empty": 0, "confsum": 0.0, "confn": 0} for k in MODELS}
    percam = {}
    idx = 0
    wins = {"n": 0, "s": 0, "tie": 0}
    for vid in videos:
        cam = os.path.basename(os.path.dirname(vid))
        percam[cam] = {k: 0 for k in MODELS}
        cap = cv2.VideoCapture(vid)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for pos in np.linspace(int(n * 0.05), int(n * 0.95), per).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            frame = None
            for _ in range(12):
                ok, f = cap.read()
                if ok:
                    frame = f
            if frame is None:
                continue
            d = {k: detect(sess[k], frame) for k in MODELS}
            for k in MODELS:
                agg[k]["veh"] += len(d[k])
                percam[cam][k] += len(d[k])
                if not d[k]:
                    agg[k]["empty"] += 1
                for det in d[k]:
                    agg[k]["confsum"] += det[4]; agg[k]["confn"] += 1
            cn, cs = len(d["n"]), len(d["s"])
            wins["s" if cs > cn else "n" if cn > cs else "tie"] += 1
            # save side-by-side for frames where they differ most, plus a sampling
            if abs(cs - cn) >= 2 or idx % 7 == 0:
                combo = np.hstack([draw(frame, d["n"], f"{cam} yolo26n"),
                                   draw(frame, d["s"], f"{cam} yolo26s")])
                cv2.imwrite(os.path.join(OUT_DIR, f"cmp_{idx:03d}_{cam}_n{cn}_s{cs}.jpg"), combo)
            idx += 1
        cap.release()

    print(f"frames per model: {idx}   conf>={CONF}\n")
    print(f"{'cam':>5} | {'yolo26n':>8} | {'yolo26s':>8} | {'delta':>6}")
    for cam in percam:
        vn, vs = percam[cam]["n"], percam[cam]["s"]
        print(f"{cam:>5} | {vn:>8} | {vs:>8} | {vs-vn:+6d}")
    print("-" * 38)
    print("\n===== OVERALL =====")
    for k in MODELS:
        a = agg[k]
        mc = a["confsum"] / max(1, a["confn"])
        print(f"yolo26{k}: {a['veh']:>4} vehicles | {a['veh']/idx:.2f}/frame | "
              f"{a['empty']} empty frames | mean conf {mc:.3f}")
    dv = agg["s"]["veh"] - agg["n"]["veh"]
    print(f"\ndelta (s - n): {dv:+d} vehicles ({100*dv/max(1,agg['n']['veh']):+.1f}%)")
    print(f"per-frame winner: yolo26s={wins['s']}  yolo26n={wins['n']}  tie={wins['tie']}")
    print(f"\nside-by-side snapshots in: {OUT_DIR}")


if __name__ == "__main__":
    main()
