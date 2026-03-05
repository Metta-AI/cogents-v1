"use client";

import { useState, useCallback } from "react";
import type { CronItem } from "@/lib/types";
import { createCron, updateCron, deleteCron, toggleCrons } from "@/lib/api";

interface CronPanelProps {
  crons: CronItem[];
  cogentName: string;
  onRefresh: () => void;
}

export function CronPanel({ crons, cogentName, onRefresh }: CronPanelProps) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Create form state
  const [newExpr, setNewExpr] = useState("*/5 * * * *");
  const [newPattern, setNewPattern] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);

  // Edit form state
  const [editExpr, setEditExpr] = useState("");
  const [editPattern, setEditPattern] = useState("");

  const handleCreate = useCallback(async () => {
    if (!newExpr.trim() || !newPattern.trim()) return;
    await createCron(cogentName, {
      cron_expression: newExpr.trim(),
      event_pattern: newPattern.trim(),
      enabled: newEnabled,
    });
    setCreating(false);
    setNewExpr("*/5 * * * *");
    setNewPattern("");
    setNewEnabled(true);
    onRefresh();
  }, [cogentName, newExpr, newPattern, newEnabled, onRefresh]);

  const handleToggle = useCallback(
    async (cron: CronItem) => {
      setToggling((s) => new Set(s).add(cron.id));
      try {
        await toggleCrons(cogentName, [cron.id], !cron.enabled);
        onRefresh();
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          next.delete(cron.id);
          return next;
        });
      }
    },
    [cogentName, onRefresh],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteCron(cogentName, id);
      setDeleteConfirm(null);
      onRefresh();
    },
    [cogentName, onRefresh],
  );

  const startEdit = useCallback((cron: CronItem) => {
    setEditingId(cron.id);
    setEditExpr(cron.cron_expression);
    setEditPattern(cron.event_pattern);
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!editingId || !editExpr.trim() || !editPattern.trim()) return;
    await updateCron(cogentName, editingId, {
      cron_expression: editExpr.trim(),
      event_pattern: editPattern.trim(),
    });
    setEditingId(null);
    onRefresh();
  }, [cogentName, editingId, editExpr, editPattern, onRefresh]);

  return (
    <div className="space-y-3">
      {/* Header with create button */}
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-[var(--text-muted)]">
          {crons.length} cron schedule{crons.length !== 1 ? "s" : ""}
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors"
            style={{
              color: "var(--accent)",
              borderColor: "var(--accent)",
              background: "transparent",
            }}
          >
            + Add Schedule
          </button>
        )}
      </div>

      {/* Create form */}
      {creating && (
        <div
          className="p-4 rounded-md border space-y-3"
          style={{
            background: "var(--bg-surface)",
            borderColor: "var(--accent)",
          }}
        >
          <div className="text-[12px] font-semibold text-[var(--text-primary)]">
            New Cron Schedule
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Cron Expression
              </label>
              <input
                value={newExpr}
                onChange={(e) => setNewExpr(e.target.value)}
                placeholder="*/5 * * * *"
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              <div className="text-[9px] text-[var(--text-muted)] mt-1">
                min hour dom month dow
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Event Pattern
              </label>
              <input
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                placeholder="cron.heartbeat"
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              <div className="text-[9px] text-[var(--text-muted)] mt-1">
                Event type emitted on each tick
              </div>
            </div>
          </div>
          <label className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={newEnabled}
              onChange={(e) => setNewEnabled(e.target.checked)}
            />
            Enabled
          </label>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newExpr.trim() || !newPattern.trim()}
              className="text-[11px] px-3 py-1 rounded border-0 cursor-pointer transition-colors disabled:opacity-40"
              style={{
                background: "var(--accent)",
                color: "white",
              }}
            >
              Create
            </button>
            <button
              onClick={() => setCreating(false)}
              className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors"
              style={{
                background: "transparent",
                borderColor: "var(--border)",
                color: "var(--text-muted)",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Cron table */}
      <div
        className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden"
      >
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Expression
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Event Pattern
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center">
                Enabled
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Created
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {crons.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="text-[var(--text-muted)] text-[13px] py-8 text-center"
                >
                  No cron schedules configured
                </td>
              </tr>
            )}
            {crons.map((c) => (
              <tr
                key={c.id}
                className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
              >
                {editingId === c.id ? (
                  <>
                    <td className="px-4 py-2">
                      <input
                        value={editExpr}
                        onChange={(e) => setEditExpr(e.target.value)}
                        className="w-full px-1.5 py-1 text-[12px] rounded border font-mono"
                        style={{
                          background: "var(--bg-base)",
                          borderColor: "var(--border)",
                          color: "var(--text-primary)",
                        }}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        value={editPattern}
                        onChange={(e) => setEditPattern(e.target.value)}
                        className="w-full px-1.5 py-1 text-[12px] rounded border font-mono"
                        style={{
                          background: "var(--bg-base)",
                          borderColor: "var(--border)",
                          color: "var(--text-primary)",
                        }}
                      />
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ToggleSwitch
                        checked={c.enabled}
                        disabled={toggling.has(c.id)}
                        onChange={() => handleToggle(c)}
                      />
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">
                      {c.created_at ? new Date(c.created_at).toLocaleDateString() : "--"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={handleUpdate}
                          className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer"
                          style={{ background: "var(--accent)", color: "white" }}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-[10px] px-2 py-0.5 rounded border cursor-pointer"
                          style={{
                            background: "transparent",
                            borderColor: "var(--border)",
                            color: "var(--text-muted)",
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                      {c.cron_expression}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)]">
                      {c.event_pattern}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ToggleSwitch
                        checked={c.enabled}
                        disabled={toggling.has(c.id)}
                        onChange={() => handleToggle(c)}
                      />
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">
                      {c.created_at ? new Date(c.created_at).toLocaleDateString() : "--"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {deleteConfirm === c.id ? (
                        <span className="text-[11px]">
                          <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                          <button
                            onClick={() => handleDelete(c.id)}
                            className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold mr-1"
                          >
                            Yes
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(null)}
                            className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]"
                          >
                            No
                          </button>
                        </span>
                      ) : (
                        <div className="flex gap-1 justify-end">
                          <button
                            onClick={() => startEdit(c)}
                            className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
                            style={{
                              background: "transparent",
                              borderColor: "var(--border)",
                              color: "var(--text-muted)",
                            }}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(c.id)}
                            className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
                            style={{
                              background: "transparent",
                              borderColor: "var(--border)",
                              color: "var(--error)",
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------- Toggle switch ---------- */

function ToggleSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className="relative inline-flex items-center h-[18px] w-[32px] rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-40"
      style={{
        background: checked ? "var(--accent)" : "var(--bg-elevated)",
        border: "1px solid var(--border)",
      }}
    >
      <span
        className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform duration-200"
        style={{
          transform: checked ? "translateX(14px)" : "translateX(1px)",
        }}
      />
    </button>
  );
}
