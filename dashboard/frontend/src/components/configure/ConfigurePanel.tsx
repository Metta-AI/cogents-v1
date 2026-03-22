"use client";

import { useState } from "react";
import type { CogosCapability } from "@/lib/types";
import { SetupPanel } from "@/components/setup/SetupPanel";
import { IntegrationsPanel } from "@/components/integrations/IntegrationsPanel";
import { CapabilitiesPanel } from "@/components/capabilities/CapabilitiesPanel";

type SubTab = "setup" | "integrations" | "capabilities";

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: "setup", label: "Setup" },
  { id: "integrations", label: "Integrations" },
  { id: "capabilities", label: "Capabilities" },
];

interface ConfigurePanelProps {
  cogentName: string;
  capabilities: CogosCapability[];
  onRefresh?: () => void;
}

export function ConfigurePanel({ cogentName, capabilities, onRefresh }: ConfigurePanelProps) {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("setup");

  return (
    <div className="space-y-5">
      <div className="inline-flex rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            className="rounded px-3 py-1.5 text-[12px] font-medium transition-colors"
            style={{
              background: activeSubTab === tab.id ? "var(--accent-glow)" : "transparent",
              color: activeSubTab === tab.id ? "var(--accent)" : "var(--text-secondary)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeSubTab === "setup" && <SetupPanel cogentName={cogentName} />}
      {activeSubTab === "integrations" && <IntegrationsPanel cogentName={cogentName} />}
      {activeSubTab === "capabilities" && (
        <CapabilitiesPanel capabilities={capabilities} cogentName={cogentName} onRefresh={onRefresh} />
      )}
    </div>
  );
}
