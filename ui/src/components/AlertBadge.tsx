const COLOR = {
  critical: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
} as const;

export default function AlertBadge({
  level,
  children,
}: {
  level: keyof typeof COLOR;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${COLOR[level]}`}
    >
      {children}
    </span>
  );
}
