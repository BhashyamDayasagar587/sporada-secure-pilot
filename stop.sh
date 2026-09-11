#!/usr/bin/env bash
# Stop the ALPR pilot: worker + config-api + UI + the test RTSP streams (rtsp_sim).
# Leaves system redis running (shared daemon; `redis-cli shutdown` if you want it gone).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# worker (both backends) + its multiprocessing consumer children. Two passes: the
# start.sh supervisor is a `while true` loop that respawns the worker, so a single
# kill can race a respawn. Children's cmdline is "python -c from multiprocessing.."
# (no script name) so the worker-name match misses them — kill the venv spawns too.
for _ in 1 2; do
  pkill -9 -f '[s]tream_fleet_sdk' 2>/dev/null || true
  pkill -9 -f '[s]tream_fleet_openvino' 2>/dev/null || true
  pkill -9 -f 'voyager-sdk/venv/bin/python -c from multiprocessing' 2>/dev/null || true
  sleep 1
done

# config-api + UI (by pid file, then by name — a stale instance from an earlier
# run can outlive its pid file and keep :8077 bound, serving old code).
for p in config-api ui; do
  pid_file="$REPO/run/$p.pid"
  [ -f "$pid_file" ] && { kill "$(cat "$pid_file")" 2>/dev/null || true; rm -f "$pid_file"; }
done
pkill -9 -f '[u]vicorn config_api' 2>/dev/null || true
pkill -f '[v]ite' 2>/dev/null || true

# test RTSP streams: the rtsp_sim launcher + its ffmpeg publishers + mediamtx broker
pkill -9 -f '[r]tsp_sim.sh' 2>/dev/null || true
pkill -9 -f 'ffmpeg.*rtsp://127.0.0.1:8554' 2>/dev/null || true
pkill -9 -f '[m]ediamtx' 2>/dev/null || true

echo "stopped worker + config-api + UI + rtsp_sim (redis left running)"
