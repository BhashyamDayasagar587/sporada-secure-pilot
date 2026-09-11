import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import ZoneEditor from "../components/ZoneEditor";
import { api, type Camera, type Geometry } from "../lib/api";

/**
 * Per-use-case geometry rules, mirroring the worker contract in
 * services/worker/pipeline/processor_config.py::USE_CASE_RULES.
 *
 * The worker MATCHES UI-drawn geometry by these exact strings:
 *   - lines  → matched by `purpose`   (line_purposes)
 *   - zones  → matched by `type`      (zone_types)
 *   - wrong-way lines additionally carry a `direction`.
 * Geometry that does not carry the right purpose/type is SILENTLY DISCARDED
 * by normalize_runtime_analytics(), so these strings are load-bearing.
 */
type UseCaseRule = {
  key: string;
  label: string;
  kind: "line" | "zone" | "mask";
  shape: "line" | "polygon";
  /** Emitted on the geometry as `purpose` (lines) or `type` (zones). */
  purpose?: string;
  type?: string;
  /** When true, ZoneEditor shows a direction selector and emits `direction`. */
  needsDirection?: boolean;
};

const USE_CASES: UseCaseRule[] = [
  { key: "vehicle_counting", label: "Vehicle counting", kind: "line", shape: "line", purpose: "object_counting" },
  { key: "pedestrian_counting", label: "Pedestrian counting", kind: "line", shape: "line", purpose: "pedestrian_counting" },
  { key: "wrong_way_driving_detection", label: "Wrong-way line", kind: "line", shape: "line", purpose: "wrong_way_direction", needsDirection: true },
  { key: "stopped_vehicle_detection", label: "Stopped-vehicle zone", kind: "zone", shape: "polygon", type: "stopped_vehicle" },
  { key: "vehicle_in_pedestrian_zone_alert", label: "Pedestrian zone", kind: "zone", shape: "polygon", type: "pedestrian" },
  { key: "parking_violation_detection", label: "No-parking zone", kind: "zone", shape: "polygon", type: "no_parking" },
  { key: "plate_detection", label: "Plate ROI", kind: "zone", shape: "polygon", type: "plate_roi" },
  { key: "fire_smoke_detection", label: "Fire/smoke zone", kind: "zone", shape: "polygon", type: "fire_smoke" },
  { key: "analysis_roi", label: "Analysis ROI (mask)", kind: "mask", shape: "polygon", type: "analysis_roi" },
  { key: "road_roi", label: "Road ROI (mask)", kind: "mask", shape: "polygon", type: "road_roi" },
];

/** Bucket on UseCaseConfig that holds a given geometry kind. */
const BUCKET = { line: "lines", zone: "zones", mask: "masks" } as const;

const STAGE_WIDTH = 1280;
const STAGE_HEIGHT = 720;

/**
 * Stored geometry points are in the camera *processing* frame; ZoneEditor draws
 * (and re-scales on save) in the displayed stage coords. Scale points back up to
 * the stage so a saved shape renders in the right place when loaded as `initial`.
 */
function denormalize(geometry: Geometry | undefined, camera: Camera): Geometry | undefined {
  if (!geometry) return undefined;
  const tw = camera.processing?.width;
  const th = camera.processing?.height;
  const sx = tw ? STAGE_WIDTH / tw : 1;
  const sy = th ? STAGE_HEIGHT / th : 1;
  return { ...geometry, points: geometry.points.map((p) => ({ x: p.x * sx, y: p.y * sy })) };
}

export default function ZoneStudio() {
  const params = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const list = cameras.data?.cameras || [];
  const cameraId = params.cameraId || list[0]?.camera_id || "";
  const camera = list.find((cam) => cam.camera_id === cameraId);
  const [useCase, setUseCase] = useState(USE_CASES[0]);

  const upsert = useMutation({
    mutationFn: (geometry: Geometry) =>
      api.upsertGeometry(cameraId, useCase.key, useCase.kind, geometry),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });

  const remove = useMutation({
    mutationFn: (geometryId: string) =>
      api.deleteGeometry(cameraId, useCase.key, useCase.kind, geometryId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });

  if (!camera) {
    return (
      <div className="text-sm text-slate-500">
        Configure a camera first (see Cameras tab).
      </div>
    );
  }

  const snapshotUrl = `/api/cameras/${cameraId}/snapshot?t=${Date.now()}`;

  // Existing geometry saved for this (camera, use case), read from the bucket
  // that matches the use case's kind. The first is shown on the canvas via
  // ZoneEditor's `initial` prop; all are listed below with delete buttons.
  const useCaseConfig = camera.analytics?.[useCase.key];
  const existing: Geometry[] = useCaseConfig?.[BUCKET[useCase.kind]] || [];
  const disabled = useCaseConfig?.enabled === false;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Zone Studio</h1>
        <select
          value={cameraId}
          onChange={(event) => navigate(`/config/zones/${event.target.value}`)}
          className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
        >
          {list.map((cam) => (
            <option key={cam.camera_id} value={cam.camera_id}>
              {cam.name}
            </option>
          ))}
        </select>
        <select
          value={useCase.key}
          onChange={(event) =>
            setUseCase(USE_CASES.find((item) => item.key === event.target.value) || USE_CASES[0])
          }
          className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
        >
          {USE_CASES.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      {disabled && (
        <div className="text-xs text-amber-600 dark:text-amber-400">
          Use case disabled — toggle it on in{" "}
          <button
            type="button"
            onClick={() => navigate("/config/cameras")}
            className="underline hover:no-underline"
          >
            Cameras
          </button>{" "}
          to activate.
        </div>
      )}
      <ZoneEditor
        key={`${cameraId}:${useCase.key}:${existing[0]?.id ?? "new"}`}
        snapshotUrl={snapshotUrl}
        width={1280}
        height={720}
        shape={useCase.shape}
        purpose={useCase.purpose}
        type={useCase.type}
        needsDirection={useCase.needsDirection}
        targetWidth={camera.processing?.width}
        targetHeight={camera.processing?.height}
        initial={denormalize(existing[0], camera)}
        onSave={(geometry) => upsert.mutate(geometry)}
      />
      {existing.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-slate-500">Saved geometry</div>
          {existing.map((geom, index) => (
            <div
              key={geom.id ?? index}
              className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300"
            >
              <span className="font-mono">{geom.name || geom.id || `#${index + 1}`}</span>
              <button
                type="button"
                className="px-2 py-0.5 rounded bg-rose-100 dark:bg-rose-900/40 text-rose-600 dark:text-rose-300 hover:bg-rose-200 dark:hover:bg-rose-900/70 disabled:opacity-50"
                onClick={() => geom.id && remove.mutate(geom.id)}
                disabled={!geom.id || remove.isPending}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
      {upsert.isPending && <div className="text-xs text-slate-500">Saving…</div>}
      {upsert.isError && (
        <div className="text-xs text-rose-500">Save failed: {(upsert.error as Error).message}</div>
      )}
    </div>
  );
}
