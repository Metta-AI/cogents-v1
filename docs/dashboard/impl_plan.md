# Cogent Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time operational dashboard for monitoring cogent AI agents, ported from metta-ai/cogents with modern React + FastAPI stack.

**Architecture:** Next.js 16 + React 19 frontend with Tailwind CSS, FastAPI backend with asyncpg, WebSocket real-time via PostgreSQL LISTEN/NOTIFY. Each cogent runs on its own domain.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Pydantic v2, Next.js 16, React 19, TypeScript, Tailwind CSS, Chart.js, Vitest

---

## Task 1: Backend project scaffold

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/app.py`
- Create: `src/dashboard/config.py`
- Modify: `pyproject.toml` (add dashboard package)

**Step 1: Add dashboard to pyproject.toml packages**

In `pyproject.toml`, add `"src/dashboard"` to the `tool.hatch.build.targets.wheel.packages` list and `"src/dashboard"` to the `tool.pyright.include` list. Also add `"dashboard"` to the `tool.ruff.lint.isort.known-first-party` list.

**Step 2: Create config module**

Create `src/dashboard/__init__.py` (empty) and `src/dashboard/config.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings


class DashboardSettings(BaseSettings):
    database_url: str = "postgresql://cogent:cogent_dev@localhost:5432/cogent"
    host: str = "0.0.0.0"
    port: int = 8100
    cors_origins: str = "*"
    cogent_name: str = ""

    model_config = {"env_prefix": "DASHBOARD_"}


settings = DashboardSettings()
```

Note: add `pydantic-settings>=2.0` to dependencies in pyproject.toml.

**Step 3: Create FastAPI app factory**

Create `src/dashboard/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Cogent Dashboard API", version="0.1.0")

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()
```

**Step 4: Write smoke test**

Create `tests/dashboard/__init__.py` (empty) and `tests/dashboard/test_app.py`:

```python
from fastapi.testclient import TestClient

from dashboard.app import create_app


def test_healthz():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
```

**Step 5: Run test**

Run: `cd /Users/daveey/code/cogents/cogents.3 && uv pip install -e ".[dev]" && pytest tests/dashboard/test_app.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/dashboard/ tests/dashboard/ pyproject.toml
git commit -m "feat(dashboard): scaffold FastAPI backend with health endpoint"
```

---

## Task 2: Database module with asyncpg pool

**Files:**
- Create: `src/dashboard/database.py`
- Create: `tests/dashboard/test_database.py`

**Step 1: Create database module**

Create `src/dashboard/database.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from dashboard.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_all(sql: str, *args: Any) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetch_one(sql: str, *args: Any) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def execute(sql: str, *args: Any) -> str:
    pool = await get_pool()
    return await pool.execute(sql, *args)
```

**Step 2: Wire pool lifecycle into FastAPI app**

In `src/dashboard/app.py`, add lifespan:

```python
from contextlib import asynccontextmanager

from dashboard.database import close_pool, get_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()
```

And pass `lifespan=lifespan` to `FastAPI(...)`.

**Step 3: Write test with real PostgreSQL**

Create `tests/dashboard/test_database.py`:

```python
import os
import pytest
import asyncpg

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://cogent:cogent_dev@localhost:5432/cogent_test")


@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


async def test_pool_connects(db_pool):
    row = await db_pool.fetchrow("SELECT 1 AS val")
    assert row["val"] == 1
