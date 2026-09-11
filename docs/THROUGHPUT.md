# Throughput & utilization track (parked)

Investigation into pushing one box (Core Ultra 7 255H + Axelera Metis AIPU) as far
as it goes on 1080p streams. The track stays **parked behind the Monday
correctness focus** (see `tmp/PILOT_GUIDE.md`) — but the hardware blocker that
originally parked it is now cleared: the Metis is back on the bus and the SDK
connects (see *Hardware status*). All findings below are measured on that box.

## Targets

| Milestone | Scale | Total fps | Verdict |
|-----------|-------|-----------|---------|
| **Monday demo** | **15 cams × 10 fps** | **150** | **Feasible** — sits *below* the measured ~175 fps end-to-end ceiling (#2). Run `CONSUMERS=3–4`. |
| Original / stretch | 30 cams × 12 fps | 360 | **Not reachable on one box at 1080p** — ~1.8× the decode ceiling, which *collapses* past ~20 cams (#1). Needs a 2nd box, lower detection resolution, or a lighter cascade. |

For context, the 20 × 10 scale these findings were first measured against falls
between the two: detection can feed it (~207 fps) but the consume side settles at
~8.7 fps/cam (~175 fps total), so 20 × 10 just *misses* 10/cam while **15 × 10
clears it with headroom**.

## Headline findings

**1. The detection/decode pipeline tops out ~200 cam-frames/s at 1080p, and
collapses past ~20 cameras** (raw pipeline, no consume work — `run/probe_ceiling.py`):

| Cameras | Requested fps | Delivered total | Per cam | Notes |
|--------:|--------------:|----------------:|--------:|-------|
| 20 | 10 | ~207 fps | 10.4 | clean |
| 24 | 12 | ~145 fps | 6.0 | h264 decode errors |
| 30 | 12 | ~136 fps | 4.5 | decode errors; *below* 20-cam total |

Adding cameras past ~20 *reduces* total goodput — saturation collapse, not a
plateau. **30 × 12 = 360 fps is ~1.8× over what one box can sustain at 1080p.**
Consistent with the 720p reference point (45 cams × 8 fps ≈ 360 worked): 1080p is
2.25× the decode pixels, which lands the ceiling near the measured ~200.

**2. End-to-end (with the full consume pipeline) settles at ~175 fps = 8.7 fps/cam**
at 20 cameras, optimal at **4–5 consumer processes** (1→111, 3→157, 4→173, 5→175,
6→166 — 6 regresses from CPU oversubscription).

**3. The consume-side cost is *not* where we assumed.** Per-frame consumer profile
(`PROFILE_CONSUMER=1`):

| Stage | Per-frame cost |
|-------|----------------|
| geometry filter | 0.02 ms (negligible) |
| tracking | ~1 ms |
| traffic analytics (zones/lines) | 0.05 ms (negligible) |
| OCR bind + submit | 0.76–12 ms (dominant, spiky) |

Skipping zone analytics would save nothing. The cost is the OCR path.

**4. But OCR compute is *fast* — the 12 ms was never GPU time.** Benchmarking the
OCR model on the 100 plate calibration images (`run/bench_ocr.py`, iGPU):

- single-inference latency **1.45 ms** (p90 1.56), throughput **~692 infer/s**.

The iGPU has large OCR headroom and nothing else competes for it (detection is on
the Metis, decode on the media engine). So the 12 ms spikes were **consume-side
Python** — per-plate preprocessing (`resize`/`cvtColor`/`transpose`), parent-vehicle
matching, and **burst-blocking on a shallow 4-request async queue** (a frame with
many plates filled it, so `start_async` blocked even though the GPU was idle).

**Consequence:** the NPU offload is **not** on the critical path for OCR — the iGPU
isn't the bottleneck. The fix is queue depth + not blocking, not more OCR silicon.

**5. The frame crop/download is not the bottleneck either** — ROI-only NV12
readback gave only a marginal gain, and GPU-side cropping was refuted (the SDK
can't surface ROI crops to Python without surgery, and the crop costs ~6 fps).

## Code changes from this track

Committed (`359864c`):
- **ROI-only NV12 crop** on the dispatcher hot path (read only plate-ROI bytes from
  the decoded buffer at native resolution; full-frame `asarray` only for live view).

In the working tree (uncommitted — validate once the Metis is back, then commit):
- **OpenVINO `MULTI:GPU,NPU`** OCR device with device resolution + graceful fallback
  to GPU (so it's a no-op until the NPU enumerates). Default device, `OCR_DEVICE` env.
- **Deepened the OCR async queue** (4 → 16, `OCR_QUEUE_DEPTH`) so plate bursts are
  absorbed inflight instead of blocking the consume loop.
- **Non-blocking drop-on-full submit** — if all requests are busy, skip OCR for that
  frame (the track is read on a later frame; OCR is voted across frames anyway).
  Adds `submitted`/`dropped` counters surfaced in the consumer profile.
- **Profilers**: `PROFILE_CONSUMER=1` (per-stage consume breakdown), `PROFILE_DISP=1`
  (dispatcher per-frame breakdown). Helpers: `run/probe_ceiling.py`, `run/ceiling.sh`,
  `run/bench_ocr.py`, `run/measure.sh` (all under gitignored `run/`).

Note: the `models/cascade-build/*.axnet` working-tree changes are runtime touch
artifacts from loading the cascade — discard them, don't commit.

## Hardware status (updated 2026-06-03)

- **Metis AIPU — back and working.** ✅ Resolved. Previously absent from `lspci`
  after a warm reboot (`axr_device_connect failed: No device found`); it needed a
  **cold power-cycle**, which has been done. The SDK now connects:
  `metis-0:1:0 · 4 subdevices · 16 GB · firmware v1.6.0 · in_use=False`. (For next
  time: a PCI rescan / warm reboot does *not* reliably re-enumerate the M.2
  accelerator — only a cold power-cycle does, and remote recovery would need
  IPMI/BMC or a networked PDU, which this OEM board likely lacks.)
- **NPU — online for OpenVINO.** ✅ Resolved 2026-06-03. Two layered causes, both fixed:
  1. **Loader too old.** `libze1` was 1.21.9.0; the 1.33 NPU driver needs loader
     **≥1.27.0**, else `zeInit → UNSUPPORTED_VERSION` and 0 drivers. The fix isn't in
     the Intel GPU repo (tops out at 1.21.9.0) — installed `libze1 1.28.2-1~24.04~ppa1`
     from the **kobuk-team intel-graphics PPA** (noble build) and `apt-mark hold`'d it.
     Rollback deb cached at `/tmp/libze1_1.21.9.0-1136~24.04_amd64.deb`.
  2. **Stale SDK L0 layers shadowed the new loader.** The Voyager venv prepends
     `/opt/axelera/runtime-1.6.0-1/lib` to `LD_LIBRARY_PATH`, which carries a
     `libze_tracing_layer.so` at **1.15.0**; the 1.28.2 loader rejects it at init
     (`zelTracingDdiTableInit … UNSUPPORTED_VERSION`) → drivers skipped again, so the
     loader upgrade alone left OpenVINO at `['CPU','GPU']`. Fix: `start.sh` stages a
     clean, self-consistent L0 dir (loader + tracing + validation, all 1.28.x, copied
     from the system libs) into `run/ze-loader-override` and prepends it for the worker
     so the matching layers win.
  Verified through the worker launch path: OpenVINO enumerates `['CPU','GPU','NPU']`
  ("Intel(R) AI Boost"); the OCR transformer **compiles and runs on the NPU** (~287
  infer/s; `MULTI:GPU,NPU` engages both, `exec=GPU.0,NPU`). Still **upside, not critical
  path**: the iGPU alone covers the demo OCR load (#4), and whether `MULTI` actually
  beats iGPU-alone for this transformer is a tuning call to make against the live
  pipeline (the micro-bench didn't clearly favor it).

## Next steps (Metis is back — 2026-06-03)

1. **Re-run the 20×4 consumer profile** with the deep-queue + drop-on-full changes —
   confirm the OCR spikes collapse; expect 20 cams to approach the ~10 fps/cam the
   detection side can already feed. Then commit the working-tree changes.
2. **For a clean 20×10**, remaining consume-side levers if needed: trim per-plate
   preprocessing; CPU affinity (dispatcher on a P-core, consumers across E-cores) to
   scale consumers past 5 without contention.
3. **For >20 cameras @ 1080p it is hardware-bound** (one media engine + one Metis).
   Real options: lower the *detection* decode resolution (OCR needs native plate
   pixels, so not trivially separable from one RTSP stream), a lighter cascade, or a
   second box / second decode path. 30 × 12 @ 1080p is not reachable on a single box.
4. **NPU** — ✅ done (see *Hardware status*): loader upgraded, SDK-layer shadow worked
   around in `start.sh`, transformer OCR confirmed compiling/running on the NPU, and
   `OCR_DEVICE=MULTI:GPU,NPU` (the default) now picks it up. Remaining: A/B `MULTI` vs
   `GPU`-only on the live pipeline to decide whether routing OCR through the NPU is a
   net win for this transformer (the micro-bench was inconclusive).

## Model & end-to-end measurements (2026-06-03, deployed yolov8s cascade)

Targets restated: **immediate 15 cams × 12 fps = 180/s**, final **30 × 12 = 360/s**.

**Vehicle-model AIPU cost** (single Metis core, 640²; model choice is for *accuracy* —
see `docs/QUALITY.md` — and is throughput-neutral):

| model | ms/inf | fps/core | Metis fps (zoo, full chip) |
|---|---|---|---|
| yolo26n (old) | 8.2 | 122 | 662 |
| yolo26s | 10.9 | 92 | 498 |
| **yolov8s (deployed)** | ~10 | ~90 | **643** |
| yolov8m | ~26 | ~38 | 242 |

Vehicle inference is **not** the bottleneck at 15 cams (≥3 cascade cores ≫ 180/s).

**What we tried (end-to-end) & results:**

| Tried | Result |
|---|---|
| 4-cam test pipeline (yolov8s, `CONSUMERS=4`, 12fps) | 13 fps/cam, **drops=0** — comfortable |
| **15-cam @ 12fps**, `CONSUMERS=4`, OCR gating | sustained **~135-157 cam-frames/s = 9-10.5 fps/cam, consumer-drops=0** → ~75-87% of 180/s |
| Bottleneck localization | the **single dispatcher process is CPU-bound at ~257% (~2.6 cores)** doing pull + `detections_from_result` parse + plate crop; consumers idle (drops=0) |
| OCR gating (attempt cap + confirm-and-hold) | removes the every-frame OCR flood → reclaims consume-side compute (`docs/QUALITY.md` Part B) |

**Chosen / concluded:**
- **15×12 is ~85% there and gated by the single-threaded dispatcher** — *not* the AIPU, model,
  or consumers. **Next step: parallelize the dispatcher pull/parse/crop** (box isn't saturated,
  just that one process). Model stays yolov8s.
- **30×12 = 360/s is not reachable on one box** → 2nd Metis / 2nd decode path, lighter cascade,
  or fewer per-cam fps.

Reproduce: `./start.sh test` + `config/cameras-15.json`; scripts in `tools/eval/`.
