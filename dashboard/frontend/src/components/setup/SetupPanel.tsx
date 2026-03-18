"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/shared/Badge";
import * as api from "@/lib/api";
import type {
  ChannelSetup,
  SetupAction,
  SetupResponse,
  SetupStatus,
  SetupStep,
} from "@/lib/types";

interface SetupPanelProps {
  cogentName: string;
}

function statusLabel(status: SetupStatus, readyForTest = false): string {
  if (readyForTest) return "Ready to test";
  if (status === "ready") return "Ready";
  if (status === "manual") return "Manual";
  if (status === "unknown") return "Checks unavailable";
  return "Needs setup";
}

function statusVariant(status: SetupStatus, readyForTest = false): "success" | "warning" | "info" | "neutral" {
  if (readyForTest || status === "ready") return "success";
  if (status === "manual") return "info";
  if (status === "unknown") return "neutral";
  return "warning";
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="mt-2 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 overflow-x-auto text-[12px] text-[var(--text-secondary)]">
      <code>{children}</code>
    </pre>
  );
}

function ActionBlock({ action }: { action: SetupAction | null }) {
  if (!action) return null;

  return (
    <div className="mt-3 space-y-2">
      {action.href && (
        <a
          href={action.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--accent)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {action.label}
        </a>
      )}
      {action.command && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{action.label}</div>
          <CodeBlock>{action.command}</CodeBlock>
        </div>
      )}
    </div>
  );
}

function StepCard({ index, step }: { index: number; step: SetupStep }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-[var(--accent-glow)] text-[var(--accent)] text-[11px] font-semibold">
              {index}
            </span>
            <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">{step.title}</h3>
          </div>
          <p className="text-[13px] leading-6 text-[var(--text-secondary)]">{step.description}</p>
          {step.detail && (
            <p className="mt-2 whitespace-pre-line text-[12px] leading-5 text-[var(--text-muted)]">{step.detail}</p>
          )}
          <ActionBlock action={step.action} />
        </div>
        <Badge variant={statusVariant(step.status)}>{statusLabel(step.status)}</Badge>
      </div>
    </div>
  );
}

/** Parse profile markdown into field values. */
function parseProfile(content: string): { name: string; discordUserId: string; discordUsername: string } {
  const fields = { name: "", discordUserId: "", discordUsername: "" };
  for (const line of content.split("\n")) {
    if (line.includes("**Name:**")) {
      fields.name = line.split("**Name:**")[1].trim();
    } else if (line.includes("**Discord User ID:**")) {
      fields.discordUserId = line.split("**Discord User ID:**")[1].trim();
    } else if (line.includes("**Discord Username:**")) {
      fields.discordUsername = line.split("**Discord Username:**")[1].trim();
    }
  }
  return fields;
}

/** Render profile markdown from field values. */
function renderProfile(fields: { name: string; discordUserId: string; discordUsername: string }): string {
  return (
    "# Profile\n" +
    "\n" +
    `- **Name:** ${fields.name}\n` +
    `- **Discord User ID:** ${fields.discordUserId}\n` +
    `- **Discord Username:** ${fields.discordUsername}\n`
  );
}

function ProfileEditor({ cogentName, step, onSaved }: { cogentName: string; step: SetupStep; onSaved: () => void }) {
  const initial = parseProfile(step.detail ?? "");
  const [name, setName] = useState(initial.name);
  const [discordUserId, setDiscordUserId] = useState(initial.discordUserId);
  const [discordUsername, setDiscordUsername] = useState(initial.discordUsername);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const isPlaceholder = (v: string) => !v || v.includes("(set on boot)") || v.includes("(set via dashboard)");
  const hasChanges =
    name !== initial.name || discordUserId !== initial.discordUserId || discordUsername !== initial.discordUsername;

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const content = renderProfile({ name, discordUserId, discordUsername });
      await api.updateFile(cogentName, "whoami/profile.md", { content, source: "human" });
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]";

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
      <div className="flex items-center gap-2 mb-4">
        <span className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-[var(--accent-glow)] text-[var(--accent)] text-[11px] font-semibold">
          1
        </span>
        <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">{step.title}</h3>
        <Badge variant={statusVariant(step.status)}>{statusLabel(step.status)}</Badge>
      </div>
      <p className="text-[13px] leading-6 text-[var(--text-secondary)] mb-4">{step.description}</p>

      <div className="space-y-3 max-w-md">
        <div>
          <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. dr.alpha"
            className={`${inputClass} ${isPlaceholder(initial.name) ? "border-[var(--warning)]" : ""}`}
          />
        </div>
        <div>
          <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Discord User ID</label>
          <input
            type="text"
            value={discordUserId}
            onChange={(e) => setDiscordUserId(e.target.value)}
            placeholder="e.g. 1234567890"
            className={`${inputClass} ${isPlaceholder(initial.discordUserId) ? "border-[var(--warning)]" : ""}`}
          />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            The bot&apos;s Discord user ID. Auto-populated when the bridge connects, or set manually.
          </p>
        </div>
        <div>
          <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Discord Username</label>
          <input
            type="text"
            value={discordUsername}
            onChange={(e) => setDiscordUsername(e.target.value)}
            placeholder="e.g. dr.alpha#1234"
            className={`${inputClass} ${isPlaceholder(initial.discordUsername) ? "border-[var(--warning)]" : ""}`}
          />
        </div>
      </div>

      {saveError && <p className="mt-3 text-[12px] text-[var(--warning)]">{saveError}</p>}

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className="rounded-md bg-[var(--accent)] px-4 py-2 text-[12px] font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving..." : "Save profile"}
        </button>
        {!hasChanges && step.status === "ready" && (
          <span className="text-[12px] text-[var(--text-muted)]">No changes</span>
        )}
      </div>
    </div>
  );
}

