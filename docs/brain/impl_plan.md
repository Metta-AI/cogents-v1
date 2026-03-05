# Brain System Port — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the cogent brain system (persistence layer + AWS CLI) from `metta-ai/cogents` into `cogents.1/src/brain/`.

**Architecture:** The brain consolidates the DB layer (previously in `memory/db/`) and CLI (previously in `brain/`) into a single `src/brain/` module. The DB layer provides async PostgreSQL CRUD via Repository. The CLI manages AWS infrastructure (CloudFormation, Lambda, ECS, RDS).

**Tech Stack:** Python 3.12, asyncpg, Pydantic v2, Click, boto3, PostgreSQL 16

**Source reference:** All original code is in the `metta-ai/cogents` GitHub repo. Key source locations:
- Models: `src/memory/db/models.py` + `src/mind/models.py` (Trigger)
- Schema: `src/memory/db/schema.sql`
- Repository: `src/memory/db/repository.py`
- Migrations: `src/memory/db/migrations.py`
- Brain CLI: `src/brain/cli.py`, `src/brain/update_cli.py`
- CLI deps: `src/cli/common.py`, `src/cli/create.py`, `src/cli/destroy.py`, `src/cli/inspect.py`
- AWS: `src/body/aws.py`

---

### Task 1: Create directory structure and init files

**Files:**
- Create: `src/brain/__init__.py`
- Create: `src/brain/db/__init__.py`

**Step 1: Create directories and init files**

```bash
mkdir -p src/brain/db
```

Write `src/brain/__init__.py`:
```python
"""Cogent brain — persistence layer, state management, and infrastructure CLI."""
```

Write `src/brain/db/__init__.py`:
```python
"""Brain database layer — models, repository, schema, migrations."""

from brain.db.models import (
    Alert,
    AlertSeverity,
    Budget,
    BudgetPeriod,
    Channel,
    ChannelType,
    Conversation,
    ConversationStatus,
    Event,
    Execution,
    ExecutionStatus,
    MemoryRecord,
    MemoryScope,
    MemoryType,
    Skill,
    Task,
    TaskStatus,
    Trace,
    Trigger,
    TriggerConfig,
    TriggerType,
)
from brain.db.repository import Repository

__all__ = [
    "Alert",
    "AlertSeverity",
    "Budget",
    "BudgetPeriod",
    "Channel",
    "ChannelType",
    "Conversation",
    "ConversationStatus",
    "Event",
    "Execution",
    "ExecutionStatus",
    "MemoryRecord",
    "MemoryScope",
    "MemoryType",
    "Repository",
    "Skill",
    "Task",
    "TaskStatus",
    "Trace",
    "Trigger",
    "TriggerConfig",
    "TriggerType",
]
```

**Step 2: Verify structure**

```bash
find src/brain -type f
```

Expected: lists `__init__.py` and `db/__init__.py`

**Step 3: Commit**

```bash
git add src/brain/
git commit -m "feat(brain): create brain module directory structure"
```

---

### Task 2: Port data models (`models.py`)

**Files:**
- Create: `src/brain/db/models.py`

Port all enums and Pydantic models from `memory/db/models.py` + the Trigger/TriggerConfig from `mind/models.py`. Improvements: use `StrEnum`, add Field validators, consolidate Trigger into brain.

**Step 1: Write models.py**

Write `src/brain/db/models.py` with the following content. Key changes from original:
- Use `StrEnum` instead of `str, enum.Enum`
- Consolidate `Trigger`, `TriggerConfig`, `TriggerType`, `RetryPolicy` (from `mind/models.py`) into this file
- Add `MemoryType` enum (fact, episodic, prompt, policy)
- Keep `cogent_id` field on all models (multi-tenant)
- All JSONB fields use `default_factory=dict` or `default_factory=list`

