"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtTimestamp, timeRangeToMs } from "@/lib/format";
import type { DashboardEvent, Trigger, TimeRange, EventType } from "@/lib/types";
import { EventTree } from "./EventTree";
import * as api from "@/lib/api";

interface EventsPanelProps {
  events: DashboardEvent[];
  cogentName: string;
  triggers: Trigger[];
  timeRange: TimeRange;
  onTabChange?: (tab: string) => void;
  eventTypes: EventType[];
  onRefresh: () => void;
}

// Build a tree from event type names grouped by colon-delimited prefix
interface EventTypeNode {
  prefix: string;       // e.g. "discord"
  fullPath: string;     // e.g. "discord" or "discord:dm"
  children: EventTypeNode[];
  eventType?: EventType; // leaf if this is an actual event type
}

function buildEventTypeTree(eventTypes: EventType[]): EventTypeNode[] {
  // Use a nested map keyed by prefix at each level
  interface TreeMap { node: EventTypeNode; children: Map<string, TreeMap> }
  const rootMap = new Map<string, TreeMap>();

  for (const et of eventTypes) {
    const parts = et.name.split(":");
    let level = rootMap;
    let path = "";

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      path = path ? `${path}:${part}` : part;

      if (!level.has(part)) {
        level.set(part, {
          node: { prefix: part, fullPath: path, children: [], eventType: undefined },
          children: new Map(),
        });
      }
      const entry = level.get(part)!;
      if (i === parts.length - 1) {
        entry.node.eventType = et;
      }
      level = entry.children;
    }
  }

  function flatten(map: Map<string, TreeMap>): EventTypeNode[] {
    return Array.from(map.values()).map((entry) => {
      entry.node.children = flatten(entry.children);
      return entry.node;
    });
  }

  return flatten(rootMap);
}

// Collect all event type names under a node (for selecting a group)
function collectNames(node: EventTypeNode): string[] {
  const names: string[] = [];
  if (node.eventType) names.push(node.eventType.name);
  for (const c of node.children) names.push(...collectNames(c));
  return names;
}

