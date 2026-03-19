# End-to-End Trace System Design

## Goal

Every user request—regardless of entry point (Discord, API, CLI, cron)—is assigned a globally unique trace ID that propagates through all downstream processes, with a trace viewer UI accessible via link.

## Data Model

Three new tables in RDS (Aurora):

```sql
CREATE TABLE traces (
    id              UUID PRIMARY KEY,
    cogent_id       VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,  -- "discord", "api", "cli", "cron"
    source_ref      VARCHAR,           -- e.g., discord channel_id:message_id
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE spans (
    id              UUID PRIMARY KEY,
    trace_id        UUID NOT NULL REFERENCES traces(id),
    parent_span_id  UUID REFERENCES spans(id),
    name            VARCHAR NOT NULL,  -- e.g., "process:supervisor", "llm_turn:3", "tool:file.read"
    coglet          VARCHAR,           -- process name
    status          VARCHAR NOT NULL DEFAULT 'running',  -- "running", "completed", "errored"
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMP,
    metadata        JSONB              -- model, tokens_in, tokens_out, cost_usd, error, stop_reason, etc.
);

CREATE TABLE span_events (
    id              UUID PRIMARY KEY,
    span_id         UUID NOT NULL REFERENCES spans(id),
    event           VARCHAR NOT NULL,  -- "log", "error", "metric"
    message         TEXT,
    timestamp       TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata        JSONB
);
```

Indexes on `spans(trace_id)`, `spans(parent_span_id)`, `span_events(span_id)`.

## Trace Context & Propagation

### Within a process (contextvars)

```python
# src/cogos/trace/context.py

_current_trace: ContextVar[TraceContext | None]

@dataclass
class TraceContext:
    trace_id: UUID
    span_id: UUID
    repo: Repository

    def start_span(name, coglet=None, metadata=None) -> SpanContext
    def log(event, message, metadata=None)

class SpanContext:  # context manager
    __enter__  → sets _current_trace to new child context, writes span row
    __exit__   → records end time + status, restores parent context

def current_trace() -> TraceContext | None
def init_trace(repo, trace_id=None, parent_span_id=None) -> TraceContext
```

### Across process boundaries

Context is serialized as `trace_id` + `span_id` at every process boundary:

- **Dispatcher → Executor Lambda**: added to invoke payload (extends existing `trace_id` pattern)
- **Process spawning** (via `procs` capability): added to spawn payload
- **Channel messages**: `trace_id` and `parent_span_id` columns added to `ChannelMessage` model. Written automatically by channels capability from current context. Dispatcher inherits trace from message when creating deliveries.

On the receiving side, `init_trace(repo, trace_id=..., parent_span_id=...)` restores the context.

### Trace origin

- If a channel message carries a `trace_id`, the dispatcher continues that trace.
- If not (external Discord message, cron tick, API call), the dispatcher creates a new trace.

## Span Granularity (Medium)

Spans are created at three levels:

1. **Process execution**: `with trace.start_span(f"process:{name}")` — wraps each coglet run
2. **LLM turns**: `with trace.start_span(f"llm_turn:{n}")` — wraps each LLM request/response cycle
3. **Tool/capability calls**: `with trace.start_span(f"tool:{capability}.{method}")` — wraps each capability method invocation

Capability span wrapping happens at the proxy layer (`_setup_capability_proxies`), so individual capability implementations are unaware of tracing.

## Trace Viewer UI

New page in the Next.js dashboard at `/traces/[traceId]`.

### API

`GET /api/traces/{trace_id}` — returns trace with all spans and events nested by parent-child.

### Timeline view (default)

- Horizontal waterfall chart — each span is a bar, width proportional to duration
- Indented by parent-child depth
- Color-coded: blue (process), green (LLM turn), orange (tool call), red (error)
- Click span to expand detail panel: metadata (tokens, cost, model), events/logs, errors
- Top summary bar: total duration, total cost, total tokens, error count

### Graph view (toggle)

- DAG layout using parent-child relationships (dagre + react-flow)
- Nodes labeled with span name + duration
- Edges show flow direction
- Failed nodes highlighted red
- Click node for same detail panel

## Discord Integration

After executor completion, if `source == "discord"` and `source_ref` is set, reply to the original Discord message with:

```
🔍 Trace: {DASHBOARD_URL}/traces/{trace_id}
```

`DASHBOARD_URL` is configured via environment variable.

## Files to Modify

| Area | Files | Change |
|------|-------|--------|
| Models | `src/cogos/db/models/` | Add `Trace`, `Span`, `SpanEvent` models |
| Models | `src/cogos/db/models/` | Add `trace_id`, `parent_span_id` to `ChannelMessage` |
| Repository | `src/cogos/db/repository.py` | CRUD for traces/spans/events, schema migration |
| Trace module | `src/cogos/trace/` (new) | `context.py`, `__init__.py` — TraceContext + contextvars API |
| Dispatcher | `src/cogtainer/lambdas/dispatcher/handler.py` | Create trace at dispatch, pass trace_id + span_id in payload, inherit trace from channel messages |
| Executor | `src/cogos/executor/handler.py` | Restore trace context, wrap process execution + LLM turns in spans |
| Sandbox | `src/cogos/sandbox/executor.py` | Wrap capability proxy calls in spans |
| Backend API | `src/dashboard/backend/` | Add `GET /api/traces/{trace_id}` |
| Frontend | `src/dashboard/frontend/` | Add `/traces/[traceId]` page with timeline + graph views |
| Discord | Executor completion path | Reply with trace link |

## Not Modified

Individual capability implementations, cog configs, image specs. Tracing is transparent to capabilities via proxy wrapping.
