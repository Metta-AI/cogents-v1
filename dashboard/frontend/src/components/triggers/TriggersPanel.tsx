"use client";

import { useState, useCallback, useMemo } from "react";
import type { Trigger } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { createTrigger, updateTrigger, deleteTrigger } from "@/lib/api";
import { fmtNum } from "@/lib/format";

interface TriggersPanelProps {
  triggers: Trigger[];
  cogentName: string;
  programs?: string[];
  onRefresh?: () => void;
}

interface CreateFormState {
  program_name: string;
  event_pattern: string;
  max_events: number;
  throttle_window_seconds: number;
}

interface EditFormState {
  program_name: string;
  event_pattern: string;
  max_events: number;
  throttle_window_seconds: number;
}

const EMPTY_CREATE: CreateFormState = {
  program_name: "",
  event_pattern: "",
  max_events: 0,
  throttle_window_seconds: 60,
};

const getTriggerGroup = (t: Trigger): string => {
  const parts = t.name.split(":");
  if (parts.length <= 1) return "other";
  return parts.slice(0, -1).join("/");
};

export function TriggersPanel({ triggers, cogentName, programs = [], onRefresh }: TriggersPanelProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>(EMPTY_CREATE);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditFormState>({ program_name: "", event_pattern: "", max_events: 0, throttle_window_seconds: 60 });
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const displayItems = useMemo(() => {
    if (!selectedPath) return triggers;
    const tree = buildTree(triggers, getTriggerGroup);
    const node = findNode(tree, selectedPath);
    return node ? getAllItems(node) : triggers;
  }, [triggers, selectedPath]);

  const handleCreate = useCallback(async () => {
    if (!createForm.program_name || !createForm.event_pattern) return;
    setCreating(true);
    try {
      await createTrigger(cogentName, {
        program_name: createForm.program_name,
        event_pattern: createForm.event_pattern,
        max_events: createForm.max_events,
        throttle_window_seconds: createForm.throttle_window_seconds,
      });
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      onRefresh?.();
    } finally {
      setCreating(false);
    }
  }, [cogentName, createForm, onRefresh]);

  const startEdit = useCallback((t: Trigger) => {
    setEditingId(t.id);
    setEditForm({
      program_name: t.program_name ?? "",
      event_pattern: t.event_pattern ?? "",
      max_events: t.max_events ?? 0,
      throttle_window_seconds: t.throttle_window_seconds ?? 60,
    });
  }, []);

  const handleSaveEdit = useCallback(async () => {
    if (!editingId) return;
    setSaving(true);
    try {
      await updateTrigger(cogentName, editingId, {
        program_name: editForm.program_name,
        event_pattern: editForm.event_pattern,
        max_events: editForm.max_events,
        throttle_window_seconds: editForm.throttle_window_seconds,
      });
      setEditingId(null);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, editingId, editForm, onRefresh]);

  const handleDelete = useCallback(async (triggerId: string) => {
    setDeletingId(triggerId);
    try {
      await deleteTrigger(cogentName, triggerId);
      setConfirmDeleteId(null);
      onRefresh?.();
    } finally {
      setDeletingId(null);
    }
  }, [cogentName, onRefresh]);

  const datalistId = "trigger-programs-list";

  const inputClass =
    "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
  const btnClass =
    "px-2.5 py-1 rounded text-[11px] font-medium transition-colors disabled:opacity-40";
  const btnPrimary = `${btnClass} bg-[var(--accent)] text-white hover:opacity-90`;
  const btnDanger = `${btnClass} bg-red-600 text-white hover:bg-red-700`;
  const btnGhost = `${btnClass} text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]`;

  const triggerLeafName = (t: Trigger) => {
    const parts = t.name.split(":");
    return parts[parts.length - 1] || t.name;
  };

  return (
    <div className="flex h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      {/* Tree sidebar */}
      <HierarchyPanel
        items={triggers}
        getGroup={getTriggerGroup}
        selectedPath={selectedPath}
        onSelectPath={setSelectedPath}
      />

      {/* Main content */}
      <div className="flex-1 overflow-auto p-3 space-y-3">
        {/* Top bar */}
        <div className="flex items-center justify-between">
          <datalist id={datalistId}>
            {programs.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
          <button
            className={btnPrimary}
            onClick={() => setShowCreate((s) => !s)}
          >
            {showCreate ? "Cancel" : "+ New Trigger"}
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-3">
            <div className="text-[13px] font-semibold text-[var(--text-primary)]">New Trigger</div>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="flex flex-col gap-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Program</span>
                <input
                  list={datalistId}
                  className={inputClass}
                  placeholder="program-name"
                  value={createForm.program_name}
                  onChange={(e) => setCreateForm((f) => ({ ...f, program_name: e.target.value }))}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Event Pattern</span>
                <input
                  className={inputClass}
                  placeholder="event.pattern.*"
                  value={createForm.event_pattern}
                  onChange={(e) => setCreateForm((f) => ({ ...f, event_pattern: e.target.value }))}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Max Events</span>
                <input
                  type="number"
                  className={`${inputClass} w-[80px]`}
                  value={createForm.max_events}
                  onChange={(e) => setCreateForm((f) => ({ ...f, max_events: parseInt(e.target.value) || 0 }))}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Window (s)</span>
                <input
                  type="number"
                  className={`${inputClass} w-[80px]`}
                  value={createForm.throttle_window_seconds}
                  onChange={(e) => setCreateForm((f) => ({ ...f, throttle_window_seconds: parseInt(e.target.value) || 60 }))}
                />
              </label>
              <button
                className={btnPrimary}
                disabled={creating || !createForm.program_name || !createForm.event_pattern}
                onClick={handleCreate}
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        )}

        {/* Trigger table */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Name
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Event
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                  1m
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                  5m
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                  1h
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                  24h
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center">
                  Throttle
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {displayItems.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-[var(--text-muted)] text-[13px] py-8 text-center">
                    No triggers configured
                  </td>
                </tr>
              )}
              {displayItems.map((t) => {
                const isEditing = editingId === t.id;
                const isConfirmingDelete = confirmDeleteId === t.id;
                const isDeleting = deletingId === t.id;

                if (isEditing) {
                  return (
                    <tr
                      key={t.id}
                      className="border-b border-[var(--border)] last:border-0 bg-[var(--bg-hover)]"
                    >
                      <td className="px-4 py-2">
                        <input
                          list={datalistId}
                          className={`${inputClass} w-full`}
                          value={editForm.program_name}
                          onChange={(e) => setEditForm((f) => ({ ...f, program_name: e.target.value }))}
                          placeholder="program-name"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <input
                          className={`${inputClass} w-full`}
                          value={editForm.event_pattern}
                          onChange={(e) => setEditForm((f) => ({ ...f, event_pattern: e.target.value }))}
                          placeholder="event.pattern.*"
                        />
                      </td>
                      <td className="px-3 py-2" colSpan={2}>
                        <div className="flex gap-2 items-center">
                          <label className="flex flex-col gap-0.5">
                            <span className="text-[9px] text-[var(--text-muted)]">Max Events</span>
                            <input
                              type="number"
                              className={`${inputClass} w-[60px]`}
                              value={editForm.max_events}
                              onChange={(e) => setEditForm((f) => ({ ...f, max_events: parseInt(e.target.value) || 0 }))}
                            />
                          </label>
                          <label className="flex flex-col gap-0.5">
                            <span className="text-[9px] text-[var(--text-muted)]">Window (s)</span>
                            <input
                              type="number"
                              className={`${inputClass} w-[60px]`}
                              value={editForm.throttle_window_seconds}
                              onChange={(e) => setEditForm((f) => ({ ...f, throttle_window_seconds: parseInt(e.target.value) || 60 }))}
                            />
                          </label>
                        </div>
                      </td>
                      <td colSpan={2} />
                      <td />
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <button
                          className={btnPrimary}
                          disabled={saving}
                          onClick={handleSaveEdit}
                        >
                          {saving ? "Saving..." : "Save"}
                        </button>
                        <button
                          className={`${btnGhost} ml-1`}
                          onClick={() => setEditingId(null)}
                        >
                          Cancel
                        </button>
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr
                    key={t.id}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                  >
                    <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                      {triggerLeafName(t)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] max-w-[200px] truncate">
                      {t.event_pattern ?? t.cron_expression ?? "--"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                      {fmtNum(t.fired_1m)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                      {fmtNum(t.fired_5m)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                      {fmtNum(t.fired_1h)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                      {fmtNum(t.fired_24h)}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {t.max_events > 0 ? (
                        <span className="inline-flex items-center gap-1.5">
                          {t.throttle_active ? (
                            <Badge variant="error">THROTTLED</Badge>
                          ) : (
                            <Badge variant="success">OK</Badge>
                          )}
                          <span className="text-[10px] text-[var(--text-muted)]">
                            {t.max_events}/{t.throttle_window_seconds}s
                          </span>
                          {t.throttle_rejected > 0 && (
                            <span className="text-[10px] text-red-400">
                              ({fmtNum(t.throttle_rejected)} rejected)
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-[10px] text-[var(--text-muted)]">--</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {isConfirmingDelete ? (
                        <span className="text-[11px]">
                          <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                          <button
                            className={btnDanger}
                            disabled={isDeleting}
                            onClick={() => handleDelete(t.id)}
                          >
                            {isDeleting ? "..." : "Yes"}
                          </button>
                          <button
                            className={`${btnGhost} ml-1`}
                            onClick={() => setConfirmDeleteId(null)}
                          >
                            No
                          </button>
                        </span>
                      ) : (
                        <>
                          <button
                            className={btnGhost}
                            onClick={() => startEdit(t)}
                          >
                            Edit
                          </button>
                          <button
                            className={`${btnGhost} ml-1 hover:!text-red-400`}
                            onClick={() => setConfirmDeleteId(t.id)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