export function EventsPanel({ events, cogentName, triggers, timeRange, onTabChange, eventTypes, onRefresh }: EventsPanelProps) {
  const [expandedId, setExpandedId] = useState<string | number | null>(null);
  const [treeId, setTreeId] = useState<string | number | null>(null);
  const [selectedEventTypes, setSelectedEventTypes] = useState<Set<string>>(new Set(["__all__"]));

  // Filter events by time range AND selected event types
  const timeFiltered = useMemo(() => {
    const cutoff = Date.now() - timeRangeToMs(timeRange);
    return events.filter((e) => {
      if (!e.created_at) return true;
      return new Date(e.created_at).getTime() >= cutoff;
    });
  }, [events, timeRange]);

  const filteredEvents = useMemo(() => {
    if (selectedEventTypes.has("__all__")) return timeFiltered;
    return timeFiltered.filter((e) => e.event_type && selectedEventTypes.has(e.event_type));
  }, [timeFiltered, selectedEventTypes]);

  // Build trigger lookup: event_pattern -> program_name[]
  const triggerMap = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const t of triggers) {
      if (t.event_pattern && t.program_name && t.enabled) {
        if (!map[t.event_pattern]) map[t.event_pattern] = [];
        map[t.event_pattern].push(t.program_name);
      }
    }
    return map;
  }, [triggers]);

  const getMatchingPrograms = useCallback((eventType: string | null): string[] => {
    if (!eventType) return [];
    const programs: string[] = [];
    for (const [pattern, progs] of Object.entries(triggerMap)) {
      // Simple glob match: pattern may use * as wildcard
      const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$");
      if (regex.test(eventType)) {
        programs.push(...progs);
      }
    }
    return [...new Set(programs)];
  }, [triggerMap]);

  const toggleExpand = useCallback((id: string | number) => {
    setExpandedId((prev) => (prev === id ? null : id));
    setTreeId(null);
  }, []);

  const formatContent = useCallback((payload: unknown): string => {
    if (payload == null) return "--";
    if (typeof payload === "object" && !Array.isArray(payload)) {
      const obj = payload as Record<string, unknown>;
      return Object.entries(obj)
        .map(([k, v]) => {
          const val = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v ?? "");
          return `[${k}: ${val}]`;
        })
        .join(" ");
    }
    return String(payload);
  }, []);

  const [newEventName, setNewEventName] = useState("");
  const [newEventDesc, setNewEventDesc] = useState("");

  const handleAddEventType = useCallback(async () => {
    const name = newEventName.trim();
    if (!name) return;
    try {
      await fetch(`/api/cogents/${cogentName}/event-types`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: newEventDesc.trim() }),
      });
      setNewEventName("");
      setNewEventDesc("");
      onRefresh();
    } catch { /* ignore */ }
  }, [newEventName, newEventDesc, cogentName, onRefresh]);

  const handleDeleteEventType = useCallback(async (name: string) => {
    try {
      await fetch(`/api/cogents/${cogentName}/event-types/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      onRefresh();
    } catch { /* ignore */ }
  }, [cogentName, onRefresh]);

  const eventTypeTree = useMemo(() => buildEventTypeTree(eventTypes), [eventTypes]);
  const allEventTypeNames = useMemo(() => eventTypes.map((et) => et.name), [eventTypes]);

  const toggleEventType = useCallback((name: string) => {
    setSelectedEventTypes((prev) => {
      const next = new Set(prev);
      if (name === "__all__") {
        return new Set(["__all__"]);
      }
      next.delete("__all__");
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      if (next.size === 0) return new Set(["__all__"]);
      return next;
    });
  }, []);

  const toggleGroup = useCallback((node: EventTypeNode) => {
    const names = collectNames(node);
    setSelectedEventTypes((prev) => {
      const next = new Set(prev);
      next.delete("__all__");
      const allSelected = names.every((n) => next.has(n));
      if (allSelected) {
        for (const n of names) next.delete(n);
      } else {
        for (const n of names) next.add(n);
      }
      if (next.size === 0) return new Set(["__all__"]);
      return next;
    });
  }, []);

  const isAll = selectedEventTypes.has("__all__");

  const renderTreeNode = useCallback((node: EventTypeNode, depth: number = 0): React.ReactNode => {
    const names = collectNames(node);
    const isLeaf = node.children.length === 0 && node.eventType;
    const isGroupSelected = !isAll && names.every((n) => selectedEventTypes.has(n));
    const isPartial = !isAll && !isGroupSelected && names.some((n) => selectedEventTypes.has(n));
    const isSelected = !isAll && node.eventType && selectedEventTypes.has(node.eventType.name);

    return (
      <div key={node.fullPath}>
        <div
          className="flex items-center gap-1.5 py-0.5 cursor-pointer select-none transition-colors rounded px-1"
          style={{
            paddingLeft: `${depth * 14 + 4}px`,
            background: (isLeaf ? isSelected : isGroupSelected) ? "rgba(99,102,241,0.12)" : "transparent",
          }}
          onClick={() => isLeaf ? toggleEventType(node.eventType!.name) : toggleGroup(node)}
          onMouseEnter={(e) => { e.currentTarget.style.background = (isLeaf ? isSelected : isGroupSelected) ? "rgba(99,102,241,0.18)" : "var(--bg-hover)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = (isLeaf ? isSelected : isGroupSelected) ? "rgba(99,102,241,0.12)" : "transparent"; }}
        >
          {!isLeaf && (
            <span className="text-[9px] text-[var(--text-muted)] w-2.5 text-center">
              {node.children.length > 0 ? "▸" : ""}
            </span>
          )}
          <span
            className={`text-[11px] font-mono ${isLeaf ? "" : "font-semibold"}`}
            style={{
              color: (isLeaf ? isSelected : isGroupSelected) ? "var(--accent)" : isPartial ? "var(--text-secondary)" : "var(--text-muted)",
            }}
          >
            {node.prefix}
          </span>
          {isLeaf && node.eventType?.source && (
            <span className="text-[9px] text-[var(--text-muted)]">({node.eventType.source})</span>
          )}
          {!isLeaf && (
            <span className="text-[9px] text-[var(--text-muted)]">({names.length})</span>
          )}
          {isLeaf && (
            <button
              onClick={(e) => { e.stopPropagation(); handleDeleteEventType(node.eventType!.name); }}
              className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0 ml-auto opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ opacity: 0 }}
              onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
              onMouseLeave={(e) => { e.currentTarget.style.opacity = "0"; }}
            >
              ×
            </button>
          )}
        </div>
        {node.children.length > 0 && node.children.map((c) => renderTreeNode(c, depth + 1))}
      </div>
    );
  }, [selectedEventTypes, isAll, toggleEventType, toggleGroup, handleDeleteEventType]);

  return (
    <div>
      {/* Event Types Tree */}
      <div
        className="rounded-md mb-4 p-3"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
            Event Types ({eventTypes.length})
          </span>
        </div>
        {/* All button + tree */}
        <div className="mb-2">
          <div
            className="flex items-center gap-1.5 py-0.5 cursor-pointer select-none rounded px-1 transition-colors"
            style={{ background: isAll ? "rgba(99,102,241,0.12)" : "transparent" }}
            onClick={() => toggleEventType("__all__")}
            onMouseEnter={(e) => { e.currentTarget.style.background = isAll ? "rgba(99,102,241,0.18)" : "var(--bg-hover)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = isAll ? "rgba(99,102,241,0.12)" : "transparent"; }}
          >
            <span
              className="text-[11px] font-mono font-semibold"
              style={{ color: isAll ? "var(--accent)" : "var(--text-muted)" }}
            >
              all
            </span>
            <span className="text-[9px] text-[var(--text-muted)]">({eventTypes.length})</span>
          </div>
          {eventTypeTree.map((node) => renderTreeNode(node, 0))}
        </div>
        {/* Add form */}
        <div className="flex gap-2 items-center">
          <input
            value={newEventName}
            onChange={(e) => setNewEventName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleAddEventType(); }}
            placeholder="event:name"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            className="bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] font-mono"
            style={{ width: "180px" }}
          />
          <input
            value={newEventDesc}
            onChange={(e) => setNewEventDesc(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleAddEventType(); }}
            placeholder="description (optional)"
            className="bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] flex-1"
          />
          <button
            onClick={handleAddEventType}
            disabled={!newEventName.trim()}
            className="px-2 py-1 text-[11px] rounded border-0 cursor-pointer transition-colors"
            style={{
              background: "var(--accent)",
              color: "white",
              opacity: newEventName.trim() ? 1 : 0.4,
            }}
          >
            Add
          </button>
        </div>
      </div>

      {/* Event Log */}
      <div className="text-[var(--text-muted)] text-xs mb-3">
        {filteredEvents.length}/{events.length} event{events.length !== 1 ? "s" : ""}
      </div>

      {filteredEvents.length === 0 && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No events</div>
      )}

      <div className="rounded-md overflow-hidden" style={{ border: filteredEvents.length ? "1px solid var(--border)" : "none" }}>
        {filteredEvents.length > 0 && (
          <div
            className="grid items-center px-3 py-1.5 text-[10px] uppercase tracking-wide font-medium text-[var(--text-muted)]"
            style={{ gridTemplateColumns: "minmax(100px, 1fr) minmax(80px, 1fr) minmax(200px, 3fr) minmax(80px, 1fr) minmax(180px, auto)", background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
          >
            <span>Event</span>
            <span>Source</span>
            <span>Content</span>
            <span>Triggers</span>
            <span className="text-right">Time</span>
          </div>
        )}
        {filteredEvents.map((evt) => {
          const isExpanded = expandedId === evt.id;
          const matchedPrograms = getMatchingPrograms(evt.event_type);

          return (
            <div key={evt.id}>
              <div
                className="grid items-center px-3 py-2 cursor-pointer transition-colors"
                style={{
                  gridTemplateColumns: "minmax(100px, 1fr) minmax(80px, 1fr) minmax(200px, 3fr) minmax(80px, 1fr) minmax(180px, auto)",
                  background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                }}
                onClick={() => toggleExpand(evt.id)}
                onMouseEnter={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-surface)";
                }}
              >
                <span className="truncate min-w-0"><Badge variant="accent">{evt.event_type ?? "event"}</Badge></span>
                <span className="text-[11px] text-[var(--text-secondary)] truncate">
                  {evt.source ?? "--"}
                </span>
                <span className="text-[11px] text-[var(--text-muted)] font-mono truncate">
                  {formatContent(evt.payload)}
                </span>
                <span className="flex gap-1 flex-wrap">
                  {matchedPrograms.map((p) => (
                    <span
                      key={p}
                      className="font-mono text-[10px] px-1.5 py-0.5 rounded text-[var(--info)] cursor-pointer hover:underline"
                      style={{ background: "rgba(59,130,246,0.1)" }}
                      onClick={(e) => { e.stopPropagation(); onTabChange?.("programs"); }}
                    >
                      {p}
                    </span>
                  ))}
                </span>
                <span className="text-[10px] text-[var(--text-muted)] text-right">{fmtTimestamp(evt.created_at)}</span>
              </div>

              {isExpanded && (
                <div
                  className="px-4 py-3 space-y-2"
                  style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
                >
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                    <span className="text-[var(--text-muted)]">id: <span className="font-mono text-[var(--text-secondary)]">{String(evt.id)}</span></span>
                    <span className="text-[var(--text-muted)]">type: <span className="font-mono text-[var(--text-secondary)]">{evt.event_type ?? "--"}</span></span>
                    {evt.source && <span className="text-[var(--text-muted)]">source: <span className="text-[var(--text-secondary)]">{evt.source}</span></span>}
                    {evt.parent_event_id != null && <span className="text-[var(--text-muted)]">parent: <span className="font-mono text-[var(--text-secondary)]">{evt.parent_event_id}</span></span>}
                    <span className="text-[var(--text-muted)]">created: <span className="text-[var(--text-secondary)]">{fmtTimestamp(evt.created_at)}</span></span>
                  </div>

                  {matchedPrograms.length > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px]">
                      <span className="text-[var(--text-muted)]">triggers:</span>
                      {matchedPrograms.map((p) => (
                        <span
                          key={p}
                          className="font-mono px-1.5 py-0.5 rounded text-[var(--info)] cursor-pointer hover:underline"
                          style={{ background: "rgba(59,130,246,0.1)" }}
                          onClick={(e) => { e.stopPropagation(); onTabChange?.("programs"); }}
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  )}

                  <JsonViewer data={evt.payload} />

                  {evt.parent_event_id != null && treeId !== evt.id && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setTreeId(evt.id); }}
                      className="px-3 py-1 text-[12px] rounded bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)] transition-colors cursor-pointer"
                    >
                      View Tree
                    </button>
                  )}
                  {treeId === evt.id && (
                    <div className="mt-2">
                      <EventTree eventId={evt.id} cogentName={cogentName} />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