```python
"""Pydantic models for all brain database tables."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# --- Enums ---


class MemoryScope(str, enum.Enum):
    POLIS = "polis"
    COGENT = "cogent"


class MemoryType(str, enum.Enum):
    FACT = "fact"
    EPISODIC = "episodic"
    PROMPT = "prompt"
    POLICY = "policy"


class TaskStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class ChannelType(str, enum.Enum):
    DISCORD = "discord"
    GITHUB = "github"
    EMAIL = "email"
    ASANA = "asana"
    CLI = "cli"


class AlertSeverity(str, enum.Enum):
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class BudgetPeriod(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TriggerType(str, enum.Enum):
    EVENT = "event"
    CRON = "cron"


# --- Core Models ---


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    scope: MemoryScope
    type: MemoryType
    name: str | None = None
    content: str = ""
    embedding: list[float] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Skill(BaseModel):
    cogent_id: str
    name: str
    skill_type: str = "markdown"
    source: str = "golden"
    description: str = ""
    content: str = ""
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    sla: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    type: ChannelType
    name: str
    external_id: str | None = None
    secret_arn: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime | None = None


# --- Work Models ---


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PROPOSED
    priority: int = 0
    source: str = "agent"
    channel_id: UUID | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    context_key: str = ""
    channel_id: UUID | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    cli_session_id: str | None = None
    started_at: datetime | None = None
    last_active: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Execution(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    skill_name: str
    trigger_id: UUID | None = None
    conversation_id: UUID | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_ms: int | None = None
    events_emitted: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Trace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    execution_id: UUID
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    memory_ops: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str | None = None
    created_at: datetime | None = None


# --- Infrastructure Models ---


class Event(BaseModel):
    id: int | None = None
    cogent_id: str
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_event_id: int | None = None
    created_at: datetime | None = None


class Alert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    severity: AlertSeverity
    alert_type: str
    source: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None


class Budget(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    period: BudgetPeriod
    period_start: date
    tokens_spent: int = 0
    cost_spent_usd: Decimal = Decimal("0")
    token_limit: int = 0
    cost_limit_usd: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Trigger Models (consolidated from mind/models.py) ---


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff: Literal["none", "linear", "exponential"] = "none"
    backoff_base_seconds: float = 5.0


class TriggerConfig(BaseModel):
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: str | None = None
    context_key_template: str | None = None


class Trigger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    trigger_type: TriggerType = TriggerType.EVENT
    event_pattern: str = ""
    cron_expression: str = ""
    skill_name: str = ""
    priority: int = 10
    config: TriggerConfig = Field(default_factory=TriggerConfig)
    enabled: bool = True
    created_at: datetime | None = None
```

**Step 2: Verify it parses**

```bash
cd src && python -c "from brain.db.models import *; print('OK')" && cd ..
```

Expected: `OK`

**Step 3: Commit**

```bash
git add src/brain/db/models.py
git commit -m "feat(brain): add data models — enums, Pydantic models, trigger config"
```

---

### Task 3: Port schema.sql

**Files:**
- Create: `src/brain/db/schema.sql`

Port from original `memory/db/schema.sql`. Start at v1. Keep all 12 tables, indexes, constraints. Remove legacy migration code (v10→v11 incremental at bottom of original).

**Step 1: Write schema.sql**

Write `src/brain/db/schema.sql` — this is the full PostgreSQL DDL. Port directly from original with these changes:
- Remove the v11 incremental migration at the bottom
- Set schema_version to 1 instead of 10
- Keep pgvector optional extension
- Keep all CHECK constraints, UNIQUE indexes, FK references
- Keep the `rds_iam` grant (wrapped in exception handler)

The schema defines 12 tables: schema_version, memory, skills, triggers, channels, tasks, conversations, executions, traces, events, alerts, budget.

Copy the original `schema.sql` content exactly but change the version insert from `VALUES (10)` to `VALUES (1)` and remove the v11 migration block at the end.

**Step 2: Verify SQL syntax**

```bash
python -c "
from pathlib import Path
sql = Path('src/brain/db/schema.sql').read_text()
print(f'Schema loaded: {len(sql)} chars')
assert 'CREATE TABLE' in sql
assert 'schema_version' in sql
print('OK')
"
```

**Step 3: Commit**

```bash
git add src/brain/db/schema.sql
git commit -m "feat(brain): add PostgreSQL schema v1 — 12 tables"
```

