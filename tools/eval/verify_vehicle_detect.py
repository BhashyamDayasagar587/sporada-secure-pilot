#!/usr/bin/env python3
"""Independent vehicle-detection verification (does NOT use the Voyager SDK / AIPU).

Runs the raw FP32 vehicle ONNX (models/weights/vehicle_yolo26n_640.onnx) via
onnxruntime on >=100 frames sampled across the demo videos, using the SAME
preprocessing and conf threshold as the SDK cascade (letterbox 640, RGB, /255,
conf>=0.4, vehicle classes {2,3,5,7}). Saves annotated snapshots and prints
per-frame detection stats.

Purpose: verify whether "vehicle detection is poor" is a MODEL problem or an
AIPU-quantization/compilation/preprocessing problem in the SDK cascade. If this
FP32 reference detects vehicles well, the model is fine and the regression is in
the SDK path.
"""
import csv
import glob
import json
import os
import sys

import cv2
import numpy as np
import onnxruntime as ort

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEIGHTS = os.path.join(REPO, "models/weights/vehicle_yolo26n_640.onnx")
VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
OUT_DIR = os.path.join(REPO, "tmp/vehicle_verify")
CONF = float(os.getenv("CONF", "0.4"))            # same as cascade.yaml
TARGET_SNAPS = int(os.getenv("SNAPS", "120"))     # >= 100
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
COCO_PERSON = 0
IMGSZ = 640


def letterbox(img, new=IMGSZ):
    h, w = img.shape[:2]
    r = min(new / h, new / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh))
    canvas = np.full((new, new, 3), 114, np.uint8)
    top, left = (new - nh) // 2, (new - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, left, top


def detect(sess, frame):
    lb, r, left, top = letterbox(frame)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    inp = rgb.transpose(2, 0, 1)[None]
    out = sess.run(None, {"images": inp})[0][0]  # (300, 6) xyxy,conf,cls
    dets = []
    for x1, y1, x2, y2, conf, cls in out:
        if conf < CONF:
            continue
        cls = int(cls)
        # un-letterbox back to original frame coords
        ox1 = (x1 - left) / r
        oy1 = (y1 - top) / r
        ox2 = (x2 - left) / r
        oy2 = (y2 - top) / r
        dets.append((ox1, oy1, ox2, oy2, float(conf), cls))
    return dets


def pick_videos():
    vids = sorted(glob.glob(os.path.join(VIDEO_DIR, "*", "*.mp4")))
    # one video per top-level camera dir for spread across scenes/times
    by_dir = {}
    for v in vids:
        by_dir.setdefault(os.path.basename(os.path.dirname(v)), []).append(v)
    chosen = []
    for d in sorted(by_dir):
        # take a midday-ish file if present, else first
        files = by_dir[d]
        pick = next((f for f in files if "14h" in f or "11h" in f or "17h" in f), files[0])
        chosen.append(pick)
    return chosen


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(OUT_DIR, "*")):
        os.remove(f)
    if not os.path.exists(WEIGHTS):
        sys.exit(f"missing weights: {WEIGHTS}")
    providers = ort.get_available_providers()
    sess = ort.InferenceSession(WEIGHTS, providers=providers)
    print(f"onnxruntime providers: {sess.get_providers()}")

    videos = pick_videos()
    per_video = max(1, TARGET_SNAPS // len(videos))
    print(f"{len(videos)} videos, ~{per_video} frames each, conf>={CONF}\n")

    rows = []
    snap_idx = 0
    for vid in videos:
        cam = os.path.basename(os.path.dirname(vid))
        cap = cv2.VideoCapture(vid)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        # sample evenly across the middle 90% of the video
        positions = np.linspace(int(n * 0.05), int(n * 0.95), per_video).astype(int)
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            # Seeking lands on the prior keyframe and inter-frames near GOP
            # boundaries can decode with smearing/corruption on these sources.
            # Decode a few frames forward so we use a cleanly-reconstructed frame.
            frame = None
            for _ in range(12):
                ok, f = cap.read()
                if ok:
                    frame = f
            if frame is None:
                continue
            dets = detect(sess, frame)
            veh = [d for d in dets if d[5] in VEHICLE_CLASSES]
            confs = [d[4] for d in veh]
            cls_counts = {}
            for d in veh:
                cls_counts[VEHICLE_CLASSES[d[5]]] = cls_counts.get(VEHICLE_CLASSES[d[5]], 0) + 1
            rows.append({
                "snap": snap_idx, "cam": cam, "frame": int(pos),
                "n_vehicles": len(veh),
                "n_person": sum(1 for d in dets if d[5] == COCO_PERSON),
                "max_conf": round(max(confs), 3) if confs else 0.0,
                "mean_conf": round(float(np.mean(confs)), 3) if confs else 0.0,
                "classes": json.dumps(cls_counts),
            })
            # annotate + save
            ann = frame.copy()
            for x1, y1, x2, y2, conf, cls in dets:
                if cls in VEHICLE_CLASSES:
                    color, label = (0, 255, 0), f"{VEHICLE_CLASSES[cls]} {conf:.2f}"
                elif cls == COCO_PERSON:
                    color, label = (255, 128, 0), f"person {conf:.2f}"
                else:
                    continue
                p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
                cv2.rectangle(ann, p1, p2, color, 2)
                cv2.putText(ann, label, (p1[0], max(0, p1[1] - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
            cv2.putText(ann, f"{cam} f{int(pos)}  vehicles={len(veh)}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.imwrite(os.path.join(OUT_DIR, f"snap_{snap_idx:03d}_{cam}_v{len(veh)}.jpg"), ann)
            snap_idx += 1
        cap.release()
        sub = [r for r in rows if r["cam"] == cam]
        zero = sum(1 for r in sub if r["n_vehicles"] == 0)
        tot = sum(r["n_vehicles"] for r in sub)
        print(f"  {cam}: {len(sub)} frames, {tot} vehicles, "
              f"{tot/max(1,len(sub)):.1f}/frame, {zero} empty frames")

    # summary
    with open(os.path.join(OUT_DIR, "results.csv"), "w", newline="") as fh:
        wri = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wri.writeheader()
        wri.writerows(rows)

    total_v = sum(r["n_vehicles"] for r in rows)
    confs = [r["max_conf"] for r in rows if r["n_vehicles"]]
    zero = sum(1 for r in rows if r["n_vehicles"] == 0)
    print("\n===== SUMMARY (FP32 onnxruntime reference) =====")
    print(f"frames analyzed     : {len(rows)}")
    print(f"total vehicles       : {total_v}")
    print(f"mean vehicles/frame  : {total_v/max(1,len(rows)):.2f}")
    print(f"frames with 0 vehicles: {zero} ({100*zero/max(1,len(rows)):.1f}%)")
    if confs:
        print(f"per-frame max-conf   : p50={np.percentile(confs,50):.3f} "
              f"p10={np.percentile(confs,10):.3f} min={min(confs):.3f}")
    print(f"snapshots + results.csv in: {OUT_DIR}")


if __name__ == "__main__":
    main()
