#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENGINE="${CONTAINER_ENGINE:-}"
if [[ -z "$ENGINE" ]]; then
  if command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then
    ENGINE=podman
  else
    echo "ERROR: docker or podman is required" >&2
    exit 1
  fi
fi

BASE_TAG="${INTEL_TRAFFIC_PILOT_BASE_TAG:-localhost/apexfabric-intel-traffic-runtime-base:intel-285h-2026.08.24-v1}"
IMAGE_VERSION="${APEXFABRIC_IMAGE_VERSION:-2026.09.11-v1}"
IMAGE_TAG="localhost/traffic-pilot-runtime:intel-285h-${IMAGE_VERSION}"
platform_args=(--platform linux/amd64)

if [[ "${BUILD_TRAFFIC_PILOT_BASE:-0}" == "1" ]]; then
  BASE_VERSION="${INTEL_TRAFFIC_PILOT_BASE_VERSION:-2026.09.11-v1}"
  BASE_TAG="localhost/apexfabric-intel-traffic-pilot-runtime-base:intel-285h-${BASE_VERSION}"
  "$ENGINE" build "${platform_args[@]}"     --build-arg TARGETARCH=amd64     -f docker/Dockerfile.traffic-pilot-base     -t "$BASE_TAG" .
fi

if ! "$ENGINE" image inspect "$BASE_TAG" >/dev/null 2>&1; then
  echo "ERROR: base image not found: $BASE_TAG" >&2
  echo "Load or tag the existing Intel environment base first, or set INTEL_TRAFFIC_PILOT_BASE_TAG." >&2
  exit 1
fi

base_digest="$("$ENGINE" image inspect "$BASE_TAG" --format '{{.Id}}')"
base_from="$BASE_TAG"

"$ENGINE" build "${platform_args[@]}"   --build-arg "INTEL_TRAFFIC_PILOT_RUNTIME_BASE=${base_from}"   --build-arg "INTEL_TRAFFIC_PILOT_RUNTIME_BASE_DIGEST=${base_digest}"   --build-arg "IMAGE_VERSION=${IMAGE_VERSION}"   -f docker/Dockerfile.traffic-pilot   -t "$IMAGE_TAG" .

mkdir -p delivery/apexfabric-v1/intel-285h/traffic-pilot
archive="delivery/apexfabric-v1/intel-285h/traffic-pilot/image-${IMAGE_VERSION}.tar"
"$ENGINE" save -o "$archive" "$IMAGE_TAG"
sha256sum "$archive" > "${archive%.tar}.sha256"

echo "built runtime base: $BASE_TAG@$base_digest"
echo "built workload:     $IMAGE_TAG"
echo "saved archive:      $archive"
