"use client";

import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtRelative } from "@/lib/format";
import type { DashboardEvent } from "@/lib/types";
import { EventTree } from "./EventTree";

interface EventsPanelProps {
  events: DashboardEvent[];
  cogentName: string;
}

const columns: Column<DashboardEvent & Record<string, unknown>>[] = [
  {
    key: "id",
    label: "ID",
    render: (row) => (
      <span className="font-mono text-[11px]">
        {String(row.id).slice(0, 8)}
      </span>
    ),
  },
  {
    key: "event_type",
    label: "Type",
    render: (row) => (
      <Badge variant="accent">{row.event_type ?? "event"}</Badge>
    ),
  },
  {
    key: "source",
    label: "Source",
    render: (row) => (
      <span className="text-[var(--text-secondary)]">
        {row.source ?? <span className="text-[var(--text-muted)]">--</span>}
      </span>
    ),
  },
  {
    key: "created_at",
    label: "Created",
    render: (row) => fmtRelative(row.created_at),
  },
];

export function EventsPanel({ events, cogentName }: EventsPanelProps) {
  const [expandedId, setExpandedId] = useState<string | number | null>(null);
  const [treeId, setTreeId] = useState<string | number | null>(null);

  const rows = events as (DashboardEvent & Record<string, unknown>)[];

  const handleRowClick = (row: DashboardEvent & Record<string, unknown>) => {
    setExpandedId((prev) => (prev === row.id ? null : row.id));
    setTreeId(null);
  };

  return (
    <div>
      <DataTable
        columns={columns}
        rows={rows}
        onRowClick={handleRowClick}
        emptyMessage="No events found"
      />
      {expandedId != null && (() => {
        const evt = events.find((e) => e.id === expandedId);
        if (!evt) return null;
        return (
          <div className="mx-3 mb-2 p-3 rounded bg-[var(--bg-elevated)] border border-[var(--border)]">
            <div className="mb-2">
              <JsonViewer data={evt.payload} />
            </div>
            {evt.parent_event_id != null && treeId !== evt.id && (
              <button
                onClick={() => setTreeId(evt.id)}
                className="px-3 py-1 text-[12px] rounded bg-[var(--bg-deep)] border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)] transition-colors"
              >
                View Tree
              </button>
            )}
            {treeId === evt.id && (
              <div className="mt-3">
                <EventTree eventId={evt.id} cogentName={cogentName} />
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
