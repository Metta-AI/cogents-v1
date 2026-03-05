"use client";

import { useState, useCallback } from "react";

interface JsonViewerProps {
  data: unknown;
  defaultExpanded?: boolean;
}

export function JsonViewer({
  data,
  defaultExpanded = false,
}: JsonViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [data]);

  return (
    <div className="relative bg-[var(--bg-deep)] border border-[var(--border)] rounded-md p-3 text-[12px] font-mono">
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-0.5 text-[10px] rounded bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border-active)] transition-colors"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <JsonNode data={data} depth={0} defaultExpanded={defaultExpanded} />
    </div>
  );
}

interface JsonNodeProps {
  data: unknown;
  depth: number;
  defaultExpanded: boolean;
  keyName?: string;
}

function JsonNode({ data, depth, defaultExpanded, keyName }: JsonNodeProps) {
  const isExpandable =
    data !== null && typeof data === "object";
  const itemCount = isExpandable
    ? Array.isArray(data)
      ? data.length
      : Object.keys(data as Record<string, unknown>).length
    : 0;

  const [expanded, setExpanded] = useState(
    defaultExpanded || (depth < 1 && itemCount <= 8),
  );

  const indent = depth * 16;

  if (!isExpandable) {
    return (
      <div style={{ paddingLeft: indent }}>
        {keyName != null && (
          <span className="text-[var(--text-muted)]">
            {`"${keyName}": `}
          </span>
        )}
        <span className={valueColorClass(data)}>{formatPrimitive(data)}</span>
      </div>
    );
  }

  const isArray = Array.isArray(data);
  const entries = isArray
    ? (data as unknown[]).map((v, i) => [String(i), v] as const)
    : Object.entries(data as Record<string, unknown>);

  const bracket = isArray ? ["[", "]"] : ["{", "}"];

  return (
    <div>
      <div
        style={{ paddingLeft: indent }}
        className="cursor-pointer hover:text-[var(--text-primary)] select-none"
        onClick={() => setExpanded((e) => !e)}
      >
        <span className="text-[var(--text-muted)] mr-1">
          {expanded ? "\u25BC" : "\u25B6"}
        </span>
        {keyName != null && (
          <span className="text-[var(--text-muted)]">
            {`"${keyName}": `}
          </span>
        )}
        <span className="text-[var(--text-muted)]">
          {bracket[0]}
          {!expanded && (
            <span className="text-[var(--text-muted)]">
              {` ${itemCount} item${itemCount !== 1 ? "s" : ""} `}
            </span>
          )}
          {!expanded && bracket[1]}
        </span>
      </div>
      {expanded && (
        <>
          {entries.map(([k, v]) => (
            <JsonNode
              key={k}
              keyName={isArray ? undefined : k}
              data={v}
              depth={depth + 1}
              defaultExpanded={defaultExpanded}
            />
          ))}
          <div
            style={{ paddingLeft: indent }}
            className="text-[var(--text-muted)]"
          >
            {bracket[1]}
          </div>
        </>
      )}
    </div>
  );
}

function formatPrimitive(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return `"${value}"`;
  return String(value);
}

function valueColorClass(value: unknown): string {
  if (value === null || value === undefined)
    return "text-[var(--text-muted)]";
  if (typeof value === "string") return "text-green-400";
  if (typeof value === "number") return "text-blue-400";
  if (typeof value === "boolean") return "text-amber-400";
  return "text-[var(--text-secondary)]";
}
