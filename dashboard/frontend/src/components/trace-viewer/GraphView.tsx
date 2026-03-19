"use client";

import React, { useMemo } from "react";
import type { SpanData } from "./SpanDetail";

interface GraphViewProps {
  spans: SpanData[];
  selectedSpanId: string | null;
  onSelectSpan: (span: SpanData) => void;
}

interface LayoutNode {
  span: SpanData;
  x: number;
  y: number;
  width: number;
  height: number;
}

const NODE_WIDTH = 200;
const NODE_HEIGHT = 48;
const H_GAP = 40;
const V_GAP = 24;
const PADDING = 20;

function getNodeFill(name: string, status: string): string {
  if (status === "errored") return "#7f1d1d";
  if (name.startsWith("process:")) return "#1e3a5f";
  if (name.startsWith("llm_turn:")) return "#1a3d2e";
  if (name.startsWith("tool:")) return "#4a2c0a";
  return "#2d1f4e";
}

function getNodeStroke(name: string, status: string): string {
  if (status === "errored") return "#ef4444";
  if (name.startsWith("process:")) return "#3b82f6";
  if (name.startsWith("llm_turn:")) return "#22c55e";
  if (name.startsWith("tool:")) return "#f97316";
  return "#a855f7";
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1) return `${(ms * 1000).toFixed(0)}us`;
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Simple layered DAG layout: assign each node to a depth layer,
 * then spread children horizontally within their layer.
 */
function layoutNodes(spans: SpanData[]): { nodes: LayoutNode[]; edges: [string, string][] } {
  const byParent = new Map<string | null, SpanData[]>();
  const spanMap = new Map<string, SpanData>();
  for (const s of spans) {
    spanMap.set(s.id, s);
    const key = s.parent_span_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(s);
  }

  for (const children of byParent.values()) {
    children.sort((a, b) => {
      if (!a.started_at || !b.started_at) return 0;
      return new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
    });
  }

  // Assign layers (depth) via BFS
  const layers = new Map<string, number>();
  const roots = byParent.get(null) ?? [];
  if (roots.length === 0 && spans.length > 0) {
    // Fallback: all spans at layer 0
    for (const s of spans) layers.set(s.id, 0);
  } else {
    const queue: { id: string; depth: number }[] = roots.map((r) => ({ id: r.id, depth: 0 }));
    while (queue.length > 0) {
      const { id, depth } = queue.shift()!;
      if (layers.has(id)) continue;
      layers.set(id, depth);
      for (const child of byParent.get(id) ?? []) {
        queue.push({ id: child.id, depth: depth + 1 });
      }
    }
  }

  // Group by layer
  const layerGroups = new Map<number, SpanData[]>();
  for (const s of spans) {
    const layer = layers.get(s.id) ?? 0;
    if (!layerGroups.has(layer)) layerGroups.set(layer, []);
    layerGroups.get(layer)!.push(s);
  }

  const maxLayer = Math.max(0, ...layerGroups.keys());
  const nodes: LayoutNode[] = [];

  for (let layer = 0; layer <= maxLayer; layer++) {
    const group = layerGroups.get(layer) ?? [];
    const y = PADDING + layer * (NODE_HEIGHT + V_GAP);
    const totalWidth = group.length * NODE_WIDTH + (group.length - 1) * H_GAP;
    const startX = PADDING + (group.length > 1 ? 0 : 0);

    group.forEach((span, i) => {
      nodes.push({
        span,
        x: startX + i * (NODE_WIDTH + H_GAP),
        y,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      });
    });
  }

  // Center each layer relative to the widest layer
  const layerWidths = new Map<number, number>();
  for (let layer = 0; layer <= maxLayer; layer++) {
    const group = layerGroups.get(layer) ?? [];
    layerWidths.set(layer, group.length * NODE_WIDTH + Math.max(0, group.length - 1) * H_GAP);
  }
  const maxWidth = Math.max(0, ...layerWidths.values());

  for (const node of nodes) {
    const layer = layers.get(node.span.id) ?? 0;
    const lw = layerWidths.get(layer) ?? 0;
    const offset = (maxWidth - lw) / 2;
    node.x += offset;
  }

  // Build edges
  const edges: [string, string][] = [];
  for (const s of spans) {
    if (s.parent_span_id && spanMap.has(s.parent_span_id)) {
      edges.push([s.parent_span_id, s.id]);
    }
  }

  return { nodes, edges };
}

export function GraphView({ spans, selectedSpanId, onSelectSpan }: GraphViewProps) {
  const { nodes, edges } = useMemo(() => layoutNodes(spans), [spans]);

  const nodeMap = useMemo(() => {
    const m = new Map<string, LayoutNode>();
    for (const n of nodes) m.set(n.span.id, n);
    return m;
  }, [nodes]);

  if (nodes.length === 0) {
    return <div className="text-white/40 text-sm p-4">No spans to display.</div>;
  }

  const svgWidth = Math.max(
    600,
    Math.max(...nodes.map((n) => n.x + n.width)) + PADDING * 2,
  );
  const svgHeight = Math.max(...nodes.map((n) => n.y + n.height)) + PADDING * 2;

  return (
    <div className="overflow-auto">
      <svg width={svgWidth} height={svgHeight} className="select-none">
        {/* Edges */}
        {edges.map(([fromId, toId]) => {
          const from = nodeMap.get(fromId);
          const to = nodeMap.get(toId);
          if (!from || !to) return null;

          const x1 = from.x + from.width / 2;
          const y1 = from.y + from.height;
          const x2 = to.x + to.width / 2;
          const y2 = to.y;
          const midY = (y1 + y2) / 2;

          return (
            <path
              key={`${fromId}-${toId}`}
              d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
              fill="none"
              stroke="rgba(255,255,255,0.15)"
              strokeWidth="1.5"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const { span, x, y, width, height } = node;
          const isSelected = span.id === selectedSpanId;
          const fill = getNodeFill(span.name, span.status);
          const stroke = getNodeStroke(span.name, span.status);

          return (
            <g
              key={span.id}
              className="cursor-pointer"
              onClick={() => onSelectSpan(span)}
            >
              <rect
                x={x}
                y={y}
                width={width}
                height={height}
                rx={6}
                fill={fill}
                stroke={isSelected ? "#ffffff" : stroke}
                strokeWidth={isSelected ? 2 : 1}
                opacity={0.95}
              />
              {/* Span name */}
              <text
                x={x + 8}
                y={y + 18}
                fill="rgba(255,255,255,0.85)"
                fontSize="11"
                fontFamily="monospace"
              >
                {span.name.length > 24 ? span.name.slice(0, 22) + ".." : span.name}
              </text>
              {/* Duration */}
              <text
                x={x + 8}
                y={y + 34}
                fill="rgba(255,255,255,0.4)"
                fontSize="10"
                fontFamily="monospace"
              >
                {formatDuration(span.duration_ms)}
                {span.status === "errored" && " [ERR]"}
                {span.status === "running" && " [RUN]"}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
