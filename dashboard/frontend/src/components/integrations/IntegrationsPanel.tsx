"use client";

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/shared/Badge";
import {
  getIntegrations,
  updateIntegration,
  deleteIntegration,
  revealIntegrationField,
  type IntegrationInfo,
  type IntegrationField,
} from "@/lib/api";
import * as api from "@/lib/api";
import type { ChannelSetup, SetupStep, SetupStatus, SetupAction } from "@/lib/types";

interface IntegrationsPanelProps {
  cogentName: string;
}

export function IntegrationsPanel({ cogentName }: IntegrationsPanelProps) {
  const [integrations, setIntegrations] = useState<IntegrationInfo[]>([]);
  const [setup, setSetup] = useState<Record<string, ChannelSetup>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedName, setExpandedName] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [intData, setupData] = await Promise.all([
        getIntegrations(cogentName),
        api.getSetup(cogentName).catch(() => ({ channels: [] })),
      ]);
      setIntegrations(intData);
      const setupMap: Record<string, ChannelSetup> = {};
      for (const ch of setupData.channels) {
        setupMap[ch.key] = ch;
      }
      setSetup(setupMap);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading && integrations.length === 0) {
    return <div style={{ color: "var(--text-muted)", padding: "2rem" }}>Loading integrations...</div>;
  }

  if (error && integrations.length === 0) {
    return <div style={{ color: "var(--error)", padding: "2rem" }}>{error}</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {integrations.map((integration) => (
        <IntegrationRow
          key={integration.name}
          integration={integration}
          setupChannel={setup[integration.name]}
          cogentName={cogentName}
          expanded={expandedName === integration.name}
          onToggle={() => setExpandedName(expandedName === integration.name ? null : integration.name)}
          onUpdate={fetchData}
        />
      ))}
    </div>
  );
}

