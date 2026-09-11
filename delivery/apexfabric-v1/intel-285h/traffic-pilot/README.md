# Traffic Pilot Runtime - ApexFabric V1 Intel Delivery

This v3 package follows the same API contract shape as the latest `Documents/PIPELINE` traffic delivery while limiting active applications to vehicle counting, pedestrian counting, ANPR, and fire/smoke detection.

## Image

```text
traffic-pilot-runtime:intel-285h-2026.09.11-v3
```

The image listens on `0.0.0.0:8080`, runs as UID/GID `10001`, uses the Intel 285H runtime base, and has no UI or Redis dependency. Mount desired state at `/configs/desired_state.json`, camera secrets under `/run/secrets/apexfabric`, and persistent state at `/state`.

## Public Contract

- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `GET /events` as continuous server-sent events with idle heartbeats
- `GET /snapshots/<state-relative-path>` for event images

`/metrics` follows `metrics.schema.json`. Analytics events follow `analytics-event.schema.json`; snapshot fields use `snapshot_ref` and `snapshot_url`, not host filesystem paths.

## Desired State

Each camera uses `solution_pack: "traffic"` and one or more of these apps:

- `vehicle_counting`
- `pedestrian_counting`
- `anpr`
- `fire_smoke_detection`

Geometry is optional. If no line or zone is supplied, counting uses the whole frame. When geometry is supplied, use typed `config.lines.<app>` or `config.zones.<app>` as shown in `desired-state.example.json`.

# Traffic Pilot Limited Runtime - ApexFabric V1 Intel Delivery

API-only traffic-pilot runtime for Intel 285H limited to people counting, vehicle counting, ANPR, and fire/smoke detection. The image contains no UI, no npm,
and no Vite dashboard. It exposes runtime control and observation endpoints on
`:8080`.

## Runtime

The container starts:

```text
python -m traffic_pilot_runtime.solution_image_entrypoint
```

It reads `/configs/desired_state.json`, validates it against the V1 contract,
accepts only `vehicle_counting`, `pedestrian_counting`, `anpr`/`plate_detection`,
and `fire_smoke_detection`, compiles the active runtime plan, writes
`/plans/traffic-pilot.runtime_plan.json`, generates the worker camera config, and
starts the OpenVINO worker.

## Hot Reload

The runtime checks desired state every 3 seconds. A newer valid revision is
compiled first while the old worker continues running. Only after validation and
config generation succeed does the runtime start the new worker and stop the old
worker. Invalid updates are rejected and the previous worker stays active.

## Required Mounts

```text
/configs/desired_state.json
/run/secrets/apexfabric/*.rtsp
/state
/dev/dri
/dev/accel
```

Camera `source` values in desired state must be secret references such as:

```text
file:/run/secrets/apexfabric/cam1.rtsp
```

The secret file may contain an RTSP/HTTP stream URL or an absolute local video
path mounted into the container.

## Counting Geometry

For each camera/input, counting uses exactly one mode:

```text
line exists      -> line crossing count
else zone exists -> zone count
else             -> whole-frame count
```


## Smoke/fire snapshots

When `fire_smoke_detection` raises a fire or smoke alert, the worker writes a JPEG frame snapshot under `/state/snapshots/<camera_id>/` and includes the snapshot path in the alert payload. The image bytes are not embedded in the event so message payloads stay small for MQTT, Kafka, SSE, and similar sinks.
