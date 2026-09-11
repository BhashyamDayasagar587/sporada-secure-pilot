import { useEffect, useRef, useState } from "react";

export type AnalyticsMessage = {
  message_type: "camera_analytics";
  schema_version: string;
  message_id?: string;
  sequence?: number;
  observed_at?: string;
  camera: { id?: string; name: string };
  frame?: { index: number; resolution: { width: number; height: number } };
  summary?: { objects: number; events: number };
  objects: Array<{
    id: number;
    class: string;
    confidence: number;
    bbox: { x1: number; y1: number; x2: number; y2: number };
    attributes?: {
      license_plates?: Array<{ text: string; confidence: number }>;
      use_cases?: Array<{ name: string; state: string; violation: boolean }>;
    };
  }>;
  events: Array<{
    id: string;
    event_type: string;
    use_case: string;
    timestamp: string;
    subject: { track_id: number; type: string };
    plate?: { text: string };
    details?: Record<string, unknown>;
  }>;
  camera_analytics?: { use_cases: any[] };
};

export type SystemMessage = {
  message_type: "system_health";
  schema_version: string;
  observed_at: string;
  host: {
    ram_used_mb: number;
    ram_total_mb: number;
    ram_pct: number;
    cpu_pct: number;
    swap_pct: number;
  };
  worker: { rss_mb: number; threads: number; open_fds: number };
  decode: { backend: string; device: string; available: boolean };
  npu: { backend: string; device: string; available: boolean; models_loaded: string[] };
};

// Throughput + emission-health heartbeat (monitor.WorkerMetricsMonitor),
// published to traffic:system alongside system_health, routed by message_type.
export type MetricsMessage = {
  message_type: "worker_metrics";
  schema_version: string;
  observed_at: string;
  throughput: {
    inferences_per_second: number;
    cameras: number;
    per_camera: Array<{ name: string; fps: number; sequence: number }>;
  };
  emission: {
    sinks: string[];
    queue_depth: number;
    queue_max: number;
    published: number;
    dropped: number;
    errors: number;
    last_error: string | null;
  };
};

export type StreamMessage = AnalyticsMessage | SystemMessage | MetricsMessage;

type Handlers = {
  onAnalytics?: (msg: AnalyticsMessage) => void;
  onSystem?: (msg: SystemMessage) => void;
  onMetrics?: (msg: MetricsMessage) => void;
  onAny?: (msg: StreamMessage) => void;
};

export function useEventStream(handlers: Handlers) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/api/events/ws`);
    ws.addEventListener("open", () => setConnected(true));
    ws.addEventListener("close", () => setConnected(false));
    ws.addEventListener("message", (event) => {
      let msg: StreamMessage;
      try {
        msg = JSON.parse(event.data) as StreamMessage;
      } catch {
        return;
      }
      handlersRef.current.onAny?.(msg);
      if (msg.message_type === "system_health") handlersRef.current.onSystem?.(msg);
      else if (msg.message_type === "worker_metrics") handlersRef.current.onMetrics?.(msg);
      else if (msg.message_type === "camera_analytics") handlersRef.current.onAnalytics?.(msg);
    });
    return () => ws.close();
  }, []);

  return connected;
}

// Backwards-compatible single-callback alias (used by older components).
export function useAnalyticsStream(onMessage: (msg: AnalyticsMessage) => void) {
  return useEventStream({ onAnalytics: onMessage });
}
