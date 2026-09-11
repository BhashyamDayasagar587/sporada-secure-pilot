# Detection & OCR Quality

Consolidated record of the quality work (June 2026) on the Axelera-Metis ALPR pilot:
**vehicle detection**, **plate OCR/stabilization**, and **tracking** — what we tried, the
measured results, and what we chose. Companion: `docs/THROUGHPUT.md`. Reproduce scripts in
`tools/eval/`.

---

# Part A — Vehicle detection (model selection)

**Problem.** Live AIPU detection was poor (dense junctions ~6 boxes where ~20 vehicles).
Root cause: the imported **yolo26n loses ~40% of detections to Metis INT8 quantization**
(yolo26 has a transformer-attention block the compiler flags "may not be supported").

**What we tried** (veh/frame, sampled deployment frames):

| Model | FP32 ref | on-AIPU (domain-cal) | Metis fps (zoo) | Note |
|---|---|---|---|---|
| yolo26n (imported) | 4.33 | 2.58 (baseline) | 662 | −40% to quant |
| yolo26s (ours export) | 7.25 | 10.38* | 498 | +100% vs n |
| yolo26s (Axelera official onnx) | — | 10.64* | 498 | ≈ ours (+2.5%, same weights) |
| **yolov8s** | — | **13.40*** | **643** | **+29% vs yolo26s, no attention** |
| yolov8m | 10.71 | 15.25* | 242 | +47% but 2.4× cost |
| yolo11s / yolo11m | 9.08 / 9.64 | — | 565 / 269 | attention (same quant risk) |
| yolov8n | 9.44 | — | — | too weak (−35% vs s) |

\* on-AIPU veh/frame measured via the SDK pipeline on 4 busy cams (different frame set →
higher absolute counts than the FP32 row; the *relative* ranking is what matters).

Also tried: **input resolution & tiling** (on busy frames) — yolov8s @640 14.6, @1280 22.4
(+53%), tiled-3×2 27.9 (+90%); but full-frame tiling **double-counts large vehicles at tile
borders** (verified), and yolov8s@960 **overflows Metis L1** (aborted). "Is it our
compilation/calibration?" — no: official vs our ONNX = +2.5% (noise); COCO vs domain calib
within ~4% (domain slightly better). Our build already uses Axelera's official ONNX + their
compiler config + decoder.

**What we chose.** **Stock `yolov8s` @ 640, domain-calibrated** (315 local frames + 120 IDD,
unlabeled — PTQ uses images only). Best accuracy/throughput, no attention → clean INT8,
643 fps headroom. Deployed: `config/cascade/vehicle-plate-cascade-v8s.yaml` →
`models/cascade-build-v8s/`, wired via `deploy/.env`. **Net on-AIPU: +158% vehicles vs the
shipped yolo26n, +85% plates end-to-end** (more vehicle crops → more plates; plate model
unchanged). Resolution > capacity (yolov8s@1280 ≈ yolov8m@1280); the affordable recall lever
later is **far-region ROI tiling**, not a bigger model or full-frame tiling.

**Plate detector: unchanged.** `plate_yolo26n_224` is **99% recall @IoU0.5 at both FP32 and
on the AIPU** (no quant loss); stock yolov8 can't replace it (no "plate" class). It's not a
bottleneck — plate gains come from the vehicle upgrade.

---

# Part B — Plate OCR & stabilization

**Problem (from 9,931 live `plate_read` events).** 100% frame-to-frame **flip**, 0% of tracks
ever repeat a read, mean 8.9 distinct strings/track (max 48); 26% malformed, 40% repeated-char
garbage (4444/EEEE); even the state code flipped every frame. **The OCR model is NOT the
problem** — it's **89% on the test set, whose crops are 384×192 px** (downsampled to the 128px
input → sharp). **Live plates are 36 px median** (p90 62) → upsampled ~3.5× → blur. Industry
threshold is **~100 px plate width**. The event stream published the raw per-frame text; the
stabilizer's vote never converged on this noise.

**What we tried (all 4 implemented & measured):**

| Step | Change | Measured effect | Verdict |
|---|---|---|---|
| **1. Vote + confirm-and-hold** | per-track weighted positional vote, lock once confirmed, publish confirmed-only | events **9,931 → 125** (1/track), flip **100% → 0%**, format-valid **→ 100%**, ~5-frame latency | ✅ **chosen — wired** |
| **2. Size/conf/format gating** | conf≥0.4 + wide Indian-format regex + conf×size weighting | per-read valid **74% → 84%**, garbage gated, confirmations 8% → **10%** | ✅ **chosen — wired** (size as *weight*; hard ≥60-80px confirmed only 6-13 tracks) |
| **3. Plate rectification** | rotation deskew before OCR | tilted OCR **79% → 80% (+1pt)** — affine can't undo perspective (lit: homography ≈ +3%) | ⏸️ **deferred** |
| **4. OC-SORT tracking** | vs CentroidTracker, 300-frame clip | **89 vs 85 IDs**, median 55 vs 64-frame tracks, ~8-9% fragments — no gain | ❌ **skipped** (tracking already adequate) |

Wide Indian-plate regex covers standard/HSRP/Delhi (`SS D(D) L(LL) NNNN`) **and BH series**
(`YY BH NNNN L(L)`), with space/hyphen normalization.

**What we chose.** **Steps 1+2** (wired in `pipeline/ocr_stabilizer.py` + `stream_fleet_sdk.py`):
the pipeline now emits **one confirmed, format-valid plate per track** instead of a 100%-flipping
garbage flood. Correct *precision* behavior. Steps 3 (marginal) and 4 (tracking already fine)
not adopted.

**The remaining ceiling is capture size, not software.** Tracks are long (median 64 frames)
and stabilization works, yet only ~10% confirm — because plates are 36px vs the ~100px
threshold. Next *quality* lever (separate effort): **near-approach OCR** (gate to plates
≥~80-100px), higher-res capture, or plate super-resolution. 4-corner homography rectification
(~+3%) and a blur-robust OCR (LPRNet/CRNN-CTC) are secondary.

---

## Reproduce (`tools/eval/`)

| Script | Purpose |
|---|---|
| `screen_models_fp32.py` | FP32 model screen (Part A) |
| `compare_aipu_models.py` / `bakeoff_aipu.py` | on-AIPU model comparison |
| `screen_inference_strategy.py` / `verify_strategy_visual.py` | resolution / tiling |
| `eval_plate_models.py` / `eval_end2end_plates.py` | plate recall + end-to-end yield |
| `study_ocr_quality.py` | OCR quality from the live redis stream (Part B) |
| `replay_ocr_fix.py` | measure Steps 1+2 by replaying recorded reads |
| `measure_rectification.py` | Step 3 tilt-recovery on the GT OCR set |
| `compare_trackers.py` | Step 4 CentroidTracker vs OC-SORT |

Key sources: Plate Recognizer / Axis / Bosch LPR capture guides (~100px plate-width
threshold); arXiv 2011.14936 (segmentation-free ALPR), 2501.02270 (best-frame selection),
2507.17335 (TransLPRNet), IEEE 7407810 (homography rectify ≈ +3%); IndiaForensic / Wikipedia
"Vehicle registration plates of India" (formats incl. BH series).
