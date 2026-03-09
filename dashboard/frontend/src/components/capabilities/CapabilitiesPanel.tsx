"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import type { CogosCapability, CapabilityProcess } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { updateCapability, getCapabilityProcesses } from "@/lib/api";

interface Props {
  capabilities: CogosCapability[];
  cogentName: string;
  onRefresh?: () => void;
}

const getCapGroup = (c: CogosCapability): string => {
  const parts = c.name.split("/");
  if (parts.length <= 1) return "other";
  return parts.slice(0, -1).join("/");
};

const inputClass =
  "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";
const btnClass =
  "px-2.5 py-1 rounded text-[11px] font-medium transition-colors disabled:opacity-40";
const btnPrimary = `${btnClass} bg-[var(--accent)] text-white hover:opacity-90`;
const btnGhost = `${btnClass} text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]`;

const STATUS_VARIANT: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
  waiting: "neutral",
  runnable: "info",
  running: "success",
  completed: "neutral",
  disabled: "error",
  blocked: "warning",
  suspended: "warning",
};

function tryParseJSON(s: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  try {
    const v = JSON.parse(s);
    if (typeof v !== "object" || v === null || Array.isArray(v)) {
      return { ok: false, error: "Must be a JSON object" };
    }
    return { ok: true, value: v };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

/* ── Detail panel for a selected capability ── */

interface DetailProps {
  cap: CogosCapability;
  cogentName: string;
  onRefresh?: () => void;
  onClose: () => void;
}

function CapabilityDetail({ cap, cogentName, onRefresh, onClose }: DetailProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [processes, setProcesses] = useState<CapabilityProcess[]>([]);
  const [loadingProcs, setLoadingProcs] = useState(false);

  const [editForm, setEditForm] = useState({
    description: "",
    instructions: "",
    input_schema: "",
    output_schema: "",
  });
  const [schemaErrors, setSchemaErrors] = useState({ input: "", output: "" });

  // Collapsed state for schema sections
  const [inputCollapsed, setInputCollapsed] = useState(false);
  const [outputCollapsed, setOutputCollapsed] = useState(false);

  // Load granted processes
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
      input_schema: JSON.stringify(cap.input_schema || {}, null, 2),
      output_schema: JSON.stringify(cap.output_schema || {}, null, 2),
    });
    setSchemaErrors({ input: "", output: "" });
    setEditing(true);
  }, [cap]);

  const validateSchemas = useCallback((): boolean => {
    const inResult = tryParseJSON(editForm.input_schema);
    const outResult = tryParseJSON(editForm.output_schema);
    setSchemaErrors({
      input: inResult.ok ? "" : inResult.error,
      output: outResult.ok ? "" : outResult.error,
    });
    return inResult.ok && outResult.ok;
  }, [editForm.input_schema, editForm.output_schema]);

  const handleSave = useCallback(async () => {
    if (!validateSchemas()) return;
    setSaving(true);
    try {
      const inParsed = JSON.parse(editForm.input_schema);
      const outParsed = JSON.parse(editForm.output_schema);
      await updateCapability(cogentName, cap.name, {
        description: editForm.description,
        instructions: editForm.instructions,
        input_schema: inParsed,
        output_schema: outParsed,
      });
      setEditing(false);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, cap.name, editForm, validateSchemas, onRefresh]);

  const handleToggle = useCallback(async () => {
    setToggling(true);
    try {
      await updateCapability(cogentName, cap.name, { enabled: !cap.enabled });
      onRefresh?.();
    } finally {
      setToggling(false);
    }
  }, [cogentName, cap, onRefresh]);

  const canSave = !schemaErrors.input && !schemaErrors.output;

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[var(--text-primary)] font-mono">{cap.name}</span>
          <Badge variant={cap.enabled ? "success" : "neutral"}>
            {cap.enabled ? "enabled" : "disabled"}
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          <button className={btnGhost} disabled={toggling} onClick={handleToggle}>
            {toggling ? "..." : cap.enabled ? "Disable" : "Enable"}
          </button>
          {!editing && (
            <button className={btnGhost} onClick={startEdit}>Edit</button>
          )}
          <button className={btnGhost} onClick={onClose}>&times;</button>
        </div>
      </div>

      {editing ? (
        <div className="space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Description</span>
            <input
              className={inputClass}
              value={editForm.description}
              onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Instructions</span>
            <textarea
              className={`${inputClass} min-h-[60px] resize-y`}
              value={editForm.instructions}
              onChange={(e) => setEditForm((f) => ({ ...f, instructions: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Input Schema</span>
            <textarea
              className={`${inputClass} min-h-[100px] resize-y font-mono text-[11px]`}
              value={editForm.input_schema}
              onChange={(e) => {
                setEditForm((f) => ({ ...f, input_schema: e.target.value }));
                const r = tryParseJSON(e.target.value);
                setSchemaErrors((prev) => ({ ...prev, input: r.ok ? "" : r.error }));
              }}
            />
            {schemaErrors.input && (
              <span className="text-[10px] text-[var(--error)]">{schemaErrors.input}</span>
            )}
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Output Schema</span>
            <textarea
              className={`${inputClass} min-h-[100px] resize-y font-mono text-[11px]`}
              value={editForm.output_schema}
              onChange={(e) => {
                setEditForm((f) => ({ ...f, output_schema: e.target.value }));
                const r = tryParseJSON(e.target.value);
                setSchemaErrors((prev) => ({ ...prev, output: r.ok ? "" : r.error }));
              }}
            />
            {schemaErrors.output && (
              <span className="text-[10px] text-[var(--error)]">{schemaErrors.output}</span>
            )}
          </label>
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={saving || !canSave} onClick={handleSave}>
              {saving ? "Saving..." : "Save"}
            </button>
            <button className={btnGhost} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="space-y-2 text-[12px]">
          <div>
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Description</span>
            <span className="text-[var(--text-secondary)]">{cap.description || "--"}</span>
          </div>
          {cap.instructions && (
            <div>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Instructions</span>
              <span className="text-[var(--text-secondary)] whitespace-pre-wrap">{cap.instructions}</span>
            </div>
          )}
          <div>
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Handler</span>
            <span className="text-[var(--text-secondary)] font-mono text-[11px]">{cap.handler || "--"}</span>
          </div>
          {cap.iam_role_arn && (
            <div>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">IAM Role</span>
              <span className="text-[var(--text-secondary)] font-mono text-[11px]">{cap.iam_role_arn}</span>
            </div>
          )}

          {/* Input Schema */}
          <div>
            <button
              className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-0.5 bg-transparent border-0 cursor-pointer p-0 flex items-center gap-1 hover:text-[var(--text-secondary)]"
              onClick={() => setInputCollapsed((c) => !c)}
            >
              <span className="text-[8px]">{inputCollapsed ? "\u25B6" : "\u25BC"}</span>
              Input Schema
            </button>
            {!inputCollapsed && (
              <pre className="text-[var(--text-muted)] font-mono text-[11px] bg-[var(--bg-elevated)] rounded p-2 overflow-x-auto m-0">
                {JSON.stringify(cap.input_schema, null, 2) || "{}"}
              </pre>
            )}
          </div>

          {/* Output Schema */}
          <div>
            <button
              className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-0.5 bg-transparent border-0 cursor-pointer p-0 flex items-center gap-1 hover:text-[var(--text-secondary)]"
              onClick={() => setOutputCollapsed((c) => !c)}
            >
              <span className="text-[8px]">{outputCollapsed ? "\u25B6" : "\u25BC"}</span>
              Output Schema
            </button>
            {!outputCollapsed && (
              <pre className="text-[var(--text-muted)] font-mono text-[11px] bg-[var(--bg-elevated)] rounded p-2 overflow-x-auto m-0">
                {JSON.stringify(cap.output_schema, null, 2) || "{}"}
              </pre>
            )}
          </div>

          {/* Granted Processes */}
          <div>
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-1">
              Granted Processes
              {!loadingProcs && <span className="ml-1">({processes.length})</span>}
            </span>
            {loadingProcs ? (
              <span className="text-[var(--text-muted)] text-[11px]">Loading...</span>
            ) : processes.length === 0 ? (
              <span className="text-[var(--text-muted)] text-[11px]">No processes granted this capability</span>
            ) : (
              <div className="space-y-1">
                {processes.map((p) => (
                  <div
                    key={p.process_id}
                    className="flex items-center gap-2 text-[11px] px-2 py-1 rounded"
                    style={{ background: "var(--bg-elevated)" }}
                  >
                    <span className="font-mono text-[var(--text-secondary)]">{p.process_name}</span>
                    <Badge variant={STATUS_VARIANT[p.process_status] || "neutral"}>{p.process_status}</Badge>
                    {p.delegatable && (
                      <span className="text-[10px] text-[var(--text-muted)]">delegatable</span>
                    )}
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

/* ── Main panel ── */

export function CapabilitiesPanel({ capabilities, cogentName, onRefresh }: Props) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const displayItems = useMemo(() => {
    if (!selectedPath) return capabilities;
    const tree = buildTree(capabilities, getCapGroup);
    const node = findNode(tree, selectedPath);
    return node ? getAllItems(node) : capabilities;
  }, [capabilities, selectedPath]);

  const expandedCap = expandedId ? displayItems.find((c) => c.id === expandedId) ?? null : null;

  return (
    <div className="flex h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      <HierarchyPanel
        items={capabilities}
        getGroup={getCapGroup}
        selectedPath={selectedPath}
        onSelectPath={setSelectedPath}
      />

      <div className="flex-1 overflow-auto p-3 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[12px] text-[var(--text-muted)]">
            {displayItems.length} capabilit{displayItems.length !== 1 ? "ies" : "y"}
            {selectedPath && <span className="ml-1 text-[var(--text-secondary)]">in {selectedPath}</span>}
          </span>
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

        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Name
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Description
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Handler
                </th>
              </tr>
            </thead>
            <tbody>
              {displayItems.length === 0 && (
                <tr>
                  <td colSpan={3} className="text-[var(--text-muted)] text-[13px] py-8 text-center">
                    No capabilities
                  </td>
                </tr>
              )}
              {displayItems.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-[var(--border)] last:border-0 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                  style={expandedId === c.id ? { background: "var(--bg-hover)" } : undefined}
                  onDoubleClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                >
                  <td className="px-4 py-2 align-top">
                    <span className="font-mono text-[12px] text-[var(--text-secondary)]">
                      {c.name}
                    </span>
                    {!c.enabled && <span className="ml-2"><Badge variant="neutral">disabled</Badge></span>}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] truncate align-top max-w-[300px]">
                    {c.description || "--"}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] font-mono text-[11px] truncate align-top max-w-[200px]">
                    {c.handler || "--"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {expandedCap && (
          <CapabilityDetail
            cap={expandedCap}
            cogentName={cogentName}
            onRefresh={onRefresh}
            onClose={() => setExpandedId(null)}
          />
        )}
      </div>
    </div>
  );
}
