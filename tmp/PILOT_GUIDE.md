# Pilot bring-up, verification & demo guide

For the engineer taking this over. Goal: bring the app up on our box, verify it
**end to end**, then **demo what works to the OTSI team and collect feedback** on
the parts listed in §8.

## 0. Scope — what to worry about, what not to

- **Pilot scale is 15 cameras @ 10 fps** to start. That's comfortably inside what
  the box handles — **do not worry about throughput/utilization.** That track is
  parked and owned separately (see `docs/THROUGHPUT.md`); ignore it for the demo.
- Your focus is **correctness and coverage**: do cameras, zones, inference, the use
  cases, and the emitted metadata all work properly, and are the models good enough.

## Deliverables for tomorrow (Definition of Done)

**Owner: Vaishnavi** (for all of the below). The bar is a clear **go / no-go on
moving the box to the deployment site and connecting the real 15 RTSP streams.**
Capture results against each item.

| Deliverable | Vaishnavi verifies with | Done when |
|---|---|---|
| All use cases run correctly | Vijay + Nitin | Every enabled use case fires the right event, with the right geometry, verified live |
| Emitted **metadata format** is correct | Vijay + Nitin | The `traffic:analytics` JSON matches the spec and carries everything OTSI needs |
| **Model accuracy** verdict | Nitin | Vehicle + plate detection and OCR are accurate enough on our footage — **or** a named replacement model is identified for vehicle/plate/OCR |
| **End-to-end** works | herself | File **and** RTSP cameras add from the UI, zones configure, inference is clean on every frame, metadata flows — all §3 checks pass |

**Go / No-Go:** if all four pass → **relocate the box to the deployment location and
connect the actual 15 RTSP streams.** If anything fails, record exactly what (which
camera / use case / model, plus the relevant log) so it's fixed before the move.
Throughput is **not** a gate for this decision (parked).

## 1. Bring up the device (COLD reboot — important)

The **Metis M.2 AIPU only re-enumerates on a cold power-cycle.** A warm `reboot`
can drop it off the PCIe bus, and then the worker fails with
`axr_device_connect failed: No device found`.

**To cold reboot:** full shutdown, leave it **powered off ~10 seconds**, then power
on. (Remote-only with no IPMI/PDU means you can't cold-cycle remotely — you need
physical access or out-of-band power. Don't `shutdown -h` from a remote session
unless you can power it back on.)

**Before starting the app, confirm the Metis is on the bus:**

```
lspci | grep -i axelera                 # must list the device
source /home/admin1/voyager-sdk/venv/bin/activate && axdevice   # must list the Metis
```

If `lspci` shows nothing → cold power-cycle again. A warm reboot or PCI rescan will
**not** reliably bring it back.

## 2. Start / stop the application

Everything runs host-native (no Docker). From `/home/admin1/traffic-pilot`:

```
CONSUMERS=4 ./start.sh        # redis + config-api (:8077) + UI (:5173) + worker
./stop.sh                     # tears it all down
```

- **Set `CONSUMERS=4`** for the 15-camera pilot (put it in `deploy/.env`). The
  default of 1 runs everything in one process and won't sustain 15×10; 4 consumer
  processes will.
- **First time on a fresh box:** copy `deploy/.env.example` → `deploy/.env` and set
  `VIDEO_DIR`, `VOYAGER_VENV`, `REDIS_PORT`, `CAMERAS_FILE`; then run `./setup.sh`
  (installs redis, ffmpeg, Node, UI deps).
- **Dashboard:** http://<box-ip>:5173 · **API:** http://<box-ip>:8077
- **Logs:** `run/worker.log`, `run/config-api.log`, `run/ui.log`

**Healthy worker** (`run/worker.log`): `inference stream up; consuming…`, then every
10 s a line like `SDK inference: 150 cam-frames/s (10.0 fps/cam x15) | plate=… ocr_text=…`.
Per-cam fps near 10 and `ocr_text` rising = inference + OCR are working.

## 3. End-to-end verification (the demo checklist)

Work through these on the box and note what passes / what needs fixing.

**3.1 Add a file-backed camera from the UI.** Cameras page → add a camera whose
source URI is a path **relative to `VIDEO_DIR`** (e.g. `20/20A.mp4`). Save. Confirm:
it appears in the list, the worker picks it up within ~5 s, and a snapshot renders
in Zone Studio (config-api pulls one frame via ffmpeg).

