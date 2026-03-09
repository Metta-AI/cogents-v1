"use client";

import type { CogosCapability } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";

interface Props {
  capabilities: CogosCapability[];
}

const columns: Column<CogosCapability & Record<string, unknown>>[] = [
  {
    key: "name",
    label: "Name",
    render: (row) => (
      <span className="text-[var(--text-primary)] font-medium">{row.name}</span>
    ),
  },
  {
    key: "description",
    label: "Description",
    render: (row) => (
      <span className="text-[var(--text-secondary)] text-xs">{row.description || "--"}</span>
    ),
  },
  {
    key: "handler",
    label: "Handler",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--text-secondary)]">{row.handler}</span>
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

export function CapabilitiesPanel({ capabilities }: Props) {
  const rows = capabilities.map((c) => ({ ...c } as CogosCapability & Record<string, unknown>));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Capabilities
          <span className="ml-2 text-[var(--text-muted)] font-normal">({capabilities.length})</span>
        </h2>
        <div className="flex gap-1.5">
          <Badge variant="success">
            {capabilities.filter((c) => c.enabled).length} enabled
          </Badge>
          {capabilities.filter((c) => !c.enabled).length > 0 && (
            <Badge variant="neutral">
              {capabilities.filter((c) => !c.enabled).length} disabled
            </Badge>
          )}
        </div>
      </div>
      <DataTable columns={columns} rows={rows} emptyMessage="No capabilities" />
    </div>
  );
}
