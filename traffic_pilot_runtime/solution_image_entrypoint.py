from __future__ import annotations

import argparse
import json
import mimetypes
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .adapter import write_worker_config
from .desired_state import DesiredState, DesiredStateValidator, file_hash
from .graph import RuntimePlan, compile_runtime_plan


class RuntimeState:
    def __init__(self, desired_state_path: str = "/configs/desired_state.json") -> None:
        self.lock = threading.Lock()
        self.started_at = time.time()
        self.desired_state_path = desired_state_path
        self.ready = False
        self.active_revision = 0
        self.active_hash = ""
        self.observed_hash = ""
        self.pending_revision: int | None = None
        self.reload_state = "idle"
        self.reload_attempts = 0
        self.applied_count = 0
        self.rejected_count = 0
        self.last_reload_at: float | None = None
        self.latest_error = ""
        self.plan: dict[str, Any] | None = None
        self.worker_pid: int | None = None
        self.worker_running = False
        self.events: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ready": self.ready,
                "active_revision": self.active_revision,
                "active_hash": self.active_hash,
                "observed_hash": self.observed_hash,
                "pending_revision": self.pending_revision,
                "reload_state": self.reload_state,
                "reload_attempts": self.reload_attempts,
                "applied_count": self.applied_count,
                "rejected_count": self.rejected_count,
                "last_reload_at": self.last_reload_at,
                "latest_error": self.latest_error,
                "worker_pid": self.worker_pid,
                "worker_running": self.worker_running,
                "plan": self.plan,
            }

    def metrics(self, stop_requested: bool = False) -> dict[str, Any]:
        with self.lock:
            plan = self.plan or {}
            camera_count = len(plan.get("cameras") or [])
            return {
                "solution_pack": "traffic",
                "edge_id": plan.get("edge_id"),
                "revision": self.active_revision or None,
                "plan_loaded": self.plan is not None,
                "models_ready": self.ready,
                "camera_count": camera_count,
                "configured_cameras": camera_count,
                "child_running": self.worker_running,
                "child_exit_code": None,
                "uptime_seconds": max(0.0, time.time() - self.started_at),
                "stop_requested": stop_requested,
                "last_error": self.latest_error or None,
                "desired_state": {
                    "path": self.desired_state_path,
                    "active_hash": self.active_hash or None,
                    "observed_hash": self.observed_hash or None,
                    "pending_revision": self.pending_revision,
                    "reload_state": self.reload_state,
                    "reload_attempts": self.reload_attempts,
                    "reload_applied": self.applied_count,
                    "reload_rejected": self.rejected_count,
                    "last_reload_at": self.last_reload_at,
                    "last_reload_error": self.latest_error or None,
                },
            }

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"observed_at": time.time(), "type": event_type, "payload": payload}
        with self.lock:
            self.events.append(event)
            self.events = self.events[-200:]


