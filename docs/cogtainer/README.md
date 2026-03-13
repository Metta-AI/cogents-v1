# CogTainer

The cogtainer is the cogent's persistent infrastructure layer — a PostgreSQL-backed data store with async CRUD, event-driven architecture, and AWS infrastructure management. It sits at the bottom of the stack: CogTainer (persistence/infra) -> CogOS (execution) -> CogWare (apps).

## Architecture

```
CLI Layer (cogtainer status/create/destroy/update)
    │
Repository (async CRUD over asyncpg pool)
    │
PostgreSQL (16 tables, JSONB metadata, LISTEN/NOTIFY)
```

## Module Structure

```
src/cogtainer/
├── __init__.py          # Package root
├── cli.py               # CogTainer CLI group (status/create/destroy)
├── update_cli.py        # Update subcommands (lambda/discord/ecs/rds/stack/docker)
└── db/
    ├── __init__.py      # Public API exports
    ├── models.py        # Pydantic models + enums
    ├── repository.py    # Async Repository
    ├── local_repository.py  # JSON-file local dev repository
    └── migrations.py    # Schema apply/reset
```

The database schema DDL lives in `src/cogos/db/schema.sql`.

## Quick Start

```python
from cogtainer.db import Repository

# Create repository (RDS Data API)
repo = Repository(cluster_arn=..., secret_arn=..., database=...)

# Or use LocalRepository for local dev (JSON file)
from cogtainer.db.local_repository import LocalRepository
repo = LocalRepository()
```

## Tables

| Table | Purpose |
|-------|---------|
| `schema_version` | Migration tracking |
| `memory` | Versioned named memory records |
| `memory_version` | Content versions per memory record |
| `programs` | Program definitions (name, memory, tools, runner) |
| `triggers` | Event pattern -> program wiring |
| `cron` | Cron schedules that emit events |
| `tools` | Tool definitions (Code Mode) |
| `tasks` | Work queue with status workflow |
| `conversations` | Multi-turn context routing |
| `runs` | Per-invocation execution summary |
| `traces` | Detailed execution audit (tool calls, memory ops) |
| `resources` | Resource pool and budget tracking |
| `resource_usage` | Per-run resource consumption |
| `events` | Append-only event log with causal chains |
| `alerts` | Algedonic emergency system |
| `budget` | Token/cost accounting by period |

## CLI

```bash
cogent <name> cogtainer status     # Infrastructure status
cogent <name> cogtainer create     # Deploy CloudFormation stack
cogent <name> cogtainer destroy    # Tear down stack
cogent <name> cogtainer update     # Update components (default: all)
```

Update subcommands: `all`, `lambda`, `discord`, `ecs`, `rds`, `stack`, `docker`
