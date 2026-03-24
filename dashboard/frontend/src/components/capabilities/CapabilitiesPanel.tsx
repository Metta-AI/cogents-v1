"use client";

import { useState, useCallback, useEffect } from "react";
import type { CogosCapability, CapabilityProcess } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { ResizableBottomPanel } from "@/components/shared/ResizableBottomPanel";
import { updateCapability, getCapabilityProcesses } from "@/lib/api";

interface Props {
  capabilities: CogosCapability[];
  cogentName: string;
  onRefresh?: () => void;
}

type CapRow = CogosCapability & Record<string, unknown>;

const STATUS_VARIANT: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
  waiting: "neutral",
  runnable: "info",
  disabled: "neutral",
  blocked: "warning",
  suspended: "warning",
};

function tryParseJSON(s: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  try {
    const v = JSON.parse(s);
    if (typeof v !== "object" || v === null || Array.isArray(v)) return { ok: false, error: "Must be a JSON object" };
    return { ok: true, value: v };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

const columns: Column<CapRow>[] = [
  {
    key: "name",
    label: "Name",
    render: (row) => (
      <span className="font-mono text-[12px]" style={{ color: row.enabled ? "var(--text-secondary)" : "var(--error)", opacity: row.enabled ? 1 : 0.7 }}>
        {row.name}
      </span>
    ),
  },
  {
    key: "description",
    label: "Description",
    render: (row) => (
      <span className="text-[var(--text-muted)] text-[12px] truncate block max-w-[300px]">
        {row.description || "--"}
      </span>
    ),
  },
  {
    key: "handler",
    label: "Handler",
    render: (row) => (
      <span className="font-mono text-[11px] text-[var(--text-muted)]">
        {row.handler || "--"}
      </span>
    ),
  },
  {
    key: "enabled",
    label: "Enabled",
    render: (row) => (
      <Badge variant={row.enabled ? "success" : "neutral"}>
        {row.enabled ? "yes" : "no"}
      </Badge>
    ),
  },
];

export function CapabilitiesPanel({ capabilities, cogentName, onRefresh }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedCap = selectedId ? capabilities.find((c) => c.id === selectedId) ?? null : null;
  const rows = capabilities.map((c) => ({ ...c } as CapRow));

  return (
    <div style={{ paddingBottom: selectedCap ? "45vh" : undefined }}>
      <DataTable
        columns={columns}
        rows={rows}
        emptyMessage="No capabilities"
        getRowId={(row) => row.id as string}
        onRowClick={(row) => setSelectedId(selectedId === row.id ? null : row.id as string)}
        getRowStyle={(row) => row.id === selectedId ? { background: "var(--bg-hover)", borderLeft: "2px solid var(--accent)" } : undefined}
      />

      {selectedCap && (
        <ResizableBottomPanel>
          <div className="p-4">
            <CapabilityDetail
              cap={selectedCap}
              cogentName={cogentName}
              onRefresh={onRefresh}
              onClose={() => setSelectedId(null)}
            />
          </div>
        </ResizableBottomPanel>
      )}
    </div>
  );
}

interface DetailProps {
  cap: CogosCapability;
  cogentName: string;
  onRefresh?: () => void;
  onClose: () => void;
}

const inputClass = "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";
const btnClass = "px-2.5 py-1 rounded text-[11px] font-medium transition-colors disabled:opacity-40";
const btnPrimary = `${btnClass} bg-[var(--accent)] text-white hover:opacity-90`;
const btnGhost = `${btnClass} text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]`;

function CapabilityDetail({ cap, cogentName, onRefresh, onClose }: DetailProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [processes, setProcesses] = useState<CapabilityProcess[]>([]);
  const [loadingProcs, setLoadingProcs] = useState(false);
  const [editForm, setEditForm] = useState({ description: "", instructions: "", schema: "" });
  const [schemaError, setSchemaError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoadingProcs(true);
    getCapabilityProcesses(cogentName, cap.name)
      .then((p) => { if (!cancelled) setProcesses(p); })
      .catch(() => { if (!cancelled) setProcesses([]); })
      .finally(() => { if (!cancelled) setLoadingProcs(false); });
    return () => { cancelled = true; };
  }, [cogentName, cap.name]);

  const startEdit = useCallback(() => {
    setEditForm({
      description: cap.description,
      instructions: cap.instructions || "",
      schema: JSON.stringify(cap.schema || {}, null, 2),
    });
    setSchemaError("");
    setEditing(true);
  }, [cap]);

  const handleSave = useCallback(async () => {
    const result = tryParseJSON(editForm.schema);
    if (!result.ok) { setSchemaError(result.error); return; }
    setSaving(true);
    try {
      await updateCapability(cogentName, cap.name, {
        description: editForm.description,
        instructions: editForm.instructions,
        schema: result.value,
      });
      setEditing(false);
      onRefresh?.();
    } finally { setSaving(false); }
  }, [cogentName, cap.name, editForm, onRefresh]);

  const handleToggle = useCallback(async () => {
    setToggling(true);
    try {
      await updateCapability(cogentName, cap.name, { enabled: !cap.enabled });
      onRefresh?.();
    } finally { setToggling(false); }
  }, [cogentName, cap, onRefresh]);

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[var(--text-primary)] font-mono">{cap.name}</span>
          <Badge variant={cap.enabled ? "success" : "neutral"}>{cap.enabled ? "enabled" : "disabled"}</Badge>
        </div>
        <div className="flex items-center gap-1">
          <button className={btnGhost} disabled={toggling} onClick={handleToggle}>
            {toggling ? "..." : cap.enabled ? "Disable" : "Enable"}
          </button>
          {!editing && <button className={btnGhost} onClick={startEdit}>Edit</button>}
          <button className={btnGhost} onClick={onClose}>&times;</button>
        </div>
      </div>

      {editing ? (
        <div className="space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Description</span>
            <input className={inputClass} value={editForm.description} onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Instructions</span>
            <textarea className={`${inputClass} resize-y`} rows={3} value={editForm.instructions} onChange={(e) => setEditForm((f) => ({ ...f, instructions: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Schema (JSON)</span>
            <textarea className={`${inputClass} font-mono resize-y`} rows={6} value={editForm.schema} onChange={(e) => { setEditForm((f) => ({ ...f, schema: e.target.value })); setSchemaError(""); }} />
            {schemaError && <span className="text-[10px] text-[var(--error)]">{schemaError}</span>}
          </label>
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={saving || !!schemaError} onClick={handleSave}>{saving ? "Saving..." : "Save"}</button>
            <button className={btnGhost} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-[12px] text-[var(--text-secondary)]">{cap.description || "No description"}</div>
          {cap.instructions && (
            <div>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Instructions</span>
              <pre className="mt-1 text-[11px] text-[var(--text-muted)] whitespace-pre-wrap">{cap.instructions}</pre>
            </div>
          )}
          {cap.handler && (
            <div className="text-[11px] text-[var(--text-muted)]">Handler: <span className="font-mono">{cap.handler}</span></div>
          )}
          {cap.schema && Object.keys(cap.schema).length > 0 && (
            <details className="text-[11px]">
              <summary className="text-[var(--text-muted)] cursor-pointer">Schema</summary>
              <pre className="mt-1 text-[10px] text-[var(--text-muted)] font-mono bg-[var(--bg-base)] rounded p-2 overflow-x-auto">
                {JSON.stringify(cap.schema, null, 2)}
              </pre>
            </details>
          )}
          {/* Granted processes */}
          <div>
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">
              Granted to {loadingProcs ? "..." : `${processes.length} process${processes.length !== 1 ? "es" : ""}`}
            </span>
            {processes.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {processes.map((p) => (
                  <div key={p.process_id} className="inline-flex items-center gap-1 text-[11px] bg-[var(--bg-base)] rounded px-2 py-0.5">
                    <span className="font-mono text-[var(--text-secondary)]">{p.process_name}</span>
                    <Badge variant={STATUS_VARIANT[p.process_status] || "neutral"}>{p.process_status}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
