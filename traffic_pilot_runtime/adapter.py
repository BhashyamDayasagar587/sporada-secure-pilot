from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .desired_state import DesiredCamera, DesiredState

LINE_PURPOSE = {
    "vehicle_counting": "vehicle_counting",
    "pedestrian_counting": "pedestrian_counting",
}
ZONE_TYPE = {
    "vehicle_counting": "vehicle_counting",
    "pedestrian_counting": "pedestrian_counting",
    "plate_detection": "plate_roi",
    "fire_smoke_detection": "fire_smoke",
}
APP_CONFIG_KEYS = {
    "plate_detection": ("plate_detection", "anpr"),
}


def write_worker_config(desired: DesiredState, output_path: Path) -> dict[str, Any]:
    payload = {"cameras": [_camera_to_worker(camera) for camera in desired.cameras]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(output_path)
    return payload


def _camera_to_worker(camera: DesiredCamera) -> dict[str, Any]:
    uri = Path(camera.source.removeprefix("file:")).read_text(encoding="utf-8").strip()
    analytics = {app: _use_case_config(app, camera.config) for app in camera.apps}
    return {
        "camera_id": camera.camera_id,
        "name": camera.name or camera.camera_id,
        "enabled": True,
        "source": {"type": _source_type(uri), "uri": uri},
        "processing": {"fps": camera.fps},
        "analytics": analytics,
    }


def _use_case_config(app: str, config: dict[str, Any]) -> dict[str, Any]:
    line_items = _items_for(config, "line", "lines", app)
    zone_items = _items_for(config, "zone", "zones", app)
    return {
        "enabled": True,
        "lines": [_line_geometry(item, app) for item in line_items],
        "zones": [_zone_geometry(item, app) for item in zone_items],
        "masks": [_zone_geometry(item, app) for item in config.get("masks", [])],
    }


def _items_for(config: dict[str, Any], singular: str, plural: str, app: str) -> list[dict[str, Any]]:
    if config.get(singular):
        return [config[singular]]
    value = config.get(plural) or []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = []
        for key in APP_CONFIG_KEYS.get(app, (app,)):
            app_items = value.get(key) or []
            if isinstance(app_items, list):
                items.extend(app_items)
        return items
    return []


def _line_geometry(item: dict[str, Any], app: str) -> dict[str, Any]:
    points = _line_points(item)
    return {
        "id": item.get("id"),
        "name": item.get("name") or "line_1",
        "shape": "line",
        "points": _point_dicts(points),
        "purpose": item.get("purpose") or LINE_PURPOSE.get(app),
        "direction": item.get("direction"),
        "normalized": True,
    }


def _zone_geometry(item: dict[str, Any], app: str) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name") or "zone_1",
        "shape": item.get("shape") or "polygon",
        "points": _point_dicts(_zone_points(item)),
        "type": item.get("type") or ZONE_TYPE.get(app),
        "normalized": True,
    }


def _line_points(item: dict[str, Any]) -> list[Any]:
    if item.get("points"):
        return item["points"][:2]
    return [item.get("a"), item.get("b")]


def _zone_points(item: dict[str, Any]) -> list[Any]:
    return item.get("poly") or item.get("points") or []


def _point_dicts(points) -> list[dict[str, float]]:
    out = []
    for point in points:
        if isinstance(point, dict):
            out.append({"x": float(point.get("x", 0)), "y": float(point.get("y", 0))})
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            out.append({"x": float(point[0]), "y": float(point[1])})
    return out


def _source_type(uri: str) -> str:
    lowered = uri.lower()
    if lowered.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    if lowered.startswith("http://"):
        return "http"
    if lowered.startswith("https://"):
        return "https"
    return "file"
