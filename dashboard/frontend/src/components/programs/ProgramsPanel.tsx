"use client";

import { useState, useCallback } from "react";
import type { Program } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtTimestamp } from "@/lib/format";
import { ExecutionDetail } from "./ExecutionDetail";

interface ProgramsPanelProps {
  programs: Program[];
  cogentName?: string;
}

function typeVariant(type: string) {
  switch (type) {
    case "skill":
      return "accent" as const;
    case "trigger":
      return "warning" as const;
    case "system":
      return "info" as const;
    default:
      return "neutral" as const;
  }
}

export function ProgramsPanel({
  programs,
  cogentName = "cogent",
}: ProgramsPanelProps) {
  const [expandedProgram, setExpandedProgram] = useState<string | null>(null);

  const toggleExpand = useCallback((name: string) => {
    setExpandedProgram((prev) => (prev === name ? null : name));
  }, []);

  return (
    <div>
      <div className="text-[var(--text-muted)] text-xs mb-3">
        {programs.length} program{programs.length !== 1 ? "s" : ""}
      </div>

      {programs.length === 0 && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No programs registered</div>
      )}

      <div className="rounded-md overflow-hidden" style={{ border: programs.length ? "1px solid var(--border)" : "none" }}>
        {programs.map((prog) => {
          const isExpanded = expandedProgram === prog.name;
          const pct = prog.runs > 0 ? ((prog.ok / prog.runs) * 100).toFixed(0) : "0";

          return (
            <div key={prog.name}>
              <div
                className="flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors"
                style={{
                  background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                }}
                onClick={() => toggleExpand(prog.name)}
                onMouseEnter={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-surface)";
                }}
              >
                <span className="font-mono text-[12px] text-[var(--text-primary)] font-medium">
                  {prog.name}
                </span>
                <Badge variant={typeVariant(prog.type)}>{prog.type}</Badge>
                {prog.description && (
                  <span className="text-[11px] text-[var(--text-muted)] truncate max-w-[300px]">
                    {prog.description}
                  </span>
                )}
                <div className="flex-1" />
                <span className="font-mono text-[10px] text-[var(--text-muted)]">
                  {prog.runs > 0 ? (
                    <>
                      <span className="text-[#22c55e]">{prog.ok}</span>
                      {prog.fail > 0 && <span className="text-[var(--error)]">/{prog.fail}</span>}
                      <span className="text-[var(--text-muted)]"> ({pct}%)</span>
                    </>
                  ) : (
                    <span>0 runs</span>
                  )}
                </span>
                {prog.total_cost > 0 && (
                  <span className="font-mono text-[10px] text-[var(--text-muted)]">{fmtCost(prog.total_cost)}</span>
                )}
                <span className="text-[10px] text-[var(--text-muted)]" style={{ minWidth: "60px", textAlign: "right" }}>
                  {fmtTimestamp(prog.last_run)}
                </span>
              </div>

              {isExpanded && (
                <ExecutionDetail programName={prog.name} cogentName={cogentName} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
