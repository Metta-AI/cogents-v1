"use client";

import { useState, useCallback, useMemo } from "react";
import type { Tool } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { toggleTools, deleteTool, updateTool } from "@/lib/api";

interface ToolsPanelProps {
  tools: Tool[];
  cogentName: string;
  onRefresh?: () => void;
}

const getToolGroup = (t: Tool): string => {
  const parts = t.name.split("/");
  if (parts.length <= 1) return "other";
  return parts.slice(0, -1).join("/");
};

export function ToolsPanel({ tools, cogentName, onRefresh }: ToolsPanelProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ description: "", instructions: "" });
  const [saving, setSaving] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const displayItems = useMemo(() => {
    if (!selectedPath) return tools;
    const tree = buildTree(tools, getToolGroup);
    const node = findNode(tree, selectedPath);
    return node ? getAllItems(node) : tools;
  }, [tools, selectedPath]);

  const handleToggle = useCallback(async (t: Tool) => {
    setTogglingId(t.id);
    try {
      await toggleTools(cogentName, [t.name], !t.enabled);
      onRefresh?.();
    } finally {
      setTogglingId(null);
    }
  }, [cogentName, onRefresh]);

  const startEdit = useCallback((t: Tool) => {
    setEditingId(t.id);
    setEditForm({ description: t.description, instructions: t.instructions });
  }, []);

  const handleSaveEdit = useCallback(async (t: Tool) => {
    setSaving(true);
    try {
      await updateTool(cogentName, t.name, {
        description: editForm.description,
        instructions: editForm.instructions,
      });
      setEditingId(null);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, editForm, onRefresh]);

  const handleDelete = useCallback(async (t: Tool) => {
    setDeletingId(t.id);
    try {
      await deleteTool(cogentName, t.name);
      setConfirmDeleteId(null);
      setExpandedId(null);
      onRefresh?.();
    } finally {
      setDeletingId(null);
    }
  }, [cogentName, onRefresh]);

  const inputClass =
    "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";
  const btnClass =
    "px-2.5 py-1 rounded text-[11px] font-medium transition-colors disabled:opacity-40";
  const btnPrimary = `${btnClass} bg-[var(--accent)] text-white hover:opacity-90`;
  const btnDanger = `${btnClass} bg-red-600 text-white hover:bg-red-700`;
  const btnGhost = `${btnClass} text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]`;

  const expandedTool = expandedId ? displayItems.find((x) => x.id === expandedId) ?? null : null;

  return (
    <div className="flex h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      <HierarchyPanel
        items={tools}
        getGroup={getToolGroup}
        selectedPath={selectedPath}
        onSelectPath={setSelectedPath}
      />

      <div className="flex-1 overflow-auto p-3 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[12px] text-[var(--text-muted)]">
            {displayItems.length} tool{displayItems.length !== 1 ? "s" : ""}
            {selectedPath && <span className="ml-1 text-[var(--text-secondary)]">in {selectedPath}</span>}
          </span>
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
              </tr>
            </thead>
            <tbody>
              {displayItems.length === 0 && (
                <tr>
                  <td colSpan={2} className="text-[var(--text-muted)] text-[13px] py-8 text-center">
                    No tools registered
                  </td>
                </tr>
              )}
              {displayItems.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-[var(--border)] last:border-0 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                  style={expandedId === t.id ? { background: "var(--bg-hover)" } : undefined}
                  onDoubleClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                >
                  <td className="px-4 py-2 align-top">
                    <span className="font-mono text-[12px] text-[var(--text-secondary)]">
                      {t.name}
                    </span>
                    {!t.enabled && <span className="ml-2"><Badge variant="neutral">disabled</Badge></span>}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] truncate align-top">
                    {t.description || "--"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Expanded detail / edit panel */}
        {expandedTool && (() => {
          const t = expandedTool;
          const isEditing = editingId === t.id;
          const isConfirmingDelete = confirmDeleteId === t.id;
          const isDeleting = deletingId === t.id;
          const isToggling = togglingId === t.id;

          return (
            <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold text-[var(--text-primary)] font-mono">{t.name}</span>
                <div className="flex items-center gap-1">
                  <button
                    className={btnGhost}
                    disabled={isToggling}
                    onClick={() => handleToggle(t)}
                  >
                    {isToggling ? "..." : t.enabled ? "Disable" : "Enable"}
                  </button>
                  {!isEditing && (
                    <button className={btnGhost} onClick={() => startEdit(t)}>Edit</button>
                  )}
                  {isConfirmingDelete ? (
                    <span className="flex items-center gap-1 text-[11px]">
                      <span className="text-[var(--text-muted)]">Delete?</span>
                      <button className={btnDanger} disabled={isDeleting} onClick={() => handleDelete(t)}>
                        {isDeleting ? "..." : "Yes"}
                      </button>
                      <button className={btnGhost} onClick={() => setConfirmDeleteId(null)}>No</button>
                    </span>
                  ) : (
                    <button className={`${btnGhost} hover:!text-red-400`} onClick={() => setConfirmDeleteId(t.id)}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {isEditing ? (
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
                      className={`${inputClass} min-h-[80px] resize-y`}
                      value={editForm.instructions}
                      onChange={(e) => setEditForm((f) => ({ ...f, instructions: e.target.value }))}
                    />
                  </label>
                  <div className="flex gap-2">
                    <button className={btnPrimary} disabled={saving} onClick={() => handleSaveEdit(t)}>
                      {saving ? "Saving..." : "Save"}
                    </button>
                    <button className={btnGhost} onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 text-[12px]">
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Description</span>
                    <span className="text-[var(--text-secondary)]">{t.description || "--"}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Instructions</span>
                    <span className="text-[var(--text-secondary)] whitespace-pre-wrap">{t.instructions || "--"}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Handler</span>
                    <span className="text-[var(--text-secondary)] font-mono text-[11px]">{t.handler || "--"}</span>
                  </div>
                  {t.iam_role_arn && (
                    <div>
                      <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">IAM Role</span>
                      <span className="text-[var(--text-secondary)] font-mono text-[11px]">{t.iam_role_arn}</span>
                    </div>
                  )}
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide block mb-0.5">Input Schema</span>
                    <pre className="text-[var(--text-muted)] font-mono text-[11px] bg-[var(--bg-elevated)] rounded p-2 overflow-x-auto">
                      {JSON.stringify(t.input_schema, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
}
