"""Compile the three ALPR models for the Axelera Metis PCIe AIPU.

Wraps the Voyager SDK `axc compile` CLI. Run on the Intel host that has
voyager-sdk installed (not inside the runtime container). Produces
`models/axelera/{vehicle,license_plate,ocr}.axl`.

Usage:
    python tools/compile_axelera.py [--target metis-pcie]

Prereqs:
    1. Voyager SDK installed (see docs/port-axelera.md).
    2. Calibration images in tools/calibration/{vehicle,plate,ocr}/.
    3. Source models at:
        models/pytorch/yolo26n.pt
        models/pytorch/yolo26n_plate_detection_224.pt
        models/onnx/cct.onnx
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTORCH_DIR = ROOT / "models" / "pytorch"
ONNX_DIR = ROOT / "models" / "onnx"
OUT_DIR = ROOT / "models" / "axelera"
CALIB_DIR = ROOT / "tools" / "calibration"


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def ensure_yolo_onnx(pt_path: Path, imgsz: int) -> Path:
    onnx_path = pt_path.with_suffix(".onnx")
    if onnx_path.exists():
        return onnx_path
    run([
        "yolo", "export",
        f"model={pt_path}",
        "format=onnx",
        f"imgsz={imgsz}",
        "opset=17",
        "dynamic=False",
        "simplify=True",
    ])
    return onnx_path


def compile_one(name: str, onnx_path: Path, target: str, calib_subdir: str) -> Path:
    out_path = OUT_DIR / f"{name}.axl"
    calib = CALIB_DIR / calib_subdir
    if not calib.exists():
        raise SystemExit(
            f"Calibration set missing: {calib}. Drop ~200 representative crops there."
        )
    run([
        "axc", "compile",
        str(onnx_path),
        "--target", target,
        "--quantize", "int8",
        "--calibration-dir", str(calib),
        "--output", str(out_path),
    ])
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="metis-pcie", help="Voyager target board")
    parser.add_argument("--only", choices=("vehicle", "plate", "ocr", "all"), default="all")
    args = parser.parse_args()

    if shutil.which("axc") is None:
        sys.stderr.write("axc (Voyager SDK CLI) not found in PATH. See docs/port-axelera.md.\n")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    built: dict[str, Path] = {}

    if args.only in ("vehicle", "all"):
        onnx = ensure_yolo_onnx(PYTORCH_DIR / "yolo26n.pt", imgsz=640)
        built["vehicle"] = compile_one("vehicle", onnx, args.target, calib_subdir="vehicle")

    if args.only in ("plate", "all"):
        onnx = ensure_yolo_onnx(PYTORCH_DIR / "yolo26n_plate_detection_224.pt", imgsz=224)
        built["license_plate"] = compile_one("license_plate", onnx, args.target, calib_subdir="plate")

    if args.only in ("ocr", "all"):
        built["ocr"] = compile_one("ocr", ONNX_DIR / "cct.onnx", args.target, calib_subdir="ocr")

    print("\nCompiled:")
    for name, path in built.items():
        print(f"  {name:>14} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
