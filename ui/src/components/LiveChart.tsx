/**
 * Live time-series line chart, ported from the ApexEdge dashboard and
 * re-themed for traffic-pilot (dark-mode aware, slate palette). recharts v2.
 *
 * Presentational only: feed it `{ ts, value }[]` from any source
 * (e.g. a rolling window over useEventStream / useAnalyticsStream).
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface LiveChartProps {
  data: { ts: string; value: number }[];
  thresholdLine?: number;
  color?: string;
  label: string;
  yLabel?: string;
}

function formatTime(ts: string) {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export default function LiveChart({ data, thresholdLine, color = "#38bdf8", label, yLabel }: LiveChartProps) {
  return (
    <div className="rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">{label}</div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
          <XAxis dataKey="ts" tickFormatter={formatTime} fontSize={11} tick={{ fontSize: 10 }} />
          <YAxis
            fontSize={11}
            tick={{ fontSize: 10 }}
            label={
              yLabel
                ? { value: yLabel, angle: -90, position: "insideLeft", fontSize: 11 }
                : undefined
            }
          />
          <Tooltip labelFormatter={formatTime} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
          {thresholdLine !== undefined && (
            <ReferenceLine
              y={thresholdLine}
              stroke="#ef4444"
              strokeDasharray="5 5"
              label={{ value: "Threshold", fill: "#ef4444", fontSize: 10 }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
