"use client";

import { useState } from "react";
import type { MessageTrace, TimeRange } from "@/lib/types";
import { TracePanel } from "./TracePanel";
import { TraceViewerPanel } from "@/components/trace-viewer/TraceViewerPanel";

interface TraceViewProps {
  traces: MessageTrace[];
  cogentName: string;
  timeRange: TimeRange;
  onRefresh?: () => Promise<void> | void;
  initialTraceId?: string;
}

type SubTab = "trace" | "viewer";

export function TraceView({ traces, cogentName, timeRange, onRefresh, initialTraceId }: TraceViewProps) {
  const [subTab, setSubTab] = useState<SubTab>(initialTraceId ? "viewer" : "trace");

  const tabStyle = (active: boolean): React.CSSProperties => ({
    fontSize: "11px",
    fontFamily: "var(--font-mono)",
    fontWeight: active ? 600 : 400,
    padding: "4px 12px",
    background: "transparent",
    border: "none",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    color: active ? "var(--accent)" : "var(--text-muted)",
    cursor: "pointer",
  });

  return (
    <div>
      <div className="flex items-center gap-0 mb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <button style={tabStyle(subTab === "trace")} onClick={() => setSubTab("trace")}>
          Trace ({traces.length})
        </button>
        <button style={tabStyle(subTab === "viewer")} onClick={() => setSubTab("viewer")}>
          Viewer
        </button>
      </div>
      {subTab === "trace" && (
        <TracePanel traces={traces} cogentName={cogentName} timeRange={timeRange} onRefresh={onRefresh} />
      )}
      {subTab === "viewer" && (
        <TraceViewerPanel cogentName={cogentName} initialTraceId={initialTraceId} />
      )}
    </div>
  );
}
