# Cogent Dashboard — Design Document

Ported and improved from metta-ai/cogents operational dashboard.

## Overview

A real-time operational dashboard for monitoring cogent AI agents. Each cogent runs on its own domain (e.g., `dr-alpha.softmax-cogents.com`). The dashboard provides live visibility into events, programs, sessions, tasks, triggers, memory, channels, and alerts.

### Key improvements over the original

- **Component-based UI** — Next.js 16 + React 19 instead of a 131KB monolithic HTML file
- **WebSocket push** — Real-time updates via PostgreSQL LISTEN/NOTIFY instead of polling
- **FastAPI backend** — Typed routers, Pydantic models, OpenAPI docs instead of raw HTTP handler
- **Type safety end-to-end** — TypeScript frontend, Pydantic backend
- **"Skills" renamed to "Programs"** throughout

## Architecture

```
┌─────────────────────────┐     ┌──────────────────────────┐
│   Next.js Frontend      │     │   FastAPI Backend         │
│                         │     │                           │
│  Single-page, tab-based │◄───►│  REST: /api/cogents/{n}/  │
│  React 19 components    │     │  WS:   /ws/cogents/{n}/   │
│  Tailwind CSS           │     │                           │
│  Chart.js               │     │  ┌─────────────────────┐  │
│                         │     │  │  Event Bus           │  │
└─────────────────────────┘     │  │  (pg LISTEN/NOTIFY)  │  │
                                │  └─────────────────────┘  │
                                │           │               │
                                │  ┌────────▼────────────┐  │
                                │  │  PostgreSQL (Aurora)  │  │
                                │  │  + pgvector           │  │
                                │  └──────────────────────┘  │
                                └──────────────────────────┘
```

**Deployment:** Each cogent domain serves the Next.js static build at `/` and the FastAPI backend at `/api/` + `/ws/`. In production, this runs behind API Gateway (Lambda) or as a standalone service. For local dev, Next.js dev server proxies API requests to the FastAPI backend.

## Frontend

### Stack

- Next.js 16 + React 19 (matching Observatory)
- TypeScript
- Tailwind CSS + CSS variables for dark theme
- Chart.js for visualizations
- Vitest + Testing Library for tests

### File structure

```
dashboard/frontend/
├── package.json
├── next.config.ts
├── tsconfig.json
├── vitest.config.ts
├── src/
│   ├── app/
│   │   ├── layout.tsx              # Root layout, dark theme, fonts (Plus Jakarta Sans, JetBrains Mono)
│   │   ├── page.tsx                # Main dashboard page (single-page, tab-based)
│   │   └── globals.css             # Tailwind + CSS variables (ported from original)
│   ├── components/
│   │   ├── Sidebar.tsx             # Icon sidebar nav (10 tabs)
│   │   ├── Header.tsx              # Cogent name, status, timezone toggle, time range picker, refresh
│   │   ├── overview/
│   │   │   ├── OverviewPanel.tsx   # Stat grid + charts (events over time, budget usage)
│   │   │   └── BudgetCard.tsx      # Budget actual vs limit with progress bar
│   │   ├── programs/
│   │   │   ├── ProgramsPanel.tsx   # Program list with execution stats
│   │   │   └── ExecutionDetail.tsx # Drill-down: logs, prompts, tokens, cost
│   │   ├── sessions/
│   │   │   └── SessionsPanel.tsx   # Active + recent sessions with event counts
│   │   ├── channels/
│   │   │   ├── ChannelsPanel.tsx   # Channel registry with stats
│   │   │   └── ChannelDetail.tsx   # Channel event stream
│   │   ├── events/
│   │   │   ├── EventsPanel.tsx     # Event log with type filters and time range
│   │   │   └── EventTree.tsx       # Causal parent-child event tree
│   │   ├── triggers/
│   │   │   └── TriggersPanel.tsx   # Grouped triggers with bulk toggle switches
│   │   ├── memory/
│   │   │   └── MemoryPanel.tsx     # Memory browser by scope (agent, global, etc.)
│   │   ├── resources/
│   │   │   └── ResourcesPanel.tsx  # Budget and resource usage
│   │   ├── tasks/
│   │   │   └── TasksPanel.tsx      # Task queue + task detail with related events
│   │   ├── alerts/
│   │   │   └── AlertsPanel.tsx     # Dead letters + algedonic alerts
│   │   └── shared/
│   │       ├── DataTable.tsx       # Reusable sortable/filterable table
│   │       ├── JsonViewer.tsx      # Collapsible JSON renderer with copy button
│   │       ├── Badge.tsx           # Status/type/event badges
│   │       └── StatCard.tsx        # Metric display card (value + label)
│   ├── hooks/
│   │   ├── useWebSocket.ts        # WS connection, auth, auto-reconnect, message routing
│   │   └── useCogentData.ts       # Initial REST fetch + WS delta merge
│   └── lib/
│       ├── api.ts                 # REST client with auth headers
│       ├── types.ts               # Shared TypeScript types
│       └── format.ts              # Time (UTC/PST/local), number, cost formatters
```

