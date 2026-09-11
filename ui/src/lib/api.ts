import type { MetricsMessage } from "./ws";
export type WorkerMetrics = MetricsMessage;

export type Camera = {
  camera_id: string;
  name: string;
  enabled: boolean;
  source: { type: string; uri: string; fps?: number; width?: number; height?: number };
  processing: { fps?: number; width?: number; height?: number };
  analytics: Record<string, UseCaseConfig>;
};

export type UseCaseConfig = {
  enabled: boolean;
  lines?: Geometry[];
  zones?: Geometry[];
  masks?: Geometry[];
};

export type Geometry = {
  id?: string;
  name?: string;
  shape: "polygon" | "rectangle" | "line";
  points: { x: number; y: number }[];
  purpose?: string;
  type?: string;
  direction?: "a_to_b" | "b_to_a" | "both";
};

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export type SystemHealth = {
  message_type: "system_health";
  schema_version: string;
  observed_at: string;
  host: { ram_used_mb: number; ram_total_mb: number; ram_pct: number; cpu_pct: number; swap_pct: number };
  worker: { rss_mb: number; threads: number; open_fds: number };
  decode: { backend: string; device: string; available: boolean };
  npu: { backend: string; device: string; available: boolean; models_loaded: string[] };
};

export type BackendMode = "all_openvino";

export type StageBackends = { vehicle: string; plate: string; ocr: string };

export type AvailableMode = {
  value: BackendMode;
  label: string;
  backends: StageBackends;
};

export type SystemSettings = {
  backend_mode: BackendMode;
  backends: StageBackends;
  available_modes: AvailableMode[];
};

// Response from PUT /api/system/backend — same as SystemSettings plus a flag
// telling the UI a worker restart is needed before the change takes effect.
export type BackendUpdateResult = SystemSettings & { restart_required: boolean };

export const api = {
  cameras: () => request<{ cameras: Camera[] }>("/api/cameras"),
  // Worker-facing view of the camera config (same shape, different route).
  processorConfig: () => request<{ cameras: Camera[] }>("/api/cameras/processor-config"),
  addCamera: (camera: Camera) =>
    request<Camera>("/api/cameras", { method: "POST", body: JSON.stringify(camera) }),
  // Full replace of the camera collection (PUT). Use sparingly — prefer
  // patchCamera for minimal-delta edits so siblings/geometry are preserved.
  replaceCameras: (cameras: Camera[]) =>
    request<{ cameras: Camera[] }>("/api/cameras", {
      method: "PUT",
      body: JSON.stringify({ cameras }),
    }),
  patchCamera: (camera_id: string, patch: Partial<Camera>) =>
    request<Camera>(`/api/cameras/${camera_id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  upsertGeometry: (
    camera_id: string,
    use_case: string,
    kind: "line" | "zone" | "mask",
    geometry: Geometry,
  ) =>
    request<Geometry>(
      `/api/cameras/${camera_id}/use-cases/${use_case}/geometry`,
      { method: "POST", body: JSON.stringify({ kind, geometry }) },
    ),
  deleteGeometry: (camera_id: string, use_case: string, kind: string, geometry_id: string) =>
    request<{ deleted: string }>(
      `/api/cameras/${camera_id}/use-cases/${use_case}/geometry/${kind}/${geometry_id}`,
      { method: "DELETE" },
    ),
  // Latest system_health snapshot the WS bridge has seen (503 until first tick).
  systemHealth: () => request<SystemHealth>("/api/health/system"),
  // Latest worker_metrics snapshot (throughput + emission health; 503 until first tick).
  metrics: () => request<WorkerMetrics>("/api/metrics"),
  // Liveness probe.
  live: () => request<{ ok: boolean }>("/api/health/live"),
  // Current backend-mode selection plus the list of available modes.
  getSystem: () => request<SystemSettings>("/api/system"),
  // Switch the global inference backend mode. Returns restart_required:true.
  setBackendMode: (mode: BackendMode) =>
    request<BackendUpdateResult>("/api/system/backend", {
      method: "PUT",
      body: JSON.stringify({ backend_mode: mode }),
    }),
};