**3.2 Add an RTSP camera from the UI.** Add a camera with source URI `rtsp://…`.
Confirm the snapshot renders and the worker starts decoding it (worker.log shows the
camera). Verify against a real OTSI RTSP feed if available — we've mostly tested
file sources, so **this is a key thing to validate live.**

**3.3 Configure zones/lines per use case (Zone Studio).** For each use case you want
to demo, draw the geometry it needs (see §4), assign it, and Save. Saving is now
idempotent (each shape carries a stable id), existing geometry loads onto the canvas
when you open a camera, and there's a per-shape Delete. **Detection masks**
(Analysis ROI / Road ROI) are now authorable too — use them to exclude clutter
(parked cars off-road, billboards, sky). The worker **hot-reloads** the change:
saving re-execs the worker within ~5 s (watch `run/worker.log` for the re-exec), no
manual restart. **Still watch the trap:** a line/zone with the wrong
`purpose`/`type`, or a use case toggled OFF, is silently dropped — Zone Studio now
shows a "use case disabled" warning, and the Cameras use-case panel shows "no
geometry" / "last fired Xs ago" per use case.

**3.4 Verify inference is proper on all frames (Live View).** Open a camera's live
page. The worker draws on demand: green = vehicle, orange = plate + OCR text, and
the **authored zones/lines/masks are overlaid** (yellow lines, cyan zones, magenta
masks) so you can confirm a counting line is where you drew it. Confirm boxes track
smoothly frame-to-frame, plates are detected, and OCR text is sane. Check several
cameras.

**3.5 Verify each use case fires (see §4 + §5).** Drive the scenario (a vehicle
crossing a counting line, sitting in a no-parking zone, going wrong-way, etc.) and
confirm the matching event appears in the metadata stream and on the dashboard
(Analytics / Plates pages).

**3.6 Inspect the emitted metadata (§5).** Tap the redis stream and confirm the JSON
matches the spec — this is the contract we hand OTSI.

**3.7 Assess the models (§6).** Decide whether vehicle/plate/OCR need swapping for
Indian traffic — see §6 for what to look for.

### Inspecting the live metadata stream

```
redis-cli XREVRANGE traffic:analytics + - COUNT 1        # newest payload
redis-cli XLEN traffic:analytics                          # is it flowing?
```

## 4. Use case ↔ geometry ↔ output contract (verify this logic)

A use case only runs if the camera has the **right geometry with the right
`purpose`/`type`** (and `direction` for lines). This is the config→model logic to
test.

| Use case | Geometry | Line `purpose` / Zone `type` | Direction | Emits event |
|---|---|---|---|---|
| `vehicle_counting` | line (+opt. counting zone) | `object_counting` | required | `vehicle_count` |
| `pedestrian_counting` | line | `pedestrian_counting` | required | `pedestrian_count` |
| `wrong_way_driving_detection` | line | `wrong_way_direction` | required | `wrong_way` |
| `stopped_vehicle_detection` | zone | type `stopped_vehicle` | — | `stopped_vehicle` |
| `vehicle_in_pedestrian_zone_alert` | zone | type `pedestrian` | — | `vehicle_in_pedestrian_zone` |
| `parking_violation_detection` | zone | type `no_parking` | — | `parking_violation` |
| `plate_detection` | zone (opt.) | type `plate_roi` | — | `plate_read` |

- **Lines** count when a tracked centroid crosses (≥2 track hits, ≥8 px movement);
  direction is `side_a_to_side_b` / `side_b_to_side_a`. Wrong-way compares the
  movement vector against the line's required direction.
- **Zone alerts** (`stopped_vehicle` ~10 s, `parking_violation` ~15 s) fire on dwell
  time; `vehicle_in_pedestrian_zone` fires immediately on entry.
- **Masks** (`type: analysis_roi` / `road_roi`) act as a detection filter for *all*
  use cases — detections outside them are dropped.
- **Plate detection** runs the OCR; a `plate_read` is emitted once per vehicle track
  when the OCR text stabilizes (multi-frame vote).

## 5. Emitted metadata format

Published per frame as a JSON string to the redis stream **`traffic:analytics`**
(`schema_version: "5.0"`, `message_type: "camera_analytics"`). Shape (trimmed):

