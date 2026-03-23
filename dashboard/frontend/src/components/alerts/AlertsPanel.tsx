"use client";

import { useState, useCallback, useEffect } from "react";
import type { Alert } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { resolveAlert, resolveAllAlerts, getResolvedAlerts, createAlert, deleteAlert } from "@/lib/api";
import { fmtTimestamp, fmtRelative } from "@/lib/format";

interface AlertsPanelProps {
  alerts: Alert[];
  cogentName: string;
  onRefresh: () => void;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

/** A group of alerts with the same message, type, and source. */
interface AlertGroup {
  key: string;
  alerts: Alert[];
  count: number;
  severity: string;
  alert_type: string | null;
  source: string | null;
  message: string | null;
  first_seen: string | null;
  last_seen: string | null;
}

/** Group alerts by (message, alert_type, source). */
function aggregateAlerts(alerts: Alert[]): AlertGroup[] {
  const groups = new Map<string, Alert[]>();
  for (const a of alerts) {
    const key = `${a.message ?? ""}||${a.alert_type ?? ""}||${a.source ?? ""}`;
    const group = groups.get(key);
    if (group) group.push(a);
    else groups.set(key, [a]);
  }
  return Array.from(groups.entries()).map(([key, groupAlerts]) => {
    // Sort by created_at ascending to find first/last
    const sorted = [...groupAlerts].sort((a, b) =>
      (a.created_at ?? "").localeCompare(b.created_at ?? "")
    );
    return {
      key,
      alerts: sorted,
      count: sorted.length,
      severity: sorted[sorted.length - 1].severity ?? "info",
      alert_type: sorted[0].alert_type,
      source: sorted[0].source,
      message: sorted[0].message,
      first_seen: sorted[0].created_at,
      last_seen: sorted.length > 1 ? sorted[sorted.length - 1].created_at : null,
    };
  });
}

const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  critical: "error",
  warning: "warning",
  emergency: "error",
  info: "info",
};

