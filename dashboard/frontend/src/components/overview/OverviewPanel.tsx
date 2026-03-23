"use client";
import { useState, useMemo } from "react";
import type { DashboardData, MessageTrace } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";
import { Badge } from "@/components/shared/Badge";
import { fmtTimestamp, fmtNum, fmtMs } from "@/lib/format";

interface Props {
  data: DashboardData;
}

type BadgeVariant = "accent" | "info" | "success" | "neutral" | "error" | "warning";

const PROCESS_STATUS_VARIANT: Record<string, BadgeVariant> = {
  waiting: "neutral",
  runnable: "info",
  running: "accent",
  completed: "success",
  disabled: "neutral",
  blocked: "warning",
  suspended: "warning",
};

const RUN_STATUS_VARIANT: Record<string, BadgeVariant> = {
  running: "accent",
  completed: "success",
  failed: "error",
  error: "error",
  timeout: "warning",
  pending: "info",
};

type TraceCategory = "tick" | "system" | "io" | "other";

function traceCategory(trace: MessageTrace): TraceCategory {
  const ch = trace.message.channel_name;
  if (ch.startsWith("system:tick:")) return "tick";
  if (ch.startsWith("system:")) return "system";
  if (ch.startsWith("io:")) return "io";
  return "other";
}

const TRACE_CATEGORY_ORDER: TraceCategory[] = ["tick", "system", "io", "other"];

export function OverviewPanel({ data }: Props) {
  const cs = data.cogosStatus;
  const s = data.status;
  const [hiddenTraceCategories, setHiddenTraceCategories] = useState<Set<TraceCategory>>(new Set(["tick"]));
  const [expandedProcessGroups, setExpandedProcessGroups] = useState<Set<string>>(new Set());

  const traceCategoryCounts = useMemo(() => {
    const counts: Record<TraceCategory, number> = { tick: 0, system: 0, io: 0, other: 0 };
    for (const trace of data.traces) counts[traceCategory(trace)]++;
    return counts;
  }, [data.traces]);

  const filteredTraces = useMemo(
    () => data.traces.filter((t) => !hiddenTraceCategories.has(traceCategory(t))),
    [data.traces, hiddenTraceCategories],
  );

  const toggleTraceCategory = (cat: TraceCategory) => {
    setHiddenTraceCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const processByStatus = useMemo(() => {
    const groups: Record<string, typeof data.processes> = {};
    for (const p of data.processes) {
      (groups[p.status] ??= []).push(p);
    }
    return groups;
  }, [data.processes]);

  const PROCESS_DISPLAY_ORDER = ["running", "runnable", "waiting", "completed"] as const;

  return (
    <div>
      {/* Three-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Processes */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Processes</h3>
          {data.processes.length > 0 ? (
            <div className="space-y-2">
              {PROCESS_DISPLAY_ORDER.map((status) => {
                const procs = processByStatus[status];
                if (!procs || procs.length === 0) return null;
                return (
                  <div
                    key={status}
                    className="rounded border p-2.5"
                    style={{ borderColor: "var(--border)", background: "var(--bg-base)" }}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge variant={PROCESS_STATUS_VARIANT[status] || "neutral"}>
                        {status}
                      </Badge>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">{procs.length}</span>
                    </div>
                    {(expandedProcessGroups.has(status) ? procs : procs.slice(0, 3)).map((p) => (
                      <div key={p.id} className="flex items-center gap-2 py-0.5 text-xs">
                        {status === "running" && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)]" style={{ animation: "pulse-dot 1.5s ease-in-out infinite" }} />
                        )}
                        <span className="text-[var(--text-primary)] font-mono truncate">{p.name}</span>
                        {p.updated_at && <span className="text-[var(--text-muted)] ml-auto text-[11px]">{fmtTimestamp(p.updated_at)}</span>}
                      </div>
                    ))}
                    {procs.length > 3 && !expandedProcessGroups.has(status) && (
                      <button
                        type="button"
                        onClick={() => setExpandedProcessGroups((prev) => new Set(prev).add(status))}
                        className="text-[10px] text-[var(--accent)] bg-transparent border-0 cursor-pointer py-0.5 hover:underline"
                      >
                        +{procs.length - 3} more
                      </button>
                    )}
                    {procs.length > 3 && expandedProcessGroups.has(status) && (
                      <button
                        type="button"
                        onClick={() => setExpandedProcessGroups((prev) => { const next = new Set(prev); next.delete(status); return next; })}
                        className="text-[10px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer py-0.5 hover:underline"
                      >
                        show less
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-[var(--text-muted)] text-xs py-2">No processes</div>
          )}
        </div>

        {/* Recent traces */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Recent Traces</h3>
          <div className="flex flex-wrap gap-1 mb-3">
            {TRACE_CATEGORY_ORDER.map((cat) => {
              const hidden = hiddenTraceCategories.has(cat);
              const count = traceCategoryCounts[cat];
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleTraceCategory(cat)}
                  className="rounded-full border px-2 py-0.5 text-[10px] font-medium font-mono transition-colors cursor-pointer"
                  style={{
                    background: hidden ? "transparent" : "var(--bg-deep)",
                    borderColor: "var(--border)",
                    color: hidden ? "var(--text-muted)" : "var(--text-primary)",
                    opacity: hidden ? 0.4 : 1,
                    textDecoration: hidden ? "line-through" : "none",
                  }}
                >
                  {cat} ({count})
                </button>
              );
            })}
          </div>
          {filteredTraces.slice(0, 5).map((trace, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 text-xs">
              <Badge variant="info">{trace.message.channel_name}</Badge>
              <span className="text-[var(--text-secondary)] font-mono truncate">
                {trace.deliveries.length} delivery{trace.deliveries.length === 1 ? "" : "ies"}
              </span>
              <span className="text-[var(--text-muted)] ml-auto">{fmtTimestamp(trace.message.created_at)}</span>
            </div>
          ))}
          {filteredTraces.length === 0 && (
            <div className="text-[var(--text-muted)] text-xs py-2">No recent traces</div>
          )}
        </div>

        {/* Recent Runs */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Recent Runs</h3>
          {(cs?.recent_runs ?? data.runs).slice(0, 5).map((r, i) => (
            <div key={i} className="flex items-center gap-3 py-1.5 text-xs">
              <span className="text-[var(--text-primary)] font-medium truncate flex-1">{r.process_name}</span>
              <Badge variant={RUN_STATUS_VARIANT[r.status] || "neutral"}>{r.status}</Badge>
              <span className="text-[var(--text-secondary)] font-mono">{fmtMs(r.duration_ms)}</span>
            </div>
          ))}
          {(cs?.recent_runs ?? data.runs).length === 0 && (
            <div className="text-[var(--text-muted)] text-xs py-2">No recent runs</div>
          )}
        </div>
      </div>
    </div>
  );
}