---

### Task 4: Port migrations.py

**Files:**
- Create: `src/brain/db/migrations.py`

Port from original. Remove the v10 migration (legacy cleanup). Start fresh with empty MIGRATIONS dict. Keep `apply_schema()` and `reset_schema()`.

**Step 1: Write migrations.py**

```python
"""Simple migration runner: apply schema.sql, track version."""

from __future__ import annotations

from pathlib import Path

import asyncpg

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


async def get_current_version(conn: asyncpg.Connection) -> int | None:
    try:
        row = await conn.fetchrow(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        return row["version"] if row else None
    except asyncpg.UndefinedTableError:
        return None


# Incremental migrations keyed by target version.
# Add new migrations here as the schema evolves.
MIGRATIONS: dict[int, str] = {}


async def apply_schema(dsn: str) -> int:
    """Apply schema.sql if not already applied, then run incremental migrations."""
    conn = await asyncpg.connect(dsn)
    try:
        current = await get_current_version(conn)
        if current is None:
            schema_sql = SCHEMA_FILE.read_text()
            await conn.execute(schema_sql)
            row = await conn.fetchrow(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            return row["version"]

        for version in sorted(MIGRATIONS.keys()):
            if version > current:
                await conn.execute(MIGRATIONS[version])
                current = version

        return current
    finally:
        await conn.close()


async def reset_schema(dsn: str) -> int:
    """Drop all tables and re-apply schema. For testing only."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("""
            DROP TABLE IF EXISTS traces CASCADE;
            DROP TABLE IF EXISTS executions CASCADE;
            DROP TABLE IF EXISTS conversations CASCADE;
            DROP TABLE IF EXISTS tasks CASCADE;
            DROP TABLE IF EXISTS channels CASCADE;
            DROP TABLE IF EXISTS triggers CASCADE;
            DROP TABLE IF EXISTS skills CASCADE;
            DROP TABLE IF EXISTS memory CASCADE;
            DROP TABLE IF EXISTS events CASCADE;
            DROP TABLE IF EXISTS alerts CASCADE;
            DROP TABLE IF EXISTS budget CASCADE;
            DROP TABLE IF EXISTS schema_version CASCADE;
        """)
        schema_sql = SCHEMA_FILE.read_text()
        await conn.execute(schema_sql)

        row = await conn.fetchrow(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        return row["version"]
    finally:
        await conn.close()
```

**Step 2: Verify import**

```bash
cd src && python -c "from brain.db.migrations import apply_schema, reset_schema; print('OK')" && cd ..
```

**Step 3: Commit**

```bash
git add src/brain/db/migrations.py
git commit -m "feat(brain): add schema migration runner — apply/reset"
```

---

### Task 5: Port repository.py

**Files:**
- Create: `src/brain/db/repository.py`

This is the largest file (~900 lines). Port all CRUD methods from original `memory/db/repository.py`. Key changes:
- Import models from `brain.db.models` instead of `memory.db.models` and `mind.models`
- Add `__aenter__`/`__aexit__` context manager
- Keep all method signatures identical to original
- Keep all SQL queries identical
- Remove `list_skill_proposals`, `resolve_skill_proposal`, `list_skill_definitions`, `sync_skill_definitions` (legacy methods that reference dropped tables)

**Step 1: Write repository.py**

Port the full Repository class. The file should contain:
- All imports from `brain.db.models`
- `Repository` class with `__init__`, `create`, `close`, `__aenter__`, `__aexit__`
- All method groups: events, memory, skills, channels, tasks, conversations, executions, traces, triggers, alerts, budget, listen/unlisten
- All `_*_from_row` helper methods

The code is a direct port from the original `memory/db/repository.py` with import paths changed from `memory.db.models` → `brain.db.models` and `mind.models` → `brain.db.models`, plus the addition of `__aenter__`/`__aexit__` and removal of legacy methods.

**Step 2: Verify import**

```bash
cd src && python -c "from brain.db.repository import Repository; print('OK')" && cd ..
```

**Step 3: Commit**