```json
{
  "schema_version": "5.0",
  "message_type": "camera_analytics",
  "camera": { "id": "cam01", "name": "cam01" },
  "frame": { "index": 120, "resolution": { "width": 1920, "height": 1080 } },
  "summary": { "objects": 3, "events": 1 },
  "objects": [
    {
      "id": 42, "class": "car", "confidence": 0.92,
      "bbox": { "x1":100,"y1":50,"x2":250,"y2":300,"width":150,"height":250 },
      "center": { "x":175,"y":175 },
      "attributes": {
        "track_age": 25, "track_hits": 24,
        "zones":    [ { "use_case":"vehicle_counting","id":"zone:..","name":".." } ],
        "use_cases":[ { "name":"vehicle_counting","state":"line_crossed","event_type":"vehicle_count","count":{"total":1,"direction":{"key":"side_a_to_side_b","count":1}} } ],
        "violations":[ { "name":"stopped_vehicle_detection","event_type":"stopped_vehicle","duration_seconds":15.3 } ],
        "license_plates":[ { "id":"plate:42:0","text":"TS09AB1234","confidence":0.98,"bbox":{...} } ]
      }
    }
  ],
  "camera_analytics": { "use_cases": [ { "name":"vehicle_counting","lines":[ { "line":{"id":"line:.."},"total":5,"directions":[{"key":"side_a_to_side_b","count":3}] } ] } ] },
  "events": [
    { "event_type":"vehicle_count","use_case":"vehicle_counting","object_id":42,"timestamp":"…","subject":{"track_id":42,"type":"car","bbox":{…}},"location":{"type":"line","id":"line:.."},"count":{"total":1,"direction":{"key":"side_a_to_side_b"}} },
    { "event_type":"plate_read","use_case":"plate_detection","subject":{"parent_track_id":42,"type":"license_plate","bbox":{…}},"plate":{"text":"TS09AB1234"} }
  ]
}
```

Key points for OTSI integration:
- **`objects[]`** = per-frame tracked state (vehicles with `id`=track id, their
  zones/use-case states, and nested `license_plates[]` with OCR `text`).
- **`events[]`** = discrete things that happened this frame (a count, a violation, a
  plate read). Each has `event_type`, `use_case`, `object_id`, `subject`, `location`.
- **`camera_analytics.use_cases[]`** = running per-camera aggregates (line totals by
  direction).
- Plate text lives on `objects[].attributes.license_plates[].text` and on the
  `plate_read` event's `plate.text` (with `subject.parent_track_id` = vehicle).

## 6. Models — and whether to swap them

| Stage | Model | Input | Notes |
|---|---|---|---|
| Vehicle detect | yolo26n (COCO-trained) | 640×640 | Emits car / motorcycle / bus / truck (COCO ids); on the Metis |
| Plate detect | yolo26n plate | 224×224 | 1 class, runs on vehicle crops; on the Metis |
| Plate OCR | CCT (transformer) | 128×64 | alphabet `0-9 A-Z _`; on the Arc iGPU (OpenVINO) |

**What to evaluate for an Indian-traffic pilot (feedback for OTSI):**
- **Vehicle model is COCO-trained** — does it reliably catch local vehicle types
  (auto-rickshaws, etc.)? Misses here cascade into missed plates. Candidate to
  retrain/swap if coverage is poor.
- **Plate detector** — is it finding plates across angles/lighting on the real feeds?
- **OCR (CCT)** — does it read **Indian plate formats** accurately? It can be noisy;
  this is the most likely swap. Verify the read text against ground truth.

## 7. Quick troubleshooting

- **Worker exits `No device found`** → Metis off the bus → cold power-cycle (§1).
- **No snapshot in Zone Studio** → check `VIDEO_DIR`/the RTSP URL; config-api uses
  ffmpeg on the source. See `run/config-api.log`.
- **A use case never fires** → geometry has the wrong `purpose`/`type`, or no
  `direction` on a line (§4) — the worker silently drops mismatched geometry.
- **Per-cam fps well below 10** → make sure you started with `CONSUMERS=4`.
- **UI not loading** → check `run/ui.log` (vite) and that `npm install` ran (`./setup.sh`).

## 8. Demo to OTSI — collect feedback on

Show what's working on our device and get OTSI's read on each:
1. Adding cameras from the UI — **file** sources and **RTSP** sources.
2. Zone/line authoring per use case in Zone Studio.
3. Inference quality on every frame (boxes, tracking, plate reads in Live View).
4. **Model fit** — vehicle detection, plate detection, and OCR accuracy on their
   real footage; what to retrain/swap.
5. All **seven use cases** firing correctly end to end.
6. The **emitted metadata format** (§5) — does it carry everything they need.
7. The **use-case ↔ zone ↔ config ↔ output logic** — is the geometry contract right.

(Utilization/throughput is **out of scope** for this demo — parked separately.)