class WorkerSupervisor:
    def __init__(self, repo_root: Path, generated_dir: Path, state: RuntimeState) -> None:
        self.repo_root = repo_root
        self.generated_dir = generated_dir
        self.state = state
        self.process: subprocess.Popen | None = None

    def start_or_replace(self, desired: DesiredState, plan: RuntimePlan, cameras_file: Path) -> None:
        env = os.environ.copy()
        env.update({
            "VIDEO_DIR": str(self.generated_dir),
            "OPENVINO_MODELS_DIR": env.get("OPENVINO_MODELS_DIR", str(self.repo_root / "models" / "openvino")),
            "WORKER_CONFIG_PATH": env.get("WORKER_CONFIG_PATH", str(self.repo_root / "config" / "worker.json")),
            "CAMERAS_FILE": str(cameras_file),
            "PYTHONPATH": str(self.repo_root / "services" / "worker"),
            "INFER_FPS": str(max(1, int(min(camera.fps for camera in desired.cameras) if desired.cameras else 1))),
            "ANALYTICS_EVENT_LOG_PATH": env.get("ANALYTICS_EVENT_LOG_PATH", "/state/events/analytics.jsonl"),
        })
        command = [sys.executable, "-u", str(self.repo_root / "services" / "worker" / "stream_fleet_openvino.py")]
        new_process = subprocess.Popen(command, cwd=str(self.repo_root), env=env)
        time.sleep(float(os.getenv("WORKER_SWAP_GRACE_SECONDS", "2")))
        if new_process.poll() is not None:
            raise RuntimeError(f"new worker exited during startup with code {new_process.returncode}")
        old_process = self.process
        self.process = new_process
        self._stop_process(old_process)
        with self.state.lock:
            self.state.worker_pid = new_process.pid
            self.state.worker_running = True
            self.state.ready = True
            self.state.active_revision = desired.revision
            self.state.active_hash = desired.content_hash
            self.state.plan = plan.to_dict()
            self.state.applied_count += 1
            self.state.latest_error = ""
        self.state.record_event("desired_state_applied", {"revision": desired.revision, "worker_pid": new_process.pid})

    def poll_worker(self) -> None:
        proc = self.process
        running = bool(proc and proc.poll() is None)
        with self.state.lock:
            self.state.worker_running = running
            self.state.worker_pid = proc.pid if running and proc else None
            self.state.ready = running and bool(self.state.plan)

    def stop(self) -> None:
        self._stop_process(self.process)
        self.process = None
        self.poll_worker()

    @staticmethod
    def _stop_process(proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


class DesiredStateReloader(threading.Thread):
    def __init__(self, args, state: RuntimeState, supervisor: WorkerSupervisor) -> None:
        super().__init__(daemon=True)
        self.args = args
        self.state = state
        self.supervisor = supervisor
        self.validator = DesiredStateValidator(Path(args.secrets_root))
        self.stop_requested = threading.Event()

    def run(self) -> None:
        while not self.stop_requested.is_set():
            self._try_reload()
            self.stop_requested.wait(float(self.args.poll_seconds))

    def _try_reload(self) -> None:
        path = Path(self.args.desired_state)
        try:
            observed_hash = file_hash(path)
        except OSError as exc:
            self._reject(f"desired-state file is unreadable: {exc}")
            return
        with self.state.lock:
            self.state.observed_hash = observed_hash
            already_active = observed_hash == self.state.active_hash
        if already_active:
            self.supervisor.poll_worker()
            return
        try:
            desired = self.validator.load(path)
            with self.state.lock:
                self.state.pending_revision = desired.revision
                self.state.reload_state = "compiling"
                self.state.reload_attempts += 1
                if desired.revision < self.state.active_revision:
                    raise ValueError(
                        f"revision {desired.revision} is older than active revision {self.state.active_revision}"
                    )
            plan = compile_runtime_plan(desired)
            plan_path = Path(self.args.plan_dir) / "traffic.runtime_plan.json"
            cameras_path = Path(self.args.generated_dir) / "cameras.generated.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
            write_worker_config(desired, cameras_path)
            with self.state.lock:
                self.state.reload_state = "applying"
            self.supervisor.start_or_replace(desired, plan, cameras_path)
            with self.state.lock:
                self.state.pending_revision = None
                self.state.reload_state = "idle"
                self.state.last_reload_at = time.time()
        except Exception as exc:  # noqa: BLE001
            self._reject(str(exc))

    def _reject(self, reason: str) -> None:
        with self.state.lock:
            if self.state.latest_error == reason:
                return
            self.state.latest_error = reason
            self.state.reload_state = "rejected"
            self.state.rejected_count += 1
            self.state.last_reload_at = time.time()
        self.state.record_event("desired_state_rejected", {"reason": reason})


class RuntimeHandler(BaseHTTPRequestHandler):
    runtime_state: RuntimeState

    def do_GET(self):
        parsed_path = urlsplit(self.path).path
        if parsed_path == "/healthz":
            self._json({"ok": True})
        elif parsed_path == "/readyz":
            snap = self.runtime_state.snapshot()
            self._json({"ready": bool(snap["ready"]), "worker_running": bool(snap["worker_running"])}, 200 if snap["ready"] else 503)
        elif parsed_path == "/metrics":
            self._json(_metrics(self.runtime_state))
        elif parsed_path == "/events":
            self._events()
        elif parsed_path.startswith("/snapshots/"):
            self._snapshot(parsed_path.removeprefix("/snapshots/"))
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        return

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        for event in _tail_events(self.runtime_state, Path(os.getenv("ANALYTICS_EVENT_LOG_PATH", "/state/events/analytics.jsonl"))):
            try:
                if event is None:
                    self.wfile.write(b": heartbeat\n\n")
                else:
                    self.wfile.write((f"id: {event['event_id']}\n").encode("utf-8"))
                    self.wfile.write(b"event: analytics\n")
                    self.wfile.write(("data: " + json.dumps(event, sort_keys=True) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    def _snapshot(self, raw_ref: str) -> None:
        resolved = _resolve_snapshot_path(raw_ref)
        if resolved is None:
            self._json({"error": "snapshot_not_found"}, 404)
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        try:
            body = resolved.read_bytes()
        except OSError as exc:
            self._json({"error": "snapshot_read_failed", "detail": str(exc)}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    payloads = []
    for line in lines:
        try:
            payloads.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return payloads


def _metrics(state: RuntimeState) -> dict[str, Any]:
    return {
        "format": "application/json",
        "runtime": state.metrics(),
        "events": {"protocol": "server-sent-events", "path": "/events"},
        "snapshots": {
            "path_prefix": "/snapshots/",
            "content_types": ["image/jpeg", "image/png"],
            "source": "persistent_state",
        },
    }


def _tail_events(state: RuntimeState, path: Path):
    position = 0
    while True:
        emitted = False
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                fh.seek(position)
                for line in fh:
                    for event in _events_from_jsonl_line(line):
                        emitted = True
                        yield event
                position = fh.tell()
        if not emitted:
            yield None
            time.sleep(5)

def _events_from_jsonl_line(line: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, dict):
        return []
    if isinstance(raw.get("events"), list):
        return [_normalize_worker_event(raw, item) for item in raw["events"] if isinstance(item, dict)]
    return [_normalize_worker_event(raw, raw)]


def _normalize_management_event(event: dict[str, Any]) -> dict[str, Any]:
    timestamp = _utc_timestamp(float(event.get("observed_at") or time.time()))
    event_type = str(event.get("type") or "runtime_event")
    return {
        "schema_version": "1.0",
        "event_id": f"runtime:{timestamp}:{event_type}",
        "timestamp": timestamp,
        "camera_id": "runtime",
        "solution_pack": "traffic",
        "application": "runtime",
        "event_type": event_type,
        "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
    }


def _normalize_worker_event(envelope: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    observed_at = event.get("timestamp") or event.get("observed_at") or envelope.get("observed_at")
    camera = envelope.get("camera") if isinstance(envelope.get("camera"), dict) else {}
    camera_id = str(envelope.get("camera_id") or camera.get("id") or camera.get("name") or "unknown")
    raw_application = str(event.get("use_case") or event.get("application") or event.get("app_id") or event.get("event_type") or event.get("type") or "analytics")
    application, event_type = _normalize_identity(raw_application, str(event.get("event_type") or event.get("type") or raw_application))
    payload = dict(event)
    for key in ("id", "timestamp", "observed_at", "use_case", "application", "app_id", "event_type", "type"):
        payload.pop(key, None)
    _attach_snapshot_refs(payload)
    return {
        "schema_version": "1.0",
        "event_id": str(event.get("id") or envelope.get("message_id") or f"{camera_id}:{application}:{observed_at}"),
        "timestamp": str(observed_at or _utc_timestamp(time.time())),
        "camera_id": camera_id,
        "solution_pack": "traffic",
        "application": application,
        "event_type": event_type,
        "payload": payload,
    }


def _normalize_identity(application: str, event_type: str) -> tuple[str, str]:
    app = {
        "plate_detection": "anpr",
        "vehicle_count": "vehicle_counting",
        "pedestrian_count": "pedestrian_counting",
        "fire_detected": "fire_smoke_detection",
        "smoke_detected": "fire_smoke_detection",
    }.get(application, application)
    evt = {
        "plate_detection": "plate_read_event",
        "anpr": "plate_read_event",
        "vehicle_count": "vehicle_count_event",
        "vehicle_counting": "vehicle_count_event",
        "pedestrian_count": "pedestrian_count_event",
        "pedestrian_counting": "pedestrian_count_event",
        "fire_detected": "fire_detected",
        "smoke_detected": "smoke_detected",
        "fire_smoke_detection": event_type,
    }.get(event_type, event_type)
    return app, evt


def _attach_snapshot_refs(payload: dict[str, Any]) -> None:
    snapshot = payload.pop("snapshot", None)
    if not isinstance(snapshot, dict):
        details = payload.get("details")
        if isinstance(details, dict):
            details.pop("snapshot_path", None)
        return
    ref = snapshot.get("ref") or _snapshot_ref_from_path(snapshot.get("path"))
    if not ref:
        return
    payload["snapshot_ref"] = ref
    payload["snapshot_url"] = _snapshot_url(ref)
    payload["snapshot_content_type"] = "image/jpeg"
    payload["snapshot_assets"] = {
        "event_frame": {
            "ref": ref,
            "url": _snapshot_url(ref),
            "content_type": "image/jpeg",
        }
    }
    details = payload.get("details")
    if isinstance(details, dict):
        details.pop("snapshot_path", None)


def _snapshot_ref_from_path(path: Any) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    state_root = Path(os.getenv("APEXFABRIC_STATE_DIR") or os.getenv("APEXFABRIC_STATE_ROOT", "/state")).resolve()
    try:
        resolved = Path(path).resolve()
        rel = resolved.relative_to(state_root)
        return str(rel).replace(os.sep, "/")
    except (OSError, ValueError):
        return None


def _snapshot_url(ref: str) -> str:
    return "/snapshots/" + ref.lstrip("/")


def _resolve_snapshot_path(raw_ref: str) -> Path | None:
    state_root = Path(os.getenv("APEXFABRIC_STATE_DIR") or os.getenv("APEXFABRIC_STATE_ROOT", "/state")).resolve()
    ref = unquote(raw_ref).lstrip("/")
    try:
        candidate = (state_root / ref).resolve()
    except OSError:
        return None
    if candidate != state_root and state_root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _utc_timestamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run traffic-pilot as an ApexFabric-style solution image")
    parser.add_argument("--repo-root", default=os.getenv("TRAFFIC_PILOT_ROOT", "/opt/traffic-pilot"))
    parser.add_argument("--desired-state", default=os.getenv("DESIRED_STATE_PATH", "/configs/desired_state.json"))
    parser.add_argument("--secrets-root", default=os.getenv("APEXFABRIC_SECRETS_ROOT", "/run/secrets/apexfabric"))
    parser.add_argument("--generated-dir", default=os.getenv("APEXFABRIC_GENERATED_DIR", "/tmp/apexfabric/generated/traffic-pilot"))
    parser.add_argument("--plan-dir", default=os.getenv("APEXFABRIC_PLAN_DIR", "/plans"))
    parser.add_argument("--host", default=os.getenv("APEX_API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("APEX_API_PORT", "8080")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("DESIRED_STATE_RELOAD_INTERVAL", "2")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = RuntimeState(args.desired_state)
    supervisor = WorkerSupervisor(Path(args.repo_root), Path(args.generated_dir), state)
    reloader = DesiredStateReloader(args, state, supervisor)

    def _shutdown(signum, frame):
        reloader.stop_requested.set()
        supervisor.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    reloader.start()
    RuntimeHandler.runtime_state = state
    server = ThreadingHTTPServer((args.host, args.port), RuntimeHandler)
    print(f"traffic-pilot solution API listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        reloader.stop_requested.set()
        supervisor.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