export function SetupPanel({ cogentName }: SetupPanelProps) {
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [activeChannelKey, setActiveChannelKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getSetup(cogentName);
      setSetup(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load setup status");
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!setup?.channels.length) {
      setActiveChannelKey(null);
      return;
    }
    if (!activeChannelKey || !setup.channels.some((channel) => channel.key === activeChannelKey)) {
      setActiveChannelKey(setup.channels[0].key);
    }
  }, [setup, activeChannelKey]);

  const activeChannel = useMemo<ChannelSetup | null>(() => {
    if (!setup?.channels.length) return null;
    return setup.channels.find((channel) => channel.key === activeChannelKey) ?? setup.channels[0];
  }, [setup, activeChannelKey]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-[18px] font-semibold text-[var(--text-primary)]">Setup</h2>
            {activeChannel && (
              <Badge variant={statusVariant(activeChannel.status, activeChannel.ready_for_test)}>
                {statusLabel(activeChannel.status, activeChannel.ready_for_test)}
              </Badge>
            )}
          </div>
          <p className="text-[13px] text-[var(--text-secondary)] max-w-[720px]">
            Walk through first-run tasks that are easy to miss after a fresh cogent bring-up.
          </p>
        </div>
        <button
          onClick={refresh}
          className="self-start rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {loading ? "Refreshing..." : "Refresh checks"}
        </button>
      </div>

      {!!setup?.channels.length && (
        <div className="inline-flex rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-1">
          {setup.channels.map((channel) => (
            <button
              key={channel.key}
              onClick={() => setActiveChannelKey(channel.key)}
              className="rounded px-3 py-1.5 text-[12px] font-medium transition-colors"
              style={{
                background: activeChannel?.key === channel.key ? "var(--accent-glow)" : "transparent",
                color: activeChannel?.key === channel.key ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              {channel.title}
            </button>
          ))}
        </div>
      )}

      {!loading && !activeChannel && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 text-[13px] text-[var(--text-secondary)]">
          No setup tracks are available for this cogent yet.
        </div>
      )}

      {activeChannel && (
        <>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">{activeChannel.title}</h3>
              <Badge variant={statusVariant(activeChannel.status, activeChannel.ready_for_test)}>
                {statusLabel(activeChannel.status, activeChannel.ready_for_test)}
              </Badge>
            </div>
            <p className="text-[13px] text-[var(--text-secondary)]">{activeChannel.description}</p>
            <p className="mt-2 text-[13px] text-[var(--text-muted)]">{activeChannel.summary}</p>
            {(error || activeChannel.diagnostics.length > 0) && (
              <div className="mt-3 text-[12px] text-[var(--warning)] space-y-1">
                {error && <div>Setup status request failed: {error}</div>}
                {activeChannel.diagnostics.map((diagnostic) => (
                  <div key={diagnostic}>{diagnostic}</div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            {activeChannel.steps.map((step, index) => {
              if (activeChannel.key === "profile" && step.key === "edit-profile") {
                return <ProfileEditor key={step.key} cogentName={cogentName} step={step} onSaved={refresh} />;
              }
              return <StepCard key={step.key} index={index + 1} step={step} />;
            })}
          </div>
        </>
      )}
    </div>
  );
}
