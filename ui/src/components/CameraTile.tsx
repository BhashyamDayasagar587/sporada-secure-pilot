/**
 * On-demand annotated live view. The browser plays the worker's MJPEG stream
 * (multipart/x-mixed-replace) natively in an <img>. Mounting the tile opens the
 * stream, which signals the worker to start drawing that camera; unmounting
 * tears it down so the worker stops. No mediamtx/WebRTC.
 *
 * Switching cameras remounts the tile (keyed by cameraId). A browser does NOT
 * reliably close an MJPEG <img> connection on DOM removal, so those persistent
 * connections pile up and hit the per-host limit (~6), leaving later cameras
 * blank. The unmount cleanup clears the src, which aborts the connection; the
 * server then drops the live:want flag and the worker stops drawing it.
 *
 * No-signal watchdog: when the worker isn't producing frames the endpoint holds
 * the connection open but sends no bytes, so the <img> fires neither load nor
 * error — an unexplained black box. If no frame arrives within NO_SIGNAL_MS we
 * surface a clear "No signal" state instead.
 */
import { useEffect, useRef, useState } from "react";
import { VideoOff, Loader2 } from "lucide-react";

type Props = {
  name: string;
  cameraId: string;
};

const NO_SIGNAL_MS = 8000;

export default function CameraTile({ name, cameraId }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "nosignal">("connecting");

  useEffect(() => {
    setStatus("connecting");
    const watchdog = setTimeout(() => {
      setStatus((s) => (s === "live" ? s : "nosignal"));
    }, NO_SIGNAL_MS);
    const img = imgRef.current;
    return () => {
      clearTimeout(watchdog);
      // On a real unmount (camera switch) the <img> leaves the DOM — abort its
      // MJPEG connection so it doesn't linger and exhaust the browser's per-host
      // limit. Deferred + isConnected guard so React StrictMode's dev double-
      // invoke (which re-runs effects while the element stays mounted) doesn't
      // clear a still-live src.
      setTimeout(() => {
        if (img && !img.isConnected) img.src = "";
      }, 0);
    };
  }, [cameraId]);

  return (
    <div className="rounded-md overflow-hidden border border-slate-200 bg-black">
      <div className="flex items-center justify-between px-3 py-1.5 bg-rail">
        <span className="text-xs uppercase tracking-widest text-slate-300">{name}</span>
        <span className="inline-flex items-center gap-1.5 text-[11px]">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              status === "live" ? "bg-ok-500" : status === "nosignal" ? "bg-crit-500" : "bg-warn-500"
            }`}
          />
          <span className="text-slate-400">
            {status === "live" ? "Live" : status === "nosignal" ? "No signal" : "Connecting"}
          </span>
        </span>
      </div>
      <div className="relative aspect-video flex items-center justify-center bg-black">
        <img
          ref={imgRef}
          src={`/api/cameras/${encodeURIComponent(cameraId)}/live`}
          alt={name}
          onLoad={() => setStatus("live")}
          onError={() => setStatus("nosignal")}
          className="w-full h-full object-contain"
        />
        {status !== "live" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center pointer-events-none">
            {status === "connecting" ? (
              <>
                <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
                <span className="text-sm text-slate-400">Connecting…</span>
              </>
            ) : (
              <>
                <VideoOff className="w-7 h-7 text-slate-500" />
                <span className="text-sm font-medium text-slate-300">No signal</span>
                <span className="text-xs text-slate-500 max-w-xs px-4">
                  No frames from the worker for this camera. Check that the worker process and its
                  RTSP source are running.
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
