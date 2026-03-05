# Brain System

The brain is the cogent's shared persistence and state management layer — a PostgreSQL-backed data store with async CRUD, event-driven architecture, and AWS infrastructure management.

## Architecture

```
CLI Layer (brain status/create/destroy/update)
    │
Repository (async CRUD over asyncpg pool)
    │
PostgreSQL (12 tables, JSONB metadata, LISTEN/NOTIFY)
```

## Module Structure

```
src/brain/
├── __init__.py          # Package root
├── cli.py               # Brain CLI group (status/create/destroy)
├── update_cli.py        # Update subcommands (lambda/discord/ecs/rds/stack/docker)
└── db/
    ├── __init__.py      # Public API exports
    ├── models.py        # Pydantic models + enums (9 enums, 15 models)
    ├── schema.sql       # PostgreSQL DDL (12 tables, v1)
    ├── repository.py    # Async Repository (~50 methods)
    └── migrations.py    # Schema apply/reset
```

## Quick Start

```python
from brain.db import Repository, MemoryRecord, MemoryScope, MemoryType

# Create repository
repo = await Repository.create("postgresql://localhost/cogent")

# Or use as context manager
async with await Repository.create(dsn) as repo:
    # Insert a memory record
    mem = MemoryRecord(
        cogent_id="my-cogent",
        scope=MemoryScope.COGENT,
        type=MemoryType.FACT,
        name="project.description",
        content="An autonomous agent platform",
    )
    await repo.insert_memory(mem)

    # Query memories
    records = await repo.query_memory("my-cogent", scope=MemoryScope.COGENT)
```

## Tables

| Table | Purpose |
|-------|---------|
| `schema_version` | Migration tracking |
| `memory` | Scoped knowledge store (facts, episodic, prompts, policies) |
| `skills` | Skill registry (markdown/python, triggers, SLA) |
| `triggers` | Event/cron → skill wiring |
| `channels` | External integrations (Discord, GitHub, email, Asana, CLI) |
| `tasks` | Work queue with status workflow |
| `conversations` | Multi-turn context routing |
| `executions` | Skill execution log |
| `traces` | Detailed execution audit (tool calls, memory ops) |
| `events` | Append-only event log with causal chains |
| `alerts` | Algedonic emergency system |
| `budget` | Token/cost accounting by period |

## CLI

```bash
cogent <name> brain status     # Infrastructure status
cogent <name> brain create     # Deploy CloudFormation stack
cogent <name> brain destroy    # Tear down stack
cogent <name> brain update     # Update components (default: all)
```

Update subcommands: `all`, `lambda`, `discord`, `ecs`, `rds`, `stack`, `docker`
