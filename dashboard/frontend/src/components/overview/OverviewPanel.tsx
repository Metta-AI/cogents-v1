"use client";
import type { DashboardData } from "@/lib/types";
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

export function OverviewPanel({ data }: Props) {
  const cs = data.cogosStatus;
  const s = data.status;

  const processesByStatus = data.processes.reduce<Record<string, number>>((acc, p) => {
    acc[p.status] = (acc[p.status] || 0) + 1;
    return acc;
  }, {});
  const runningProcesses = data.processes.filter((p) => p.status === "running");
  const runnableProcesses = data.processes.filter((p) => p.status === "runnable");

  return (
    <div>
      {/* Stat grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3 mb-5">
        <StatCard
          value={cs ? cs.processes.total : data.processes.length || null}
          label="Processes"
          variant="accent"
        />
        <StatCard value={cs ? cs.files : data.files.length || null} label="Files" />
        <StatCard value={cs ? cs.capabilities : data.capabilities.length || null} label="Capabilities" />
        <StatCard
          value={s ? s.unresolved_alerts : data.alerts.filter((a) => !a.resolved_at).length}
          label="Alerts"
          variant={(s?.unresolved_alerts ?? data.alerts.filter((a) => !a.resolved_at).length) > 0 ? "error" : "default"}
        />
        <StatCard value={cs ? cs.recent_events : s ? s.recent_events : null} label="Recent Events" />
      </div>

      {/* Three-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Processes */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Processes</h3>
          {data.processes.length > 0 ? (
            <>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {Object.entries(processesByStatus).map(([status, count]) => (
                  <Badge key={status} variant={PROCESS_STATUS_VARIANT[status] || "neutral"}>
                    {count} {status}
                  </Badge>
                ))}
              </div>
              {runningProcesses.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Running</div>
                  {runningProcesses.slice(0, 3).map((p) => (
                    <div key={p.id} className="flex items-center gap-2 py-1 text-xs">
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)]" style={{ animation: "pulse-dot 1.5s ease-in-out infinite" }} />
                      <span className="text-[var(--text-primary)] font-mono truncate">{p.name}</span>
                      {p.updated_at && <span className="text-[var(--text-muted)] ml-auto">{fmtTimestamp(p.updated_at)}</span>}
                    </div>
                  ))}
                </div>
              )}
              {runnableProcesses.length > 0 && runningProcesses.length === 0 && (
                <div>
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Runnable</div>
                  {runnableProcesses.slice(0, 5).map((p) => (
                    <div key={p.id} className="flex items-center gap-2 py-1 text-xs">
                      <span className="text-[var(--text-primary)] font-mono truncate">{p.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="text-[var(--text-muted)] text-xs py-2">No processes</div>
          )}
        </div>

        {/* Recent events */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Recent Events</h3>
          {data.events.slice(0, 5).map((e, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 text-xs">
              <Badge variant="info">{e.event_type || "unknown"}</Badge>
              <span className="text-[var(--text-secondary)] font-mono truncate">{e.source}</span>
              <span className="text-[var(--text-muted)] ml-auto">{fmtTimestamp(e.created_at)}</span>
            </div>
          ))}
          {data.events.length === 0 && (
            <div className="text-[var(--text-muted)] text-xs py-2">No recent events</div>
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