```

**Step 4: Run test**

Run: `pytest tests/dashboard/test_database.py -v`
Expected: PASS (requires local PostgreSQL running)

**Step 5: Commit**

```bash
git add src/dashboard/database.py src/dashboard/app.py tests/dashboard/test_database.py
git commit -m "feat(dashboard): add asyncpg database pool with lifecycle management"
```

---

## Task 3: Pydantic response models

**Files:**
- Create: `src/dashboard/models.py`
- Create: `tests/dashboard/test_models.py`

**Step 1: Create all Pydantic models in a single file**

Create `src/dashboard/models.py` with all response models. These match the JSON shapes from the original metta-ai/cogents Lambda handler, with "skill" renamed to "program":

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StatusResponse(BaseModel):
    cogent_id: str
    active_sessions: int = 0
    total_conversations: int = 0
    trigger_count: int = 0
    unresolved_alerts: int = 0
    recent_events: int = 0


class Execution(BaseModel):
    id: str
    program_name: str
    conversation_id: str | None = None
    status: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float = 0
    error: str | None = None


class Program(BaseModel):
    name: str
    type: str = "markdown"
    description: str = ""
    complexity: str | None = None
    model: str | None = None
    trigger_count: int = 0
    group: str = ""
    runs: int = 0
    ok: int = 0
    fail: int = 0
    total_cost: float = 0
    last_run: str | None = None


class ProgramsResponse(BaseModel):
    cogent_id: str
    count: int
    programs: list[Program]


class ExecutionsResponse(BaseModel):
    cogent_id: str
    count: int
    executions: list[Execution]


class Session(BaseModel):
    id: str
    context_key: str | None = None
    status: str | None = None
    cli_session_id: str | None = None
    started_at: str | None = None
    last_active: str | None = None
    metadata: dict[str, Any] | None = None
    runs: int = 0
    ok: int = 0
    fail: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_cost: float = 0


class SessionsResponse(BaseModel):
    cogent_id: str
    count: int
    sessions: list[Session]


class Event(BaseModel):
    id: int | str
    event_type: str | None = None
    source: str | None = None
    payload: Any = None
    parent_event_id: int | None = None
    created_at: str | None = None


class EventsResponse(BaseModel):
    cogent_id: str
    count: int
    events: list[Event]


class EventTreeResponse(BaseModel):
    root_event_id: int | str | None = None
    count: int
    events: list[Event]


class Trigger(BaseModel):
    id: str
    name: str = ""
    trigger_type: str | None = None
    event_pattern: str | None = None
    cron_expression: str | None = None
    skill_name: str | None = None
    priority: int | None = None
    enabled: bool = True
    created_at: str | None = None
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0


class TriggersResponse(BaseModel):
    cogent_id: str
    count: int
    triggers: list[Trigger]


class ToggleRequest(BaseModel):
    ids: list[str]
    enabled: bool


class ToggleResponse(BaseModel):
    updated: int
    enabled: bool


class MemoryItem(BaseModel):
    id: str
    scope: str | None = None
    type: str | None = None
    name: str = ""
    group: str = ""
    content: str = ""
    provenance: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryResponse(BaseModel):
    cogent_id: str
    count: int
    memory: list[MemoryItem]


class Task(BaseModel):
    id: str
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    source: str | None = None
    external_id: str | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class TasksResponse(BaseModel):
    cogent_id: str
    count: int
    tasks: list[Task]


class Channel(BaseModel):
    name: str
    type: str | None = None
    enabled: bool = True
    created_at: str | None = None


class ChannelsResponse(BaseModel):
    cogent_id: str
    count: int
    channels: list[Channel]


class Alert(BaseModel):
    id: str
    severity: str | None = None
    alert_type: str | None = None
    source: str | None = None
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


class AlertsResponse(BaseModel):
    cogent_id: str
    count: int
    alerts: list[Alert]


class ResourcesResponse(BaseModel):
    cogent_id: str
    active_sessions: int = 0
    conversations: list[dict[str, Any]] = []
```

**Step 2: Write model tests**

Create `tests/dashboard/test_models.py`:

```python
from dashboard.models import StatusResponse, Program, Event, Trigger


def test_status_response_defaults():
    s = StatusResponse(cogent_id="test")
    assert s.active_sessions == 0
    assert s.cogent_id == "test"


def test_program_from_dict():
    p = Program(name="code-review", runs=10, ok=8, fail=2, total_cost=1.5)
    assert p.name == "code-review"
    assert p.ok == 8


def test_event_accepts_int_or_str_id():
    e1 = Event(id=42, event_type="test")
    e2 = Event(id="abc-123", event_type="test")
    assert e1.id == 42
    assert e2.id == "abc-123"


def test_trigger_defaults():
    t = Trigger(id="abc", name="github.push:code-review")
    assert t.enabled is True
    assert t.fired_1h == 0
```

**Step 3: Run tests**

Run: `pytest tests/dashboard/test_models.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/dashboard/models.py tests/dashboard/test_models.py
git commit -m "feat(dashboard): add Pydantic response models for all API endpoints"
```

---

## Task 4: Database schema (SQL migrations)

