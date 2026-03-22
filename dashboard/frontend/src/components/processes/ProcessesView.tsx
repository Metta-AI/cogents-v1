"use client";

import { useState } from "react";
import type { CogosProcess, CogosRun, CogosFile, CogosCapability, EventType, Resource, CogosExecutor } from "@/lib/types";
import { ProcessesPanel } from "./ProcessesPanel";
import { RunsPanel } from "@/components/runs/RunsPanel";
import { ExecutorsPanel } from "@/components/executors/ExecutorsPanel";
import { CapabilitiesPanel } from "@/components/capabilities/CapabilitiesPanel";
import { ResourcesPanel } from "@/components/resources/ResourcesPanel";

interface ProcessesViewProps {
  processes: CogosProcess[];
  cogentName: string;
  onRefresh: () => void;
  resources: Resource[];
  runs: CogosRun[];
  files: CogosFile[];
  capabilities: CogosCapability[];
  eventTypes: EventType[];
  currentEpoch?: number;
  executors: CogosExecutor[];
}

type SubTab = "processes" | "runs" | "executors" | "capabilities" | "resources";

export function ProcessesView({
  processes, cogentName, onRefresh, resources, runs, files, capabilities, eventTypes, currentEpoch, executors,
}: ProcessesViewProps) {
  const [subTab, setSubTab] = useState<SubTab>("processes");

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
        <button style={tabStyle(subTab === "processes")} onClick={() => setSubTab("processes")}>
          Processes ({processes.length})
        </button>
        <button style={tabStyle(subTab === "runs")} onClick={() => setSubTab("runs")}>
          Runs ({runs.length})
        </button>
        <button style={tabStyle(subTab === "executors")} onClick={() => setSubTab("executors")}>
          Executors ({executors.length})
        </button>
        <button style={tabStyle(subTab === "capabilities")} onClick={() => setSubTab("capabilities")}>
          Capabilities ({capabilities.length})
        </button>
        <button style={tabStyle(subTab === "resources")} onClick={() => setSubTab("resources")}>
          Resources ({resources.length})
        </button>
      </div>
      {subTab === "processes" && (
        <ProcessesPanel
          processes={processes}
          cogentName={cogentName}
          onRefresh={onRefresh}
          resources={resources}
          runs={runs}
          files={files}
          capabilities={capabilities}
          eventTypes={eventTypes}
          currentEpoch={currentEpoch}
        />
      )}
      {subTab === "runs" && (
        <RunsPanel runs={runs} cogentName={cogentName} currentEpoch={currentEpoch} />
      )}
      {subTab === "executors" && (
        <ExecutorsPanel executors={executors} runs={runs} cogentName={cogentName} />
      )}
      {subTab === "capabilities" && (
        <CapabilitiesPanel capabilities={capabilities} cogentName={cogentName} onRefresh={onRefresh} />
      )}
      {subTab === "resources" && (
        <ResourcesPanel resources={resources} />
      )}
    </div>
  );
}
