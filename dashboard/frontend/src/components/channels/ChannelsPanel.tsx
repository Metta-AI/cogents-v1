"use client";

import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/shared/Badge";
import { fmtRelative } from "@/lib/format";
import type { Channel } from "@/lib/types";

interface ChannelsPanelProps {
  channels: Channel[];
}

const columns: Column<Channel & Record<string, unknown>>[] = [
  {
    key: "name",
    label: "Name",
    render: (row) => (
      <span className="text-[var(--text-primary)] font-medium">
        {row.name}
      </span>
    ),
  },
  {
    key: "type",
    label: "Type",
    render: (row) => (
      <Badge variant="info">{row.type ?? "unknown"}</Badge>
    ),
  },
  {
    key: "enabled",
    label: "Enabled",
    render: (row) => (
      <span className="inline-flex items-center gap-1.5">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            row.enabled ? "bg-green-400" : "bg-red-400"
          }`}
        />
        <span className="text-[var(--text-secondary)]">
          {row.enabled ? "Yes" : "No"}
        </span>
      </span>
    ),
  },
  {
    key: "created_at",
    label: "Created",
    render: (row) => fmtRelative(row.created_at),
  },
];

export function ChannelsPanel({ channels }: ChannelsPanelProps) {
  const rows = channels as (Channel & Record<string, unknown>)[];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      emptyMessage="No channels found"
    />
  );
}