**Files:**
- Create: `src/dashboard/schema.sql`
- Create: `tests/dashboard/test_schema.py`

**Step 1: Create schema file**

Create `src/dashboard/schema.sql` with all tables needed by the dashboard. These match the tables queried by the original metta-ai/cogents dashboard:

```sql
-- Cogent dashboard database schema
-- Tables: conversations, events, executions, triggers, memory, tasks, alerts, channels, skills, traces

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    context_key TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    cli_session_id TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    last_active TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_cogent ON conversations(cogent_id);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    cogent_id TEXT NOT NULL,
    event_type TEXT,
    source TEXT,
    payload JSONB DEFAULT '{}'::jsonb,
    parent_event_id BIGINT REFERENCES events(id),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_cogent ON events(cogent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(cogent_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_event_id);

CREATE TABLE IF NOT EXISTS executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    conversation_id UUID REFERENCES conversations(id),
    trigger_id UUID,
    status TEXT DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    duration_ms INT,
    tokens_input INT DEFAULT 0,
    tokens_output INT DEFAULT 0,
    cost_usd NUMERIC(12, 6) DEFAULT 0,
    events_emitted JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_executions_cogent ON executions(cogent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_skill ON executions(cogent_id, skill_name);
CREATE INDEX IF NOT EXISTS idx_executions_conv ON executions(conversation_id);

CREATE TABLE IF NOT EXISTS triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    trigger_type TEXT,
    event_pattern TEXT,
    cron_expression TEXT,
    skill_name TEXT,
    priority INT DEFAULT 100,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_triggers_cogent ON triggers(cogent_id);

CREATE TABLE IF NOT EXISTS memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    scope TEXT DEFAULT 'agent',
    type TEXT DEFAULT 'text',
    name TEXT,
    content TEXT,
    provenance JSONB,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_cogent ON memory(cogent_id, name);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority INT DEFAULT 100,
    source TEXT,
    external_id TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_cogent ON tasks(cogent_id, status);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    severity TEXT DEFAULT 'warning',
    alert_type TEXT,
    source TEXT,
    message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alerts_cogent ON alerts(cogent_id);

CREATE TABLE IF NOT EXISTS channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_channels_cogent ON channels(cogent_id);

CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    skill_type TEXT DEFAULT 'markdown',
    description TEXT,
    content TEXT,
    sla JSONB,
    triggers JSONB,
    resources JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_skills_cogent ON skills(cogent_id, name);

CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID REFERENCES executions(id),
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_exec ON traces(execution_id);
```

**Step 2: Add schema loader helper to database.py**

Add to `src/dashboard/database.py`:

```python
from pathlib import Path

async def apply_schema() -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    pool = await get_pool()
    await pool.execute(sql)
```

**Step 3: Write schema test**

Create `tests/dashboard/test_schema.py`:

```python
import os
import pytest
import asyncpg

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://cogent:cogent_dev@localhost:5432/cogent_test")


@pytest.fixture
async def db():
    conn = await asyncpg.connect(TEST_DB_URL)
    # Apply schema
    from pathlib import Path
    schema = (Path(__file__).parent.parent.parent / "src" / "dashboard" / "schema.sql").read_text()
    await conn.execute(schema)
    yield conn
    # Clean up tables
    for table in ["traces", "executions", "events", "conversations", "triggers", "memory", "tasks", "alerts", "channels", "skills"]:
        await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    await conn.close()


async def test_schema_creates_all_tables(db):
    rows = await db.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
    )
    names = {r["table_name"] for r in rows}
    expected = {"conversations", "events", "executions", "triggers", "memory", "tasks", "alerts", "channels", "skills", "traces"}
    assert expected.issubset(names)
```

**Step 4: Run test**

Run: `pytest tests/dashboard/test_schema.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/dashboard/schema.sql src/dashboard/database.py tests/dashboard/test_schema.py
git commit -m "feat(dashboard): add database schema for all dashboard tables"
```

---

## Task 5: REST API routers — status, programs, sessions

**Files:**
- Create: `src/dashboard/routers/__init__.py`
- Create: `src/dashboard/routers/status.py`
- Create: `src/dashboard/routers/programs.py`
- Create: `src/dashboard/routers/sessions.py`
- Modify: `src/dashboard/app.py` (register routers)
- Create: `tests/dashboard/test_routers_core.py`

