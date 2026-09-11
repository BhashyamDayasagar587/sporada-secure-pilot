/**
 * Per-camera use-case enable panel.
 *
 * Renders the 7 ALPR use cases as toggles. On toggle it sends a MINIMAL-DELTA
 * PATCH to /api/cameras/{id}: { analytics: { <uc>: { enabled } } }. The config
 * API's storage._deep_merge preserves the rest of the use-case block (lines /
 * zones / masks) and sibling use cases, so flipping a toggle never clobbers
 * geometry drawn in Zone Studio.
 *
 * Beside each toggle a small status reflects live health:
 *   - "no geometry" (warning) when the use case has no lines/zones/masks, or
 *   - "last fired Xs ago" (green) derived from the WS analytics/event stream.
 */
import { useEffect, useRef, useState } from "react";
import type { Camera } from "../lib/api";
import { useEventStream } from "../lib/ws";

export const USE_CASES: { key: string; label: string }[] = [
  { key: "vehicle_counting", label: "Vehicle counting" },
  { key: "pedestrian_counting", label: "Pedestrian counting" },
  { key: "wrong_way_driving_detection", label: "Wrong-way driving" },
  { key: "stopped_vehicle_detection", label: "Stopped vehicle" },
  { key: "vehicle_in_pedestrian_zone_alert", label: "Vehicle in pedestrian zone" },
  { key: "plate_detection", label: "Plate detection" },
  { key: "parking_violation_detection", label: "Parking violation" },
  { key: "fire_smoke_detection", label: "Fire/smoke detection" },
];

type Props = {
  camera: Camera;
  /** Issue a minimal-delta PATCH for this camera. */
  onToggle: (useCase: string, enabled: boolean) => void;
  disabled?: boolean;
};

// True when the use case has at least one configured line / zone / mask.
function hasGeometry(camera: Camera, key: string): boolean {
  const uc = camera.analytics?.[key];
  if (!uc) return false;
  return Boolean(uc.lines?.length || uc.zones?.length || uc.masks?.length);
}

export default function UseCasePanel({ camera, onToggle, disabled }: Props) {
  // Per-use-case last-fired epoch (ms), keyed by use-case name. Subscribes to
  // the shared WS event stream and records the timestamp whenever an event for
  // THIS camera names the use case.
  const [lastFired, setLastFired] = useState<Record<string, number>>({});
  // Re-render once a second so the "Xs ago" labels stay fresh.
  const [, setTick] = useState(0);
  const cameraIdRef = useRef(camera.camera_id);
  cameraIdRef.current = camera.camera_id;

  useEventStream({
    onAnalytics: (msg) => {
      const id = msg.camera?.id ?? msg.camera?.name;
      if (id !== cameraIdRef.current) return;
      const events = msg.events || [];
      if (!events.length) return;
      setLastFired((prev) => {
        const next = { ...prev };
        for (const event of events) {
          if (event.use_case) next[event.use_case] = Date.now();
        }
        return next;
      });
    },
  });

  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      {USE_CASES.map(({ key, label }) => {
        const enabled = !!camera.analytics?.[key]?.enabled;
        const geometry = hasGeometry(camera, key);
        const firedAt = lastFired[key];
        return (
          <div key={key} className="flex flex-col gap-0.5">
            <label
              className="text-xs flex items-center gap-2 select-none"
              title={key}
            >
              <input
                type="checkbox"
                checked={enabled}
                disabled={disabled}
                onChange={(event) => onToggle(key, event.target.checked)}
              />
              {label}
            </label>
            {enabled && (
              <span className="text-[10px] pl-6">
                {!geometry ? (
                  <span className="text-amber-600 dark:text-amber-400" title="No lines/zones/masks configured">
                    no geometry
                  </span>
                ) : firedAt ? (
                  <span className="text-emerald-600 dark:text-emerald-400">
                    last fired {Math.max(0, Math.round((Date.now() - firedAt) / 1000))}s ago
                  </span>
                ) : (
                  <span className="text-slate-400">no events yet</span>
                )}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
