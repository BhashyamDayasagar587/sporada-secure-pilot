#!/usr/bin/env bash
# Start the ALPR pilot on the host (no Docker): redis + config-api + UI + worker.
# Per-box config in deploy/.env (VIDEO_DIR, optional Python venv). Stop with ./stop.sh
#
# Usage:
#   ./start.sh         App only. Camera streams are whatever you configure from the
#                      UI (config/cameras.json). Use this for real/production cameras.
#   ./start.sh test    Self-contained demo: ALSO launches the 4 demo videos as local
#                      RTSP streams (run/rtsp_sim.sh) and points the pipeline at them
#                      (config/cameras-test.json). No external cameras needed.
set -e
MODE="${1:-app}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$REPO/deploy/.env"
[ -f "$ENV_FILE" ] || { echo "ERROR: $ENV_FILE missing. Copy deploy/.env.example."; exit 1; }
set -a; . "$ENV_FILE"; set +a

VENV="${WORKER_VENV:-${VOYAGER_VENV:-/home/admin1/voyager-sdk/venv}}"
SDK="$(dirname "$VENV")"
VIDEO_DIR="${VIDEO_DIR:?set VIDEO_DIR in deploy/.env}"
RPORT="${REDIS_PORT:-6379}"
# test mode: fixed 4-cam RTSP demo config (fed by rtsp_sim). app mode: UI-managed cameras.json.
if [ "$MODE" = "test" ]; then
  CAMERAS="$REPO/config/cameras-test.json"
else
  CAMERAS="${CAMERAS_FILE:-$REPO/config/cameras.json}"
fi
mkdir -p "$REPO/run"

[ -d "$VIDEO_DIR" ]         || { echo "ERROR: VIDEO_DIR $VIDEO_DIR does not exist."; exit 1; }
command -v redis-server >/dev/null || { echo "ERROR: redis-server not installed."; exit 1; }
if [ -f "$VENV/bin/activate" ]; then
  PYTHON_BIN="$VENV/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  echo "[start] WARN: worker venv not found; using $PYTHON_BIN for OpenVINO services."
fi

# 1. redis (system)
redis-cli -p "$RPORT" ping >/dev/null 2>&1 || { echo "[start] launching redis on $RPORT…"; redis-server --port "$RPORT" --daemonize yes; }

# 1b. test mode: serve the 4 demo videos as local RTSP streams (rtsp://127.0.0.1:8554/cam01..04)
# so the pipeline has live RTSP input without any external cameras. Blocks ~9s until up.
if [ "$MODE" = "test" ]; then
  echo "[start] test mode: launching 4 demo RTSP streams (rtsp_sim)…"
  bash "$REPO/run/rtsp_sim.sh" || echo "[start] WARN: rtsp_sim failed to start"
fi

# 2. config-api (uvicorn, host) — config + zones + WS analytics + snapshot + live
echo "[start] config-api on :8077…"
( cd "$REPO/services" && \
  VIDEO_DIR="$VIDEO_DIR" REDIS_HOST=localhost REDIS_PORT="$RPORT" \
  CAMERAS_FILE="$CAMERAS" SYSTEM_FILE="$REPO/run/system.json" \
  DEFAULT_BACKEND_MODE=all_openvino nohup "$PYTHON_BIN" -m uvicorn config_api.main:app --host 0.0.0.0 --port 8077 \
  > "$REPO/run/config-api.log" 2>&1 & echo $! > "$REPO/run/config-api.pid" )

# 3. UI (vite dev) — proxies /api to :8077
if command -v npm >/dev/null; then
  echo "[start] UI (vite) on :5173…"
  ( cd "$REPO/ui" && nohup npm run dev > "$REPO/run/ui.log" 2>&1 & echo $! > "$REPO/run/ui.pid" )
else
  echo "[start] WARN: npm not found — skipping UI. Install node, then: cd ui && npm install && npm run dev"
fi

# 4. worker — all-OpenVINO on Intel iGPU/NPU/CPU.
WORKER_SCRIPT="stream_fleet_openvino.py"
echo "[start] worker (all-OpenVINO on Intel iGPU/NPU/CPU)…"
pkill -9 -f '[s]tream_fleet_sdk' 2>/dev/null || true
pkill -9 -f '[s]tream_fleet_openvino' 2>/dev/null || true
pkill -9 -f 'voyager-sdk/venv/bin/python -c from multiprocessing' 2>/dev/null || true  # stale consumer children
sleep 1

# NPU enablement for OpenVINO: stage a clean Level-Zero loader/layer directory
# from system libs and prepend it for the worker. Harmless on CPU-only systems.
ZEOVR="$REPO/run/ze-loader-override"
mkdir -p "$ZEOVR"
for base in libze_loader libze_tracing_layer libze_validation_layer; do
  real="$(readlink -f /usr/lib/x86_64-linux-gnu/$base.so.1 2>/dev/null)" || continue
  [ -f "$real" ] && cp -u "$real" "$ZEOVR/" && ln -sf "$(basename "$real")" "$ZEOVR/$base.so.1"
done

nohup setsid env \
  VIDEO_DIR="$VIDEO_DIR" OPENVINO_MODELS_DIR="$REPO/models/openvino" \
  REDIS_HOST=localhost REDIS_PORT="$RPORT" ANALYTICS_REDIS_STREAM=traffic:analytics \
  SYSTEM_CONFIG_URL=http://localhost:8077/api/system WORKER_CONFIG_PATH="$REPO/config/worker.json" \
  CAMERAS_FILE="$CAMERAS" PYTHONPATH="$REPO/services/worker" INFER_FPS="${INFER_FPS:-12}" \
  CONSUMERS="${CONSUMERS:-1}" \
  bash -c "if [ -f '$VENV/bin/activate' ]; then cd '$SDK' && source '$VENV/bin/activate'; else cd '$REPO'; fi; export LD_LIBRARY_PATH='$ZEOVR':\$LD_LIBRARY_PATH; while true; do '$PYTHON_BIN' -u '$REPO/services/worker/$WORKER_SCRIPT'; echo \"[supervisor] worker exited (\$?) — likely RTSP drop / inference timeout; restarting in 3s\"; sleep 3; done" \
  > "$REPO/run/worker.log" 2>&1 < /dev/null &
disown 2>/dev/null || true

echo
echo "  ALPR pilot started (host, no Docker) — mode=$MODE, cameras=$(basename "$CAMERAS")."
[ "$MODE" = "test" ] && echo "  RTSP demo streams: rtsp://127.0.0.1:8554/cam01..04 (rtsp_sim)"
echo "  UI:   http://localhost:5173    API: http://localhost:8077"
echo "  Logs: $REPO/run/*.log          Stop: $REPO/stop.sh"