**Step 1: Create status router**

Create `src/dashboard/routers/__init__.py` (empty) and `src/dashboard/routers/status.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Query

from dashboard.database import fetch_one
from dashboard.models import StatusResponse

router = APIRouter()

_RANGE_TO_INTERVAL = {
    "1m": "1 minute",
    "10m": "10 minutes",
    "1h": "1 hour",
    "24h": "24 hours",
    "1w": "7 days",
}


def _interval(range_str: str) -> str:
    return _RANGE_TO_INTERVAL.get(range_str, "1 hour")


@router.get("/status", response_model=StatusResponse)
async def get_status(name: str, range: str = Query("1h", alias="range")):
    interval = _interval(range)
    row = await fetch_one(
        "SELECT "
        "(SELECT count(*) FROM conversations WHERE cogent_id = $1 AND status = 'active') AS active_sessions, "
        "(SELECT count(*) FROM conversations WHERE cogent_id = $1) AS total_conversations, "
        "(SELECT count(*) FROM triggers WHERE cogent_id = $1 AND enabled = true) AS trigger_count, "
        "(SELECT count(*) FROM alerts WHERE cogent_id = $1 AND resolved_at IS NULL) AS unresolved_alerts, "
        f"(SELECT count(*) FROM events WHERE cogent_id = $1 AND created_at > now() - interval '{interval}') AS recent_events",
        name,
    )
    return StatusResponse(cogent_id=name, **(row or {}))
```

**Step 2: Create programs router**

Create `src/dashboard/routers/programs.py`:

```python
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from dashboard.database import fetch_all
from dashboard.models import ExecutionsResponse, Program, ProgramsResponse

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    return val


@router.get("/programs", response_model=ProgramsResponse)
async def get_programs(name: str):
    # Execution stats per skill
    stats_rows = await fetch_all(
        "SELECT skill_name, count(*) as runs, "
        "count(*) FILTER (WHERE status = 'completed') as ok, "
        "count(*) FILTER (WHERE status IN ('failed', 'timeout')) as fail, "
        "sum(cost_usd)::float as total_cost, "
        "max(started_at)::text as last_run "
        "FROM executions WHERE cogent_id = $1 GROUP BY skill_name",
        name,
    )
    stats = {r["skill_name"]: r for r in stats_rows}

    # Skill definitions
    skill_rows = await fetch_all(
        "SELECT name, skill_type, description, sla, triggers FROM skills WHERE cogent_id = $1 ORDER BY name",
        name,
    )

    programs = []
    for s in skill_rows:
        sname = s["name"]
        sla = _try_parse_json(s.get("sla")) or {}
        triggers = _try_parse_json(s.get("triggers")) or []
        st = stats.get(sname, {})
        programs.append(
            Program(
                name=sname,
                type=s.get("skill_type", "markdown"),
                description=s.get("description", ""),
                complexity=sla.get("complexity"),
                model=sla.get("model"),
                trigger_count=len(triggers) if isinstance(triggers, list) else 0,
                group=sname.rsplit(".", 1)[0] if "." in sname else "",
                runs=st.get("runs", 0),
                ok=st.get("ok", 0),
                fail=st.get("fail", 0),
                total_cost=st.get("total_cost") or 0,
                last_run=st.get("last_run"),
            )
        )
    return ProgramsResponse(cogent_id=name, count=len(programs), programs=programs)


@router.get("/programs/{program_name}/executions", response_model=ExecutionsResponse)
async def get_program_executions(name: str, program_name: str, limit: int = Query(50)):
    rows = await fetch_all(
        "SELECT id::text, skill_name, conversation_id::text, status, "
        "started_at::text, completed_at::text, duration_ms, "
        "tokens_input, tokens_output, cost_usd::float, error "
        "FROM executions WHERE cogent_id = $1 AND skill_name = $2 "
        "ORDER BY started_at DESC NULLS LAST LIMIT $3",
        name,
        program_name,
        limit,
    )
    execs = [
        {
            "id": r["id"],
            "program_name": r["skill_name"],
            "conversation_id": r["conversation_id"],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "duration_ms": r["duration_ms"],
            "tokens_input": r["tokens_input"],
            "tokens_output": r["tokens_output"],
            "cost_usd": r["cost_usd"] or 0,
            "error": r["error"],
        }
        for r in rows
    ]
    return ExecutionsResponse(cogent_id=name, count=len(execs), executions=execs)
```

