#!/usr/bin/env bash
# One-time prerequisites for the ALPR pilot on a fresh box. Run once: ./setup.sh
# (needs sudo for apt). After this, use ./start.sh / ./stop.sh.
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[setup] prerequisites…"

# deploy/.env (per-box config)
if [ ! -f "$REPO/deploy/.env" ]; then
  cp "$REPO/deploy/.env.example" "$REPO/deploy/.env"
  echo "  created deploy/.env — EDIT IT (VIDEO_DIR, VOYAGER_VENV) before ./start.sh"
fi

# redis (analytics bus) + ffmpeg (snapshots) — system packages
command -v redis-server >/dev/null || { echo "  installing redis-server…"; sudo apt-get update && sudo apt-get install -y redis-server; }
command -v ffmpeg       >/dev/null || { echo "  installing ffmpeg…";       sudo apt-get install -y ffmpeg; }

# Node.js (UI / vite dev server)
if ! command -v npm >/dev/null; then
  echo "  installing Node.js 20 (NodeSource)…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
echo "[setup] installing UI deps…"
( cd "$REPO/ui" && npm install )

# Voyager SDK venv (external Axelera runtime — must be installed separately)
# shellcheck disable=SC1091
[ -f "$REPO/deploy/.env" ] && . "$REPO/deploy/.env" || true
VENV="${VOYAGER_VENV:-/opt/voyager-sdk/venv}"
if [ -f "$VENV/bin/activate" ]; then
  echo "  Voyager SDK venv: $VENV ✓"
else
  echo "  WARN: Voyager SDK venv not at $VENV — install the Axelera Voyager SDK and set VOYAGER_VENV in deploy/.env"
fi

# compiled cascade must be present in-repo
[ -d "$REPO/models/cascade-build/alpr-vehicle-plate" ] && echo "  compiled cascade ✓" \
  || echo "  WARN: compiled cascade missing (models/cascade-build/) — see REPLICATION.md"

echo "[setup] done. Edit deploy/.env if needed, then: ./start.sh"
