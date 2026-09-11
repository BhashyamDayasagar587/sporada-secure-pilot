from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STREAM_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://")
SUPPORTED_APPS = {
    "vehicle_counting",
    "pedestrian_counting",
    "plate_detection",
    "fire_smoke_detection",
}
APP_ALIASES = {
    "anpr": "plate_detection",
}
APP_CONFIG_KEYS = {
    "plate_detection": ("plate_detection", "anpr"),
}
LINE_APPS = {"vehicle_counting", "pedestrian_counting"}
ZONE_APPS = {
    "vehicle_counting",
    "pedestrian_counting",
    "plate_detection",
    "fire_smoke_detection",
}
REQUIRED_LINE_APPS = set()
REQUIRED_ZONE_APPS = set()


@dataclass(frozen=True)
class DesiredCamera:
    camera_id: str
    source: str
    apps: tuple[str, ...]
    fps: float = 10.0
    config: dict[str, Any] = field(default_factory=dict)
    name: str | None = None


@dataclass(frozen=True)
class DesiredState:
    edge_id: str
    revision: int
    cameras: tuple[DesiredCamera, ...]
    content_hash: str


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DesiredStateValidator:
    def __init__(self, secrets_root: Path) -> None:
        self.secrets_root = secrets_root.resolve()

    def load(self, path: Path) -> DesiredState:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except FileNotFoundError as exc:
            raise ValueError(f"desired-state file not found: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"desired-state file is invalid: {exc}") from exc
        self.validate(data)
        cameras = []
        for cam in data["cameras"]:
            camera_id = _camera_id(cam)
            cameras.append(
                DesiredCamera(
                    camera_id=camera_id,
                    name=str(cam.get("name") or camera_id),
                    source=str(cam["source"]),
                    apps=tuple(_canonical_app(str(app)) for app in cam["apps"]),
                    fps=float(cam.get("fps", 10.0)),
                    config=dict(cam.get("config") or {}),
                )
            )
        cameras = tuple(cameras)
        return DesiredState(
            edge_id=str(data["edge_id"]),
            revision=int(data["revision"]),
            cameras=cameras,
            content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise ValueError("desired state must be a JSON object")
        unknown = set(data) - {"edge_id", "revision", "cameras"}
        if unknown:
            raise ValueError(f"unknown desired-state fields: {sorted(unknown)}")
        if not isinstance(data.get("edge_id"), str) or not data["edge_id"].strip():
            raise ValueError("edge_id must be a non-empty string")
        if not isinstance(data.get("revision"), int) or data["revision"] < 1:
            raise ValueError("revision must be an integer greater than zero")
        cameras = data.get("cameras")
        if not isinstance(cameras, list):
            raise ValueError("cameras must be an array")
        seen: set[str] = set()
        for index, camera in enumerate(cameras):
            self._validate_camera(index, camera, seen)

    def _validate_camera(self, index: int, camera: Any, seen: set[str]) -> None:
        if not isinstance(camera, dict):
            raise ValueError(f"camera at index {index} must be an object")
        unknown = set(camera) - {"camera_id", "id", "name", "source", "fps", "apps", "config", "solution_pack"}
        if unknown:
            raise ValueError(f"camera at index {index} has unknown fields: {sorted(unknown)}")
        missing = {"source", "apps"} - set(camera)
        if missing:
            raise ValueError(f"camera at index {index} is missing fields: {sorted(missing)}")
        if "camera_id" not in camera and "id" not in camera:
            raise ValueError(f"camera at index {index} is missing fields: ['camera_id']")
        if "camera_id" in camera and "id" in camera and camera["camera_id"] != camera["id"]:
            raise ValueError(f"camera at index {index} has conflicting camera_id and id")
        camera_id = _camera_id(camera)
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise ValueError(f"camera at index {index} has an invalid camera_id")
        if camera_id in seen:
            raise ValueError(f"duplicate camera_id: {camera_id}")
        seen.add(camera_id)
        fps = camera.get("fps", 10.0)
        if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
            raise ValueError(f"camera {camera_id} fps must be greater than zero")
        apps = camera["apps"]
        if not isinstance(apps, list) or not apps or any(not isinstance(app, str) for app in apps):
            raise ValueError(f"camera {camera_id} apps must be a non-empty string array")
        canonical_apps = [_canonical_app(app) for app in apps]
        if len(canonical_apps) != len(set(canonical_apps)):
            raise ValueError(f"camera {camera_id} contains duplicate apps")
        unsupported = set(canonical_apps) - SUPPORTED_APPS
        if unsupported:
            raise ValueError(f"camera {camera_id} uses unsupported apps: {sorted(unsupported)}")
        config = camera.get("config", {})
        if not isinstance(config, dict):
            raise ValueError(f"camera {camera_id} config must be an object")
        self._validate_source(camera_id, camera["source"])
        self._validate_geometry_config(camera_id, set(canonical_apps), config)

    def _validate_source(self, camera_id: str, source: Any) -> None:
        if not isinstance(source, str) or not source.startswith("file:"):
            raise ValueError(f"camera {camera_id} source must reference a mounted Secret with file:")
        secret_path = Path(source.removeprefix("file:").strip())
        if not str(secret_path):
            raise ValueError(f"camera {camera_id} Secret path is empty")
        try:
            resolved = secret_path.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValueError(f"camera {camera_id} Secret file is missing or unreadable") from exc
        if resolved != self.secrets_root and self.secrets_root not in resolved.parents:
            raise ValueError(f"camera {camera_id} Secret must be under {self.secrets_root}")
        try:
            value = resolved.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"camera {camera_id} Secret file is missing or unreadable") from exc
        if not value:
            raise ValueError(f"camera {camera_id} Secret is empty")
        if not value.startswith(STREAM_SCHEMES) and not Path(value).is_absolute():
            raise ValueError(f"camera {camera_id} Secret must contain a stream URL or absolute file path")

    def _validate_geometry_config(self, camera_id: str, apps: set[str], config: dict[str, Any]) -> None:
        unknown = set(config) - {"line", "zone", "lines", "zones", "masks"}
        if unknown:
            raise ValueError(f"camera {camera_id} config has unknown fields: {sorted(unknown)}")
        line = config.get("line")
        zone = config.get("zone")
        lines = self._configured_items(config, "line", "lines", apps & LINE_APPS)
        zones = self._configured_items(config, "zone", "zones", apps & ZONE_APPS)
        if line and zone:
            raise ValueError(f"camera {camera_id} must use either line or zone for an input, not both")
        if (
            config.get("lines")
            and config.get("zones")
            and not isinstance(config.get("lines"), dict)
            and not isinstance(config.get("zones"), dict)
        ):
            raise ValueError(f"camera {camera_id} must use either lines or zones for an input, not both")
        for index, item in enumerate(lines):
            self._validate_line(camera_id, index, item)
        for index, item in enumerate(zones):
            self._validate_zone(camera_id, index, item)
        if apps & REQUIRED_LINE_APPS and not lines:
            raise ValueError(f"camera {camera_id} apps {sorted(apps & REQUIRED_LINE_APPS)} require a line")
        if apps & REQUIRED_ZONE_APPS and not zones:
            raise ValueError(f"camera {camera_id} apps {sorted(apps & REQUIRED_ZONE_APPS)} require a zone")

    @staticmethod
    def _configured_items(config: dict[str, Any], singular: str, plural: str, active_apps: set[str]) -> list[Any]:
        if config.get(singular):
            return [config[singular]]
        value = config.get(plural) or []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            items = []
            for app in active_apps:
                for key in APP_CONFIG_KEYS.get(app, (app,)):
                    app_items = value.get(key) or []
                    if isinstance(app_items, list):
                        items.extend(app_items)
            return items
        return []

    def _validate_line(self, camera_id: str, index: int, line: Any) -> None:
        if not isinstance(line, dict):
            raise ValueError(f"camera {camera_id} line {index} must be an object")
        unknown = set(line) - {"id", "name", "shape", "points", "a", "b", "purpose", "type", "direction"}
        if unknown:
            raise ValueError(f"camera {camera_id} line {index} has unknown fields: {sorted(unknown)}")
        points = _line_points(line)
        if len(points) < 2:
            raise ValueError(f"camera {camera_id} line {index} needs at least 2 points")
        for point_index, point in enumerate(points[:2]):
            self._validate_point(camera_id, f"line {index} point {point_index}", point)
        if line.get("direction") not in {None, "a_to_b", "b_to_a", "both"}:
            raise ValueError(f"camera {camera_id} line {index} direction must be a_to_b, b_to_a, or both")

    def _validate_zone(self, camera_id: str, index: int, zone: Any) -> None:
        if not isinstance(zone, dict):
            raise ValueError(f"camera {camera_id} zone {index} must be an object")
        unknown = set(zone) - {"id", "name", "shape", "points", "poly", "purpose", "type"}
        if unknown:
            raise ValueError(f"camera {camera_id} zone {index} has unknown fields: {sorted(unknown)}")
        points = _zone_points(zone)
        if len(points) < 3:
            raise ValueError(f"camera {camera_id} zone {index} needs at least 3 points")
        for point_index, point in enumerate(points):
            self._validate_point(camera_id, f"zone {index} point {point_index}", point)

    @staticmethod
    def _validate_point(camera_id: str, field: str, point: Any) -> None:
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 2
            or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in point)
            or any(value < 0 or value > 1 for value in point)
        ):
            raise ValueError(f"camera {camera_id} {field} must be [x, y] normalized from 0 to 1")


def _canonical_app(app: str) -> str:
    return APP_ALIASES.get(app, app)


def _camera_id(camera: dict[str, Any]) -> str:
    return str(camera.get("camera_id") or camera.get("id"))


def _line_points(line: dict[str, Any]) -> list[Any]:
    if line.get("points"):
        return [_point_pair(p) for p in line["points"]]
    points = []
    for key in ("a", "b"):
        if key in line:
            points.append(_point_pair(line[key]))
    return points


def _zone_points(zone: dict[str, Any]) -> list[Any]:
    return [_point_pair(p) for p in (zone.get("poly") or zone.get("points") or [])]


def _point_pair(point: Any) -> list[float]:
    if isinstance(point, dict):
        return [float(point.get("x", 0)), float(point.get("y", 0))]
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return [float(point[0]), float(point[1])]
    return []
