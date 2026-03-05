interface StatCardProps {
  value: string | number | null;
  label: string;
  variant?: "default" | "accent" | "warning" | "error";
}

export function StatCard({
  value,
  label,
  variant = "default",
}: StatCardProps) {
  const colorClass = {
    default: "text-[var(--text-primary)]",
    accent: "text-[var(--accent)]",
    warning: "text-[var(--warning)]",
    error: "text-[var(--error)]",
  }[variant];

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md px-4 py-3.5">
      <div
        className={`font-mono text-2xl font-medium leading-tight ${value == null ? "text-[var(--text-muted)]" : colorClass}`}
      >
        {value == null ? "--" : value}
      </div>
      <div className="text-[11px] text-[var(--text-muted)] mt-1 uppercase tracking-wide font-medium">
        {label}
      </div>
    </div>
  );
}
