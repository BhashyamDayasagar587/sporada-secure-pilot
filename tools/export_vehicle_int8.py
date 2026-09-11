"""Quantize the yolo26s vehicle detector to INT8 (NNCF PTQ) for the all-OpenVINO
worker. INT8 ~doubles throughput on the Arc iGPU and the NPU is INT-optimized,
which is the lever to lift the all-OV path from ~5 to ~7-8 cams @ 12fps.

Source is the same yolo26s.onnx the Axelera -s cascade was built from (NMS baked
in, output [1,300,6]). Calibration uses the COCO repr set. transform_fn reproduces
the detector's exact preprocessing: letterbox 640 (gray 114) -> RGB -> /255 -> NCHW.

Usage:
    python tools/export_vehicle_int8.py            # -> /tmp/yolo26s_int8/yolo26s.xml
Then validate parity vs FP16 before replacing models/openvino/vehicle.xml.
"""
from __future__ import annotations

import glob
import sys

import cv2
import numpy as np
import openvino as ov
import nncf

ONNX = "/home/admin1/traffic-pilot/yolo26s.onnx"
CAL_GLOB = "/home/admin1/.cache/axelera/data/coco2017_repr400/*.jpg"
OUT = "/tmp/yolo26s_int8/yolo26s.xml"
SZ = 640
SUBSET = 300


def letterbox(im, size=SZ):
    h, w = im.shape[:2]
    s = size / max(h, w)
    nw, nh = round(w * s), round(h * s)
    r = cv2.resize(im, (nw, nh))
    c = np.full((size, size, 3), 114, np.uint8)
    px, py = (size - nw) // 2, (size - nh) // 2
    c[py:py + nh, px:px + nw] = r
    return c


def transform_fn(path):
    im = cv2.imread(path)
    if im is None:
        im = np.zeros((SZ, SZ, 3), np.uint8)
    rgb = cv2.cvtColor(letterbox(im), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.transpose(rgb, (2, 0, 1))[None]


def main() -> int:
    cal = sorted(glob.glob(CAL_GLOB))[:SUBSET]
    print(f"calibration images: {len(cal)}")
    core = ov.Core()
    model = core.read_model(ONNX)
    ds = nncf.Dataset(cal, transform_fn)
    # PERFORMANCE preset = symmetric INT8 weights+activations (best speed). If parity
    # regresses, retry with preset=nncf.QuantizationPreset.MIXED or add ignored_scope
    # for the detection-head / NMS subgraph.
    q = nncf.quantize(model, ds, subset_size=SUBSET)
    ov.save_model(q, OUT)
    print(f"saved INT8 IR -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
