"use client";

import { useState, useEffect } from "react";
import { Badge } from "@/components/shared/Badge";
import { fmtRelative } from "@/lib/format";
import { getEventTree } from "@/lib/api";
import type { DashboardEvent } from "@/lib/types";

interface EventTreeProps {
  eventId: number | string;
  cogentName: string;
}

interface TreeNode {
  event: DashboardEvent;
  children: TreeNode[];
}

function buildTree(events: DashboardEvent[], rootId: number | string): TreeNode | null {
  const byId = new Map<number | string, DashboardEvent>();
  for (const e of events) byId.set(e.id, e);

  const childrenMap = new Map<number | string, DashboardEvent[]>();
  for (const e of events) {
    if (e.parent_event_id != null) {
      const list = childrenMap.get(e.parent_event_id) ?? [];
      list.push(e);
      childrenMap.set(e.parent_event_id, list);
    }
  }

  function makeNode(id: number | string): TreeNode | null {
    const event = byId.get(id);
    if (!event) return null;
    const kids = childrenMap.get(id) ?? [];
    return {
      event,
      children: kids.map((c) => makeNode(c.id)).filter(Boolean) as TreeNode[],
    };
  }

  // Find root: event with no parent or the top-most ancestor
  let root = byId.get(rootId);
  if (!root) return null;

  // Walk up to find ultimate root
  const visited = new Set<number | string>();
  let current = root;
  while (current.parent_event_id != null && byId.has(current.parent_event_id)) {
    if (visited.has(current.parent_event_id)) break;
    visited.add(current.parent_event_id);
    current = byId.get(current.parent_event_id)!;
  }

  return makeNode(current.id);
}

function TreeNodeView({
  node,
  depth,
  highlightId,
}: {
  node: TreeNode;
  depth: number;
  highlightId: number | string;
}) {
  const isHighlighted = node.event.id === highlightId;
  return (
    <div>
      <div
        className={`flex items-center gap-2 py-1 px-2 rounded text-[12px] ${
          isHighlighted
            ? "bg-[var(--accent-glow)] border border-[var(--accent)]/30"
            : ""
        }`}
        style={{ marginLeft: depth * 20 }}
      >
        <Badge variant={isHighlighted ? "accent" : "neutral"}>
          {node.event.event_type ?? "event"}
        </Badge>
        <span className="text-[var(--text-secondary)]">
          {node.event.source ?? "--"}
        </span>
        <span className="text-[var(--text-muted)] text-[11px] ml-auto">
          {fmtRelative(node.event.created_at)}
        </span>
      </div>
      {node.children.map((child) => (
        <TreeNodeView
          key={String(child.event.id)}
          node={child}
          depth={depth + 1}
          highlightId={highlightId}
        />
      ))}
    </div>
  );
}

export function EventTree({ eventId, cogentName }: EventTreeProps) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getEventTree(cogentName, eventId)
      .then((events) => {
        if (cancelled) return;
        const root = buildTree(events, eventId);
        setTree(root);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load tree");
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [eventId, cogentName]);

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-[12px] py-2">
        Loading event tree...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-red-400 text-[12px] py-2">
        Error: {error}
      </div>
    );
  }

  if (!tree) {
    return (
      <div className="text-[var(--text-muted)] text-[12px] py-2">
        No tree data available.
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-deep)] border border-[var(--border)] rounded-md p-2">
      <div className="text-[var(--text-muted)] text-[10px] uppercase tracking-wide font-medium mb-2">
        Event Tree
      </div>
      <TreeNodeView node={tree} depth={0} highlightId={eventId} />
    </div>
  );
}
