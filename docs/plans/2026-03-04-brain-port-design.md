# Brain System Port Design

## Overview

Port the cogent brain system from `metta-ai/cogents` into `cogents.1`. The brain is the shared persistence and state management layer — a PostgreSQL-backed data store with async CRUD, event-driven architecture, and AWS infrastructure management CLI.

This is a **full port with improvements**: same scope as the original (data layer + AWS CLI), but with stronger types, better ergonomics, testability, and cleaner code.

## Module Structure

```
src/brain/
├── __init__.py              # Public API exports
├── cli.py                   # Top-level brain CLI group (status/create/destroy)
├── update_cli.py            # Update subcommands (lambda/discord/ecs/rds/stack/docker)
└── db/
    ├── __init__.py          # DB public API (Repository, models)
    ├── schema.sql           # PostgreSQL schema (reset-based, starts at v1)
    ├── models.py            # Pydantic models + enums
    ├── repository.py        # Async Repository with all CRUD ops
    └── migrations.py        # Schema versioning (apply/reset)

docs/brain/
├── README.md               # Overview, quickstart, architecture diagram
├── schema.md               # Table-by-table documentation
├── repository-api.md        # Full Repository method reference
└── cli.md                   # CLI command reference
```

## Data Models

### Enums (StrEnum for clean serialization)

| Enum | Values |
|------|--------|
| `MemoryScope` | polis, cogent |
| `TaskStatus` | proposed, approved, in_progress, completed, failed |
| `ExecutionStatus` | running, completed, failed, timeout |
| `ConversationStatus` | active, idle, closed |
| `ChannelType` | discord, github, email, asana, cli |
| `AlertSeverity` | warning, critical, emergency |
| `BudgetPeriod` | daily, weekly, monthly |

### Core Models (Pydantic v2)

All models use:
- `Field(default_factory=uuid4)` for auto-generated IDs
- `Field(min_length=..., max_length=...)` validators where appropriate
- `datetime | None` union types
- `dict[str, Any]` for JSONB fields with `default_factory=dict`

**Knowledge & Skills:**
- `MemoryRecord` — scoped knowledge store (id, scope, name, content, provenance, disabled, timestamps)
- `Skill` — skill definition (name, type, description, content, execution_context, model, version)

**Event System:**
- `Event` — append-only log entry (id, event_type, source, source_execution_id, payload)
- `EventTrigger` — event pattern → skill wiring (id, event_pattern, skill_name, priority, disabled)
- `CronTrigger` — scheduled event emission (id, cron_expression, event_type, disabled)

**Work Management:**
- `Task` — work item (id, title, description, status, priority, source, channel_id, conversation_id, metadata, error)
- `Conversation` — multi-turn context (id, context_key, channel_id, status, cli_session_id, metadata)
- `Execution` — skill run log (id, skill_name, event_id, conversation_id, status, tokens, cost, duration, tool_calls, model_version, error)

**Infrastructure:**
- `Channel` — external integration (id, type, name, external_id, secret_arn, config, disabled)
- `Alert` — algedonic emergency (id, severity, alert_type, source, message, metadata, timestamps)
- `Budget` — token/cost accounting (id, period, period_start, tokens_spent, cost_spent_usd, limits)

## Repository

### Design

```python
class Repository:
    """Async PostgreSQL CRUD wrapper for all brain tables."""

    def __init__(self, pool: asyncpg.Pool) -> None: ...

    @classmethod
    async def create(cls, dsn: str | None = None, **kwargs) -> Repository:
        """Create from DSN string or keyword args."""

    @classmethod
    async def create_with_iam(cls, config: LambdaConfig) -> Repository:
        """Create with RDS IAM token auth (auto-rotating)."""

    async def close(self) -> None: ...
    async def __aenter__(self) -> Repository: ...
    async def __aexit__(self, *exc) -> None: ...
```

### Protocol for Testability

```python
class RepositoryProtocol(Protocol):
    """Interface for dependency injection and testing."""
    async def append_event(self, event: Event) -> int: ...
    async def get_events(self, ...) -> list[Event]: ...
    # ... all public methods
```

### Method Groups (~50 async methods)

**Events:** append_event, get_events
**Memory:** insert_memory, get_memory, query_memory, query_memory_by_prefixes, delete_memory
**Skills:** upsert_skill, list_skills, delete_skill
**Event Triggers:** insert_event_trigger, list_event_triggers, delete_event_trigger
**Cron Triggers:** insert_cron_trigger, list_cron_triggers, delete_cron_trigger
**Channels:** upsert_channel, list_channels
**Tasks:** create_task, get_task, update_task_status, claim_task, list_tasks
**Conversations:** upsert_conversation, get_conversation_by_context, list_conversations, close_conversation
**Executions:** insert_execution, update_execution, query_executions
**Alerts:** create_alert, get_unresolved_alerts, resolve_alert
**Budget:** get_or_create_budget, record_spend, check_budget
**Pub/Sub:** listen, unlisten

