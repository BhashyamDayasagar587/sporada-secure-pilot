/**
 * Presentational formatting helpers ported from the ApexEdge dashboard.
 * Pure, envelope-agnostic — no API/WS coupling.
 */
export function formatWait(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

export function formatNumber(n: number): string {
  if (!isFinite(n)) return "—";
  return n.toLocaleString("en-US");
}