```bash
git add src/brain/db/repository.py
git commit -m "feat(brain): add async Repository — CRUD for all 12 tables"
```

---

### Task 6: Port brain CLI (`cli.py`)

**Files:**
- Create: `src/brain/cli.py`

Port from original `brain/cli.py`. The original imports from `cli.common`, `cli.create`, `cli.destroy`, `cli.inspect` — these modules don't exist yet in our repo. For now, create a self-contained version that stubs the missing imports with lazy loading that gives clear errors.

**Step 1: Write cli.py**

```python
"""cogent brain — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click


class DefaultCommandGroup(click.Group):
    """Group that defaults to a given subcommand when none is provided."""

    def __init__(self, *args, default_cmd: str = "status", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx, args):
        if not args or (args[0].startswith("-") and args[0] != "--help"):
            args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)


def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent name from the root context."""
    name = ctx.find_root().obj.get("cogent_id") if ctx.find_root().obj else None
    if not name:
        raise click.UsageError(
            "No cogent specified. Use: cogent <name> <command> or set COGENT_ID env var."
        )
    return name


@click.group(cls=DefaultCommandGroup, default_cmd="status")
def brain():
    """Manage cogent infrastructure, ECS, and Lambda components."""
    pass


@brain.command("status")
@click.pass_context
def status_cmd(ctx: click.Context):
    """Show infrastructure status for a cogent."""
    from brain.update_cli import update  # noqa: F401 — lazy import check

    name = get_cogent_name(ctx)
    click.echo(f"Status for cogent-{name}: not yet implemented (needs body.aws)")


@brain.command("create")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def create_cmd(ctx: click.Context, profile: str, watch: bool):
    """Deploy a cogent's CloudFormation stack."""
    name = get_cogent_name(ctx)
    click.echo(f"Creating cogent-{name}: not yet implemented (needs body.aws, body.cfn)")


@brain.command("destroy")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--watch", "-w", is_flag=True, help="Wait for deletion to complete")
@click.pass_context
def destroy_cmd(ctx: click.Context, profile: str, yes: bool, watch: bool):
    """Destroy a cogent's CloudFormation stack."""
    name = get_cogent_name(ctx)
    if not yes:
        click.confirm(
            f"This will destroy the stack for cogent-{name}. Continue?",
            abort=True,
        )
    click.echo(f"Destroying cogent-{name}: not yet implemented (needs body.aws)")
```

**Step 2: Verify import**

```bash
cd src && python -c "from brain.cli import brain; print('OK')" && cd ..
```

**Step 3: Commit**

```bash
git add src/brain/cli.py
git commit -m "feat(brain): add brain CLI — status, create, destroy commands"
```

---

### Task 7: Port update CLI (`update_cli.py`)

**Files:**
- Create: `src/brain/update_cli.py`

Port from original `brain/update_cli.py`. The original imports `body.aws.AwsContext` and various CLI helpers. Since those modules don't exist yet, keep the command structure but make the AWS calls lazy-imported with clear error messages.

**Step 1: Write update_cli.py**

Port the full update CLI with all 6 subcommands (all, lambda, discord, ecs, rds, stack, docker). Each command should:
- Have the same Click signature as original (options, flags)
- Lazy-import `body.aws.AwsContext` at call time
- Contain the full AWS logic from the original