function IntegrationRow({
  integration,
  setupChannel,
  cogentName,
  expanded,
  onToggle,
  onUpdate,
}: {
  integration: IntegrationInfo;
  setupChannel?: ChannelSetup;
  cogentName: string;
  expanded: boolean;
  onToggle: () => void;
  onUpdate: () => void;
}) {
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    if (expanded) {
      const values: Record<string, string> = {};
      for (const field of integration.fields) {
        values[field.name] = "";
      }
      setFormValues(values);
      setSaveError(null);
      setDeleteConfirm(false);
    }
  }, [expanded, integration.fields]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const config: Record<string, string> = {};
      for (const [k, v] of Object.entries(formValues)) {
        if (v.trim()) config[k] = v.trim();
      }
      if (Object.keys(config).length === 0) {
        setSaveError("Enter at least one field.");
        setSaving(false);
        return;
      }
      await updateIntegration(cogentName, integration.name, config);
      onUpdate();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteIntegration(cogentName, integration.name);
      setDeleteConfirm(false);
      onUpdate();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  const isConfigured = integration.status.configured;
  const hasAnyConfig = Object.values(integration.config).some((v) => v && v !== "");
  const missingFields = new Set(integration.status.missing_fields);

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "var(--bg-surface)",
        overflow: "hidden",
      }}
    >
      {/* Clickable header */}
      <div
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          cursor: "pointer",
          userSelect: "none",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <IntegrationIcon name={integration.name} />
          <div>
            <span style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: "13px" }}>
              {integration.display_name}
            </span>
            <span style={{ fontSize: "12px", color: "var(--text-muted)", marginLeft: 8 }}>
              {integration.description}
            </span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <StatusPill configured={isConfigured} hasAnyConfig={hasAnyConfig} />
          <span style={{ color: "var(--text-muted)", fontSize: "12px", transform: expanded ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 150ms" }}>
            ▶
          </span>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "14px 16px" }}>
          {/* Config fields — always editable */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 480 }}>
            {integration.fields.map((field) => (
              <FieldRow
                key={field.name}
                field={field}
                currentValue={integration.config[field.name] ?? ""}
                editValue={formValues[field.name] ?? ""}
                onChange={(v) => setFormValues((prev) => ({ ...prev, [field.name]: v }))}
                cogentName={cogentName}
                integrationName={integration.name}
                isMissing={missingFields.has(field.name)}
              />
            ))}
          </div>

          {saveError && (
            <div style={{ color: "var(--error)", fontSize: "12px", marginTop: 8 }}>{saveError}</div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-[11px] px-3 py-1 rounded border-0 cursor-pointer disabled:opacity-40"
              style={{ background: "var(--accent)", color: "white" }}
            >
              {saving ? "Saving..." : "Save"}
            </button>
            {isConfigured && !deleteConfirm && (
              <button
                onClick={() => setDeleteConfirm(true)}
                className="text-[11px] px-3 py-1 rounded border cursor-pointer"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--error)" }}
              >
                Remove
              </button>
            )}
            {deleteConfirm && (
              <>
                <span className="text-[11px] text-[var(--text-muted)]">Remove all config?</span>
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="text-[11px] px-2 py-0.5 rounded border-0 cursor-pointer disabled:opacity-40"
                  style={{ background: "var(--error)", color: "white" }}
                >
                  {deleting ? "..." : "Yes"}
                </button>
                <button
                  onClick={() => setDeleteConfirm(false)}
                  className="text-[11px] px-2 py-0.5 rounded border cursor-pointer"
                  style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
                >
                  No
                </button>
              </>
            )}
          </div>

          {/* Setup instructions */}
          {setupChannel && setupChannel.steps.length > 0 && (
            <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)] mb-2">
                Setup Instructions
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {setupChannel.steps.map((step, i) => (
                  <StepItem key={step.key} index={i + 1} step={step} />
                ))}
              </div>
              {setupChannel.diagnostics.length > 0 && (
                <div className="mt-2 text-[11px] text-[var(--warning)] space-y-1">
                  {setupChannel.diagnostics.map((d) => <div key={d}>{d}</div>)}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FieldRow({
  field,
  currentValue,
  editValue,
  onChange,
  cogentName,
  integrationName,
  isMissing,
}: {
  field: IntegrationField;
  currentValue: string;
  editValue: string;
  onChange: (v: string) => void;
  cogentName: string;
  integrationName: string;
  isMissing: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const [revealedValue, setRevealedValue] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);

  const isSecret = field.type === "secret";
  const inputType = isSecret ? "password" : field.type === "email" ? "email" : field.type === "url" ? "url" : "text";

  const displayCurrent = !currentValue
    ? ""
    : isSecret && !revealed
      ? currentValue
      : isSecret && revealed && revealedValue !== null
        ? revealedValue
        : currentValue;

  const handleReveal = async () => {
    if (revealed) { setRevealed(false); return; }
    setRevealing(true);
    try {
      const raw = await revealIntegrationField(cogentName, integrationName, field.name);
      setRevealedValue(raw);
      setRevealed(true);
    } catch { /* ignore */ }
    finally { setRevealing(false); }
  };

  const placeholder = currentValue ? `Current: ${currentValue}` : field.placeholder || field.label;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
        <label className="text-[11px] font-medium" style={{ color: isMissing ? "var(--error)" : "var(--text-secondary)" }}>
          {field.label}
          {field.required && <span style={{ color: "var(--error)", marginLeft: 2 }}>*</span>}
          {isMissing && <span className="text-[9px] ml-1">(required)</span>}
        </label>
        {isSecret && currentValue && (
          <button
            onClick={handleReveal}
            disabled={revealing}
            className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer"
            style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            {revealing ? "..." : revealed ? "Hide" : "View"}
          </button>
        )}
        {currentValue && !isSecret && (
          <span className="text-[10px] font-mono text-[var(--text-muted)]">{displayCurrent}</span>
        )}
        {isSecret && revealed && revealedValue && (
          <span className="text-[10px] font-mono text-[var(--text-muted)]">{revealedValue}</span>
        )}
      </div>
      {field.type === "textarea" ? (
        <textarea
          value={editValue}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
          style={{ background: "var(--bg-base)", borderColor: "var(--border)", color: "var(--text-primary)" }}
        />
      ) : (
        <input
          type={inputType}
          value={editValue}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full px-2 py-1.5 text-[12px] rounded border"
          style={{
            background: "var(--bg-base)",
            borderColor: "var(--border)",
            color: "var(--text-primary)",
            fontFamily: inputType === "password" ? "inherit" : "var(--font-mono)",
          }}
        />
      )}
      {field.help_text && (
        <div className="text-[10px] text-[var(--text-muted)] mt-1">{field.help_text}</div>
      )}
    </div>
  );
}

function StepItem({ index, step }: { index: number; step: SetupStep }) {
  const variant = step.status === "ready" ? "success"
    : step.status === "manual" ? "info"
    : step.status === "unknown" ? "neutral"
    : "warning";

  return (
    <div className="flex items-start gap-2">
      <span
        className="inline-flex w-4 h-4 items-center justify-center rounded-full text-[9px] font-semibold shrink-0 mt-0.5"
        style={{
          background: step.status === "ready" ? "rgba(52,211,153,0.15)" : "var(--accent-glow)",
          color: step.status === "ready" ? "var(--success)" : "var(--accent)",
        }}
      >
        {step.status === "ready" ? "✓" : index}
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-medium text-[var(--text-primary)]">{step.title}</span>
          <Badge variant={variant}>
            {step.status === "ready" ? "Done" : step.status === "manual" ? "Manual" : step.status === "unknown" ? "Unknown" : "Action needed"}
          </Badge>
        </div>
        <div className="text-[11px] text-[var(--text-muted)] mt-0.5">{step.description}</div>
        {step.detail && (
          <div className="text-[11px] text-[var(--text-muted)] mt-1 whitespace-pre-line">{step.detail}</div>
        )}
        {step.action && (
          <div className="mt-1">
            {step.action.href && (
              <a href={step.action.href} target="_blank" rel="noreferrer" className="text-[11px] text-[var(--accent)] hover:underline">
                {step.action.label} →
              </a>
            )}
            {step.action.command && (
              <pre className="mt-1 rounded border border-[var(--border)] bg-[var(--bg-base)] px-2 py-1 text-[10px] text-[var(--text-secondary)] overflow-x-auto">
                <code>{step.action.command}</code>
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPill({ configured, hasAnyConfig }: { configured: boolean; hasAnyConfig: boolean }) {
  const bg = configured ? "rgba(34,197,94,0.12)" : hasAnyConfig ? "rgba(239,68,68,0.12)" : "rgba(250,204,21,0.12)";
  const color = configured ? "var(--success)" : hasAnyConfig ? "var(--error)" : "var(--warning)";
  const label = configured ? "Connected" : hasAnyConfig ? "Incomplete" : "Not configured";

  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 12,
      fontSize: "10px", fontWeight: 500, background: bg, color,
    }}>
      {label}
    </span>
  );
}

function IntegrationIcon({ name }: { name: string }) {
  const size = 24;
  const style = { width: size, height: size, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 5, flexShrink: 0 } as const;

  switch (name) {
    case "discord":
      return (
        <div style={{ ...style, background: "rgba(88,101,242,0.15)", color: "#5865f2" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
          </svg>
        </div>
      );
    case "github":
      return (
        <div style={{ ...style, background: "rgba(255,255,255,0.1)", color: "var(--text-primary)" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
          </svg>
        </div>
      );
    case "asana":
      return (
        <div style={{ ...style, background: "rgba(246,116,99,0.15)", color: "#f67463" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.78 12.653c-2.882 0-5.22 2.337-5.22 5.218S15.898 23.09 18.78 23.09 24 20.752 24 17.871s-2.338-5.218-5.22-5.218zM5.22 12.653C2.338 12.653 0 14.99 0 17.871s2.338 5.218 5.22 5.218 5.22-2.337 5.22-5.218-2.338-5.218-5.22-5.218zM12 .91c-2.882 0-5.22 2.337-5.22 5.218S9.118 11.346 12 11.346s5.22-2.337 5.22-5.218S14.882.91 12 .91z" />
          </svg>
        </div>
      );
    case "email":
      return (
        <div style={{ ...style, background: "rgba(59,130,246,0.15)", color: "#3b82f6" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="M22 7l-10 7L2 7" />
          </svg>
        </div>
      );
    default:
      return (
        <div style={{ ...style, background: "rgba(148,163,184,0.15)", color: "var(--text-muted)" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
      );
  }
}