**Step 3: Create sessions router**

Create `src/dashboard/routers/sessions.py`:

```python
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from dashboard.database import fetch_all
from dashboard.models import SessionsResponse

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    return val


@router.get("/sessions", response_model=SessionsResponse)
async def get_sessions(name: str):
    rows = await fetch_all(
        "SELECT id::text, context_key, status, cli_session_id, "
        "started_at::text, last_active::text, metadata "
        "FROM conversations WHERE cogent_id = $1 ORDER BY last_active DESC NULLS LAST",
        name,
    )
    stat_rows = await fetch_all(
        "SELECT conversation_id::text, count(*) as runs, "
        "count(*) FILTER (WHERE status = 'completed') as ok, "
        "count(*) FILTER (WHERE status IN ('failed', 'timeout')) as fail, "
        "coalesce(sum(tokens_input), 0)::int as tokens_in, "
        "coalesce(sum(tokens_output), 0)::int as tokens_out, "
        "coalesce(sum(cost_usd), 0)::float as total_cost "
        "FROM executions WHERE cogent_id = $1 AND conversation_id IS NOT NULL "
        "GROUP BY conversation_id",
        name,
    )
    stats = {r["conversation_id"]: r for r in stat_rows}

    sessions = []
    for r in rows:
        st = stats.get(r["id"], {})
        sessions.append(
            {
                "id": r["id"],
                "context_key": r["context_key"],
                "status": r["status"],
                "cli_session_id": r["cli_session_id"],
                "started_at": r["started_at"],
                "last_active": r["last_active"],
                "metadata": _try_parse_json(r.get("metadata")),
                "runs": st.get("runs", 0),
                "ok": st.get("ok", 0),
                "fail": st.get("fail", 0),
                "tokens_in": st.get("tokens_in", 0),
                "tokens_out": st.get("tokens_out", 0),
                "total_cost": st.get("total_cost", 0),
            }
        )
    return SessionsResponse(cogent_id=name, count=len(sessions), sessions=sessions)
```

**Step 4: Register routers in app.py**

In `src/dashboard/app.py`, import and include the routers:

```python
from dashboard.routers import status, programs, sessions

# Inside create_app(), after CORS middleware:
app.include_router(status.router, prefix="/api/cogents/{name}")
app.include_router(programs.router, prefix="/api/cogents/{name}")
app.include_router(sessions.router, prefix="/api/cogents/{name}")
```

**Step 5: Write router tests**

Create `tests/dashboard/test_routers_core.py` that tests the three routers against a real database with seeded data. Use a fixture that applies the schema, inserts test data, and cleans up.

**Step 6: Run tests**

Run: `pytest tests/dashboard/ -v`
Expected: all PASS

**Step 7: Commit**

```bash
git add src/dashboard/routers/ src/dashboard/app.py tests/dashboard/test_routers_core.py
git commit -m "feat(dashboard): add status, programs, sessions API routers"
```

---

## Task 6: REST API routers — events, triggers, memory

**Files:**
- Create: `src/dashboard/routers/events.py`
- Create: `src/dashboard/routers/triggers.py`
- Create: `src/dashboard/routers/memory.py`
- Modify: `src/dashboard/app.py`
- Create: `tests/dashboard/test_routers_events.py`

**Step 1: Create events router**

Port the events and event tree queries from the original. The event tree uses recursive CTEs to walk parent→root then root→descendants.

**Step 2: Create triggers router**

Port triggers with the fired_1m/5m/1h/24h subquery stats. Include POST toggle endpoint.

**Step 3: Create memory router**

Port memory browser with group derivation from name prefix.

**Step 4: Register routers, write tests, run, commit**

```bash
git commit -m "feat(dashboard): add events, triggers, memory API routers"
```

---

## Task 7: REST API routers — tasks, channels, alerts, resources

**Files:**
- Create: `src/dashboard/routers/tasks.py`
- Create: `src/dashboard/routers/channels.py`
- Create: `src/dashboard/routers/alerts.py`
- Create: `src/dashboard/routers/resources.py`
- Modify: `src/dashboard/app.py`

