from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from services.worker.pipeline.analytics import TrafficAnalyticsStage
from services.worker.pipeline.output_sinks import JsonlFileSink, build_analytics_sink, simple_event, sink_kinds
from services.worker.pipeline.processor_config import normalize_runtime_analytics
from services.worker.pipeline.types import Detection, FramePacket


def _det(cls="car", bbox=None, track_id=1, hits=2):
    return Detection(
        bbox=bbox or [40, 40, 60, 60],
        class_id=2 if cls != "pedestrian" else 0,
        class_name=cls,
        confidence=0.9,
        model_name="vehicle",
        metadata={"track_id": track_id, "track_hits": hits},
    )


def _packet(index, det):
    return FramePacket(index=index, name="cam1", frame=np.zeros((100, 100, 3), dtype=np.uint8), detections=[det])


def _run_two(stage, first, second):
    p1 = _packet(1, first)
    p2 = _packet(2, second)
    stage.process([p1])
    stage.process([p2])
    return p1, p2


def test_vehicle_counting_line_mode_counts_crossing_once():
    line = {"id": "line-main", "shape": "line", "points": [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]}
    cam = {"runtime_analytics": {"vehicle_counting": {"lines": [line], "zones": []}}}
    stage = TrafficAnalyticsStage({"cam1": cam})

    _, p2 = _run_two(stage, _det(bbox=[40, 20, 60, 40]), _det(bbox=[40, 60, 60, 80]))

    assert len(p2.analytics_events) == 1
    assert p2.analytics_events[0]["type"] == "vehicle_count"
    assert p2.analytics_events[0]["geometry"]["id"] == "line-main"
    assert p2.analytics_events[0]["value"] == 1


def test_line_mode_has_priority_over_zone_when_both_exist():
    line = {"id": "line-main", "shape": "line", "points": [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]}
    zone = {"id": "zone-main", "shape": "polygon", "points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}
    cam = {"runtime_analytics": {"vehicle_counting": {"lines": [line], "zones": [zone]}}}
    stage = TrafficAnalyticsStage({"cam1": cam})

    _, p2 = _run_two(stage, _det(bbox=[40, 40, 60, 60]), _det(bbox=[42, 40, 62, 60]))

    assert p2.analytics_events == []
    state_geometry = p2.analytics_state["use_cases"]["vehicle_counting"]["geometry"]
    assert [item["geometry"]["type"] for item in state_geometry] == ["line", "zone"]
    assert state_geometry[0]["count"] == 0


def test_vehicle_counting_zone_mode_counts_stable_track_once():
    zone = {"id": "zone-main", "shape": "polygon", "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}
    cam = {"runtime_analytics": {"vehicle_counting": {"lines": [], "zones": [zone]}}}
    stage = TrafficAnalyticsStage({"cam1": cam})

    _, p2 = _run_two(stage, _det(bbox=[40, 40, 60, 60]), _det(bbox=[42, 40, 62, 60]))
    p3 = _packet(3, _det(bbox=[44, 40, 64, 60]))
    stage.process([p3])

    assert len(p2.analytics_events) == 1
    assert p2.analytics_events[0]["geometry"]["id"] == "zone-main"
    assert p2.analytics_events[0]["value"] == 1
    assert p3.analytics_events == []


def test_pedestrian_counting_whole_frame_default_counts_once():
    cam = {"runtime_analytics": {"pedestrian_counting": {"lines": [], "zones": []}}}
    stage = TrafficAnalyticsStage({"cam1": cam})

    _, p2 = _run_two(stage, _det(cls="pedestrian", bbox=[10, 10, 30, 40]), _det(cls="pedestrian", bbox=[12, 10, 32, 40]))

    assert len(p2.analytics_events) == 1
    assert p2.analytics_events[0]["type"] == "pedestrian_count"
    assert p2.analytics_events[0]["geometry"]["id"] == "zone:whole_frame"
    state_geometry = p2.analytics_state["use_cases"]["pedestrian_counting"]["geometry"]
    assert state_geometry[0]["geometry"]["name"] == "whole_frame"
    assert state_geometry[0]["count"] == 1


def test_processor_config_accepts_plain_counting_line_or_zone():
    line = {"shape": "line", "points": [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]}
    zone = {"shape": "polygon", "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}

    normalized_line = normalize_runtime_analytics({"analytics": {"vehicle_counting": {"enabled": True, "lines": [line], "zones": [zone]}}})
    normalized_zone = normalize_runtime_analytics({"analytics": {"pedestrian_counting": {"enabled": True, "lines": [], "zones": [zone]}}})

    assert normalized_line["vehicle_counting"]["lines"] == [line]
    assert normalized_line["vehicle_counting"]["zones"] == [zone]
    assert normalized_zone["pedestrian_counting"]["zones"] == [zone]


def test_smoke_fire_alert_writes_snapshot_and_output_payload(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    monkeypatch.setenv("SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    stage = TrafficAnalyticsStage({"cam1": {"runtime_analytics": {"fire_smoke_detection": {"enabled": True}}}})
    frame = np.full((80, 120, 3), 127, dtype=np.uint8)
    detection = Detection(
        bbox=[10, 12, 50, 60],
        class_id=1,
        class_name="smoke",
        confidence=0.82,
        model_name="smoke_fire",
    )
    packet = FramePacket(index=7, name="cam1", frame=frame, detections=[detection])

    stage.process([packet])

    assert len(packet.analytics_events) == 1
    event = packet.analytics_events[0]
    snapshot = event["snapshot"]
    snapshot_path = Path(snapshot["path"])
    assert event["type"] == "smoke_detected"
    assert snapshot["format"] == "jpg"
    assert snapshot["frame_index"] == 7
    assert snapshot["bbox"] == [10, 12, 50, 60]
    assert snapshot_path.exists()
    payload = simple_event(event)
    assert payload["snapshot"]["path"] == str(snapshot_path)
    assert payload["details"]["snapshot_path"] == str(snapshot_path)

def test_analytics_sink_has_no_redis_default(monkeypatch):
    monkeypatch.delenv("ANALYTICS_REDIS_TAP", raising=False)
    sink = build_analytics_sink(
        {"json_streaming": {"enabled": True, "outputs": []}},
        redis_host="redis",
        redis_port=6379,
        stream_key="traffic:analytics",
    )

    assert sink is None

def test_analytics_sink_writes_local_event_log_when_configured(tmp_path, monkeypatch):
    event_log = tmp_path / "events" / "analytics.jsonl"
    monkeypatch.setenv("ANALYTICS_EVENT_LOG_PATH", str(event_log))
    sink = build_analytics_sink(
        {"json_streaming": {"enabled": True, "outputs": []}},
        redis_host="redis",
        redis_port=6379,
    )

    assert isinstance(sink, JsonlFileSink)
    assert sink_kinds(sink) == ["jsonl"]
    sink.publish({"message_type": "camera_observation", "events": [{"type": "smoke_detected"}]})
    assert '"smoke_detected"' in event_log.read_text(encoding="utf-8")
