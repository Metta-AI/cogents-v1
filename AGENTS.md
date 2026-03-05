# Agents

## Dashboard Testing with agent-browser

Use the `agent-browser` skill to test the Cogent Dashboard interactively.

### Prerequisites

Start the dashboard backend and frontend:

```bash
# Terminal 1: Backend (FastAPI on port 8100)
uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100 --reload

# Terminal 2: Frontend (Next.js on port 5174)
cd dashboard/frontend && npm run dev
```

### Quick Start

```bash
agent-browser open http://localhost:5174 && agent-browser wait --load networkidle && agent-browser snapshot -i
```

### Dashboard Panels to Test

The dashboard has 10 tabs accessible via the sidebar:

| Tab | Description | Key interactions |
|-----|-------------|-----------------|
| Overview | Stat cards, recent events, top programs | Verify stat rendering |
| Programs | Program table with expandable executions | Click rows to expand execution detail |
| Sessions | Session list with execution stats | Sort columns, verify data |
| Events | Event log with expandable payloads | Expand events, click tree view button |
| Triggers | Grouped triggers with toggle switches | Toggle switches on/off |
| Memory | Scoped memory browser | Expand/collapse groups |
| Resources | Active sessions with stat cards | Verify stat cards |
| Tasks | Task queue with expandable detail | Expand task rows |
| Channels | Channel registry table | Click for channel detail |
| Alerts | Alert list with severity badges | Check badge colors by severity |

### Testing Workflow

```bash
# Open dashboard and orient
agent-browser open http://localhost:5174
agent-browser wait --load networkidle
agent-browser snapshot -i

# Click through each sidebar tab
agent-browser click @e{N}  # Use ref from snapshot for sidebar tab
agent-browser wait --load networkidle
agent-browser snapshot -i

# Test interactive elements (expand rows, toggle switches, etc.)
agent-browser click @e{N}
agent-browser snapshot -i

# Check for console errors
agent-browser console

# Take annotated screenshots for visual review
agent-browser screenshot --annotate ./test-output/dashboard.png
```

### Dogfooding

For a full QA pass, use the `dogfood` skill:

```
/dogfood http://localhost:5174
```

This will systematically explore the dashboard, document issues with screenshots and repro videos, and produce a structured report.

### API Endpoints

The backend serves REST API under `/api/cogents/{name}/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Health check |
| `/api/cogents/{name}/status` | GET | Cogent status |
| `/api/cogents/{name}/programs` | GET | Programs list |
| `/api/cogents/{name}/sessions` | GET | Sessions list |
| `/api/cogents/{name}/events` | GET | Events log |
| `/api/cogents/{name}/events/{id}/tree` | GET | Event causal tree |
| `/api/cogents/{name}/triggers` | GET | Triggers list |
| `/api/cogents/{name}/triggers/toggle` | POST | Toggle trigger |
| `/api/cogents/{name}/memory` | GET | Memory items |
| `/api/cogents/{name}/tasks` | GET | Task queue |
| `/api/cogents/{name}/channels` | GET | Channels |
| `/api/cogents/{name}/alerts` | GET | Unresolved alerts |
| `/api/cogents/{name}/resources` | GET | Active resources |
| `/ws/cogents/{name}` | WS | Real-time updates |

### Architecture

- **Backend**: FastAPI + asyncpg (PostgreSQL), port 8100
- **Frontend**: Next.js 15 + React 19 + Tailwind v4, port 5174
- **Real-time**: WebSocket via PostgreSQL LISTEN/NOTIFY
- **Auth**: API key in `x-api-key` header (SHA-256 hashed, stored in Secrets Manager)