**Step 1-4: Create remaining routers, register, test, commit**

```bash
git commit -m "feat(dashboard): add tasks, channels, alerts, resources API routers"
```

---

## Task 8: WebSocket manager

**Files:**
- Create: `src/dashboard/ws.py`
- Modify: `src/dashboard/app.py`
- Create: `tests/dashboard/test_ws.py`

**Step 1: Create WebSocket manager**

Create `src/dashboard/ws.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # cogent_name -> [ws]

    async def connect(self, cogent_name: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(cogent_name, []).append(ws)

    def disconnect(self, cogent_name: str, ws: WebSocket):
        conns = self._connections.get(cogent_name, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, cogent_name: str, message: dict):
        payload = json.dumps(message, default=str)
        dead = []
        for ws in self._connections.get(cogent_name, []):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(cogent_name, ws)


manager = ConnectionManager()
```

**Step 2: Add WebSocket endpoint to app.py**

```python
from fastapi import WebSocket, WebSocketDisconnect
from dashboard.ws import manager

@app.websocket("/ws/cogents/{name}")
async def ws_endpoint(ws: WebSocket, name: str):
    await manager.connect(name, ws)
    try:
        while True:
            await ws.receive_text()  # Keep alive; client can send pings
    except WebSocketDisconnect:
        manager.disconnect(name, ws)
```

**Step 3: Add PostgreSQL LISTEN/NOTIFY listener**

In `src/dashboard/database.py`, add a background task that listens for notifications and broadcasts to WebSocket clients:

```python
async def start_listener(cogent_name: str):
    """Listen for PostgreSQL NOTIFY and broadcast to WebSocket clients."""
    from dashboard.ws import manager

    pool = await get_pool()
    conn = await pool.acquire()
    try:
        await conn.add_listener(f"cogent_{cogent_name.replace('.', '_')}_events",
            lambda conn, pid, channel, payload: asyncio.create_task(
                manager.broadcast(cogent_name, json.loads(payload))
            ))
        # Keep connection alive
        while True:
            await asyncio.sleep(60)
    finally:
        pool.release(conn)
```

**Step 4: Write tests, run, commit**

```bash
git commit -m "feat(dashboard): add WebSocket manager with pg LISTEN/NOTIFY"
```

---

## Task 9: Frontend scaffold — Next.js + Tailwind

**Files:**
- Create: `dashboard/frontend/package.json`
- Create: `dashboard/frontend/next.config.ts`
- Create: `dashboard/frontend/tsconfig.json`
- Create: `dashboard/frontend/vitest.config.ts`
- Create: `dashboard/frontend/src/app/layout.tsx`
- Create: `dashboard/frontend/src/app/page.tsx`
- Create: `dashboard/frontend/src/app/globals.css`

**Step 1: Create package.json**

```json
{
  "name": "@cogent/dashboard",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "next dev --webpack -p 5174",
    "build": "next build",
    "start": "next start -p 5174",
    "type-check": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "16.1.6",
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "@testing-library/react": "^16.3.0",
    "@types/node": "^24.3.0",
    "@types/react": "^19.2.13",
    "@types/react-dom": "^19.1.0",
    "eslint": "^9.32.0",
    "eslint-config-next": "16.1.6",
    "jsdom": "^27.0.0",
    "tailwindcss": "^4.0",
    "@tailwindcss/postcss": "^4.0",
    "typescript": "^5.2.2",
    "vitest": "^3.2.4"
  }
}
```

**Step 2: Create next.config.ts with API proxy**

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8100/api/:path*" },
      { source: "/ws/:path*", destination: "http://localhost:8100/ws/:path*" },
    ];
  },
};

export default nextConfig;
```

**Step 3: Create globals.css with dark theme**

Port the CSS variables from the original SPA:

```css
@import "tailwindcss";

:root {
  --bg-deep: #06080c;
  --bg-base: #0c1017;
  --bg-surface: #131920;
  --bg-elevated: #1a2230;
  --bg-hover: #1e2a38;
  --border: #1c2a3a;
  --border-active: #2a3e54;
  --accent: #00d4aa;
  --accent-dim: #008f72;
  --accent-glow: rgba(0, 212, 170, 0.08);
  --accent-glow-strong: rgba(0, 212, 170, 0.18);
  --warning: #f59e0b;
  --error: #ef4444;
  --success: #22c55e;
  --info: #3b82f6;
  --text-primary: #e0e7ef;
  --text-secondary: #8494a7;
  --text-muted: #4a5568;
  --font-sans: 'Plus Jakarta Sans', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --sidebar-w: 56px;
  --header-h: 48px;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-deep);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.5;
}

