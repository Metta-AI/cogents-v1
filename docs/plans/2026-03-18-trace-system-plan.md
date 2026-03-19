# End-to-End Trace System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add distributed tracing with span hierarchy across all CogOS process execution, with a trace viewer UI in the dashboard.

**Architecture:** New `cogos.trace` module provides `TraceContext` via Python `contextvars`. Spans are stored in RDS via three new tables (`cogos_trace_v2`, `cogos_span`, `cogos_span_event`). The existing dashboard (FastAPI + Next.js) serves a trace viewer at `/traces/{traceId}`. Context propagates across Lambda boundaries via payload serialization and across channel messages via existing `trace_meta` field on `ChannelMessage`.

**Tech Stack:** Python 3.12+, pydantic, FastAPI, Next.js 15, React 19, Tailwind CSS 4, dagre/react-flow for graph view.

**Design doc:** `docs/plans/2026-03-18-trace-system-design.md`

---

### Task 1: Trace Data Models (Pydantic)

**Files:**
- Create: `src/cogos/db/models/span.py`
- Modify: `src/cogos/db/models/__init__.py`
- Modify: `src/cogos/db/models/trace.py`

**Step 1: Create Span and SpanEvent models**

Create `src/cogos/db/models/span.py`:

```python
"""Span models for distributed tracing."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SpanStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ERRORED = "errored"


class Span(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    parent_span_id: UUID | None = None
    name: str
    coglet: str | None = None
    status: SpanStatus = SpanStatus.RUNNING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpanEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    span_id: UUID
    event: str  # "log", "error", "metric"
    message: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**Step 2: Update trace model for new schema**

The existing `Trace` model in `src/cogos/db/models/trace.py` tracks per-run audit data (capability_calls, file_ops). The new trace system is request-scoped, not run-scoped. Add a new `RequestTrace` model to `trace.py`:

```python
class RequestTrace(BaseModel):
    """Request-level trace — groups spans across processes."""
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str = ""
    source: str = ""  # "discord", "api", "cli", "cron"
    source_ref: str | None = None  # e.g., discord channel_id:message_id
    created_at: datetime | None = None
