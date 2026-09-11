from __future__ import annotations

import json
from pathlib import Path

from traffic_pilot_runtime.solution_image_entrypoint import (
    RuntimeState,
    _events_from_jsonl_line,
    _metrics,
    _resolve_snapshot_path,
)


def test_metrics_matches_apexfabric_outer_contract():
    state = RuntimeState("/configs/desired_state.json")
    payload = _metrics(state)

    assert payload["format"] == "application/json"
    assert payload["events"] == {"protocol": "server-sent-events", "path": "/events"}
    assert payload["snapshots"]["path_prefix"] == "/snapshots/"
    assert payload["snapshots"]["source"] == "persistent_state"
    runtime = payload["runtime"]
    assert runtime["solution_pack"] == "traffic"
    assert runtime["desired_state"]["path"] == "/configs/desired_state.json"
    assert runtime["desired_state"]["reload_state"] == "idle"


def test_worker_jsonl_is_normalized_to_apexfabric_analytics_event(monkeypatch, tmp_path):
    state_root = tmp_path / "state"
    snapshot_path = state_root / "snapshots" / "cam1" / "frame.jpg"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_bytes(b"jpeg")
    monkeypatch.setenv("APEXFABRIC_STATE_ROOT", str(state_root))
    line = json.dumps({
        "message_id": "msg-1",
        "observed_at": "2026-09-11T10:00:00Z",
        "camera": {"id": "cam1"},
        "events": [{
            "id": "evt-1",
            "type": "smoke_detected",
            "use_case": "fire_smoke_detection",
            "timestamp": "2026-09-11T10:00:01Z",
            "snapshot": {"path": str(snapshot_path)},
            "details": {"snapshot_path": str(snapshot_path)},
        }],
    })

    events = _events_from_jsonl_line(line)

    assert len(events) == 1
    event = events[0]
    assert event["schema_version"] == "1.0"
    assert event["solution_pack"] == "traffic"
    assert event["application"] == "fire_smoke_detection"
    assert event["event_type"] == "smoke_detected"
    assert event["payload"]["snapshot_ref"] == "snapshots/cam1/frame.jpg"
    assert event["payload"]["snapshot_url"] == "/snapshots/snapshots/cam1/frame.jpg"
    assert "snapshot" not in event["payload"]
    assert "snapshot_path" not in event["payload"].get("details", {})


def test_snapshot_refs_are_served_from_state_root(monkeypatch, tmp_path):
    state_root = tmp_path / "state"
    image = state_root / "snapshots" / "cam1" / "frame.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg")
    monkeypatch.setenv("APEXFABRIC_STATE_ROOT", str(state_root))

    assert _resolve_snapshot_path("snapshots/cam1/frame.jpg") == image.resolve()
    assert _resolve_snapshot_path("../outside.jpg") is None
