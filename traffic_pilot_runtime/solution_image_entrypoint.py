from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .adapter import write_worker_config
from .desired_state import DesiredState, DesiredStateValidator, file_hash
from .graph import RuntimePlan, compile_runtime_plan


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ready = False
        self.active_revision = 0
        self.active_hash = ""
        self.observed_hash = ""
        self.applied_count = 0
        self.rejected_count = 0
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
                "applied_count": self.applied_count,
                "rejected_count": self.rejected_count,
                "latest_error": self.latest_error,
                "worker_pid": self.worker_pid,
                "worker_running": self.worker_running,
                "plan": self.plan,
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
                if desired.revision < self.state.active_revision:
                    raise ValueError(
                        f"revision {desired.revision} is older than active revision {self.state.active_revision}"
                    )
            plan = compile_runtime_plan(desired)
            plan_path = Path(self.args.plan_dir) / "traffic-pilot.runtime_plan.json"
            cameras_path = Path(self.args.generated_dir) / "cameras.generated.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
            write_worker_config(desired, cameras_path)
            self.supervisor.start_or_replace(desired, plan, cameras_path)
        except Exception as exc:  # noqa: BLE001
            self._reject(str(exc))

    def _reject(self, reason: str) -> None:
        with self.state.lock:
            if self.state.latest_error == reason:
                return
            self.state.latest_error = reason
            self.state.rejected_count += 1
        self.state.record_event("desired_state_rejected", {"reason": reason})


class RuntimeHandler(BaseHTTPRequestHandler):
    runtime_state: RuntimeState

    def do_GET(self):
        if self.path == "/healthz":
            self._json({"ok": True})
        elif self.path == "/readyz":
            snap = self.runtime_state.snapshot()
            self._json({"ready": bool(snap["ready"]), "worker_running": bool(snap["worker_running"])}, 200 if snap["ready"] else 503)
        elif self.path == "/metrics":
            self._json({"runtime": {"desired_state": self.runtime_state.snapshot()}})
        elif self.path == "/events":
            self._events()
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        return

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        snap = self.runtime_state.snapshot()
        self.wfile.write(b"event: runtime\n")
        self.wfile.write(("data: " + json.dumps(snap) + "\n\n").encode("utf-8"))
        with self.runtime_state.lock:
            events = list(self.runtime_state.events)
        for event in events:
            self.wfile.write(b"event: management\n")
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode("utf-8"))
        for payload in _tail_jsonl(Path(os.getenv("ANALYTICS_EVENT_LOG_PATH", "/state/events/analytics.jsonl")), 200):
            self.wfile.write(b"event: analytics\n")
            self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode("utf-8"))


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run traffic-pilot as an ApexFabric-style solution image")
    parser.add_argument("--repo-root", default=os.getenv("TRAFFIC_PILOT_ROOT", "/opt/traffic-pilot"))
    parser.add_argument("--desired-state", default=os.getenv("DESIRED_STATE_PATH", "/configs/desired_state.json"))
    parser.add_argument("--secrets-root", default=os.getenv("APEXFABRIC_SECRETS_ROOT", "/run/secrets/apexfabric"))
    parser.add_argument("--generated-dir", default=os.getenv("APEXFABRIC_GENERATED_DIR", "/tmp/apexfabric/generated/traffic-pilot"))
    parser.add_argument("--plan-dir", default=os.getenv("APEXFABRIC_PLAN_DIR", "/plans"))
    parser.add_argument("--host", default=os.getenv("APEX_API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("APEX_API_PORT", "8080")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("DESIRED_STATE_RELOAD_INTERVAL", "3")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = RuntimeState()
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
    try:
        server.serve_forever()
    finally:
        reloader.stop_requested.set()
        supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
