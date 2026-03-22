"use client";

import type { CogosHandler } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";

interface Props {
  handlers: CogosHandler[];
}

const columns: Column<CogosHandler & Record<string, unknown>>[] = [
  {
    key: "channel_name",
    label: "Channel",
    render: (row) => (
      <span className="font-mono text-xs">
        {row.channel_name ?? row.channel_id ?? "--"}
      </span>
    ),
  },
  {
    key: "process_name",
    label: "Process",
    render: (row) => (
      <span className="text-xs">
        {row.process_name || row.process}
      </span>
    ),
  },
  {
    key: "created_at",
    label: "Created",
    render: (row) => (
      <span className="text-[11px]">
        {row.created_at ? new Date(row.created_at).toLocaleDateString() : "--"}
      </span>
    ),
  },
];

export function HandlersTab({ handlers }: Props) {
  const rows = handlers.map((h) => ({ ...h } as CogosHandler & Record<string, unknown>));

  return (
    <DataTable
      columns={columns}
      rows={rows}
      emptyMessage="No handlers"
      getRowStyle={(row) =>
        row.enabled ? undefined : { color: "var(--error)", opacity: 0.7 }
      }
    />
  );
}