### Improvements over Original

- Context manager support (`async with Repository.create(...) as repo:`)
- Methods accept model objects or keyword args
- Return `T | None` instead of raising on not-found
- `@overload` for type-safe return types
- `FOR UPDATE SKIP LOCKED` for atomic task claiming (preserved from original)

## Schema

### Approach

- Reset-based: full `schema.sql` defines all tables
- `apply_schema()` creates tables if not exist
- `reset_schema()` drops and recreates (dev/test only)
- `schema_version` table tracks version
- **Start at v1** (fresh start for this repo)

### Tables (11)

1. `schema_version` — migration tracking
2. `memory` — scoped knowledge store (unique name within scope)
3. `skills` — skill registry (name PK, type, execution_context, model)
4. `event_triggers` — event pattern → skill wiring
5. `cron_triggers` — cron expression → event emission
6. `channels` — external integration registry
7. `tasks` — work queue with status workflow
8. `conversations` — multi-turn context routing
9. `executions` — skill execution log
10. `events` — append-only event log (BIGSERIAL PK)
11. `alerts` — algedonic emergency system
12. `budget` — token/cost accounting by period

### Constraints

- CHECK constraints on all enum columns
- UNIQUE constraints on natural keys (scope+name, type+name, etc.)
- FK references between tasks↔conversations, executions↔events, etc.
- JSONB columns for metadata, config, payload, provenance

## CLI

### brain group (`brain/cli.py`)

```
cogent <name> brain status    # Dashboard: connection, schema version, table counts
cogent <name> brain create    # Deploy CloudFormation stack
cogent <name> brain destroy   # Tear down CloudFormation stack (with --dry-run)
cogent <name> brain update    # Update subcommands
```

### brain update subcommands (`brain/update_cli.py`)

```
brain update all       # Lambda + Discord + RDS + mind (default)
brain update lambda    # Deploy new Lambda function code
brain update discord   # Force new ECS deployment (Discord bridge)
brain update ecs       # Force new ECS deployment
brain update rds       # Run schema migrations
brain update stack     # Full CloudFormation redeployment
brain update docker    # Build and push Docker image to ECR
```

### Improvements

- `rich` for colored status tables and progress bars
- `--dry-run` flag on destructive commands
- Better error messages with suggested fixes
- `brain status` shows dashboard view

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     BRAIN SYSTEM                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────┐                  │
│  │            CLI Layer                  │                  │
│  │  brain status / create / destroy      │                  │
│  │  brain update {all,lambda,ecs,...}    │                  │
│  └──────────────┬───────────────────────┘                  │
│                 │                                           │
│  ┌──────────────▼───────────────────────┐                  │
│  │         Repository                    │                  │
│  │  (async CRUD over asyncpg pool)       │                  │
│  │                                       │                  │
│  │  Events · Memory · Skills · Triggers  │                  │
│  │  Channels · Tasks · Conversations     │                  │
│  │  Executions · Alerts · Budget         │                  │
│  └──────────────┬───────────────────────┘                  │
│                 │                                           │
│  ┌──────────────▼───────────────────────┐                  │
│  │       PostgreSQL (schema.sql)         │                  │
│  │  12 tables · JSONB metadata           │                  │
│  │  Append-only events · SKIP LOCKED     │                  │
│  │  LISTEN/NOTIFY pub/sub               │                  │
│  └──────────────────────────────────────┘                  │
│                                                             │
│  ┌──────────────────────────────────────┐                  │
│  │       Pydantic Models                 │                  │
│  │  18 models · 7 StrEnum types          │                  │
│  │  Field validators · Auto UUIDs        │                  │
│  └──────────────────────────────────────┘                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Order

1. **`src/brain/db/models.py`** — Enums and Pydantic models (no dependencies)
2. **`src/brain/db/schema.sql`** — PostgreSQL DDL
3. **`src/brain/db/migrations.py`** — Schema apply/reset
4. **`src/brain/db/repository.py`** — Async Repository (depends on models + schema)
5. **`src/brain/db/__init__.py`** — DB public API
6. **`src/brain/__init__.py`** — Module public API
7. **`src/brain/cli.py`** — Brain CLI group
8. **`src/brain/update_cli.py`** — Update subcommands
9. **`docs/brain/`** — Documentation (README, schema, API ref, CLI ref)
