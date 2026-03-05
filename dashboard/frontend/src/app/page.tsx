"use client";

import { useState, useEffect, useCallback } from "react";
import { Sidebar, type TabId, VALID_TABS } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { useCogentData } from "@/hooks/useCogentData";
import { OverviewPanel } from "@/components/overview/OverviewPanel";
import { ProgramsPanel } from "@/components/programs/ProgramsPanel";
import { SessionsPanel } from "@/components/sessions/SessionsPanel";
import { ChannelsPanel } from "@/components/channels/ChannelsPanel";
import { EventsPanel } from "@/components/events/EventsPanel";
import { TriggersPanel } from "@/components/triggers/TriggersPanel";
import { MemoryPanel } from "@/components/memory/MemoryPanel";
import { ResourcesPanel } from "@/components/resources/ResourcesPanel";
import { TasksPanel } from "@/components/tasks/TasksPanel";
import { AlertsPanel } from "@/components/alerts/AlertsPanel";

function getTabFromHash(): TabId {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.replace("#", "");
  return VALID_TABS.has(hash as TabId) ? (hash as TabId) : "overview";
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>(getTabFromHash);

  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    window.location.hash = tab === "overview" ? "" : tab;
  }, []);

  useEffect(() => {
    const onPopState = () => setActiveTab(getTabFromHash());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  // For now, hardcode cogent name. Will come from URL/config later.
  const cogentName = "cogent";
  const { data, loading, error, refresh, timeRange, setTimeRange, connected } = useCogentData(cogentName);

  const statusText = loading && !data.status
    ? "connecting..."
    : error
      ? error
      : data.status
        ? `${data.status.active_sessions} active · ${data.status.trigger_count} triggers · ${data.status.unresolved_alerts} alerts`
        : "no data";

  return (
    <div className="h-screen overflow-hidden">
      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        alertCount={data.status?.unresolved_alerts}
        triggerCount={data.status?.trigger_count}
      />
      <Header
        cogentName={cogentName}
        statusText={statusText}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        onRefresh={refresh}
        loading={loading}
        error={error}
        wsConnected={connected}
      />
      <main
        className="fixed overflow-y-auto p-5"
        style={{
          top: "var(--header-h)",
          left: "var(--sidebar-w)",
          right: 0,
          bottom: 0,
        }}
      >
        {activeTab === "overview" && <OverviewPanel data={data} />}
        {activeTab === "programs" && (
          <ProgramsPanel programs={data.programs} cogentName={cogentName} />
        )}
        {activeTab === "sessions" && (
          <SessionsPanel sessions={data.sessions} />
        )}
        {activeTab === "channels" && (
          <ChannelsPanel channels={data.channels} />
        )}
        {activeTab === "events" && (
          <EventsPanel events={data.events} cogentName={cogentName} />
        )}
        {activeTab === "triggers" && (
          <TriggersPanel triggers={data.triggers} cogentName={cogentName} />
        )}
        {activeTab === "memory" && (
          <MemoryPanel memory={data.memory} />
        )}
        {activeTab === "resources" && (
          <ResourcesPanel data={data} />
        )}
        {activeTab === "tasks" && (
          <TasksPanel tasks={data.tasks} cogentName={cogentName} />
        )}
        {activeTab === "alerts" && (
          <AlertsPanel alerts={data.alerts} />
        )}
      </main>
    </div>
  );
}
