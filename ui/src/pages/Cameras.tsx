import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import UseCasePanel from "../components/UseCasePanel";
import { api, type Camera } from "../lib/api";

export default function Cameras() {
  const qc = useQueryClient();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Camera> }) => api.patchCamera(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });
  const add = useMutation({
    mutationFn: (camera: Camera) => api.addCamera(camera),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });
  const [draft, setDraft] = useState<{
    camera_id: string;
    name: string;
    uri: string;
    fps: number;
    transport: "tcp" | "udp";
    username: string;
    password: string;
  }>({
    camera_id: "",
    name: "",
    uri: "",
    fps: 25,
    transport: "tcp",
    username: "",
    password: "",
  });

  // Derive the source.type from the URI scheme, matching the CameraSource
  // model enum (file | rtsp | http | https). rtsp:// and rtsps:// both map to
  // "rtsp"; rtmp:// has no dedicated enum value so it also rides on "rtsp".
  const sourceTypeFor = (uri: string): "file" | "rtsp" | "http" | "https" => {
    const u = uri.trim().toLowerCase();
    if (u.startsWith("rtsp://") || u.startsWith("rtsps://") || u.startsWith("rtmp://")) return "rtsp";
    if (u.startsWith("https://")) return "https";
    if (u.startsWith("http://")) return "http";
    return "file";
  };
  const isRtsp = sourceTypeFor(draft.uri) === "rtsp";

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Cameras</h1>
      <div className="space-y-3">
        {(cameras.data?.cameras || []).map((camera) => (
          <div
            key={camera.camera_id}
            className="rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="font-semibold">{camera.name}</div>
                <div className="text-xs text-slate-500">{camera.source.uri}</div>
              </div>
              <label className="text-xs flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={camera.enabled}
                  onChange={(event) =>
                    patch.mutate({
                      id: camera.camera_id,
                      body: { enabled: event.target.checked },
                    })
                  }
                />
                Enabled
              </label>
            </div>
            <UseCasePanel
              camera={camera}
              disabled={patch.isPending}
              onToggle={(useCase, enabled) =>
                patch.mutate({
                  id: camera.camera_id,
                  // Minimal-delta PATCH: only the enabled flag for this one use
                  // case. _deep_merge preserves geometry + sibling use cases.
                  body: { analytics: { [useCase]: { enabled } } } as Partial<Camera>,
                })
              }
            />
          </div>
        ))}
      </div>
      <div className="rounded border border-dashed border-slate-300 dark:border-slate-700 p-4">
        <h2 className="font-semibold mb-2">Add camera</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <input
            placeholder="camera_id"
            value={draft.camera_id}
            onChange={(event) => setDraft({ ...draft, camera_id: event.target.value })}
            className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
          />
          <input
            placeholder="name"
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
          />
          <input
            placeholder="rtsp://… or 20/20A.mp4"
            value={draft.uri}
            onChange={(event) => setDraft({ ...draft, uri: event.target.value })}
            className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
          />
          <button
            onClick={() =>
              add.mutate({
                camera_id: draft.camera_id,
                name: draft.name,
                enabled: true,
                source: {
                  type: sourceTypeFor(draft.uri),
                  uri: draft.uri,
                  fps: draft.fps,
                  // RTSP-only connection knobs; only included when set.
                  ...(isRtsp
                    ? {
                        transport: draft.transport,
                        ...(draft.username ? { username: draft.username } : {}),
                        ...(draft.password ? { password: draft.password } : {}),
                      }
                    : {}),
                },
                processing: { fps: 12 },
                analytics: {},
              } as Camera)
            }
            className="px-3 py-1.5 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
            disabled={!draft.camera_id || !draft.uri}
          >
            Add
          </button>
        </div>
        {isRtsp && (
          <div className="mt-2 grid grid-cols-1 md:grid-cols-4 gap-2">
            <select
              value={draft.transport}
              onChange={(event) =>
                setDraft({ ...draft, transport: event.target.value as "tcp" | "udp" })
              }
              className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
              title="RTSP transport"
            >
              <option value="tcp">Transport: TCP</option>
              <option value="udp">Transport: UDP</option>
            </select>
            <input
              placeholder="username (optional)"
              value={draft.username}
              onChange={(event) => setDraft({ ...draft, username: event.target.value })}
              className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
            />
            <input
              placeholder="password (optional)"
              type="password"
              value={draft.password}
              onChange={(event) => setDraft({ ...draft, password: event.target.value })}
              className="px-3 py-1.5 text-sm rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
            />
          </div>
        )}
      </div>
    </div>
  );
}
