/**
 * Bar histogram, ported from the ApexEdge dashboard and re-themed for
 * traffic-pilot (dark-mode aware). recharts v2. Presentational only.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface HistogramProps {
  buckets: { label: string; count: number }[];
  title?: string;
  color?: string;
  thresholdLine?: number;
}

export default function Histogram({ buckets, title = "Distribution", color = "#38bdf8", thresholdLine }: HistogramProps) {
  return (
    <div className="rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">{title}</div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={buckets} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
          <XAxis dataKey="label" fontSize={11} tick={{ fontSize: 10 }} />
          <YAxis fontSize={11} tick={{ fontSize: 10 }} />
          <Tooltip />
          <Bar dataKey="count" fill={color} radius={[3, 3, 0, 0]} />
          {thresholdLine !== undefined && (
            <ReferenceLine y={thresholdLine} stroke="#ef4444" strokeDasharray="5 5" />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
