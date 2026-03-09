"use client";

import type { CogosProcess } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtTimestamp } from "@/lib/format";

interface Props {
  processes: CogosProcess[];
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  waiting: "neutral",
  runnable: "info",
  running: "success",
  completed: "accent",
  disabled: "error",
  blocked: "warning",
  suspended: "warning",
};

const columns: Column<CogosProcess & Record<string, unknown>>[] = [
  {
    key: "name",
    label: "Name",
    render: (row) => (
      <span className="text-[var(--text-primary)] font-medium">{row.name}</span>
    ),
  },
  {
    key: "mode",
    label: "Mode",
    render: (row) => (
      <Badge variant={row.mode === "daemon" ? "accent" : "info"}>{row.mode}</Badge>
    ),
  },
  {
    key: "status",
    label: "Status",
    render: (row) => (
      <Badge variant={STATUS_VARIANT[row.status] || "neutral"}>{row.status}</Badge>
    ),
  },
  {
    key: "priority",
    label: "Priority",
    sortable: true,
  },
  {
    key: "runner",
    label: "Runner",
  },
  {
    key: "model",
    label: "Model",
    render: (row) =>
      row.model ? (
        <span className="text-[var(--text-secondary)]">{row.model}</span>
      ) : (
        <span className="text-[var(--text-muted)]">--</span>
      ),
  },
  {
    key: "preemptible",
    label: "Preemptible",
    render: (row) => (
      <span className={row.preemptible ? "text-green-400" : "text-[var(--text-muted)]"}>
        {row.preemptible ? "yes" : "no"}
      </span>
    ),
  },
  {
    key: "updated_at",
    label: "Updated",
    render: (row) => (
      <span className="text-[var(--text-muted)] text-xs">{fmtTimestamp(row.updated_at)}</span>
    ),
  },
];

export function ProcessesPanel({ processes }: Props) {
  const rows = processes.map((p) => ({ ...p } as CogosProcess & Record<string, unknown>));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Processes
          <span className="ml-2 text-[var(--text-muted)] font-normal">({processes.length})</span>
        </h2>
        <div className="flex gap-1.5">
          {Object.entries(
            processes.reduce<Record<string, number>>((acc, p) => {
              acc[p.status] = (acc[p.status] || 0) + 1;
              return acc;
            }, {}),
          ).map(([status, count]) => (
            <Badge key={status} variant={STATUS_VARIANT[status] || "neutral"}>
              {count} {status}
            </Badge>
          ))}
        </div>
      </div>
      <DataTable columns={columns} rows={rows} emptyMessage="No processes" />
    </div>
  );
}