```

**Step 3: Update `__init__.py` to export new models**

Add to `src/cogos/db/models/__init__.py`:
```python
from cogos.db.models.span import Span, SpanEvent, SpanStatus
from cogos.db.models.trace import RequestTrace
```

And add `"Span"`, `"SpanEvent"`, `"SpanStatus"`, `"RequestTrace"` to `__all__`.

**Step 4: Commit**

```bash
git add src/cogos/db/models/span.py src/cogos/db/models/trace.py src/cogos/db/models/__init__.py
git commit -m "feat(trace): add Span, SpanEvent, RequestTrace data models"
```

---

### Task 2: Database Migration

**Files:**
- Create: `src/cogos/db/migrations/018_trace_spans.sql`

**Step 1: Write migration SQL**

Create `src/cogos/db/migrations/018_trace_spans.sql`:

```sql
-- Distributed tracing: request traces, spans, and span events
CREATE TABLE IF NOT EXISTS cogos_request_trace (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id       VARCHAR NOT NULL DEFAULT '',
    source          VARCHAR NOT NULL DEFAULT '',
    source_ref      VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cogos_span (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL REFERENCES cogos_request_trace(id),
    parent_span_id  UUID REFERENCES cogos_span(id),
    name            VARCHAR NOT NULL,
    coglet          VARCHAR,
    status          VARCHAR NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cogos_span_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id         UUID NOT NULL REFERENCES cogos_span(id),
    event           VARCHAR NOT NULL,
    message         TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_cogos_span_trace ON cogos_span(trace_id);
CREATE INDEX IF NOT EXISTS idx_cogos_span_parent ON cogos_span(parent_span_id) WHERE parent_span_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cogos_span_event_span ON cogos_span_event(span_id);
CREATE INDEX IF NOT EXISTS idx_cogos_request_trace_created ON cogos_request_trace(created_at);
```

**Step 2: Commit**

```bash
git add src/cogos/db/migrations/018_trace_spans.sql
git commit -m "feat(trace): add migration for request_trace, span, span_event tables"
```

---

### Task 3: Repository Methods for Traces and Spans

**Files:**
- Modify: `src/cogos/db/repository.py` — add CRUD for request traces, spans, span events

**Step 1: Add repository methods**

Add after the existing `create_trace` method in `src/cogos/db/repository.py`:

```python
# ═══════════════════════════════════════════════════════════
# REQUEST TRACES & SPANS
# ═══════════════════════════════════════════════════════════

def create_request_trace(self, trace: RequestTrace) -> UUID:
    response = self._execute(
        """INSERT INTO cogos_request_trace (id, cogent_id, source, source_ref)
           VALUES (:id, :cogent_id, :source, :source_ref)
           RETURNING id, created_at""",
        [
            self._param("id", trace.id),
            self._param("cogent_id", trace.cogent_id),
            self._param("source", trace.source),
            self._param("source_ref", trace.source_ref),
        ],
    )
    row = self._first_row(response)
    if row:
        trace.created_at = self._ts(row, "created_at")
        return UUID(row["id"])
    raise RuntimeError("Failed to create request trace")

def get_request_trace(self, trace_id: UUID) -> RequestTrace | None:
    response = self._execute(
        "SELECT * FROM cogos_request_trace WHERE id = :id",
        [self._param("id", trace_id)],
    )
    row = self._first_row(response)
    if not row:
        return None
    return RequestTrace(
        id=UUID(row["id"]),
        cogent_id=row.get("cogent_id", ""),
        source=row.get("source", ""),
        source_ref=row.get("source_ref"),
        created_at=self._ts(row, "created_at"),
    )

def create_span(self, span: Span) -> UUID:
    response = self._execute(
        """INSERT INTO cogos_span
               (id, trace_id, parent_span_id, name, coglet, status, metadata)
           VALUES (:id, :trace_id, :parent_span_id, :name, :coglet, :status, :metadata::jsonb)
           RETURNING id, started_at""",
        [
            self._param("id", span.id),
            self._param("trace_id", span.trace_id),
            self._param("parent_span_id", span.parent_span_id),
            self._param("name", span.name),
            self._param("coglet", span.coglet),
            self._param("status", span.status.value),
            self._param("metadata", span.metadata),
        ],
    )
    row = self._first_row(response)
    if row:
        span.started_at = self._ts(row, "started_at")
        return UUID(row["id"])
    raise RuntimeError("Failed to create span")

def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool:
    if metadata:
        response = self._execute(
            """UPDATE cogos_span SET status = :status, ended_at = now(),
                   metadata = metadata || :metadata::jsonb
               WHERE id = :id""",
            [
                self._param("id", span_id),
                self._param("status", status),
                self._param("metadata", metadata),
            ],
        )
    else:
        response = self._execute(
            "UPDATE cogos_span SET status = :status, ended_at = now() WHERE id = :id",
            [self._param("id", span_id), self._param("status", status)],
        )
    return response.get("numberOfRecordsUpdated", 0) == 1

def list_spans(self, trace_id: UUID) -> list[Span]:
    response = self._execute(
        "SELECT * FROM cogos_span WHERE trace_id = :trace_id ORDER BY started_at",
        [self._param("trace_id", trace_id)],
    )
    return [self._span_from_row(r) for r in self._rows_to_dicts(response)]

def create_span_event(self, event: SpanEvent) -> UUID:
    response = self._execute(
        """INSERT INTO cogos_span_event (id, span_id, event, message, metadata)
           VALUES (:id, :span_id, :event, :message, :metadata::jsonb)
           RETURNING id, timestamp""",
        [
            self._param("id", event.id),
            self._param("span_id", event.span_id),
            self._param("event", event.event),
            self._param("message", event.message),
            self._param("metadata", event.metadata),
        ],
    )
    row = self._first_row(response)
    if row:
        event.timestamp = self._ts(row, "timestamp")
        return UUID(row["id"])
    raise RuntimeError("Failed to create span event")

def list_span_events(self, span_id: UUID) -> list[SpanEvent]:
    response = self._execute(
        "SELECT * FROM cogos_span_event WHERE span_id = :span_id ORDER BY timestamp",
        [self._param("span_id", span_id)],
    )
    return [self._span_event_from_row(r) for r in self._rows_to_dicts(response)]

def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]:
    response = self._execute(
        """SELECT e.* FROM cogos_span_event e
           JOIN cogos_span s ON s.id = e.span_id
           WHERE s.trace_id = :trace_id
           ORDER BY e.timestamp""",
        [self._param("trace_id", trace_id)],
    )
    return [self._span_event_from_row(r) for r in self._rows_to_dicts(response)]

def _span_from_row(self, row: dict) -> Span:
    from cogos.db.models.span import SpanStatus
    return Span(
        id=UUID(row["id"]),
        trace_id=UUID(row["trace_id"]),
        parent_span_id=UUID(row["parent_span_id"]) if row.get("parent_span_id") else None,
        name=row["name"],
        coglet=row.get("coglet"),
        status=SpanStatus(row["status"]),
        started_at=self._ts(row, "started_at"),
        ended_at=self._ts(row, "ended_at"),
        metadata=self._json_field(row, "metadata", {}),
    )

def _span_event_from_row(self, row: dict) -> SpanEvent:
    return SpanEvent(
        id=UUID(row["id"]),
        span_id=UUID(row["span_id"]),
        event=row["event"],
        message=row.get("message"),
        timestamp=self._ts(row, "timestamp"),
        metadata=self._json_field(row, "metadata", {}),
    )
```

Also add `RequestTrace`, `Span`, `SpanEvent`, `SpanStatus` to the imports at the top of repository.py.

**Step 2: Add request_trace table to `_ALL_TABLES` and `_CONFIG_TABLES`**

In `repository.py`, update `_ALL_TABLES` to include `"cogos_span_event"`, `"cogos_span"`, `"cogos_request_trace"` (before `cogos_trace`) and add them to `_CONFIG_TABLES` as well.

**Step 3: Commit**

```bash
git add src/cogos/db/repository.py
git commit -m "feat(trace): add repository CRUD for request traces, spans, span events"
```

---

### Task 4: TraceContext Module (contextvars)

**Files:**
- Create: `src/cogos/trace/__init__.py`
- Create: `src/cogos/trace/context.py`

**Step 1: Create the trace context module**

Create `src/cogos/trace/__init__.py`:

```python
"""CogOS distributed tracing."""
from cogos.trace.context import TraceContext, current_trace, init_trace
```

Create `src/cogos/trace/context.py`:

```python
"""Trace context propagation via contextvars."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from cogos.db.models.span import Span, SpanEvent, SpanStatus
from cogos.db.models.trace import RequestTrace

logger = logging.getLogger(__name__)

_current_trace: ContextVar[TraceContext | None] = ContextVar("_current_trace", default=None)


@dataclass
class TraceContext:
    """Holds the active trace + current span for the executing context."""
    trace_id: UUID
    span_id: UUID
    repo: Any  # Repository — typed as Any to avoid circular import

    def start_span(self, name: str, *, coglet: str | None = None, metadata: dict | None = None) -> SpanContext:
        """Create a child span. Use as a context manager."""
        return SpanContext(
            parent=self,
            name=name,
            coglet=coglet,
            metadata=metadata or {},
        )

    def log(self, event: str, message: str, metadata: dict | None = None) -> None:
        """Log an event to the current span."""
        try:
            self.repo.create_span_event(SpanEvent(
                span_id=self.span_id,
                event=event,
                message=message,
                metadata=metadata or {},
            ))
        except Exception:
            logger.debug("Failed to log span event", exc_info=True)

    def serialize(self) -> dict[str, str]:
        """Serialize for cross-process propagation."""
        return {
            "trace_id": str(self.trace_id),
            "span_id": str(self.span_id),
        }


class SpanContext:
    """Context manager that creates a child span and restores parent on exit."""

    def __init__(
        self,
        parent: TraceContext,
        name: str,
        coglet: str | None,
        metadata: dict,
    ) -> None:
        self._parent = parent
        self._name = name
        self._coglet = coglet
        self._metadata = metadata
        self._span_id = uuid4()
        self._token = None

    def __enter__(self) -> TraceContext:
        span = Span(
            id=self._span_id,
            trace_id=self._parent.trace_id,
            parent_span_id=self._parent.span_id,
            name=self._name,
            coglet=self._coglet,
            metadata=self._metadata,
        )
        try:
            self._parent.repo.create_span(span)
        except Exception:
            logger.debug("Failed to create span %s", self._name, exc_info=True)

        child_ctx = TraceContext(
            trace_id=self._parent.trace_id,
            span_id=self._span_id,
            repo=self._parent.repo,
        )
        self._token = _current_trace.set(child_ctx)
        return child_ctx

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        status = "errored" if exc_type else "completed"
        extra_meta = {}
        if exc_val:
            extra_meta["error"] = str(exc_val)[:1000]
        try:
            self._parent.repo.complete_span(
                self._span_id,
                status=status,
                metadata=extra_meta or None,
            )
        except Exception:
            logger.debug("Failed to complete span %s", self._name, exc_info=True)

        if self._token is not None:
            _current_trace.reset(self._token)


def current_trace() -> TraceContext | None:
    """Get the current trace context, if any."""
    return _current_trace.get()


def init_trace(
    repo,
    *,
    trace_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    source: str = "",
    source_ref: str | None = None,
    cogent_id: str = "",
) -> TraceContext:
    """Initialize a new trace or continue an existing one.

    - If trace_id is None, creates a new RequestTrace in the DB.
    - If trace_id is provided, continues that trace (cross-process).
    - Always creates a root span for this process.

    Returns the TraceContext and sets it as the current context.
    """
    if trace_id is None:
        trace_id = uuid4()
        try:
            repo.create_request_trace(RequestTrace(
                id=trace_id,
                cogent_id=cogent_id,
                source=source,
                source_ref=source_ref,
            ))
        except Exception:
            logger.debug("Failed to create request trace", exc_info=True)

    root_span_id = uuid4()
    ctx = TraceContext(trace_id=trace_id, span_id=root_span_id, repo=repo)

    # Create root span in DB (parent_span_id links to previous process's span)
    span = Span(
        id=root_span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        name="root",
        metadata={"source": source},
    )
    try:
        repo.create_span(span)
    except Exception:
        logger.debug("Failed to create root span", exc_info=True)

    _current_trace.set(ctx)
    return ctx
```

**Step 2: Commit**

```bash
git add src/cogos/trace/__init__.py src/cogos/trace/context.py
git commit -m "feat(trace): add TraceContext module with contextvars propagation"
```

---

### Task 5: Integrate Tracing into Executor

**Files:**
- Modify: `src/cogos/executor/handler.py`

This is the core integration. We need to:
1. Initialize trace context when executor starts
2. Wrap the LLM turn loop in spans
3. Wrap tool calls in spans

**Step 1: Initialize trace context in `handler()` function**

After line ~248 where `trace_id` is extracted from the event, add trace context initialization:

```python
# Initialize distributed trace context
from cogos.trace import init_trace
parent_span_id = None
if event.get("parent_span_id"):
    try:
        parent_span_id = UUID(event["parent_span_id"])
    except (ValueError, Exception):
        pass

trace_ctx = init_trace(
    repo,
    trace_id=trace_id,
    parent_span_id=parent_span_id,
    source=event.get("source", ""),
    source_ref=event.get("source_ref"),
    cogent_id=os.environ.get("COGENT_NAME", ""),
)
trace_id = trace_ctx.trace_id  # ensure we use the (possibly new) trace_id
```

**Step 2: Wrap `execute_process` call in a process span**

In `handler()`, wrap the `execute_process` call (~line 254):

```python
with trace_ctx.start_span(f"process:{process.name}", coglet=process.name):
    run = execute_process(process, event, run, config, repo, trace_id=trace_id)
```

**Step 3: Wrap LLM turns in spans**

In `execute_process()`, inside the `for _turn in range(config.max_turns):` loop (~line 651), wrap the bedrock call:

```python
from cogos.trace import current_trace

ctx = current_trace()
if ctx:
    span_cm = ctx.start_span(f"llm_turn:{turn_number}", metadata={"model": model_id})
    span_cm.__enter__()
```

After processing the response (after usage tracking ~line 676):

```python
if ctx and span_cm:
    span_cm.__exit__(None, None, None)
```

Note: This needs care — we enter the span before the bedrock call, and exit after processing. If there's a tool_use stop_reason, the span exits before tool processing.

Actually, a cleaner approach: wrap each bedrock converse call + its response processing in a span. The tool calls get their own spans (next step).

**Step 4: Wrap tool/capability calls in spans**

In `_setup_capability_proxies()` (~line 1060), after instantiating each capability, wrap its methods with span creation. Add a helper function:

```python
def _wrap_capability_with_tracing(instance, namespace: str):
    """Wrap capability methods to automatically create spans."""
    from cogos.trace import current_trace

    class TracingProxy:
        def __init__(self, target, ns):
            object.__setattr__(self, '_target', target)
            object.__setattr__(self, '_ns', ns)

        def __getattr__(self, name):
            attr = getattr(self._target, name)
            if not callable(attr) or name.startswith('_'):
                return attr
            ns = self._ns

            def traced_method(*args, **kwargs):
                ctx = current_trace()
                if ctx:
                    with ctx.start_span(f"tool:{ns}.{name}"):
                        return attr(*args, **kwargs)
                return attr(*args, **kwargs)
            return traced_method

    return TracingProxy(instance, namespace)
```

In `_setup_capability_proxies`, after the `instance = instance.scope(**pc.config)` line, add:

```python
instance = _wrap_capability_with_tracing(instance, ns)
```

**Step 5: Commit**

```bash
git add src/cogos/executor/handler.py
git commit -m "feat(trace): integrate span creation into executor — process, LLM turn, and tool spans"
```

---

### Task 6: Propagate Trace Context Through Channel Messages

**Files:**
- Modify: `src/cogos/capabilities/channels.py`
- Modify: `src/cogos/capabilities/scheduler.py`

**Step 1: Stamp trace context on channel messages**

In `channels.py`, in the `send()` method (~line 179), modify the ChannelMessage construction to include trace context:

```python
from cogos.trace import current_trace

ctx = current_trace()
trace_meta_dict = None
if ctx:
    trace_meta_dict = ctx.serialize()

msg = ChannelMessage(
    channel=ch.id,
    sender_process=self.process_id,
    payload=payload,
    trace_id=ctx.trace_id if ctx else None,
    trace_meta=trace_meta_dict,
)
```

**Step 2: Inherit trace from delivery in scheduler**

In `scheduler.py`, `dispatch_process()` method (~line 190), the trace_id is already inherited from deliveries. To also carry `parent_span_id`, we need to read it from the delivery's message's `trace_meta`:

After `trace_id = deliveries[0].trace_id if deliveries else None` (~line 190), add:

```python
parent_span_id = None
if deliveries and deliveries[0].message:
    try:
        msg_rows = self.repo.query(
            "SELECT trace_meta FROM cogos_channel_message WHERE id = :id",
            {"id": deliveries[0].message},
        )
        if msg_rows:
            trace_meta = self.repo._json_field(msg_rows[0], "trace_meta")
            if trace_meta and "span_id" in trace_meta:
                parent_span_id = trace_meta["span_id"]
    except Exception:
        pass
```

Then include `parent_span_id` in the `DispatchResult`.

**Step 3: Pass parent_span_id through dispatch event**

In `src/cogos/runtime/dispatch.py`, `build_dispatch_event()`, add:

```python
"parent_span_id": getattr(dispatch_result, "parent_span_id", None),
```

**Step 4: Commit**

```bash
git add src/cogos/capabilities/channels.py src/cogos/capabilities/scheduler.py src/cogos/runtime/dispatch.py
git commit -m "feat(trace): propagate trace context through channel messages and dispatch"
```

---

### Task 7: Dashboard API Endpoint

**Files:**
- Create: `src/dashboard/routers/trace_viewer.py`
- Modify: `src/dashboard/app.py`

**Step 1: Create the trace viewer API endpoint**

Create `src/dashboard/routers/trace_viewer.py`:

```python
"""Trace viewer API — returns full trace with spans and events."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.db import get_repo

router = APIRouter(tags=["trace-viewer"])


class SpanEventOut(BaseModel):
    id: str
    event: str
    message: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpanOut(BaseModel):
    id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    coglet: str | None = None
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEventOut] = Field(default_factory=list)


