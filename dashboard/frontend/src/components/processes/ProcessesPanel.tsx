"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type { CogosProcess, CogosProcessRun, Resource, CogosRun } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import * as api from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

interface Props {
  processes: CogosProcess[];
  cogentName: string;
  onRefresh: () => void;
  resources: Resource[];
  runs: CogosRun[];
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  waiting: "neutral",
  runnable: "info",
  running: "success",
  completed: "accent",
  disabled: "error",
  blocked: "warning",
  suspended: "warning",
};

const STATUSES = ["waiting", "runnable", "running", "completed", "disabled", "blocked", "suspended"];
const MODES: ("daemon" | "one_shot")[] = ["one_shot", "daemon"];
const RUNNERS = ["lambda", "ecs"];

const INPUT_CLS = "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";

interface ProcessForm {
  name: string;
  mode: "daemon" | "one_shot";
  content: string;
  priority: string;
  runner: string;
  status: string;
  model: string;
  max_duration_ms: string;
  max_retries: string;
  preemptible: boolean;
  clear_context: boolean;
  resources: string[];
}

const EMPTY_FORM: ProcessForm = {
  name: "",
  mode: "one_shot",
  content: "",
  priority: "0",
  runner: "lambda",
  status: "waiting",
  model: "",
  max_duration_ms: "",
  max_retries: "0",
  preemptible: false,
  clear_context: false,
  resources: [],
};

