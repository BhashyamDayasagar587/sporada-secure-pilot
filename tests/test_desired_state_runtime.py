from __future__ import annotations

import json
from pathlib import Path

import pytest

from traffic_pilot_runtime.adapter import write_worker_config
from traffic_pilot_runtime.desired_state import DesiredStateValidator
from traffic_pilot_runtime.graph import compile_runtime_plan


def _desired(tmp_path: Path, apps, config=None):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    source = secrets / "cam1.rtsp"
    source.write_text("rtsp://camera.test/stream\n", encoding="utf-8")
    desired = tmp_path / "desired_state.json"
    desired.write_text(json.dumps({
        "edge_id": "edge-test",
        "revision": 1,
        "cameras": [{
            "camera_id": "cam1",
            "source": f"file:{source}",
            "solution_pack": "traffic",
            "fps": 8,
            "apps": apps,
            "config": config or {},
        }],
    }), encoding="utf-8")
    return desired, secrets


def test_desired_state_requires_secret_source(tmp_path):
    desired = tmp_path / "desired_state.json"
    desired.write_text(json.dumps({
        "edge_id": "edge-test",
        "revision": 1,
        "cameras": [{"camera_id": "cam1", "source": "rtsp://camera", "solution_pack": "traffic", "apps": ["vehicle_counting"]}],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="mounted Secret"):
        DesiredStateValidator(tmp_path).load(desired)


def test_dynamic_graph_only_contains_active_counting_nodes(tmp_path):
    desired_path, secrets = _desired(tmp_path, ["vehicle_counting"])
    desired = DesiredStateValidator(secrets).load(desired_path)

    plan = compile_runtime_plan(desired)
    graph = plan.cameras[0]

    assert graph.config_mode == "whole_frame"
    assert "vehicle_detector" in graph.node_ids
    assert "vehicle_tracker" in graph.node_ids
    assert "vehicle_counting" in graph.node_ids
    assert "plate_detector" not in graph.node_ids
    assert "ocr_service" not in graph.node_ids
    assert "smoke_fire_detector" not in graph.node_ids
    vehicle_node = next(node for node in graph.nodes if node["id"] == "vehicle_detector")
    assert vehicle_node == {"id": "vehicle_detector", "label": "Vehicle Detector", "kind": "model", "device": "GPU", "active": True}


def test_dynamic_graph_adds_plate_and_smoke_only_when_active(tmp_path):
    desired_path, secrets = _desired(tmp_path, ["plate_detection", "fire_smoke_detection"])
    desired = DesiredStateValidator(secrets).load(desired_path)

    graph = compile_runtime_plan(desired).cameras[0]

    assert "plate_detector" in graph.node_ids
    assert "ocr_service" in graph.node_ids
    assert "smoke_fire_detector" in graph.node_ids
    assert "snapshot_storage" in graph.node_ids
    assert graph.devices["smoke_fire_detector"] == "GPU"
    assert {"source": "fire_smoke_detection", "target": "snapshot_storage"} in graph.edges


def test_adapter_writes_worker_config_from_secret_and_line(tmp_path):
    line = {"name": "gate", "a": [0.1, 0.5], "b": [0.9, 0.5], "direction": "both"}
    desired_path, secrets = _desired(tmp_path, ["vehicle_counting"], {"line": line})
    desired = DesiredStateValidator(secrets).load(desired_path)

    out = tmp_path / "generated" / "cameras.json"
    payload = write_worker_config(desired, out)

    camera = payload["cameras"][0]
    assert camera["source"]["uri"] == "rtsp://camera.test/stream"
    assert camera["processing"]["fps"] == 8
    line_config = camera["analytics"]["vehicle_counting"]["lines"][0]
    assert line_config["purpose"] == "vehicle_counting"
    assert line_config["normalized"] is True


def test_validator_rejects_line_and_zone_on_same_input(tmp_path):
    config = {
        "line": {"a": [0.1, 0.5], "b": [0.9, 0.5]},
        "zone": {"poly": [[0, 0], [1, 0], [1, 1]]},
    }
    desired_path, secrets = _desired(tmp_path, ["vehicle_counting"], config)

    with pytest.raises(ValueError, match="either line or zone"):
        DesiredStateValidator(secrets).load(desired_path)


def test_desired_state_accepts_id_alias(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    source = secrets / "cam1.rtsp"
    source.write_text("rtsp://camera.test/stream\n", encoding="utf-8")
    desired = tmp_path / "desired_state.json"
    desired.write_text(json.dumps({
        "edge_id": "edge-test",
        "revision": 1,
        "cameras": [{
            "id": "cam1",
            "source": f"file:{source}",
            "solution_pack": "traffic",
            "apps": ["vehicle_counting"],
        }],
    }), encoding="utf-8")

    state = DesiredStateValidator(secrets).load(desired)

    assert state.cameras[0].camera_id == "cam1"


def test_desired_state_rejects_conflicting_camera_ids(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    source = secrets / "cam1.rtsp"
    source.write_text("rtsp://camera.test/stream\n", encoding="utf-8")
    desired = tmp_path / "desired_state.json"
    desired.write_text(json.dumps({
        "edge_id": "edge-test",
        "revision": 1,
        "cameras": [{
            "camera_id": "cam1",
            "id": "other",
            "source": f"file:{source}",
            "solution_pack": "traffic",
            "apps": ["vehicle_counting"],
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting camera_id and id"):
        DesiredStateValidator(secrets).load(desired)

def test_desired_state_accepts_limited_pipeline_app_aliases(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    source = secrets / "cam-traffic-01.rtsp"
    source.write_text("/videos/sample.mp4\n", encoding="utf-8")
    desired = tmp_path / "desired_state.json"
    desired.write_text(json.dumps({
        "edge_id": "intel-box-example",
        "revision": 1,
        "cameras": [{
            "camera_id": "cam-traffic-01",
            "source": f"file:{source}",
            "solution_pack": "traffic",
            "fps": 8,
            "apps": ["anpr", "vehicle_counting", "pedestrian_counting", "fire_smoke_detection"],
            "config": {
                "zones": {
                    "anpr": [{"name": "plate_roi", "poly": [[0.1, 0.4], [0.9, 0.4], [0.9, 0.95], [0.1, 0.95]]}],
                    "fire_smoke_detection": [{"name": "fire_area", "poly": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}],
                },
                "lines": {
                    "vehicle_counting": [{"name": "vehicle_count_line", "a": [0.15, 0.68], "b": [0.85, 0.68]}],
                    "pedestrian_counting": [{"name": "pedestrian_count_line", "a": [0.15, 0.78], "b": [0.85, 0.78]}],
                },
            },
        }],
    }), encoding="utf-8")

    state = DesiredStateValidator(secrets).load(desired)
    payload = write_worker_config(state, tmp_path / "generated" / "cameras.json")

    camera = state.cameras[0]
    assert camera.apps == (
        "plate_detection",
        "vehicle_counting",
        "pedestrian_counting",
        "fire_smoke_detection",
    )
    analytics = payload["cameras"][0]["analytics"]
    assert analytics["plate_detection"]["zones"][0]["type"] == "plate_roi"
    assert analytics["vehicle_counting"]["lines"][0]["purpose"] == "vehicle_counting"
    assert analytics["pedestrian_counting"]["lines"][0]["purpose"] == "pedestrian_counting"
    assert analytics["fire_smoke_detection"]["zones"][0]["type"] == "fire_smoke"


def test_desired_state_rejects_apps_not_in_limited_image(tmp_path):
    desired_path, secrets = _desired(tmp_path, ["wrong_way", "illegal_parking"])

    with pytest.raises(ValueError, match="unsupported apps"):
        DesiredStateValidator(secrets).load(desired_path)

