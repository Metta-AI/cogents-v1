"use client";

import { useState } from "react";
import type { CogosFile } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { fmtTimestamp } from "@/lib/format";

interface Props {
  files: CogosFile[];
}

function FileRow({ file }: { file: CogosFile }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-[var(--border)]">
      <button
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-[var(--bg-hover)] transition-colors cursor-pointer bg-transparent border-0"
        onClick={() => setExpanded(!expanded)}
      >
        <span
          className="text-[var(--text-muted)] text-xs transition-transform"
          style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
        >
          {"\u25B6"}
        </span>
        <span className="text-[var(--text-primary)] font-mono text-[13px] flex-1 truncate">
          {file.key}
        </span>
        {file.versions && file.versions.length > 0 && (
          <Badge variant="info">{file.versions.length} ver</Badge>
        )}
      </button>
      {expanded && (
        <div className="px-6 pb-3">
          {file.content != null ? (
            <pre className="text-xs text-[var(--text-secondary)] bg-[var(--bg-base)] rounded p-3 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto border border-[var(--border)]">
              {file.content || "(empty)"}
            </pre>
          ) : (
            <div className="text-xs text-[var(--text-muted)] py-2">No content loaded</div>
          )}
          {file.versions && file.versions.length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Versions</div>
              {file.versions.map((v) => (
                <div key={v.version} className="flex items-center gap-2 py-1 text-xs">
                  <span className="font-mono text-[var(--text-secondary)]">v{v.version}</span>
                  <span className="text-[var(--text-muted)]">{v.source}</span>
                  {v.is_active && <Badge variant="success">active</Badge>}
                  <span className="text-[var(--text-muted)] ml-auto">{fmtTimestamp(v.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function FilesPanel({ files }: Props) {
  // Group files by prefix (first path segment)
  const grouped = files.reduce<Record<string, CogosFile[]>>((acc, f) => {
    const parts = f.key.split("/");
    const group = parts.length > 1 ? parts[0] : "(root)";
    if (!acc[group]) acc[group] = [];
    acc[group].push(f);
    return acc;
  }, {});

  const sortedGroups = Object.keys(grouped).sort();

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Files
          <span className="ml-2 text-[var(--text-muted)] font-normal">({files.length})</span>
        </h2>
      </div>
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        {files.length === 0 ? (
          <div className="px-3 py-8 text-center text-[var(--text-muted)]">No files</div>
        ) : sortedGroups.length === 1 ? (
          files.map((f) => <FileRow key={f.id} file={f} />)
        ) : (
          sortedGroups.map((group) => (
            <div key={group}>
              <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-[var(--text-muted)] font-semibold bg-[var(--bg-base)] border-b border-[var(--border)]">
                {group}
              </div>
              {grouped[group].map((f) => (
                <FileRow key={f.id} file={f} />
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
