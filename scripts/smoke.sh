#!/usr/bin/env bash
# Offline sanity check. Confirms:
#   1. Python imports resolve from the new layout with stubbed deps.
#   2. docker compose can parse the YAML and find every build context.
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

echo "== ALPR edge smoke test =="

echo "[1/2] Python import graph"
python - <<'PYEOF'
import os, sys, types
sys.path.insert(0, "services/worker")
os.environ["DETECTOR_BACKEND"] = "axelera"
os.environ["DECODER_BACKEND"] = "gstreamer"


def stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


stub("cv2",
    dnn=types.SimpleNamespace(NMSBoxes=lambda *a, **k: []),
    resize=lambda *a, **k: None,
    cvtColor=lambda *a, **k: None,
    rectangle=lambda *a, **k: None,
    putText=lambda *a, **k: None,
    getTextSize=lambda *a, **k: ((0, 0), 0),
    FONT_HERSHEY_SIMPLEX=0,
    LINE_AA=0,
    COLOR_BGR2RGB=4,
)
stub("av")
stub("PIL", Image=types.SimpleNamespace(Image=object, fromarray=lambda x: x))
stub("PIL.Image", Image=object, fromarray=lambda x: x)
stub("onnxruntime",
    SessionOptions=lambda: types.SimpleNamespace(graph_optimization_level=0),
    GraphOptimizationLevel=types.SimpleNamespace(ORT_ENABLE_ALL=0),
    get_available_providers=lambda: [],
)
stub("torch", cuda=types.SimpleNamespace(is_available=lambda: False))
stub("ultralytics", YOLO=lambda *a, **k: None)
stub("fcntl", flock=lambda *a, **k: None, LOCK_EX=0, LOCK_NB=0, LOCK_UN=0)
stub("psutil",
    virtual_memory=lambda: types.SimpleNamespace(total=0, available=0, percent=0),
    swap_memory=lambda: types.SimpleNamespace(percent=0),
    cpu_percent=lambda interval=None: 0.0,
    Process=lambda: types.SimpleNamespace(
        memory_info=lambda: types.SimpleNamespace(rss=0),
        num_threads=lambda: 1,
        num_fds=lambda: 1,
        oneshot=lambda: __import__("contextlib").nullcontext(),
    ),
)

import pipeline.stage_factory
import pipeline.analytics
import detectors
import monitor
import hardware_check
import streaming
print("import graph OK")
PYEOF

echo "[2/2] docker compose config"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  docker compose -f deploy/docker-compose.intel-axelera.yml config --quiet
  echo "compose config OK"
else
  echo "docker compose not available locally; skipping (it'll run on the Intel host)"
fi

echo -e "${GREEN}Smoke test passed.${RESET}"