### Sidebar tabs (10 sections, same as original)

1. **Overview** — stat grid (active sessions, trigger count, unresolved alerts, event rate), activity chart, budget summary
2. **Programs** — program definitions table with execution count, success rate, avg duration. Click to drill into execution detail (logs, prompts, token usage, cost).
3. **Sessions** — active and recent conversation sessions with event counts and duration
4. **Channels** — channel registry (Discord, Slack, etc.) with message counts. Click for channel event stream.
5. **Events** — full event log with type filter and time range. Expandable rows show payload JSON. "Tree" button shows causal event tree.
6. **Triggers** — grouped by prefix (e.g., `github.`, `slack.`), with individual and bulk toggle switches. Click for trigger detail (cron expression, fired count, last fired).
7. **Memory** — scoped memory browser (agent, global, etc.) with key-value display and expandable JSON values
8. **Resources** — budget usage (API calls, tokens, cost) with actual vs limit progress bars
9. **Tasks** — task queue with status badges. Click for task detail showing related events, executions, and conversations.
10. **Alerts** — dead letters and algedonic alerts with severity badges and timestamps

### Design system

Ported from the original dark theme:
- Background: `#06080c` (deep) → `#0c1017` (base) → `#131920` (surface) → `#1a2230` (elevated)
- Accent: `#00d4aa` (teal green)
- Fonts: Plus Jakarta Sans (UI), JetBrains Mono (data/code)
- All CSS variables preserved for easy theming

## Backend

### Stack

- FastAPI + Uvicorn
- asyncpg for PostgreSQL
- Pydantic v2 for request/response models
- WebSocket support (native FastAPI)
- PostgreSQL LISTEN/NOTIFY for real-time event bus

### File structure

```
dashboard/backend/
├── pyproject.toml
├── dashboard_backend/
│   ├── __init__.py
│   ├── app.py                  # FastAPI app factory, CORS, middleware
│   ├── config.py               # Settings from env (DB URL, domain, secrets ARN)
│   ├── database.py             # asyncpg pool management + LISTEN/NOTIFY listener
│   ├── auth.py                 # API key validation (SHA-256 hashed, cached from Secrets Manager)
│   ├── ws.py                   # WebSocket connection manager + broadcast
│   ├── models/
│   │   ├── status.py
│   │   ├── program.py
│   │   ├── session.py
│   │   ├── event.py
│   │   ├── trigger.py
│   │   ├── memory.py
│   │   ├── task.py
│   │   ├── channel.py
│   │   └── alert.py
│   └── routers/
│       ├── status.py
│       ├── programs.py
│       ├── sessions.py
│       ├── events.py
│       ├── triggers.py
│       ├── memory.py
│       ├── tasks.py
│       ├── channels.py
│       └── alerts.py
```

### REST API

All endpoints scoped to `/api/cogents/{name}/`:

