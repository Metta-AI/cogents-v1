"use client";

import React from "react";

const TABS = [
  {
    id: "overview",
    label: "Overview",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    id: "chat",
    label: "Chat",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
    ),
  },
  {
    id: "processes",
    label: "Processes",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
  },
  {
    id: "files",
    label: "Files",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
        <polyline points="13 2 13 9 20 9" />
      </svg>
    ),
  },
  {
    id: "events",
    label: "Events",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 01-3.46 0" />
      </svg>
    ),
  },
  {
    id: "diagnostics",
    label: "Diagnostics",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </svg>
    ),
  },
  {
    id: "configure",
    label: "Configure",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
] as const;

export type TabId = (typeof TABS)[number]["id"];
export const VALID_TABS = new Set<string>(TABS.map((t) => t.id));

interface SidebarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  stuckProcessCount?: number;
}

export function Sidebar({ activeTab, onTabChange, stuckProcessCount }: SidebarProps) {
  return (
    <nav
      className="fixed top-0 left-0 bottom-0 flex flex-col items-center py-2 z-50"
      style={{
        width: "var(--sidebar-w)",
        background: "var(--bg-base)",
        borderRight: "1px solid var(--border)",
      }}
    >
      {TABS.map((tab) => {
        const isActive = activeTab === tab.id;
        const badgeCount =
          tab.id === "processes" ? stuckProcessCount :
          undefined;

        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            title={tab.label}
            className="sidebar-btn relative flex flex-col items-center justify-center gap-0.5 w-full cursor-pointer border-0 bg-transparent transition-colors duration-150"
            style={{
              width: "var(--sidebar-w)",
              height: "var(--sidebar-w)",
              color: isActive ? "var(--accent)" : "var(--text-muted)",
              background: isActive ? "var(--accent-glow)" : "transparent",
              borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
            }}
            onMouseEnter={(e) => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--text-secondary)";
                e.currentTarget.style.background = "var(--bg-hover)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--text-muted)";
                e.currentTarget.style.background = "transparent";
              }
            }}
          >
            {tab.icon}
            <span
              style={{
                fontSize: "9px",
                lineHeight: 1,
                fontWeight: 500,
                marginTop: "2px",
                maxWidth: "calc(var(--sidebar-w) - 8px)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {tab.label}
            </span>
            {badgeCount != null && badgeCount > 0 && (
              <span
                className="absolute flex items-center justify-center rounded-full text-white font-bold"
                style={{
                  top: "4px",
                  right: "6px",
                  minWidth: "14px",
                  height: "14px",
                  fontSize: "8px",
                  padding: "0 3px",
                  background: "var(--warning)",
                }}
              >
                {badgeCount > 99 ? "99+" : badgeCount}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
