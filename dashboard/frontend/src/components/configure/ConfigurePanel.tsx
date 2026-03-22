"use client";

import { IntegrationsPanel } from "@/components/integrations/IntegrationsPanel";

interface ConfigurePanelProps {
  cogentName: string;
}

export function ConfigurePanel({ cogentName }: ConfigurePanelProps) {
  return <IntegrationsPanel cogentName={cogentName} />;
}
