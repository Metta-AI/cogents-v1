"use client";

import React, { useMemo } from "react";
import type { SpanData } from "./SpanDetail";

interface TimelineViewProps {
  spans: SpanData[];
  traceStartMs: number;
  totalDurationMs: number;
  selectedSpanId: string | null;
  onSelectSpan: (span: SpanData) => void;
}

function getSpanColor(name: string, status: string): string {
  if (status === "errored") return "bg-red-500/80";
  if (name.startsWith("process:")) return "bg-blue-500/70";
  if (name.startsWith("llm_turn:")) return "bg-green-500/70";
  if (name.startsWith("tool:")) return "bg-orange-500/70";
  return "bg-purple-500/60";
}

function getSpanBorderColor(name: string, status: string): string {
  if (status === "errored") return "border-red-400";
  if (name.startsWith("process:")) return "border-blue-400";
  if (name.startsWith("llm_turn:")) return "border-green-400";
  if (name.startsWith("tool:")) return "border-orange-400";
  return "border-purple-400";
}

interface FlatSpan {
  span: SpanData;
  depth: number;
}

function flattenSpans(spans: SpanData[]): FlatSpan[] {
  const byParent = new Map<string | null, SpanData[]>();
  for (const s of spans) {
    const key = s.parent_span_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(s);
  }

  // Sort children by start time
  for (const children of byParent.values()) {
    children.sort((a, b) => {
      if (!a.started_at || !b.started_at) return 0;
      return new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
    });
  }

  const result: FlatSpan[] = [];
  function dfs(parentId: string | null, depth: number) {
    const children = byParent.get(parentId) ?? [];
    for (const child of children) {
      result.push({ span: child, depth });
      dfs(child.id, depth + 1);
    }
  }
  dfs(null, 0);

  // If nothing was found (no roots), just list them all at depth 0
  if (result.length === 0) {
    for (const s of spans) {
      result.push({ span: s, depth: 0 });
    }
  }

  return result;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1) return `${(ms * 1000).toFixed(0)}us`;
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

const ROW_HEIGHT = 32;
const LABEL_WIDTH = 280;

export function TimelineView({ spans, traceStartMs, totalDurationMs, selectedSpanId, onSelectSpan }: TimelineViewProps) {
  const flatSpans = useMemo(() => flattenSpans(spans), [spans]);
  const effectiveDuration = totalDurationMs > 0 ? totalDurationMs : 1;

  // Generate time axis ticks
  const tickCount = 6;
  const ticks = useMemo(() => {
    return Array.from({ length: tickCount + 1 }, (_, i) => {
      const ms = (effectiveDuration / tickCount) * i;
      return { ms, label: formatDuration(ms) };
    });
  }, [effectiveDuration]);

  return (
    <div className="overflow-x-auto">
      {/* Time axis */}
      <div className="flex border-b border-white/10" style={{ minWidth: LABEL_WIDTH + 600 }}>
        <div style={{ width: LABEL_WIDTH, minWidth: LABEL_WIDTH }} className="shrink-0 px-2 py-1 text-[10px] text-white/30">
          Span
        </div>
        <div className="flex-1 relative h-6">
          {ticks.map((tick) => {
            const pct = (tick.ms / effectiveDuration) * 100;
            return (
              <span
                key={tick.ms}
                className="absolute text-[10px] text-white/30 -translate-x-1/2"
                style={{ left: `${pct}%`, top: "4px" }}
              >
                {tick.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* Rows */}
      <div style={{ minWidth: LABEL_WIDTH + 600 }}>
        {flatSpans.map(({ span, depth }) => {
          const startOffset = span.started_at
            ? new Date(span.started_at).getTime() - traceStartMs
            : 0;
          const duration = span.duration_ms ?? 0;
          const leftPct = (startOffset / effectiveDuration) * 100;
          const widthPct = (duration / effectiveDuration) * 100;
          const isSelected = span.id === selectedSpanId;

          return (
            <div
              key={span.id}
              className={`flex items-center cursor-pointer transition-colors ${
                isSelected ? "bg-white/10" : "hover:bg-white/5"
              }`}
              style={{ height: ROW_HEIGHT }}
              onClick={() => onSelectSpan(span)}
            >
              {/* Label */}
              <div
                className="shrink-0 px-2 truncate text-xs"
                style={{
                  width: LABEL_WIDTH,
                  minWidth: LABEL_WIDTH,
                  paddingLeft: `${12 + depth * 16}px`,
                }}
              >
                <span className={`${span.status === "errored" ? "text-red-400" : "text-white/70"}`}>
                  {span.name}
                </span>
              </div>

              {/* Bar area */}
              <div className="flex-1 relative" style={{ height: ROW_HEIGHT }}>
                {/* Grid lines */}
                {ticks.map((tick) => {
                  const pct = (tick.ms / effectiveDuration) * 100;
                  return (
                    <div
                      key={tick.ms}
                      className="absolute top-0 bottom-0 border-l border-white/5"
                      style={{ left: `${pct}%` }}
                    />
                  );
                })}

                {/* Span bar */}
                <div
                  className={`absolute top-1.5 rounded-sm border ${getSpanColor(span.name, span.status)} ${getSpanBorderColor(span.name, span.status)}`}
                  style={{
                    left: `${Math.max(0, leftPct)}%`,
                    width: `${Math.max(0.3, widthPct)}%`,
                    height: ROW_HEIGHT - 12,
                  }}
                />

                {/* Duration label */}
                {span.duration_ms != null && (
                  <span
                    className="absolute text-[10px] text-white/40 whitespace-nowrap"
                    style={{
                      left: `${Math.max(0, leftPct) + Math.max(0.3, widthPct) + 0.5}%`,
                      top: "50%",
                      transform: "translateY(-50%)",
                    }}
                  >
                    {formatDuration(span.duration_ms)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