| Method | Path | Query params | Description |
|--------|------|-------------|-------------|
| GET | `/status` | `range` | Health summary, active sessions, trigger count, alert count, event rate |
| GET | `/programs` | | Program definitions with execution count, success rate, avg duration |
| GET | `/programs/{id}/executions` | `limit` | Execution history for a program |
| GET | `/sessions` | `range` | Active + recent sessions |
| GET | `/events` | `range`, `type`, `since` | Event log with filters |
| GET | `/events/{id}/tree` | | Causal event tree (parent-child chain) |
| GET | `/triggers` | | All triggers |
| POST | `/triggers/toggle` | | Enable/disable triggers (body: `{ids, enabled}`) |
| GET | `/memory` | `scope` | Memory key-value pairs by scope |
| GET | `/resources` | | Budget and resource usage |
| GET | `/tasks` | | Task queue |
| GET | `/tasks/{id}` | | Task detail with related events/executions |
| GET | `/channels` | `range` | Channel registry with message stats |
| GET | `/alerts` | `range` | Alerts + dead letters |
| POST | `/events` | | Inject test event |
| POST | `/programs/{name}/invoke` | | Manual program invocation |

### WebSocket

```
WS /ws/cogents/{name}/
```

**Connection flow:**
1. Client connects with `x-api-key` in query param or first message
2. Server validates key (same SHA-256 check as REST)
3. Server subscribes to PostgreSQL NOTIFY channels for this cogent
4. Server pushes delta updates as they arrive:

```json
{"type": "event", "data": {...}}
{"type": "session_update", "data": {...}}
{"type": "trigger_fired", "data": {...}}
{"type": "alert", "data": {...}}
{"type": "status", "data": {...}}
{"type": "task_update", "data": {...}}
```

**PostgreSQL LISTEN/NOTIFY setup:**
- The cogent's event-writing code does `NOTIFY cogent_{name}_events, '{json}'` after inserts
- The dashboard backend runs a persistent listener connection that routes notifications to connected WebSocket clients
- Fallback: if NOTIFY is not set up, the frontend falls back to 30-second polling (same as original)

### Authentication

Same pattern as the original Lambda deployment:
- API keys stored in AWS Secrets Manager, hashed with SHA-256
- Cached for 5 minutes to avoid Secrets Manager throttling
- `x-api-key` header for REST, query param or first message for WebSocket
- CLI: `cogent <name> dashboard login` generates and stores a key locally

## CLI integration

```
cogent <name> dashboard          # Start local dev server (backend + frontend)
cogent <name> dashboard --prod   # Serve static build
cogent <name> dashboard login    # Generate API key and store locally
cogent <name> dashboard logout   # Remove local API key
cogent <name> dashboard keys     # List/manage API keys
```

Local dev mode:
- Starts FastAPI on port 8100
- Starts Next.js dev server on port 5174 with proxy to backend
- Opens browser automatically

## Implementation plan

### Phase 1: Backend foundation
1. Set up `dashboard/backend/` with FastAPI app factory
2. Implement `database.py` with asyncpg pool
3. Port SQL queries from original `dashboard.py` DataAPI class
4. Implement auth middleware (API key validation)
5. Build all REST routers with Pydantic models

### Phase 2: Frontend foundation
6. Set up `dashboard/frontend/` with Next.js 16 + React 19
7. Port CSS variables and dark theme from original
8. Build shared components (DataTable, JsonViewer, Badge, StatCard)
9. Build Sidebar + Header + tab switching
10. Implement `api.ts` REST client

### Phase 3: Dashboard panels
11. Overview panel with stat grid and charts
12. Programs panel with execution detail drill-down
13. Sessions panel
14. Events panel with causal tree visualization
15. Triggers panel with grouped toggles
16. Memory browser
17. Resources panel
18. Tasks panel
19. Channels panel with detail view
20. Alerts panel

### Phase 4: Real-time
21. Implement WebSocket manager in backend (`ws.py`)
22. Set up PostgreSQL LISTEN/NOTIFY in `database.py`
23. Build `useWebSocket` hook with auto-reconnect
24. Build `useCogentData` hook merging REST + WS updates
25. Wire up all panels to receive live updates

### Phase 5: CLI + deployment
26. Port CLI commands from original `dashboard.py`
27. Wire up local dev server mode
28. Static build serving for production
29. Lambda deployment configuration (if needed)
