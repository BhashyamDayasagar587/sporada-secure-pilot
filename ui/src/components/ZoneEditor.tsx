/**
 * Konva-based geometry editor for the ZoneStudio page.
 *
 * Lets the user click to drop polygon/line/rectangle vertices on a still
 * frame, then submits to /api/cameras/{id}/use-cases/{use_case}/geometry.
 *
 * Two correctness concerns are handled here (see the worker contract in
 * services/worker/pipeline/processor_config.py::USE_CASE_RULES):
 *
 *   1. Lines/zones MUST carry the right `purpose`/`type` (and wrong-way lines a
 *      `direction`), otherwise the worker silently discards the geometry. The
 *      caller passes these in as props and `save()` stamps them onto the
 *      emitted Geometry.
 *
 *   2. The user draws on the displayed stage (width x height px), but the worker
 *      matches geometry against the camera's *processing* frame coordinates. If
 *      `targetWidth`/`targetHeight` differ from the displayed size we scale the
 *      points on save so they align with the frames the worker actually sees.
 */
import { useEffect, useMemo, useState } from "react";
import { Stage, Layer, Image as KonvaImage, Line as KonvaLine, Circle, Rect } from "react-konva";
import type { Geometry } from "../lib/api";

type Direction = "a_to_b" | "b_to_a" | "both";

function useImage(url: string): [HTMLImageElement | undefined] {
  const [image, setImage] = useState<HTMLImageElement | undefined>(undefined);
  useEffect(() => {
    if (!url) return;
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.src = url;
    img.onload = () => setImage(img);
    return () => {
      img.onload = null;
    };
  }, [url]);
  return [image];
}

type ShapeKind = "polygon" | "rectangle" | "line";

type Props = {
  snapshotUrl: string;
  width: number;
  height: number;
  shape: ShapeKind;
  /** Stamped onto the saved geometry as `purpose` (line use cases). */
  purpose?: string;
  /** Stamped onto the saved geometry as `type` (zone use cases). */
  type?: string;
  /** When true, show the direction selector + arrowhead (wrong-way). */
  needsDirection?: boolean;
  /** Camera processing frame size; points are scaled to this on save. */
  targetWidth?: number;
  targetHeight?: number;
  initial?: Geometry;
  onSave: (geometry: Geometry) => void;
};

/**
 * Arrowhead polyline for a direction-aware line. `dir` selects which endpoint
 * the head sits on (or both). Returns flat [x,y,...] segments for KonvaLine.
 */
function arrowHeads(
  a: { x: number; y: number },
  b: { x: number; y: number },
  dir: Direction,
): number[][] {
  const size = 14;
  const headAt = (tip: { x: number; y: number }, from: { x: number; y: number }) => {
    const dx = tip.x - from.x;
    const dy = tip.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    // two barbs rotated +/- ~30deg from the reverse direction
    const angle = Math.PI / 6;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const left = {
      x: tip.x - size * (ux * cos - uy * sin),
      y: tip.y - size * (uy * cos + ux * sin),
    };
    const right = {
      x: tip.x - size * (ux * cos + uy * sin),
      y: tip.y - size * (uy * cos - ux * sin),
    };
    return [left.x, left.y, tip.x, tip.y, right.x, right.y];
  };
  const heads: number[][] = [];
  if (dir === "a_to_b" || dir === "both") heads.push(headAt(b, a));
  if (dir === "b_to_a" || dir === "both") heads.push(headAt(a, b));
  return heads;
}

