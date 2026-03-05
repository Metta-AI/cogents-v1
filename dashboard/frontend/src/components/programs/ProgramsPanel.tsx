"use client";

import { useState } from "react";
import type { Program } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtNum, fmtRelative } from "@/lib/format";
import { ExecutionDetail } from "./ExecutionDetail";

interface ProgramsPanelProps {
  programs: Program[];
  cogentName?: string;
}

function typeVariant(type: string) {
  switch (type) {
    case "skill":
      return "accent" as const;
    case "trigger":
      return "warning" as const;
    case "system":
      return "info" as const;
    default:
      return "neutral" as const;
  }
}

export function ProgramsPanel({
  programs,
  cogentName = "cogent",
}: ProgramsPanelProps) {
  const [expandedProgram, setExpandedProgram] = useState<string | null>(null);

  const columns: Column<Program & Record<string, unknown>>[] = [
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
      render: (row) => <Badge variant={typeVariant(row.type)}>{row.type}</Badge>,
    },
    {
      key: "runs",
      label: "Runs",
      render: (row) => <span className="font-mono">{fmtNum(row.runs)}</span>,
    },
    {
      key: "ok",
      label: "Success",
      render: (row) => {
        const pct = row.runs > 0 ? ((row.ok / row.runs) * 100).toFixed(0) : "0";
        return (
          <span className="text-green-400 font-mono">
            {row.ok}/{row.runs} ({pct}%)
          </span>
        );
      },
    },
    {
      key: "fail",
      label: "Fail",
      render: (row) => (
        <span
          className={`font-mono ${row.fail > 0 ? "text-red-400" : "text-[var(--text-muted)]"}`}
        >
          {row.fail}
        </span>
      ),
    },
    {
      key: "total_cost",
      label: "Cost",
      render: (row) => (
        <span className="font-mono">{fmtCost(row.total_cost)}</span>
      ),
    },
    {
      key: "last_run",
      label: "Last Run",
      render: (row) => (
        <span className="text-[var(--text-muted)]">
          {fmtRelative(row.last_run)}
        </span>
      ),
    },
  ];

  const handleRowClick = (row: Program & Record<string, unknown>) => {
    setExpandedProgram((prev) => (prev === row.name ? null : row.name));
  };

  return (
    <div>
      <DataTable
        columns={columns}
        rows={programs as (Program & Record<string, unknown>)[]}
        onRowClick={handleRowClick}
        emptyMessage="No programs registered"
      />
      {expandedProgram && (
        <ExecutionDetail
          programName={expandedProgram}
          cogentName={cogentName}
        />
      )}
    </div>
  );
}
