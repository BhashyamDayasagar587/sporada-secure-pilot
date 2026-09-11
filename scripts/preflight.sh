#!/usr/bin/env bash
# Run before `make up`. Verifies the Intel host has the Axelera NPU and the
# iGPU media stack visible — catches "wrong machine" / "missing driver"
# mistakes early so the container doesn't fail later in confusing ways.
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${RESET} $*"; }
warn() { echo -e "  ${YELLOW}[!! ]${RESET} $*"; }
fail() { echo -e "  ${RED}[FAIL]${RESET} $*"; FAILED=1; }

FAILED=0
echo "== ALPR edge preflight =="

# 1. Axelera NPU
echo "Checking Axelera NPU..."
if lspci -k 2>/dev/null | grep -i axelera >/dev/null; then
  ok "PCIe device visible: $(lspci -k | grep -i axelera | head -n1 | sed 's/^\s*//')"
else
  fail "lspci: no Axelera device found. Install axelera-driver-dkms and reboot."
fi

if [ -c /dev/metis0 ]; then
  ok "Device node /dev/metis0 present"
else
  fail "Device node /dev/metis0 missing — kernel module not loaded?"
fi

# 2. Intel iGPU
echo "Checking Intel iGPU..."
if [ -c /dev/dri/renderD128 ]; then
  ok "Device node /dev/dri/renderD128 present"
else
  fail "/dev/dri/renderD128 missing — install Intel media driver (intel-media-va-driver-non-free)"
fi

if command -v vainfo >/dev/null 2>&1; then
  if vainfo 2>/dev/null | grep -E 'VAEntrypointVLD|VAEntrypointEncSlice' >/dev/null; then
    ok "vainfo reports decode + encode profiles"
  else
    warn "vainfo OK but no encode/decode profiles found — output streaming may fall back to CPU"
  fi
else
  warn "vainfo not installed on host; skipping (the container still has it)"
fi

# 3. GStreamer iGPU decoders (optional — only relevant if running gst-launch on host)
if command -v gst-inspect-1.0 >/dev/null 2>&1; then
  for element in qsvh264dec vaapih264dec; do
    if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
      ok "GStreamer element on host: $element"
    else
      warn "GStreamer element missing on host: $element (container has its own copy)"
    fi
  done
fi

# 4. Compose config + required env
echo "Checking deploy config..."
if [ ! -f deploy/.env ]; then
  fail "deploy/.env missing. Copy deploy/.env.example to deploy/.env and set VIDEO_DIR/MODELS_DIR."
fi
if [ ! -f config/cameras.json ]; then
  warn "config/cameras.json missing. Will use the example on first boot if present."
fi
if [ -f config/cameras.example.json ] && [ ! -f config/cameras.json ]; then
  warn "Tip: cp config/cameras.example.json config/cameras.json"
fi

# 5. Required Axelera artifacts
echo "Checking compiled models..."
for model in vehicle license_plate ocr; do
  if [ -f "models/axelera/${model}.axl" ]; then
    ok "models/axelera/${model}.axl"
  else
    fail "models/axelera/${model}.axl missing. See HANDOFF_MODEL_CONVERSION.md."
  fi
done

echo
if [ "$FAILED" -ne 0 ]; then
  echo -e "${RED}Preflight FAILED.${RESET} Fix the [FAIL] lines above and retry."
  exit 1
fi
echo -e "${GREEN}Preflight passed.${RESET}"
