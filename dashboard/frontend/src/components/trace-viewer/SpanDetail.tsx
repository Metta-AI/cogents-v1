"use client";

import React from "react";

export interface SpanEventData {
  id: string;
  event: string;
  message: string | null;
  timestamp: string | null;
  metadata: Record<string, any>;
}

export interface SpanData {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  coglet: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  metadata: Record<string, any>;
  events: SpanEventData[];
}

interface SpanDetailProps {
  span: SpanData;
  onClose: () => void;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "-";
  if (ms < 1) return `${(ms * 1000).toFixed(0)}us`;
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

const STATUS_COLORS: Record<string, string> = {
  running: "text-blue-400",
  completed: "text-green-400",
  errored: "text-red-400",
};

export function SpanDetail({ span, onClose }: SpanDetailProps) {
  const metaEntries = Object.entries(span.metadata).filter(
    ([k]) => !["tokens_in", "tokens_out", "cost_usd", "model", "error"].includes(k),
  );

  return (
    <div className="w-96 border-l border-white/10 bg-[#0a0a0a] overflow-y-auto h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10">
        <h3 className="text-sm font-semibold text-white truncate flex-1 mr-2">
          Span Detail
        </h3>
        <button
          onClick={onClose}
          className="text-white/40 hover:text-white/80 transition-colors cursor-pointer"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div className="p-4 space-y-4 text-xs">
        {/* Basic info */}
        <div className="space-y-2">
          <Row label="Name" value={span.name} />
          {span.coglet && <Row label="Coglet" value={span.coglet} />}
          <div className="flex justify-between">
            <span className="text-white/40">Status</span>
            <span className={STATUS_COLORS[span.status] ?? "text-white/70"}>
              {span.status}
            </span>
          </div>
          <Row label="Duration" value={formatDuration(span.duration_ms)} />
          {span.started_at && (
            <Row label="Started" value={new Date(span.started_at).toLocaleTimeString()} />
          )}
          {span.ended_at && (
            <Row label="Ended" value={new Date(span.ended_at).toLocaleTimeString()} />
          )}
          <Row label="Span ID" value={span.id} mono />
          {span.parent_span_id && (
            <Row label="Parent ID" value={span.parent_span_id} mono />
          )}
        </div>

        {/* Key metrics */}
        {(span.metadata.tokens_in != null || span.metadata.tokens_out != null || span.metadata.cost_usd != null || span.metadata.model) && (
          <div className="space-y-2 border-t border-white/10 pt-3">
            <h4 className="text-white/60 font-medium uppercase tracking-wider text-[10px]">
              LLM Metrics
            </h4>
            {span.metadata.model && <Row label="Model" value={span.metadata.model} />}
            {span.metadata.tokens_in != null && (
              <Row label="Tokens In" value={String(span.metadata.tokens_in)} />
            )}
            {span.metadata.tokens_out != null && (
              <Row label="Tokens Out" value={String(span.metadata.tokens_out)} />
            )}
            {span.metadata.cost_usd != null && (
              <Row label="Cost" value={`$${Number(span.metadata.cost_usd).toFixed(4)}`} />
            )}
          </div>
        )}

        {/* Error */}
        {span.metadata.error && (
          <div className="space-y-1 border-t border-white/10 pt-3">
            <h4 className="text-red-400 font-medium uppercase tracking-wider text-[10px]">
              Error
            </h4>
            <pre className="text-red-300 bg-red-900/20 p-2 rounded text-[11px] whitespace-pre-wrap break-all">
              {String(span.metadata.error)}
            </pre>
          </div>
        )}

        {/* Other metadata */}
        {metaEntries.length > 0 && (
          <div className="space-y-2 border-t border-white/10 pt-3">
            <h4 className="text-white/60 font-medium uppercase tracking-wider text-[10px]">
              Metadata
            </h4>
            {metaEntries.map(([k, v]) => (
              <Row key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
            ))}
          </div>
        )}

        {/* Events */}
        {span.events.length > 0 && (
          <div className="space-y-2 border-t border-white/10 pt-3">
            <h4 className="text-white/60 font-medium uppercase tracking-wider text-[10px]">
              Events ({span.events.length})
            </h4>
            <div className="space-y-2">
              {span.events
                .sort((a, b) => {
                  if (!a.timestamp || !b.timestamp) return 0;
                  return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
                })
                .map((evt) => (
                  <div key={evt.id} className="bg-white/5 rounded p-2 space-y-1">
                    <div className="flex justify-between items-center">
                      <span className="text-white/80 font-medium">{evt.event}</span>
                      {evt.timestamp && (
                        <span className="text-white/30 text-[10px]">
                          {new Date(evt.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                    {evt.message && (
                      <p className="text-white/50 text-[11px]">{evt.message}</p>
                    )}
                    {Object.keys(evt.metadata).length > 0 && (
                      <pre className="text-white/40 text-[10px] whitespace-pre-wrap break-all">
                        {JSON.stringify(evt.metadata, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-white/40 shrink-0">{label}</span>
      <span className={`text-white/70 text-right truncate ${mono ? "font-mono text-[10px]" : ""}`}>
        {value}
      </span>
    </div>
  );
}
