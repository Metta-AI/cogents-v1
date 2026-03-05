"use client";

import React, { useState, useCallback, useEffect } from "react";
import type { TimeRange } from "@/lib/types";

const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "10m", label: "10m" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "1w", label: "1w" },
];

interface HeaderProps {
  cogentName: string;
  statusText: string;
  timeRange: TimeRange;
  onTimeRangeChange: (range: TimeRange) => void;
  onRefresh: () => void;
  loading: boolean;
  error: string | null;
  wsConnected: boolean;
}

export function Header({
  cogentName,
  statusText,
  timeRange,
  onTimeRangeChange,
  onRefresh,
  loading,
  error,
  wsConnected,
}: HeaderProps) {
  // Show spin for at least 400ms so the user sees feedback
  const [spinning, setSpinning] = useState(false);
  const handleRefresh = useCallback(() => {
    setSpinning(true);
    onRefresh();
    setTimeout(() => setSpinning(false), 400);
  }, [onRefresh]);
  const showSpin = loading || spinning;

  // Debounce WS connected state to avoid rapid flickering
  const [stableConnected, setStableConnected] = useState(false);
  useEffect(() => {
    if (wsConnected) {
      const timer = setTimeout(() => setStableConnected(true), 2000);
      return () => clearTimeout(timer);
    } else {
      setStableConnected(false);
    }
  }, [wsConnected]);

  return (
    <header
      className="fixed top-0 right-0 flex items-center justify-between px-4 z-40"
      style={{
        left: "var(--sidebar-w)",
        height: "var(--header-h)",
        background: "var(--bg-base)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      {/* Left: cogent name + status + WS indicator */}
      <div className="flex items-center gap-3">
        <span
          style={{
            color: "var(--accent)",
            fontSize: "15px",
            fontWeight: 700,
          }}
        >
          {cogentName}
        </span>
        <span
          style={{
            color: error ? "var(--error)" : "var(--text-muted)",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
          }}
        >
          {statusText}
        </span>
        {/* WebSocket connection indicator */}
        <span
          title={stableConnected ? "Real-time connected" : "Real-time disconnected — polling for updates"}
          className={!stableConnected ? "ws-reconnecting" : ""}
          style={{
            display: "inline-block",
            width: "6px",
            height: "6px",
            borderRadius: "50%",
            background: stableConnected ? "var(--success)" : "var(--warning)",
            flexShrink: 0,
          }}
        />
      </div>

      {/* Right: time range picker + refresh */}
      <div className="flex items-center gap-3">
        {/* Time range picker */}
        <div
          className="flex items-center rounded-md overflow-hidden"
          style={{
            border: "1px solid var(--border)",
            gap: "1px",
            background: "var(--border)",
          }}
        >
          {TIME_RANGES.map((tr) => (
            <button
              key={tr.value}
              onClick={() => onTimeRangeChange(tr.value)}
              className="border-0 cursor-pointer transition-colors duration-100"
              style={{
                padding: "4px 10px",
                fontSize: "11px",
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                color: timeRange === tr.value ? "var(--bg-deep)" : "var(--text-secondary)",
                background: timeRange === tr.value ? "var(--accent)" : "var(--bg-surface)",
              }}
              onMouseEnter={(e) => {
                if (timeRange !== tr.value) {
                  e.currentTarget.style.background = "var(--bg-hover)";
                }
              }}
              onMouseLeave={(e) => {
                if (timeRange !== tr.value) {
                  e.currentTarget.style.background = "var(--bg-surface)";
                }
              }}
            >
              {tr.label}
            </button>
          ))}
        </div>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          disabled={showSpin}
          className="flex items-center justify-center border-0 rounded-md cursor-pointer transition-colors duration-150"
          style={{
            width: "32px",
            height: "32px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            color: showSpin ? "var(--accent)" : "var(--text-secondary)",
          }}
          title="Refresh data"
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--bg-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--bg-surface)";
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={showSpin ? "header-spin" : ""}
          >
            <polyline points="23 4 23 10 17 10" />
            <polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
          </svg>
        </button>
      </div>
    </header>
  );
}