/* Custom scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-active); }
```

**Step 4: Create layout.tsx and page.tsx**

`layout.tsx`: Root layout with Google Fonts (Plus Jakarta Sans, JetBrains Mono), meta viewport, import globals.css.

`page.tsx`: Placeholder that renders "Cogent Dashboard" text. Will be replaced with full dashboard in Task 11.

**Step 5: Install dependencies, verify dev server starts**

```bash
cd dashboard/frontend && npm install && npm run dev
```

**Step 6: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): scaffold Next.js 16 frontend with Tailwind dark theme"
```

---

## Task 10: Shared components + TypeScript types + API client

**Files:**
- Create: `dashboard/frontend/src/lib/types.ts`
- Create: `dashboard/frontend/src/lib/api.ts`
- Create: `dashboard/frontend/src/lib/format.ts`
- Create: `dashboard/frontend/src/components/shared/DataTable.tsx`
- Create: `dashboard/frontend/src/components/shared/Badge.tsx`
- Create: `dashboard/frontend/src/components/shared/StatCard.tsx`
- Create: `dashboard/frontend/src/components/shared/JsonViewer.tsx`

**Step 1: Create TypeScript types**

`types.ts` mirrors the Pydantic models from the backend — StatusResponse, Program, Execution, Session, Event, Trigger, MemoryItem, Task, Channel, Alert, etc.

**Step 2: Create API client**

`api.ts`: fetch wrapper with API key from localStorage, error handling for 401. Functions: `fetchJSON(path)`, `getStatus(name)`, `getPrograms(name)`, etc.

**Step 3: Create formatters**

`format.ts`: Port `fmtNum`, `fmtCost`, `fmtMs`, `fmtTime`, `fmtRelative`, `fmtDateTime` from the original SPA. Support UTC/PST/Local timezone toggle.

**Step 4: Create shared components**

- `DataTable`: Generic sortable table. Props: columns (key, label, render?), rows, onSort.
- `Badge`: Status/type badge with color variants (success, warning, error, info, neutral, accent).
- `StatCard`: Metric card with value (mono font, large), label (uppercase, muted), optional color variant.
- `JsonViewer`: Collapsible JSON tree with copy button. Handles nested objects/arrays.

**Step 5: Write component tests with Vitest + Testing Library**

**Step 6: Commit**

```bash
git commit -m "feat(dashboard): add shared components, types, API client, formatters"
```

---

## Task 11: Sidebar + Header + tab switching

**Files:**
- Create: `dashboard/frontend/src/components/Sidebar.tsx`
- Create: `dashboard/frontend/src/components/Header.tsx`
- Modify: `dashboard/frontend/src/app/page.tsx`
- Create: `dashboard/frontend/src/hooks/useCogentData.ts`

**Step 1: Build Sidebar**

Port the 10-tab icon sidebar from the original SPA. Use inline SVG icons (same as original). Active tab gets accent border-left and glow background. Badge counts for triggers and alerts.

**Step 2: Build Header**

Cogent name (accent color), status text, beta toggle, time range picker (1m/10m/1h/24h/1w), timezone toggle, refresh button with loading pulse animation.

**Step 3: Build useCogentData hook**

Manages all dashboard state — calls all REST endpoints on mount, stores responses, provides refresh function. Returns `{ data, loading, refresh, timeRange, setTimeRange }`.

**Step 4: Wire up page.tsx**

Compose Sidebar + Header + content area. Tab switching shows/hides panel components (placeholder divs for now).

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): add Sidebar, Header, tab navigation, data hook"
```

---

## Task 12: Overview panel

**Files:**
- Create: `dashboard/frontend/src/components/overview/OverviewPanel.tsx`
- Create: `dashboard/frontend/src/components/overview/BudgetCard.tsx`

**Step 1: Build OverviewPanel**

Stat grid (4 cards): Active Sessions, Trigger Count, Unresolved Alerts, Recent Events. Below: events-over-time chart (Chart.js line chart), budget summary cards.

**Step 2: Commit**

```bash
git commit -m "feat(dashboard): add Overview panel with stat grid and charts"
```

---

## Task 13: Programs panel

**Files:**
- Create: `dashboard/frontend/src/components/programs/ProgramsPanel.tsx`
- Create: `dashboard/frontend/src/components/programs/ExecutionDetail.tsx`

**Step 1: Build ProgramsPanel**

Table of programs with columns: Name, Type, Runs, OK/Fail, Cost, Last Run. Click row to expand ExecutionDetail.

**Step 2: Build ExecutionDetail**

Shows execution list for a program. Each execution row: status badge, duration, tokens, cost, error. Expandable to show full prompt content, tool calls, response text.

**Step 3: Commit**

```bash
git commit -m "feat(dashboard): add Programs panel with execution drill-down"
```

---

## Task 14: Sessions, Channels, Events panels

**Step 1: Build SessionsPanel** — Table of conversations with status badge, execution stats, duration.

**Step 2: Build ChannelsPanel + ChannelDetail** — Channel list with type badges. Click for event stream.

**Step 3: Build EventsPanel + EventTree** — Event log with type filter. Expandable payload JSON. Tree button opens recursive causal tree visualization (indented list with depth lines).

**Step 4: Commit**

```bash
git commit -m "feat(dashboard): add Sessions, Channels, Events panels with event tree"
```

---

## Task 15: Triggers, Memory, Resources, Tasks, Alerts panels

**Step 1: Build TriggersPanel** — Grouped by prefix. Toggle switches for individual + bulk enable/disable. Fired counts (1m/5m/1h/24h).

**Step 2: Build MemoryPanel** — Scoped browser with collapsible groups. Expandable JSON values.

**Step 3: Build ResourcesPanel** — Active sessions list with budget display.

**Step 4: Build TasksPanel** — Task queue table with status badges. Click for task detail (related events, executions, conversations).

**Step 5: Build AlertsPanel** — Alert list with severity badges and timestamps.

**Step 6: Commit**

```bash
git commit -m "feat(dashboard): add Triggers, Memory, Resources, Tasks, Alerts panels"
```

---

## Task 16: WebSocket hook + real-time updates

**Files:**
- Create: `dashboard/frontend/src/hooks/useWebSocket.ts`
- Modify: `dashboard/frontend/src/hooks/useCogentData.ts`

**Step 1: Build useWebSocket hook**

Manages WebSocket connection lifecycle:
- Connect with API key in query param
- Auto-reconnect with exponential backoff (1s, 2s, 4s... max 30s)
- Parse incoming messages and route by type
- Returns `{ connected, lastMessage }`

**Step 2: Integrate into useCogentData**

When a WebSocket message arrives, merge it into the existing data:
- `event` → prepend to events list
- `session_update` → update matching session
- `trigger_fired` → update trigger fired counts
- `alert` → prepend to alerts list
- `status` → replace status data
- `task_update` → update matching task

Fallback: if WebSocket fails to connect, fall back to 30-second polling.

**Step 3: Commit**

```bash
git commit -m "feat(dashboard): add WebSocket hook with real-time data merging"
```

---

## Task 17: CLI integration

**Files:**
- Create: `src/cli/dashboard.py`
- Modify: `src/cli/__main__.py` (register dashboard command)

**Step 1: Create CLI dashboard command**

Port from the original metta-ai/cogents `dashboard.py`. Click command group with subcommands:

- `cogent <name> dashboard` — Start local dev server (uvicorn + next dev)
- `cogent <name> dashboard --prod` — Serve static build
- `cogent <name> dashboard login` — Generate API key
- `cogent <name> dashboard logout` — Remove local key
- `cogent <name> dashboard keys` — List/manage keys

**Step 2: Commit**

```bash
git commit -m "feat(dashboard): add CLI commands for dashboard server and auth"
```

---

## Task 18: Integration test + polish

**Step 1: Write end-to-end integration test**

Test that starts the FastAPI server, seeds data, and verifies each endpoint returns expected shapes.

**Step 2: Verify frontend builds**

```bash
cd dashboard/frontend && npm run build && npm run type-check
```

**Step 3: Final commit**

```bash
git commit -m "feat(dashboard): add integration tests and verify build"
```