export function AlertsPanel({ alerts, cogentName, onRefresh }: AlertsPanelProps) {
  const [creating, setCreating] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [resolving, setResolving] = useState<Set<string>>(new Set());
  const [resolvingAll, setResolvingAll] = useState(false);
  const [resolvedAlerts, setResolvedAlerts] = useState<Alert[]>([]);
  const [showResolved, setShowResolved] = useState(false);
  const [resolvedLimit, setResolvedLimit] = useState(25);

  // Create form state
  const [newSeverity, setNewSeverity] = useState("warning");
  const [newAlertType, setNewAlertType] = useState("");
  const [newSource, setNewSource] = useState("");
  const [newMessage, setNewMessage] = useState("");
  const [newMetadata, setNewMetadata] = useState("");

  const fetchResolved = useCallback(async () => {
    try {
      const resolved = await getResolvedAlerts(cogentName, resolvedLimit);
      setResolvedAlerts(resolved);
    } catch { /* ignore */ }
  }, [cogentName, resolvedLimit]);

  useEffect(() => {
    if (showResolved) fetchResolved();
  }, [showResolved, fetchResolved]);

  const handleResolve = useCallback(
    async (alertId: string) => {
      setResolving((s) => new Set(s).add(alertId));
      try {
        await resolveAlert(cogentName, alertId);
        onRefresh();
        if (showResolved) fetchResolved();
      } finally {
        setResolving((s) => {
          const next = new Set(s);
          next.delete(alertId);
          return next;
        });
      }
    },
    [cogentName, onRefresh, showResolved, fetchResolved],
  );

  const handleDelete = useCallback(
    async (alertId: string) => {
      await deleteAlert(cogentName, alertId);
      setDeleteConfirm(null);
      onRefresh();
    },
    [cogentName, onRefresh],
  );

  const handleResolveAll = useCallback(async () => {
    setResolvingAll(true);
    try {
      await resolveAllAlerts(cogentName);
      onRefresh();
      if (showResolved) fetchResolved();
    } finally {
      setResolvingAll(false);
    }
  }, [cogentName, onRefresh, showResolved, fetchResolved]);

  const handleCreate = useCallback(async () => {
    if (!newMessage.trim()) return;
    let metadata: Record<string, unknown> = {};
    if (newMetadata.trim()) {
      try {
        metadata = JSON.parse(newMetadata.trim());
      } catch {
        return; // invalid JSON, do nothing
      }
    }
    await createAlert(cogentName, {
      severity: newSeverity,
      alert_type: newAlertType.trim(),
      source: newSource.trim(),
      message: newMessage.trim(),
      metadata,
    });
    setCreating(false);
    setNewSeverity("warning");
    setNewAlertType("");
    setNewSource("");
    setNewMessage("");
    setNewMetadata("");
    onRefresh();
  }, [cogentName, newSeverity, newAlertType, newSource, newMessage, newMetadata, onRefresh]);

  return (
    <div className="space-y-3">
      {/* Header with create button */}
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-[var(--text-muted)]">
          {alerts.length} unresolved alert{alerts.length !== 1 ? "s" : ""}
        </div>
        <div className="flex gap-2">
          {alerts.length > 0 && (
            <button
              onClick={handleResolveAll}
              disabled={resolvingAll}
              className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors disabled:opacity-40"
              style={{
                color: "var(--accent)",
                borderColor: "var(--accent)",
                background: "transparent",
              }}
            >
              {resolvingAll ? "Resolving..." : "Resolve All"}
            </button>
          )}
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
              + New Alert
            </button>
          )}
        </div>
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
            New Alert
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Severity
              </label>
              <select
                value={newSeverity}
                onChange={(e) => setNewSeverity(e.target.value)}
                className="w-full px-2 py-1.5 text-[12px] rounded border"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                <option value="warning">warning</option>
                <option value="critical">critical</option>
                <option value="emergency">emergency</option>
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Alert Type
              </label>
              <input
                value={newAlertType}
                onChange={(e) => setNewAlertType(e.target.value)}
                placeholder="e.g. budget_exceeded"
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
                Source
              </label>
              <input
                value={newSource}
                onChange={(e) => setNewSource(e.target.value)}
                placeholder="e.g. monitor"
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
          </div>
          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
              Message
            </label>
            <input
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              placeholder="Alert message..."
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
              Metadata (JSON, optional)
            </label>
            <textarea
              value={newMetadata}
              onChange={(e) => setNewMetadata(e.target.value)}
              placeholder='{"key": "value"}'
              rows={2}
              className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
              style={{
                background: "var(--bg-base)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newMessage.trim()}
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

      {/* Alerts table (aggregated) */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Severity
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Count
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Type
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Source
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Message
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Time Range
              </th>
              <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {alerts.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="text-[var(--text-muted)] text-[13px] py-8 text-center"
                >
                  No alerts
                </td>
              </tr>
            )}
            {aggregateAlerts(alerts).map((g) => {
              const msg = g.message ?? "--";
              const truncated = msg.length > 100 ? msg.slice(0, 100) + "..." : msg;
              // For resolve/delete, use the most recent alert in the group
              const latestAlert = g.alerts[g.alerts.length - 1];

              return (
                <tr
                  key={g.key}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2">
                    <Badge variant={SEVERITY_VARIANT[g.severity] ?? "neutral"}>
                      {g.severity === "emergency" ? (
                        <span style={{ color: "red" }}>{g.severity}</span>
                      ) : (
                        g.severity
                      )}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {g.count > 1 ? (
                      <span className="inline-flex items-center justify-center min-w-[20px] px-1 py-0.5 rounded-full text-[10px] font-semibold"
                        style={{ background: "var(--error)", color: "white" }}>
                        {g.count}x
                      </span>
                    ) : (
                      <span className="text-[var(--text-muted)]">1</span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {g.alert_type ?? "--"}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)]">
                    {g.source ?? "--"}
                  </td>
                  <td
                    className="px-3 py-2 text-[var(--text-secondary)]"
                    title={msg}
                  >
                    {truncated}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">
                    {g.last_seen ? (
                      <span title={`First: ${g.first_seen}\nLast: ${g.last_seen}`}>
                        {fmtRelative(g.first_seen)} — {fmtRelative(g.last_seen)}
                      </span>
                    ) : (
                      fmtTimestamp(g.first_seen)
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {deleteConfirm === g.key ? (
                      <span className="text-[11px]">
                        <span className="text-[var(--text-muted)] mr-1">Delete{g.count > 1 ? ` all ${g.count}` : ""}?</span>
                        <button
                          onClick={async () => {
                            for (const a of g.alerts) await deleteAlert(cogentName, a.id);
                            setDeleteConfirm(null);
                            onRefresh();
                          }}
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
                        {!latestAlert.resolved_at && (
                          <button
                            onClick={async () => {
                              setResolving((s) => new Set(s).add(g.key));
                              try {
                                for (const a of g.alerts) await resolveAlert(cogentName, a.id);
                                onRefresh();
                                if (showResolved) fetchResolved();
                              } finally {
                                setResolving((s) => { const next = new Set(s); next.delete(g.key); return next; });
                              }
                            }}
                            disabled={resolving.has(g.key)}
                            className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer transition-colors disabled:opacity-40"
                            style={{
                              background: "var(--accent)",
                              color: "white",
                            }}
                          >
                            Resolve{g.count > 1 ? ` (${g.count})` : ""}
                          </button>
                        )}
                        <button
                          onClick={() => setDeleteConfirm(g.key)}
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Resolved alerts section */}
      <div className="mt-6">
        <button
          onClick={() => setShowResolved((v) => !v)}
          className="text-[11px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer hover:text-[var(--text-secondary)] transition-colors flex items-center gap-1"
        >
          <span style={{ display: "inline-block", transform: showResolved ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 150ms" }}>
            ▶
          </span>
          Resolved Alerts
          {resolvedAlerts.length > 0 && showResolved && (
            <span className="text-[var(--text-muted)]">({resolvedAlerts.length})</span>
          )}
        </button>

        {showResolved && (
          <div className="mt-2 bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="px-4 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Severity</th>
                  <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Type</th>
                  <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Source</th>
                  <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Message</th>
                  <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">First Seen</th>
                  <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Resolved</th>
                </tr>
              </thead>
              <tbody>
                {resolvedAlerts.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-[var(--text-muted)] text-[13px] py-6 text-center">
                      No resolved alerts
                    </td>
                  </tr>
                )}
                {resolvedAlerts.map((a) => {
                  const severity = a.severity ?? "info";
                  const msg = a.message ?? "--";
                  const truncated = msg.length > 100 ? msg.slice(0, 100) + "..." : msg;
                  return (
                    <tr key={a.id} className="border-b border-[var(--border)] last:border-0">
                      <td className="px-4 py-2">
                        <Badge variant={SEVERITY_VARIANT[severity] ?? "neutral"}>{severity}</Badge>
                      </td>
                      <td className="px-3 py-2 font-mono text-[var(--text-secondary)]">{a.alert_type ?? "--"}</td>
                      <td className="px-3 py-2 font-mono text-[var(--text-muted)]">{a.source ?? "--"}</td>
                      <td className="px-3 py-2 text-[var(--text-secondary)]" title={msg}>{truncated}</td>
                      <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">{fmtTimestamp(a.created_at)}</td>
                      <td className="px-3 py-2 text-[var(--text-muted)] text-[11px]">{fmtTimestamp(a.resolved_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {resolvedAlerts.length >= resolvedLimit && (
              <div className="text-center py-2 border-t border-[var(--border)]">
                <button
                  onClick={() => setResolvedLimit((l) => l + 25)}
                  className="text-[11px] text-[var(--accent)] bg-transparent border-0 cursor-pointer hover:underline"
                >
                  Load more
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
