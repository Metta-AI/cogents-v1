"use client";

import { useState, useEffect } from "react";
import type { Execution } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtMs, fmtNum, fmtRelative } from "@/lib/format";

interface ExecutionDetailProps {
  programName: string;
  cogentName: string;
}

function statusVariant(status: string | null) {
  switch (status) {
    case "success":
    case "completed":
      return "success" as const;
    case "running":
    case "in_progress":
      return "info" as const;
    case "failed":
    case "error":
      return "error" as const;
    default:
      return "neutral" as const;
  }
}

const columns: Column<Execution & Record<string, unknown>>[] = [
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
    key: "started_at",
    label: "Started",
    render: (row) => (
      <span className="text-[var(--text-secondary)]">
        {fmtRelative(row.started_at)}
      </span>
    ),
  },
  {
    key: "duration_ms",
    label: "Duration",
    render: (row) => (
      <span className="font-mono">{fmtMs(row.duration_ms)}</span>
    ),
  },
  {
    key: "tokens_input",
    label: "Tokens In",
    render: (row) => (
      <span className="font-mono">{fmtNum(row.tokens_input)}</span>
    ),
  },
  {
    key: "tokens_output",
    label: "Tokens Out",
    render: (row) => (
      <span className="font-mono">{fmtNum(row.tokens_output)}</span>
    ),
  },
  {
    key: "cost_usd",
    label: "Cost",
    render: (row) => (
      <span className="font-mono">{fmtCost(row.cost_usd)}</span>
    ),
  },
  {
    key: "error",
    label: "Error",
    render: (row) =>
      row.error ? (
        <span className="text-red-400 truncate max-w-[200px] inline-block">
          {row.error}
        </span>
      ) : (
        <span className="text-[var(--text-muted)]">--</span>
      ),
  },
];

export function ExecutionDetail({
  programName,
  cogentName,
}: ExecutionDetailProps) {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchExecutions() {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(
          `/api/cogents/${cogentName}/programs/${programName}/executions`,
        );
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        const data = await resp.json();
        if (!cancelled) {
          setExecutions(data.executions ?? []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchExecutions();
    return () => {
      cancelled = true;
    };
  }, [cogentName, programName]);

  if (loading) {
    return (
      <div className="px-4 py-3 text-[12px] text-[var(--text-muted)]">
        Loading executions...
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-4 py-3 text-[12px] text-red-400">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-4 mt-1 mb-2">
      <div className="text-[11px] text-[var(--text-muted)] uppercase tracking-wide mb-2">
        Execution History &mdash;{" "}
        <span className="text-[var(--text-primary)]">{programName}</span>
      </div>
      <DataTable
        columns={columns}
        rows={
          executions as (Execution & Record<string, unknown>)[]
        }
        emptyMessage="No executions found"
      />
    </div>
  );
}
