type BadgeVariant =
  | "success"
  | "warning"
  | "error"
  | "info"
  | "neutral"
  | "accent";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
}

export function Badge({ children, variant = "neutral" }: BadgeProps) {
  const styles: Record<BadgeVariant, string> = {
    success: "bg-green-500/15 text-green-400",
    warning: "bg-amber-500/15 text-amber-400",
    error: "bg-red-500/15 text-red-400",
    info: "bg-blue-500/15 text-blue-400",
    neutral: "bg-slate-500/15 text-slate-400",
    accent: "bg-[var(--accent-glow-strong)] text-[var(--accent)]",
  };

  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide max-w-full truncate ${styles[variant]}`}
    >
      {children}
    </span>
  );
}
