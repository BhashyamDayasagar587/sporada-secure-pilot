import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, RotateCw } from "lucide-react";
import { api, type AvailableMode, type BackendMode } from "../lib/api";

// Per-stage backend chip. Colour-codes the OpenVINO stages running on Intel
// iGPU/NPU/CPU.
function BackendChip({ stage, backend }: { stage: string; backend: string }) {
  const tone =
    backend === "openvino"
        ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200"
        : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
  return (
    <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{stage}</span>
      <span className={`rounded px-1.5 py-0.5 ${tone}`}>{backend}</span>
    </span>
  );
}

export default function Settings() {
  const qc = useQueryClient();
  const system = useQuery({ queryKey: ["system"], queryFn: api.getSystem });
  // Tracks the mode the user just switched to so we can show the
  // restart-required banner until the query state settles / page is left.
  const [changedTo, setChangedTo] = useState<string | null>(null);

  const setMode = useMutation({
    mutationFn: (mode: BackendMode) => api.setBackendMode(mode),
    onSuccess: (result) => {
      const label =
        result.available_modes.find((m) => m.value === result.backend_mode)?.label ??
        result.backend_mode;
      if (result.restart_required) setChangedTo(label);
      qc.invalidateQueries({ queryKey: ["system"] });
    },
  });

  const active = system.data?.backend_mode;
  const modes: AvailableMode[] = system.data?.available_modes ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <section className="space-y-3">
        <h2 className="text-[10px] uppercase tracking-widest text-slate-500">Inference backend mode</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Select where each detection stage runs. Changing the mode reconfigures the worker pipeline.
        </p>

        {changedTo && (
          <div className="flex items-center gap-2 rounded border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200 px-3 py-2 text-sm">
            <RotateCw className="w-4 h-4 shrink-0" />
            <span>
              Backend changed to <span className="font-semibold">{changedTo}</span> — restart the worker
              to apply.
            </span>
          </div>
        )}

        {system.isLoading && <div className="text-sm text-slate-500">Loading…</div>}
        {system.isError && (
          <div className="text-sm text-rose-600 dark:text-rose-400">Failed to load system settings.</div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {modes.map((mode) => {
            const isActive = mode.value === active;
            return (
              <button
                key={mode.value}
                type="button"
                disabled={setMode.isPending}
                onClick={() => {
                  if (mode.value !== active) setMode.mutate(mode.value);
                }}
                className={`text-left rounded-md border p-4 transition-colors ${
                  "disabled:opacity-60"
                } ${
                  isActive
                    ? "border-sky-500 ring-1 ring-sky-500 bg-sky-50 dark:bg-sky-900/20"
                    : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-sm">{mode.label}</span>
                  {isActive && (
                    <span className="inline-flex items-center gap-1 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200">
                      <Check className="w-3 h-3" />
                      Active
                    </span>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <BackendChip stage="vehicle" backend={mode.backends.vehicle} />
                  <BackendChip stage="plate" backend={mode.backends.plate} />
                  <BackendChip stage="ocr" backend={mode.backends.ocr} />
                </div>
              </button>
            );
          })}
        </div>

        {setMode.isError && (
          <div className="text-sm text-rose-600 dark:text-rose-400">
            Failed to change backend mode.
          </div>
        )}
      </section>
    </div>
  );
}
