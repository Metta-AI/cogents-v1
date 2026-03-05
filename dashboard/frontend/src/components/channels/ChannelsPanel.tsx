"use client";

import { useState, useCallback } from "react";
import type { Channel } from "@/lib/types";
import { createChannel, updateChannel, deleteChannel } from "@/lib/api";

const CHANNEL_TYPES = ["discord", "github", "email", "asana", "cli"] as const;

interface ChannelsPanelProps {
  channels: Channel[];
  cogentName: string;
  onRefresh: () => void;
}

export function ChannelsPanel({ channels, cogentName, onRefresh }: ChannelsPanelProps) {
  const [creating, setCreating] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Create form state
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<string>("cli");
  const [newEnabled, setNewEnabled] = useState(true);

  // Edit form state
  const [editType, setEditType] = useState<string>("cli");

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    await createChannel(cogentName, {
      name: newName.trim(),
      type: newType,
      enabled: newEnabled,
    });
    setCreating(false);
    setNewName("");
    setNewType("cli");
    setNewEnabled(true);
    onRefresh();
  }, [cogentName, newName, newType, newEnabled, onRefresh]);

  const handleToggle = useCallback(
    async (ch: Channel) => {
      setToggling((s) => new Set(s).add(ch.name));
      try {
        await updateChannel(cogentName, ch.name, { enabled: !ch.enabled });
        onRefresh();
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          next.delete(ch.name);
          return next;
        });
      }
    },
    [cogentName, onRefresh],
  );

  const handleDelete = useCallback(
    async (channelName: string) => {
      await deleteChannel(cogentName, channelName);
      setDeleteConfirm(null);
      onRefresh();
    },
    [cogentName, onRefresh],
  );

  const startEdit = useCallback((ch: Channel) => {
    setEditingName(ch.name);
    setEditType(ch.type ?? "cli");
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!editingName) return;
    await updateChannel(cogentName, editingName, {
      type: editType,
    });
    setEditingName(null);
    onRefresh();
  }, [cogentName, editingName, editType, onRefresh]);

  return (
    <div className="space-y-3">
      {/* Header with create button */}
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-[var(--text-muted)]">
          {channels.length} channel{channels.length !== 1 ? "s" : ""}
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
            + New Channel
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
            New Channel
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Name
              </label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="my-channel"
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Type
              </label>
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                className="w-full px-2 py-1.5 text-[12px] rounded border"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                {CHANNEL_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
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
              disabled={!newName.trim()}
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

      {/* Channels table */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Name
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Type
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
            {channels.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="text-[var(--text-muted)] text-[13px] py-8 text-center"
                >
                  No channels found
                </td>
              </tr>
            )}
            {channels.map((ch) => (
              <tr
                key={ch.name}
                className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
              >
                {editingName === ch.name ? (
                  <>
                    <td className="px-4 py-2 font-mono text-[var(--text-primary)] font-medium">
                      {ch.name}
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={editType}
                        onChange={(e) => setEditType(e.target.value)}
                        className="w-full px-1.5 py-1 text-[12px] rounded border"
                        style={{
                          background: "var(--bg-base)",
                          borderColor: "var(--border)",
                          color: "var(--text-primary)",
                        }}
                      >
                        {CHANNEL_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ToggleSwitch
                        checked={ch.enabled}
                        disabled={toggling.has(ch.name)}
                        onChange={() => handleToggle(ch)}
                      />
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">
                      {ch.created_at ? new Date(ch.created_at).toLocaleDateString() : "--"}
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
                          onClick={() => setEditingName(null)}
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
                    <td className="px-4 py-2 font-mono text-[var(--text-primary)] font-medium">
                      {ch.name}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-secondary)]">
                      {ch.type ?? "unknown"}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ToggleSwitch
                        checked={ch.enabled}
                        disabled={toggling.has(ch.name)}
                        onChange={() => handleToggle(ch)}
                      />
                    </td>
                    <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">
                      {ch.created_at ? new Date(ch.created_at).toLocaleDateString() : "--"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {deleteConfirm === ch.name ? (
                        <span className="text-[11px]">
                          <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                          <button
                            onClick={() => handleDelete(ch.name)}
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
                            onClick={() => startEdit(ch)}
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
                            onClick={() => setDeleteConfirm(ch.name)}
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
