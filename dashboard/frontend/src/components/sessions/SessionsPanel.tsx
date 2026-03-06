"use client";

import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtTimestamp, fmtNum } from "@/lib/format";
import type { Session } from "@/lib/types";

interface SessionsPanelProps {
  sessions: Session[];
}

function statusVariant(status: string | null): "success" | "neutral" | "error" {
  switch (status) {
    case "active":
      return "success";
    case "completed":
      return "neutral";
    case "failed":
      return "error";
    default:
      return "neutral";
  }
}

const columns: Column<Session & Record<string, unknown>>[] = [
  {
    key: "status",
    label: "Status",
    render: (row) => (
      <Badge variant={statusVariant(row.status)}>
        {row.status ?? "unknown"}
      </Badge>
    ),
  },
  {
    key: "context_key",
    label: "Context Key",
    render: (row) => (
      <span className="text-[var(--text-primary)]">
        {row.context_key ?? <span className="text-[var(--text-muted)]">--</span>}
      </span>
    ),
  },
  {
    key: "cli_session_id",
    label: "CLI Session",
    render: (row) => (
      <span className="font-mono text-[11px]">
        {row.cli_session_id
          ? String(row.cli_session_id).slice(0, 12)
          : <span className="text-[var(--text-muted)]">--</span>}
      </span>
    ),
  },
  {
    key: "runs",
    label: "Runs",
    render: (row) => <span className="font-mono">{fmtNum(row.runs)}</span>,
  },
  {
    key: "ok",
    label: "OK / Fail",
    render: (row) => (
      <span>
        <span className="text-green-400">{fmtNum(row.ok)}</span>
        {" / "}
        <span className="text-red-400">{fmtNum(row.fail)}</span>
      </span>
    ),
  },
  {
    key: "total_cost",
    label: "Cost",
    render: (row) => fmtCost(row.total_cost),
  },
  {
    key: "last_active",
    label: "Last Active",
    render: (row) => fmtTimestamp(row.last_active),
  },
];

export function SessionsPanel({ sessions }: SessionsPanelProps) {
  const rows = sessions as (Session & Record<string, unknown>)[];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      emptyMessage="No sessions found"
    />
  );
}