```python
"""cogent brain update — update subcommands for individual components."""

from __future__ import annotations

import sys

import click

from brain.cli import DefaultCommandGroup, get_cogent_name


class UpdateGroup(DefaultCommandGroup):
    """Update group that defaults to 'all'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, default_cmd="all", **kwargs)


@click.group(cls=UpdateGroup)
def update():
    """Update components of a running cogent.

    \b
    Default (no subcommand): update Lambda code + Discord bridge service.
    """
    pass


def _get_aws(profile: str):
    """Lazy import AwsContext — fails clearly if body.aws not yet ported."""
    from body.aws import AwsContext

    return AwsContext(profile=profile)


@update.command("all")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for Discord bridge stability")
@click.pass_context
def update_all(ctx: click.Context, profile: str, skip_health: bool):
    """Update Lambda + Discord + DB migrations + mind content (default)."""
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_discord, profile=profile, skip_health=skip_health)
    ctx.invoke(update_rds, profile=profile, force=False)


@update.command("lambda")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str):
    """Update Lambda function code."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating cogent-{name} Lambda functions...")

    from cli.create import _package_and_upload_lambdas

    s3_bucket, s3_key = _package_and_upload_lambdas(session, aws.region)

    lambda_client = session.client("lambda", region_name=aws.region)

    lambda_functions = [
        f"cogent-{safe_name}-orchestrator",
        f"cogent-{safe_name}-reconciler",
        f"cogent-{safe_name}-github-ingestion",
        f"cogent-{safe_name}-api",
        f"cogent-{safe_name}-api-beta",
    ]

    for fn_name in lambda_functions:
        try:
            lambda_client.update_function_code(
                FunctionName=fn_name,
                S3Bucket=s3_bucket,
                S3Key=s3_key,
            )
            click.echo(f"  {fn_name}: {click.style('updated', fg='green')}")
        except lambda_client.exceptions.ResourceNotFoundException:
            click.echo(f"  {fn_name}: {click.style('not found', fg='red')}")
        except Exception as e:
            click.echo(f"  {fn_name}: {click.style(str(e), fg='red')}")

    executor_name = f"cogent-{safe_name}-executor"
    try:
        fn_config = lambda_client.get_function(FunctionName=executor_name)
        image_uri = fn_config["Code"].get("ImageUri", "")
        if image_uri:
            lambda_client.update_function_code(
                FunctionName=executor_name,
                ImageUri=image_uri,
            )
            click.echo(f"  {executor_name}: {click.style('updated (image)', fg='green')}")
        else:
            lambda_client.update_function_code(
                FunctionName=executor_name,
                S3Bucket=s3_bucket,
                S3Key=s3_key,
            )
            click.echo(f"  {executor_name}: {click.style('updated', fg='green')}")
    except lambda_client.exceptions.ResourceNotFoundException:
        click.echo(f"  {executor_name}: {click.style('not found', fg='red')}")
    except Exception as e:
        click.echo(f"  {executor_name}: {click.style(str(e), fg='red')}")

    click.echo(f"  Lambda update for cogent-{name} completed.")


@update.command("discord")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_discord(ctx: click.Context, profile: str, skip_health: bool):
    """Update Discord bridge service (force new ECS deployment)."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating Discord bridge for cogent-{name}...")
    outputs = aws.get_stack_outputs(session, name)
    cluster = outputs.get("ClusterArn", "")
    if not cluster:
        click.echo(f"  No ECS cluster found in stack outputs for cogent-{name}")
        return
    bridge_service = f"cogent-{safe_name}-discord-bridge"

    try:
        ecs = session.client("ecs", region_name=aws.region)
        ecs.update_service(
            cluster=cluster,
            service=bridge_service,
            forceNewDeployment=True,
        )
        click.echo(f"  {bridge_service}: {click.style('new deployment triggered', fg='green')}")

        if not skip_health:
            click.echo("  Waiting for bridge service to stabilize...")
            try:
                aws.wait_for_stable(session, cluster, bridge_service)
                click.echo("  Bridge service stabilized.")
            except Exception as e:
                click.echo(f"  Bridge did not stabilize: {e}", err=True)
    except Exception as e:
        click.echo(f"  {bridge_service}: {click.style(str(e), fg='red')}")


@update.command("ecs")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_ecs(ctx: click.Context, profile: str, skip_health: bool):
    """Force new ECS deployment (new container)."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    ecs_info = aws.get_ecs_info(session, name)
    cluster = ecs_info["cluster_arn"]
    service = ecs_info["service_name"]

    if not cluster or not service:
        click.echo(f"  No ECS service found for cogent-{name}.")
        click.echo("  This cogent may be in serverless mode. Use 'update discord' or 'update lambda' instead.")
        return

    click.echo(f"Forcing new ECS deployment for cogent-{name}...")
    click.echo(f"  Cluster: {cluster}")
    click.echo(f"  Service: {service}")

    aws.force_new_deployment(session, cluster, service)

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            aws.wait_for_stable(session, cluster, service)
            click.echo(f"  ECS deployment for cogent-{name} completed.")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            sys.exit(1)
    else:
        click.echo(f"  ECS deployment for cogent-{name} initiated.")


@update.command("rds")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--force", is_flag=True, help="Force re-run migrations even if already applied")
@click.pass_context
def update_rds(ctx: click.Context, profile: str, force: bool):
    """Run database schema migrations via the migrate Lambda."""
    import json

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    fn_name = f"cogent-{safe_name}-migrate"
    click.echo(f"Running migrations for cogent-{name} via {fn_name}...")

    lambda_client = session.client("lambda", region_name=aws.region)
    try:
        payload = json.dumps({"force": force})
        resp = lambda_client.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=payload.encode(),
        )
        result = json.loads(resp["Payload"].read())
        status_code = result.get("statusCode", 0)

        if status_code == 200:
            body = json.loads(result.get("body", "{}"))
            click.echo(f"  Status: {click.style(body.get('status', 'ok'), fg='green')}")
            click.echo(f"  Database: {body.get('database', '?')}")
            tables = body.get("tables", [])
            if tables:
                click.echo(f"  Tables: {len(tables)}")
                for t in tables:
                    click.echo(f"    {t}")
        else:
            click.echo(f"  Migration failed: {click.style(result.get('body', 'unknown error'), fg='red')}")
            sys.exit(1)
    except lambda_client.exceptions.ResourceNotFoundException:
        click.echo(f"  {fn_name}: {click.style('not found', fg='red')}")
        click.echo("  Hint: the migrate Lambda may not be deployed in this stack.")
        sys.exit(1)
    except Exception as e:
        click.echo(f"  Error: {click.style(str(e), fg='red')}")
        sys.exit(1)


@update.command("stack")
@click.option("--egg", default="ovo", help="Egg config to use")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def update_stack(ctx: click.Context, egg: str, profile: str, watch: bool):
    """Full CloudFormation stack update (repackage + deploy)."""
    from body.aws import stack_name_for
    from cli.create import _deploy_and_wait, _package_and_upload_lambdas
    from polis.aws import find_polis_account
    from polis.eggs.ovo.config import OvoConfig

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)

    egg_config = OvoConfig()
    image_uri = egg_config.resolve_image_uri()

    click.echo(f"Updating stack for cogent-{name}...")
    click.echo(f"  Image: {image_uri}")

    vpc_id, subnet_ids = aws.discover_vpc_and_subnets(session)
    lambda_s3_bucket, lambda_s3_key = _package_and_upload_lambdas(session, aws.region)
    polis_account_id = find_polis_account(aws)

    from body.cfn.template import build_template

    hosted_zone_id = ""
    domain = ""
    try:
        _cfn = session.client("cloudformation", region_name=aws.region)
        polis_resp = _cfn.describe_stacks(StackName="cogent-polis")
        polis_outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in polis_resp["Stacks"][0].get("Outputs", [])
        }
        hosted_zone_id = polis_outputs.get("HostedZoneId", "")
        domain = polis_outputs.get("Domain", "")
    except Exception:
        pass

    template = build_template(
        name,
        polis_account_id=polis_account_id,
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        image_uri=image_uri,
        command=egg_config.brain_command(),
        extra_env=[
            {"Name": "COGENT_POLICY_REPO", "Value": egg_config.policy.repo},
            {"Name": "COGENT_POLICY_BRANCH", "Value": egg_config.policy.branch},
            {"Name": "COGENT_WORKDIR_PATH", "Value": egg_config.workdir_path},
        ],
        egg=egg,
        lambda_s3_bucket=lambda_s3_bucket,
        lambda_s3_key=lambda_s3_key,
        hosted_zone_id=hosted_zone_id,
        domain=domain,
    )

    stack = stack_name_for(name)
    cfn = session.client("cloudformation", region_name=aws.region)
    _deploy_and_wait(cfn, template, stack, watch=watch, name=name)

    click.echo(f"Stack update for cogent-{name} {'completed' if watch else 'submitted'}.")


@update.command("docker")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_docker(ctx: click.Context, profile: str):
    """Build and push Docker image to ECR."""
    import base64
    import subprocess
    from pathlib import Path

    from polis.eggs.ovo.config import OvoConfig

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)

    egg_config = OvoConfig()
    click.echo(f"Building and pushing Docker image for cogent-{name}...")

    image_uri = egg_config.resolve_image_uri()
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = repo_root / "src" / "polis" / "eggs" / "ovo" / "docker" / "Dockerfile"

    ecr = session.client("ecr", region_name=aws.region)
    token = ecr.get_authorization_token()
    auth = token["authorizationData"][0]
    registry = auth["proxyEndpoint"]

    click.echo(f"  Logging into ECR ({registry})...")
    login = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=auth["authorizationToken"],
        capture_output=True,
        text=True,
    )
    if login.returncode != 0:
        decoded = base64.b64decode(auth["authorizationToken"]).decode()
        password = decoded.split(":", 1)[1]
        login = subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", registry],
            input=password,
            capture_output=True,
            text=True,
        )
        if login.returncode != 0:
            raise RuntimeError(f"ECR login failed: {login.stderr}")

    click.echo(f"  Building image: {image_uri}")
    build = subprocess.run(
        ["docker", "build", "-t", image_uri, "-f", str(dockerfile), str(repo_root)],
        capture_output=False,
    )
    if build.returncode != 0:
        raise RuntimeError("Docker build failed")

    click.echo(f"  Pushing image: {image_uri}")
    push = subprocess.run(
        ["docker", "push", image_uri],
        capture_output=False,
    )
    if push.returncode != 0:
        raise RuntimeError("Docker push failed")

    click.echo("  Image built and pushed.")
```