export default function ZoneEditor({
  snapshotUrl,
  width,
  height,
  shape,
  purpose,
  type,
  needsDirection,
  targetWidth,
  targetHeight,
  initial,
  onSave,
}: Props) {
  const [image] = useImage(snapshotUrl);
  const [points, setPoints] = useState<{ x: number; y: number }[]>(initial?.points || []);
  const [direction, setDirection] = useState<Direction>(
    (initial?.direction as Direction) || "both",
  );

  const flat: number[] = points.flatMap((point) => [point.x, point.y]);

  const heads = useMemo(() => {
    if (shape !== "line" || !needsDirection || points.length < 2) return [];
    return arrowHeads(points[0], points[1], direction);
  }, [shape, needsDirection, points, direction]);

  const handleClick = (event: any) => {
    const { x, y } = event.target.getStage().getPointerPosition();
    if (shape === "line" && points.length >= 2) return setPoints([{ x, y }]);
    if (shape === "rectangle" && points.length >= 2) return setPoints([{ x, y }]);
    setPoints([...points, { x, y }]);
  };

  const undo = () => setPoints(points.slice(0, -1));
  const clear = () => setPoints([]);

  const save = () => {
    // Scale from displayed stage coords to the camera processing frame so the
    // worker's geometry matching lines up with the frames it actually sees.
    const sx = targetWidth ? targetWidth / width : 1;
    const sy = targetHeight ? targetHeight / height : 1;
    const scaled = points.map((p) => ({ x: p.x * sx, y: p.y * sy }));

    const geometry: Geometry = {
      ...(initial || {}),
      // Reuse the existing geometry's id on edit; mint a stable one for a new
      // geometry so storage.upsert_geometry REPLACES instead of appending.
      id: initial?.id ?? crypto.randomUUID(),
      shape,
      points: scaled,
    };
    if (purpose) geometry.purpose = purpose;
    if (type) geometry.type = type;
    if (needsDirection) geometry.direction = direction;
    onSave(geometry);
  };

  const DIRECTIONS: { value: Direction; label: string }[] = [
    { value: "a_to_b", label: "A → B" },
    { value: "b_to_a", label: "B → A" },
    { value: "both", label: "Both" },
  ];

  return (
    <div className="space-y-3">
      <div className="border border-slate-200 dark:border-slate-800 rounded overflow-hidden">
        <Stage width={width} height={height} onClick={handleClick}>
          <Layer>
            {image && <KonvaImage image={image} width={width} height={height} />}
            {shape === "polygon" && points.length > 0 && (
              <KonvaLine
                points={[...flat, points[0].x, points[0].y]}
                stroke="#22d3ee"
                strokeWidth={2}
                closed={points.length >= 3}
                fill="rgba(34,211,238,0.15)"
              />
            )}
            {shape === "line" && points.length >= 2 && (
              <KonvaLine points={flat} stroke="#f97316" strokeWidth={3} />
            )}
            {heads.map((head, index) => (
              <KonvaLine key={`head-${index}`} points={head} stroke="#f97316" strokeWidth={3} />
            ))}
            {shape === "rectangle" && points.length >= 2 && (
              <Rect
                x={Math.min(points[0].x, points[1].x)}
                y={Math.min(points[0].y, points[1].y)}
                width={Math.abs(points[1].x - points[0].x)}
                height={Math.abs(points[1].y - points[0].y)}
                stroke="#a855f7"
                strokeWidth={2}
                fill="rgba(168,85,247,0.12)"
              />
            )}
            {points.map((point, index) => (
              <Circle key={index} x={point.x} y={point.y} radius={4} fill="#facc15" />
            ))}
          </Layer>
        </Stage>
      </div>

      {shape === "line" && (
        <div className="text-xs text-slate-500">
          Click two points to draw the {needsDirection ? "wrong-way" : "counting"} line
          (A = first point, B = second).
        </div>
      )}

      {needsDirection && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Direction</span>
          <div className="inline-flex rounded border border-slate-300 dark:border-slate-700 overflow-hidden">
            {DIRECTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => setDirection(option.value)}
                className={`px-3 py-1.5 text-xs ${
                  direction === option.value
                    ? "bg-sky-600 text-white"
                    : "bg-white dark:bg-slate-900 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <button
          className="px-3 py-1.5 text-sm rounded bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700"
          onClick={undo}
        >
          Undo
        </button>
        <button
          className="px-3 py-1.5 text-sm rounded bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700"
          onClick={clear}
        >
          Clear
        </button>
        <button
          className="ml-auto px-3 py-1.5 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
          onClick={save}
          disabled={points.length < (shape === "polygon" ? 3 : 2)}
        >
          Save
        </button>
      </div>
    </div>
  );
}
