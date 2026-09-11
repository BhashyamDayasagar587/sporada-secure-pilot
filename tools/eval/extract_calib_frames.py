#!/usr/bin/env python3
"""Extract domain calibration frames from the deployment videos for INT8 PTQ.
Samples N frames per video evenly across the middle of each clip, decoding a few
frames forward from each seek so we keep cleanly-reconstructed frames (these
sources have corrupt GOPs on raw seeks). Saves full-res JPGs."""
import glob
import os

import cv2
import numpy as np

VIDEO_DIR = os.getenv("VIDEO_DIR", "/home/admin1/Videos/traffic_pilot_videos")
OUT = os.getenv("OUT", "/home/admin1/traffic-pilot/datasets/calib_local")
PER_VIDEO = int(os.getenv("PER_VIDEO", "9"))

os.makedirs(OUT, exist_ok=True)
vids = sorted(glob.glob(os.path.join(VIDEO_DIR, "*", "*.mp4")))
n_saved = 0
for vid in vids:
    cam = os.path.basename(os.path.dirname(vid))
    stem = os.path.splitext(os.path.basename(vid))[0].replace(" ", "_")[:40]
    cap = cv2.VideoCapture(vid)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    for j, pos in enumerate(np.linspace(int(n * 0.05), int(n * 0.95), PER_VIDEO).astype(int)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
        frame = None
        for _ in range(12):
            ok, f = cap.read()
            if ok:
                frame = f
        if frame is None:
            continue
        cv2.imwrite(os.path.join(OUT, f"{cam}_{stem}_{j:02d}.jpg"), frame)
        n_saved += 1
    cap.release()
print(f"saved {n_saved} calibration frames from {len(vids)} videos -> {OUT}")
