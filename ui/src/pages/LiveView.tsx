import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import CameraTile from "../components/CameraTile";
import { api } from "../lib/api";

export default function LiveView() {
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const list = cameras.data?.cameras || [];
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected ?? list[0]?.camera_id ?? null;
  const cam = list.find((c) => c.camera_id === active);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">
        Live view{" "}
        <span className="text-xs font-normal text-slate-500">(annotated · on-demand · one camera at a time)</span>
      </h1>

      {list.length === 0 ? (
        <div className="rounded border border-dashed border-slate-300 dark:border-slate-700 p-8 text-center text-sm text-slate-500">
          No cameras configured. Add one in the Cameras tab.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {list.map((c) => (
              <button
                key={c.camera_id}
                onClick={() => setSelected(c.camera_id)}
                className={`px-3 py-1 rounded text-sm ${
                  c.camera_id === active
                    ? "bg-sky-600 text-white"
                    : "bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700"
                }`}
              >
                {c.name}
              </button>
            ))}
          </div>
          {cam && <CameraTile key={cam.camera_id} name={cam.name} cameraId={cam.camera_id} />}
        </>
      )}
    </div>
  );
}
