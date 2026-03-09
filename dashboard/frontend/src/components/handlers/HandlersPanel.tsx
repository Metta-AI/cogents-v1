"use client";

import type { CogosHandler } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";

interface Props {
  handlers: CogosHandler[];
}

const columns: Column<CogosHandler & Record<string, unknown>>[] = [
  {
    key: "process_name",
    label: "Process",
    render: (row) => (
      <span className="text-[var(--text-primary)] font-medium">
        {row.process_name || row.process}
      </span>
    ),
  },
  {
    key: "event_pattern",
    label: "Event Pattern",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--text-secondary)]">{row.event_pattern}</span>
    ),
  },
  {
    key: "enabled",
    label: "Enabled",
    render: (row) => (
      <Badge variant={row.enabled ? "success" : "neutral"}>
        {row.enabled ? "enabled" : "disabled"}
      </Badge>
    ),
  },
];

export function HandlersPanel({ handlers }: Props) {
  const rows = handlers.map((h) => ({ ...h } as CogosHandler & Record<string, unknown>));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Handlers
          <span className="ml-2 text-[var(--text-muted)] font-normal">({handlers.length})</span>
        </h2>
      </div>
      <DataTable columns={columns} rows={rows} emptyMessage="No handlers" />
    </div>
  );
}
