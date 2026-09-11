/**
 * Day x hour activity heatmap, ported from the ApexEdge dashboard and
 * re-themed for traffic-pilot (dark-mode aware). Presentational only — feed
 * it `{ hour, day, value }[]`. Pure CSS grid, no chart dependency.
 */
interface HeatmapProps {
  data: { hour: number; day: number; value: number }[];
  title?: string;
  maxValue?: number;
}

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function cellColor(value: number, max: number): string {
  if (max === 0) return "bg-slate-100 dark:bg-slate-800";
  const intensity = value / max;
  if (intensity > 0.8) return "bg-rose-500";
  if (intensity > 0.6) return "bg-orange-400";
  if (intensity > 0.4) return "bg-amber-400";
  if (intensity > 0.2) return "bg-sky-300";
  if (intensity > 0) return "bg-sky-100 dark:bg-sky-900/50";
  return "bg-slate-100 dark:bg-slate-800";
}

export default function Heatmap({ data, title = "Hourly Heatmap", maxValue }: HeatmapProps) {
  const lookup = new Map<string, number>();
  let computedMax = maxValue ?? 0;
  data.forEach((d) => {
    lookup.set(`${d.day}-${d.hour}`, d.value);
    if (!maxValue && d.value > computedMax) computedMax = d.value;
  });

  return (
    <div className="rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">{title}</div>
      <div className="overflow-x-auto">
        <div className="grid gap-0.5" style={{ gridTemplateColumns: `40px repeat(7, 1fr)` }}>
          <div />
          {days.map((d) => (
            <div key={d} className="text-[10px] text-slate-500 text-center py-1">
              {d}
            </div>
          ))}

          {Array.from({ length: 24 }, (_, hour) => (
            <div key={hour} className="contents">
              <div className="text-[10px] text-slate-500 flex items-center justify-end pr-1">
                {hour.toString().padStart(2, "0")}:00
              </div>
              {Array.from({ length: 7 }, (_, day) => {
                const val = lookup.get(`${day}-${hour}`) ?? 0;
                return (
                  <div
                    key={day}
                    className={`h-4 rounded-sm ${cellColor(val, computedMax)} cursor-default`}
                    title={`${days[day]} ${hour}:00 — ${val}`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2 mt-3 text-[10px] text-slate-500">
        <span>Low</span>
        <div className="flex gap-0.5">
          <div className="w-4 h-3 rounded-sm bg-slate-100 dark:bg-slate-800" />
          <div className="w-4 h-3 rounded-sm bg-sky-100 dark:bg-sky-900/50" />
          <div className="w-4 h-3 rounded-sm bg-sky-300" />
          <div className="w-4 h-3 rounded-sm bg-amber-400" />
          <div className="w-4 h-3 rounded-sm bg-orange-400" />
          <div className="w-4 h-3 rounded-sm bg-rose-500" />
        </div>
        <span>High</span>
      </div>
    </div>
  );
}