class TraceOut(BaseModel):
    id: str
    cogent_id: str
    source: str
    source_ref: str | None = None
    created_at: str | None = None
    spans: list[SpanOut] = Field(default_factory=list)
    summary: TraceSummary


class TraceSummary(BaseModel):
    total_duration_ms: int | None = None
    total_spans: int = 0
    error_count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0


@router.get("/trace-viewer/{trace_id}", response_model=TraceOut)
def get_trace(name: str, trace_id: str) -> TraceOut:
    repo = get_repo()
    try:
        tid = UUID(trace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid trace_id")

    trace = repo.get_request_trace(tid)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = repo.list_spans(tid)
    all_events = repo.list_span_events_for_trace(tid)

    events_by_span: dict[UUID, list] = {}
    for evt in all_events:
        events_by_span.setdefault(evt.span_id, []).append(evt)

    span_outs = []
    error_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for span in spans:
        duration_ms = None
        if span.started_at and span.ended_at:
            duration_ms = int((span.ended_at - span.started_at).total_seconds() * 1000)

        if span.status.value == "errored":
            error_count += 1

        meta = span.metadata or {}
        total_tokens_in += meta.get("tokens_in", 0)
        total_tokens_out += meta.get("tokens_out", 0)
        total_cost += meta.get("cost_usd", 0.0)

        span_events = [
            SpanEventOut(
                id=str(e.id),
                event=e.event,
                message=e.message,
                timestamp=e.timestamp.isoformat() if e.timestamp else None,
                metadata=e.metadata,
            )
            for e in events_by_span.get(span.id, [])
        ]

        span_outs.append(SpanOut(
            id=str(span.id),
            trace_id=str(span.trace_id),
            parent_span_id=str(span.parent_span_id) if span.parent_span_id else None,
            name=span.name,
            coglet=span.coglet,
            status=span.status.value,
            started_at=span.started_at.isoformat() if span.started_at else None,
            ended_at=span.ended_at.isoformat() if span.ended_at else None,
            duration_ms=duration_ms,
            metadata=meta,
            events=span_events,
        ))

    total_duration_ms = None
    if spans:
        earliest = min((s.started_at for s in spans if s.started_at), default=None)
        latest = max((s.ended_at for s in spans if s.ended_at), default=None)
        if earliest and latest:
            total_duration_ms = int((latest - earliest).total_seconds() * 1000)

    return TraceOut(
        id=str(trace.id),
        cogent_id=trace.cogent_id,
        source=trace.source,
        source_ref=trace.source_ref,
        created_at=trace.created_at.isoformat() if trace.created_at else None,
        spans=span_outs,
        summary=TraceSummary(
            total_duration_ms=total_duration_ms,
            total_spans=len(spans),
            error_count=error_count,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_cost_usd=total_cost,
        ),
    )
```

**Step 2: Register router in app.py**

In `src/dashboard/app.py`, import and include the router:

```python
from dashboard.routers import trace_viewer
app.include_router(trace_viewer.router, prefix=f"{prefix}")
```

**Step 3: Commit**

```bash
git add src/dashboard/routers/trace_viewer.py src/dashboard/app.py
git commit -m "feat(trace): add GET /trace-viewer/{trace_id} API endpoint"
```

---

### Task 8: Dashboard Frontend — Trace Viewer Page (Timeline View)

**Files:**
- Create: `dashboard/frontend/src/components/trace/TraceViewerPanel.tsx`
- Create: `dashboard/frontend/src/components/trace/TimelineView.tsx`
- Create: `dashboard/frontend/src/components/trace/SpanDetail.tsx`
- Modify: `dashboard/frontend/src/app/page.tsx` — add trace viewer tab/route
- Modify: `dashboard/frontend/src/lib/api.ts` — add API call

**Step 1: Add API call**

In `dashboard/frontend/src/lib/api.ts`, add:

```typescript
async getTraceViewer(cogentName: string, traceId: string) {
    const res = await fetch(`/api/cogents/${cogentName}/trace-viewer/${traceId}`);
    if (!res.ok) throw new Error(`Failed to fetch trace: ${res.status}`);
    return res.json();
},
```

**Step 2: Create SpanDetail component**

`dashboard/frontend/src/components/trace/SpanDetail.tsx`:

A side panel that shows span metadata (tokens, cost, model, error), events/logs, and timing info when a span is clicked.

**Step 3: Create TimelineView component**

`dashboard/frontend/src/components/trace/TimelineView.tsx`:

Horizontal waterfall chart using absolute-positioned divs:
- Calculate total trace duration for scale
- For each span, compute left offset (start relative to trace start) and width (duration)
- Indent by depth (count parent chain)
- Color-code: blue (process spans), green (llm_turn), orange (tool:*), red (errored)
- onClick handler to select a span for detail view

**Step 4: Create TraceViewerPanel component**

`dashboard/frontend/src/components/trace/TraceViewerPanel.tsx`:

Main panel with:
- Text input for trace_id (pre-filled from URL hash if present)
- Summary bar (duration, cost, tokens, error count)
- Toggle between Timeline and Graph view
- Renders TimelineView (default) or GraphView
- Side panel for SpanDetail when a span is selected

**Step 5: Wire into page routing**

In `dashboard/frontend/src/app/page.tsx`, add `trace-viewer` to the tab routing. The hash format: `#trace-viewer` or `#trace-viewer:TRACE_ID`.

**Step 6: Commit**

```bash
git add dashboard/frontend/src/components/trace/ dashboard/frontend/src/lib/api.ts dashboard/frontend/src/app/page.tsx
git commit -m "feat(trace): add trace viewer timeline view in dashboard frontend"
```

---

### Task 9: Dashboard Frontend — Graph View

**Files:**
- Modify: `dashboard/frontend/package.json` — add dagre, reactflow dependencies
- Create: `dashboard/frontend/src/components/trace/GraphView.tsx`

**Step 1: Install dependencies**

```bash
cd dashboard/frontend && npm install @xyflow/react dagre @types/dagre
```

**Step 2: Create GraphView component**

`dashboard/frontend/src/components/trace/GraphView.tsx`:

DAG layout using dagre for positioning and @xyflow/react for rendering:
- Convert spans to nodes (label = span name + duration)
- Convert parent_span_id relationships to edges
- Failed nodes highlighted with red border
- Click node to select for detail view

**Step 3: Wire into TraceViewerPanel toggle**

The TraceViewerPanel already has a timeline/graph toggle — this just renders GraphView when graph mode is active.

**Step 4: Commit**

```bash
git add dashboard/frontend/package.json dashboard/frontend/package-lock.json dashboard/frontend/src/components/trace/GraphView.tsx dashboard/frontend/src/components/trace/TraceViewerPanel.tsx
git commit -m "feat(trace): add DAG graph view to trace viewer"
```

---

### Task 10: Discord Trace Link Reply

**Files:**
- Modify: `src/cogos/executor/handler.py`

**Step 1: Add trace link reply after executor completion**

In `handler()`, after the successful completion block (~line 308, after `logger.info(f"Run {run_id} completed in {duration_ms}ms")`), add:

```python
# Reply to originating Discord message with trace link
_reply_trace_link(repo, process, event, trace_ctx.trace_id)
```

Add the helper function:

```python
def _reply_trace_link(repo, process, event_data: dict, trace_id: UUID) -> None:
    """Reply to the originating Discord message with a trace viewer link."""
    dashboard_url = os.environ.get("DASHBOARD_URL", "")
    if not dashboard_url:
        return

    source_ref = event_data.get("source_ref")
    if not source_ref:
        return

    # Only reply for Discord-originated requests
    payload = event_data.get("payload", {})
    if not isinstance(payload, dict):
        return

    discord_channel_id = payload.get("discord_channel_id")
    discord_message_id = payload.get("discord_message_id")
    if not discord_channel_id or not discord_message_id:
        return

    trace_link = f"{dashboard_url}/#trace-viewer:{trace_id}"
    try:
        # Use the Discord capability to reply
        # Find discord capability for any process
        from cogos.capabilities.discord_cap import DiscordCapability
        discord_cap = DiscordCapability(repo, process.id)
        discord_cap.reply(
            channel_id=discord_channel_id,
            message_id=discord_message_id,
            content=f"🔍 Trace: {trace_link}",
        )
    except Exception:
        logger.debug("Failed to reply with trace link", exc_info=True)
```

Note: The exact Discord reply mechanism depends on how the Discord capability exposes reply functionality. Check `src/cogos/capabilities/discord_cap.py` or equivalent and adapt. If no direct reply is available, write to the Discord output channel instead.

**Step 2: Pass source info through dispatch event**

In `src/cogos/runtime/dispatch.py`, `build_dispatch_event()`, ensure `source` and `source_ref` are included:

```python
"source": "channel",
"source_ref": ...,  # derive from the channel message's discord metadata
```

**Step 3: Commit**

```bash
git add src/cogos/executor/handler.py src/cogos/runtime/dispatch.py
git commit -m "feat(trace): reply to Discord messages with trace viewer link"
```

---

### Task 11: Local Repository Support

**Files:**
- Modify: `src/cogos/db/local_repository.py`

**Step 1: Add trace/span storage to LocalRepository**

The local repository uses JSON files for storage. Add in-memory dicts for request traces, spans, and span events, and implement the same methods as the RDS repository:

- `create_request_trace`, `get_request_trace`
- `create_span`, `complete_span`, `list_spans`
- `create_span_event`, `list_span_events`, `list_span_events_for_trace`

Use the same pattern as existing local repository methods (in-memory dicts with JSON serialization).

**Step 2: Commit**

```bash
git add src/cogos/db/local_repository.py
git commit -m "feat(trace): add trace/span support to LocalRepository"
```

---

### Task 12: End-to-End Verification

**Step 1: Run existing tests to verify nothing is broken**

```bash
pytest tests/ -x -q
```

Expected: All existing tests pass.

**Step 2: Manual local test**

Run a local cogent process and verify:
- Trace and spans are created
- Timeline shows in dashboard
- Channel message propagation carries trace context

**Step 3: Run lint**

```bash
ruff check src/cogos/trace/ src/dashboard/routers/trace_viewer.py
```

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(trace): address test/lint issues from end-to-end verification"
```
