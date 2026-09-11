#!/usr/bin/env python3
"""On-AIPU bake-off via the SDK pipeline (family-agnostic decode). For each
(name, yaml, build_root) it runs create_inference_stream on the same frames,
counts vehicle detections (COCO {2,3,5,7}) and measures wall-clock fps.
Run with the live worker STOPPED (single-stream device)."""
import sys, time, pathlib
sys.path.insert(0, "/home/admin1/traffic-pilot/services/worker")
from axelera.app.config import HardwareCaps, HardwareEnable, SystemConfig
from axelera.app.stream import create_inference_stream
from stream_fleet_sdk import detections_from_result

V = "/home/admin1/Videos/traffic_pilot_videos"
# busy daytime sources (where model differences show)
SOURCES = [
    f"{V}/03/RAVINDRA BHARATI_Lakdikapul Bus Stop-2026-04-24_11h00min00s000ms.mp4",
    f"{V}/02/RAVINDRA BHARATI_PCR2-2026-04-24_14h00min00s000ms.mp4",
    f"{V}/04/RAVINDRA BHARATI_PCR-2026-04-24_17h00min00s000ms.mp4",
    f"{V}/20/20A.mp4",
]
NFRAMES = 240

# (label, network yaml, build_root)
MODELS = [
    ("yolo26n (orig)",  "/home/admin1/traffic-pilot/config/cascade/vehicle-plate-cascade.yaml",   "/home/admin1/traffic-pilot/models/cascade-build"),
    ("yolo26s-mine",    "/home/admin1/traffic-pilot/config/cascade/vehicle-plate-cascade-s.yaml",  "/home/admin1/traffic-pilot/models/cascade-build-s"),
    ("yolo26s-official","/home/admin1/traffic-pilot/config/cascade/vehicle-26s-official.yaml",     "/home/admin1/traffic-pilot/models/aipu-compare"),
    ("yolov8s",         "/home/admin1/traffic-pilot/config/cascade/vehicle-v8s.yaml",              "/home/admin1/traffic-pilot/models/aipu-compare"),
    ("yolov8m",         "/home/admin1/traffic-pilot/config/cascade/vehicle-v8m.yaml",              "/home/admin1/traffic-pilot/models/aipu-compare"),
]

def run(label, yaml, build):
    sc = SystemConfig(allow_hardware_codec=True, hardware_caps=HardwareCaps(
        vaapi=HardwareEnable.enable, opencl=HardwareEnable.detect, opengl=HardwareEnable.detect))
    st = create_inference_stream(system_config=sc, network=yaml, build_root=pathlib.Path(build),
        sources=[f"loop:{s}" for s in SOURCES], pipe_type="gst", aipu_cores=4,
        low_latency=True, specified_frame_rate=0)  # 0 = run as fast as possible (throughput)
    tot = n = 0; t0 = time.time()
    for fr in st:
        tot += sum(1 for d in detections_from_result(fr) if d.model_name == "vehicle")
        n += 1
        if n >= NFRAMES: break
    dt = time.time() - t0
    st.stop()
    return n, tot, tot/max(1,n), n/dt

def main():
    print(f"{'model':18} {'frames':>6} {'veh/frame':>10} {'fps(4-src)':>11}")
    rows = []
    for label, yaml, build in MODELS:
        if not pathlib.Path(build).exists():
            print(f"{label:18} SKIP (no build)"); continue
        try:
            n, tot, vpf, fps = run(label, yaml, build)
            rows.append((label, vpf, fps)); print(f"{label:18} {n:>6} {vpf:>10.2f} {fps:>11.1f}")
        except Exception as e:
            print(f"{label:18} FAILED: {repr(e)[:120]}")
    base = next((r for r in rows if r[0]=="yolo26s-mine"), None)
    if base:
        print(f"\nvs yolo26s-mine ({base[1]:.2f}/frame):")
        for label, vpf, fps in rows:
            if label==base[0]: continue
            print(f"  {label:18}: {100*(vpf-base[1])/base[1]:+6.1f}% veh   {fps:.0f} fps")

if __name__ == "__main__":
    main()