function formFromProcess(p: CogosProcess): ProcessForm {
  return {
    name: p.name,
    mode: p.mode,
    content: p.content,
    priority: String(p.priority),
    runner: p.runner,
    status: p.status,
    model: p.model ?? "",
    max_duration_ms: p.max_duration_ms != null ? String(p.max_duration_ms) : "",
    max_retries: String(p.max_retries),
    preemptible: p.preemptible,
    clear_context: p.clear_context,
    resources: p.resources ?? [],
  };
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m${rem}s`;
}

function fmtTokens(n: number): string {
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/* ── TagListEditor: editable list with typeahead ── */

function TagListEditor({
  label,
  items,
  onChange,
  suggestions,
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  suggestions: string[];
}) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!query) return suggestions.filter((s) => !items.includes(s)).slice(0, 8);
    const q = query.toLowerCase();
    return suggestions
      .filter((s) => s.toLowerCase().includes(q) && !items.includes(s))
      .slice(0, 8);
  }, [query, suggestions, items]);

  const addItem = useCallback((val: string) => {
    const trimmed = val.trim();
    if (trimmed && !items.includes(trimmed)) {
      onChange([...items, trimmed]);
    }
    setQuery("");
    setShowSuggestions(false);
  }, [items, onChange]);

  const removeItem = useCallback((idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  }, [items, onChange]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={wrapperRef}>
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">{label}</label>
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {items.map((item, idx) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
              style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            >
              {item}
              <button
                onClick={() => removeItem(idx)}
                className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0"
              >
                x
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (filtered.length > 0) addItem(filtered[0]);
              else if (query.trim()) addItem(query);
            }
            if (e.key === "Escape") setShowSuggestions(false);
          }}
          placeholder={`Add ${label.toLowerCase()}...`}
          className={INPUT_CLS}
          style={{ fontSize: "11px" }}
        />
        {showSuggestions && filtered.length > 0 && (
          <div
            className="absolute z-50 left-0 right-0 mt-1 rounded overflow-hidden shadow-lg"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", maxHeight: "160px", overflowY: "auto" }}
          >
            {filtered.map((s) => (
              <button
                key={s}
                onClick={() => addItem(s)}
                className="w-full text-left px-2 py-1 text-[11px] font-mono border-0 cursor-pointer"
                style={{ background: "transparent", color: "var(--text-secondary)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Last Run Display ── */

function LastRunInfo({ run }: { run: CogosProcessRun }) {
  const [showResult, setShowResult] = useState(false);
  return (
    <div
      className="rounded p-3 space-y-2"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Last Run</span>
        <Badge variant={run.status === "completed" ? "success" : run.status === "failed" ? "error" : "warning"}>
          {run.status}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="text-[var(--text-muted)]">
          duration: <span className="text-[var(--text-secondary)]">{fmtDuration(run.duration_ms)}</span>
        </span>
        <span className="text-[var(--text-muted)]">
          tokens: <span className="text-[var(--text-secondary)]">{fmtTokens(run.tokens_in)} in / {fmtTokens(run.tokens_out)} out</span>
        </span>
        <span className="text-[var(--text-muted)]">
          cost: <span className="text-[var(--text-secondary)]">${run.cost_usd.toFixed(4)}</span>
        </span>
        {run.created_at && (
          <span className="text-[var(--text-muted)]">
            at: <span className="text-[var(--text-secondary)]">{fmtTimestamp(run.created_at)}</span>
          </span>
        )}
      </div>
      {run.error && (
        <div className="text-[11px] text-[var(--error)] font-mono whitespace-pre-wrap break-all p-2 rounded" style={{ background: "rgba(239,68,68,0.08)" }}>
          {run.error}
        </div>
      )}
      {run.result && (
        <div>
          <button
            onClick={() => setShowResult(!showResult)}
            className="text-[11px] text-[var(--accent)] bg-transparent border-0 cursor-pointer hover:underline p-0"
          >
            {showResult ? "Hide result" : "Show result"}
          </button>
          {showResult && (
            <div className="mt-1">
              <JsonViewer data={run.result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Process Form ── */

function ProcessFormEditor({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
  isNew,
  resourceSuggestions,
}: {
  form: ProcessForm;
  onChange: (form: ProcessForm) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  isNew: boolean;
  resourceSuggestions: string[];
}) {
  return (
    <div className="space-y-3 p-4 rounded-md" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] font-semibold text-[var(--text-primary)]">
          {isNew ? "New Process" : "Edit Process"}
        </span>
      </div>

      {/* Name */}
      <div>
        <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Name</label>
        <input className={INPUT_CLS} value={form.name} onChange={(e) => onChange({ ...form, name: e.target.value })} />
      </div>

      {/* Content */}
      <div>
        <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Content (prompt)</label>
        <textarea
          className={INPUT_CLS}
          rows={4}
          value={form.content}
          onChange={(e) => onChange({ ...form, content: e.target.value })}
          style={{ resize: "vertical" }}
        />
      </div>

      {/* Row: mode, status, runner */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Mode</label>
          <select className={INPUT_CLS} value={form.mode} onChange={(e) => onChange({ ...form, mode: e.target.value as "daemon" | "one_shot" })}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Status</label>
          <select className={INPUT_CLS} value={form.status} onChange={(e) => onChange({ ...form, status: e.target.value })}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Runner</label>
          <select className={INPUT_CLS} value={form.runner} onChange={(e) => onChange({ ...form, runner: e.target.value })}>
            {RUNNERS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>

      {/* Row: priority, model, max_duration_ms, max_retries */}
      <div className="grid grid-cols-4 gap-3">
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Priority</label>
          <input className={INPUT_CLS} type="number" step="0.1" value={form.priority} onChange={(e) => onChange({ ...form, priority: e.target.value })} />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Model</label>
          <input className={INPUT_CLS} value={form.model} onChange={(e) => onChange({ ...form, model: e.target.value })} placeholder="default" />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Max Duration (ms)</label>
          <input className={INPUT_CLS} type="number" value={form.max_duration_ms} onChange={(e) => onChange({ ...form, max_duration_ms: e.target.value })} placeholder="none" />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Max Retries</label>
          <input className={INPUT_CLS} type="number" value={form.max_retries} onChange={(e) => onChange({ ...form, max_retries: e.target.value })} />
        </div>
      </div>

      {/* Checkboxes */}
      <div className="flex gap-6">
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)] cursor-pointer">
          <input type="checkbox" checked={form.preemptible} onChange={(e) => onChange({ ...form, preemptible: e.target.checked })} />
          Preemptible
        </label>
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)] cursor-pointer">
          <input type="checkbox" checked={form.clear_context} onChange={(e) => onChange({ ...form, clear_context: e.target.checked })} />
          Clear Context
        </label>
      </div>

      {/* Resources with typeahead */}
      <TagListEditor
        label="Resources"
        items={form.resources}
        onChange={(resources) => onChange({ ...form, resources })}
        suggestions={resourceSuggestions}
      />

      {/* Save / Cancel */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onSave}
          disabled={saving || !form.name.trim()}
          className="px-3 py-1 text-[12px] rounded border-0 cursor-pointer transition-colors"
          style={{
            background: "var(--accent)",
            color: "white",
            opacity: saving || !form.name.trim() ? 0.5 : 1,
          }}
        >
          {saving ? "Saving..." : isNew ? "Create" : "Save"}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ── Main Panel ── */

export function ProcessesPanel({ processes, cogentName, onRefresh, resources, runs }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null); // "new" for create
  const [form, setForm] = useState<ProcessForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [detailRuns, setDetailRuns] = useState<CogosProcessRun[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const resourceSuggestions = useMemo(() => resources.map((r) => r.name), [resources]);

  // Build map of process_id -> latest run from the runs list
  const lastRunByProcess = useMemo(() => {
    const map: Record<string, CogosRun> = {};
    for (const r of runs) {
      const pid = r.process;
      if (!map[pid] || (r.created_at && (!map[pid].created_at || r.created_at > map[pid].created_at))) {
        map[pid] = r;
      }
    }
    return map;
  }, [runs]);

  const handleSelect = useCallback(async (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
      setDetailRuns([]);
      return;
    }
    setSelectedId(id);
    setLoadingDetail(true);
    try {
      const detail = await api.getProcessDetail(cogentName, id);
      setDetailRuns(detail.runs);
    } catch {
      setDetailRuns([]);
    }
    setLoadingDetail(false);
  }, [selectedId, cogentName]);

  const handleNew = useCallback(() => {
    setEditingId("new");
    setForm(EMPTY_FORM);
    setSelectedId(null);
  }, []);

  const handleEdit = useCallback((p: CogosProcess) => {
    setEditingId(p.id);
    setForm(formFromProcess(p));
  }, []);

  const handleCancel = useCallback(() => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        mode: form.mode,
        content: form.content,
        priority: parseFloat(form.priority) || 0,
        runner: form.runner,
        status: form.status,
        model: form.model.trim() || null,
        max_duration_ms: form.max_duration_ms ? parseInt(form.max_duration_ms) : null,
        max_retries: parseInt(form.max_retries) || 0,
        preemptible: form.preemptible,
        clear_context: form.clear_context,
        resources: form.resources,
      };
      if (editingId === "new") {
        await api.createProcess(cogentName, body as Parameters<typeof api.createProcess>[1]);
      } else {
        await api.updateProcess(cogentName, editingId!, body as Parameters<typeof api.updateProcess>[2]);
      }
      setEditingId(null);
      setForm(EMPTY_FORM);
      onRefresh();
    } catch (err) {
      console.error("Failed to save process:", err);
    }
    setSaving(false);
  }, [form, editingId, cogentName, onRefresh]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await api.deleteProcess(cogentName, id);
      setConfirmDeleteId(null);
      setSelectedId(null);
      setEditingId(null);
      onRefresh();
    } catch (err) {
      console.error("Failed to delete process:", err);
    }
  }, [cogentName, onRefresh]);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Processes
          <span className="ml-2 text-[var(--text-muted)] font-normal">({processes.length})</span>
        </h2>
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            {Object.entries(
              processes.reduce<Record<string, number>>((acc, p) => {
                acc[p.status] = (acc[p.status] || 0) + 1;
                return acc;
              }, {}),
            ).map(([status, count]) => (
              <Badge key={status} variant={STATUS_VARIANT[status] || "neutral"}>
                {count} {status}
              </Badge>
            ))}
          </div>
          <button
            onClick={handleNew}
            className="px-3 py-1 text-[12px] rounded border-0 cursor-pointer transition-colors"
            style={{ background: "var(--accent)", color: "white" }}
          >
            + New
          </button>
        </div>
      </div>

      {/* New process form */}
      {editingId === "new" && (
        <div className="mb-4">
          <ProcessFormEditor
            form={form}
            onChange={setForm}
            onSave={handleSave}
            onCancel={handleCancel}
            saving={saving}
            isNew
            resourceSuggestions={resourceSuggestions}
          />
        </div>
      )}

      {/* Process list */}
      {processes.length === 0 && editingId !== "new" && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No processes</div>
      )}

      <div className="rounded-md overflow-hidden" style={{ border: processes.length ? "1px solid var(--border)" : "none" }}>
        {processes.length > 0 && (
          <div
            className="grid items-center px-3 py-1.5 text-[10px] uppercase tracking-wide font-medium text-[var(--text-muted)]"
            style={{
              gridTemplateColumns: "minmax(120px, 2fr) 80px 80px 60px 80px 80px 60px auto",
              background: "var(--bg-deep)",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <span>Name</span>
            <span>Mode</span>
            <span>Status</span>
            <span>Pri</span>
            <span>Runner</span>
            <span>Model</span>
            <span>Last Run</span>
            <span className="text-right">Updated</span>
          </div>
        )}
        {processes.map((proc) => {
          const isSelected = selectedId === proc.id;
          const isEditing = editingId === proc.id;
          const lastRun = lastRunByProcess[proc.id];

          return (
            <div key={proc.id}>
              {/* Row */}
              <div
                className="grid items-center px-3 py-2 cursor-pointer transition-colors"
                style={{
                  gridTemplateColumns: "minmax(120px, 2fr) 80px 80px 60px 80px 80px 60px auto",
                  background: isSelected ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                }}
                onClick={() => handleSelect(proc.id)}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-surface)"; }}
              >
                <span className="text-[var(--text-primary)] font-medium text-[12px] truncate">{proc.name}</span>
                <span><Badge variant={proc.mode === "daemon" ? "accent" : "info"}>{proc.mode}</Badge></span>
                <span><Badge variant={STATUS_VARIANT[proc.status] || "neutral"}>{proc.status}</Badge></span>
                <span className="text-[11px] text-[var(--text-secondary)]">{proc.priority}</span>
                <span className="text-[11px] text-[var(--text-secondary)]">{proc.runner}</span>
                <span className="text-[11px] text-[var(--text-secondary)] truncate">{proc.model ?? "--"}</span>
                <span>
                  {lastRun ? (
                    <Badge variant={lastRun.status === "completed" ? "success" : lastRun.status === "failed" ? "error" : "warning"}>
                      {lastRun.status === "completed" ? "ok" : lastRun.status ?? "?"}
                    </Badge>
                  ) : (
                    <span className="text-[var(--text-muted)] text-[11px]">--</span>
                  )}
                </span>
                <span className="text-[var(--text-muted)] text-xs text-right">{fmtTimestamp(proc.updated_at)}</span>
              </div>

              {/* Expanded detail */}
              {isSelected && !isEditing && (
                <div
                  className="px-4 py-3 space-y-3"
                  style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
                >
                  {/* Metadata row */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                    <span className="text-[var(--text-muted)]">id: <span className="font-mono text-[var(--text-secondary)]">{proc.id}</span></span>
                    <span className="text-[var(--text-muted)]">retries: <span className="text-[var(--text-secondary)]">{proc.retry_count}/{proc.max_retries}</span></span>
                    {proc.max_duration_ms != null && (
                      <span className="text-[var(--text-muted)]">max duration: <span className="text-[var(--text-secondary)]">{fmtDuration(proc.max_duration_ms)}</span></span>
                    )}
                    <span className="text-[var(--text-muted)]">preemptible: <span className="text-[var(--text-secondary)]">{proc.preemptible ? "yes" : "no"}</span></span>
                    <span className="text-[var(--text-muted)]">clear ctx: <span className="text-[var(--text-secondary)]">{proc.clear_context ? "yes" : "no"}</span></span>
                  </div>

                  {/* Content */}
                  {proc.content && (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Content</div>
                      <div className="text-[11px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap p-2 rounded" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", maxHeight: "200px", overflowY: "auto" }}>
                        {proc.content}
                      </div>
                    </div>
                  )}

                  {/* Resources */}
                  {proc.resources && proc.resources.length > 0 && (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Resources</div>
                      <div className="flex flex-wrap gap-1">
                        {proc.resources.map((r) => (
                          <span key={r} className="px-1.5 py-0.5 rounded text-[11px] font-mono" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Last run detail */}
                  {loadingDetail ? (
                    <div className="text-[11px] text-[var(--text-muted)]">Loading runs...</div>
                  ) : detailRuns.length > 0 ? (
                    <LastRunInfo run={detailRuns[0]} />
                  ) : lastRun ? (
                    <LastRunInfo run={{
                      id: lastRun.id,
                      status: lastRun.status,
                      tokens_in: lastRun.tokens_in,
                      tokens_out: lastRun.tokens_out,
                      cost_usd: lastRun.cost_usd,
                      duration_ms: lastRun.duration_ms,
                      error: lastRun.error,
                      result: null,
                      created_at: lastRun.created_at,
                      completed_at: null,
                    }} />
                  ) : null}

                  {/* Actions */}
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleEdit(proc); }}
                      className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)] cursor-pointer transition-colors"
                    >
                      Edit
                    </button>
                    {confirmDeleteId === proc.id ? (
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-[var(--error)]">Delete?</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(proc.id); }}
                          className="px-2 py-0.5 text-[11px] rounded border-0 cursor-pointer"
                          style={{ background: "var(--error)", color: "white" }}
                        >
                          Yes
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}
                          className="px-2 py-0.5 text-[11px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] cursor-pointer"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(proc.id); }}
                        className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--error)] hover:border-[var(--error)] cursor-pointer transition-colors"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Inline edit form */}
              {isEditing && (
                <div className="px-4 py-3" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
                  <ProcessFormEditor
                    form={form}
                    onChange={setForm}
                    onSave={handleSave}
                    onCancel={handleCancel}
                    saving={saving}
                    isNew={false}
                    resourceSuggestions={resourceSuggestions}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