**Step 2: Wire update into brain CLI**

Add the update command to `brain/cli.py`:
```python
from brain.update_cli import update
brain.add_command(update)
```

**Step 3: Verify import**

```bash
cd src && python -c "from brain.cli import brain; print(list(brain.commands.keys()))" && cd ..
```

Expected: `['status', 'create', 'destroy', 'update']`

**Step 4: Commit**

```bash
git add src/brain/
git commit -m "feat(brain): add update CLI — lambda, discord, ecs, rds, stack, docker"
```

---

### Task 8: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

Ensure `src/brain` is in the packages list and hatch sources.

**Step 1: Verify pyproject.toml already includes brain**

Check that `src/brain` is already in `[tool.hatch.build.targets.wheel] packages` — it should be since the original pyproject.toml already lists it.

**Step 2: Commit if changed**

Only commit if a change was needed.

---

### Task 9: Write documentation

**Files:**
- Create: `docs/brain/README.md`
- Create: `docs/brain/schema.md`
- Create: `docs/brain/repository-api.md`
- Create: `docs/brain/cli.md`

**Step 1: Write docs/brain/README.md**

Overview doc with architecture diagram, quickstart, and links to other docs.

**Step 2: Write docs/brain/schema.md**

Table-by-table documentation of the PostgreSQL schema.

**Step 3: Write docs/brain/repository-api.md**

Full Repository method reference organized by domain group.

**Step 4: Write docs/brain/cli.md**

CLI command reference for brain status/create/destroy/update.

**Step 5: Commit**

```bash
git add docs/brain/
git commit -m "docs(brain): add brain system documentation"
```

---

### Task 10: Final verification and cleanup

**Step 1: Run ruff lint**

```bash
ruff check src/brain/
```

Fix any issues found.

**Step 2: Run pyright type check**

```bash
pyright src/brain/
```

Fix any type errors.

**Step 3: Verify all imports work**

```bash
cd src && python -c "
from brain.db import Repository, MemoryRecord, Event, Task, Trigger
from brain.db.migrations import apply_schema, reset_schema
from brain.cli import brain
print('All imports OK')
print(f'Brain CLI commands: {list(brain.commands.keys())}')
" && cd ..
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore(brain): lint fixes and final cleanup"
```
