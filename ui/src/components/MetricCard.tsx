type Props = {
  label: string;
  value: string | number;
  accent?: "brand" | "ok" | "warn" | "crit" | "slate";
  sub?: string;
};

const ACCENT: Record<NonNullable<Props["accent"]>, string> = {
  brand: "border-l-brand-500",
  ok: "border-l-ok-500",
  warn: "border-l-warn-500",
  crit: "border-l-crit-500",
  slate: "border-l-slate-400",
};

export default function MetricCard({ label, value, accent = "brand", sub }: Props) {
  return (
    <div
      className={`rounded-md bg-panel border border-slate-200 border-l-4 ${ACCENT[accent]} p-4 shadow-sm`}
    >
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-4xl font-bold text-ink">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}
