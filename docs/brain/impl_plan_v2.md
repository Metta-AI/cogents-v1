# Body Port Implementation Plan — Lambda, ECS, EventBridge, CDK

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port lambda handlers, ECS compute, and EventBridge routing into `src/brain/`, with Data API backend, CDK infrastructure, and skills→programs/executions→runs rename.

**Architecture:** Event-driven system where EventBridge delivers events to an Orchestrator Lambda that matches triggers and dispatches to Executor (Lambda for short tasks, ECS Fargate for long tasks). Executor runs programs via Bedrock converse API (Lambda) or Claude Code CLI (ECS). All DB access through RDS Data API.

**Tech Stack:** Python 3.12, boto3 (rds-data, bedrock-runtime, lambda, ecs, events), Pydantic v2, Click, AWS CDK v2

**Reference files (original metta-ai/cogents repo, fetch with `gh api repos/metta-ai/cogents/contents/<path> --jq '.content' | base64 -d`):**
- `src/body/lambdas/shared/config.py` — LambdaConfig dataclass
- `src/body/lambdas/shared/db.py` — DataApiRepository singleton
- `src/body/lambdas/shared/events.py` — EventBridge ↔ Event converters
- `src/body/lambdas/orchestrator/handler.py` — Orchestrator (484 lines)
- `src/body/lambdas/executor/handler.py` — Executor (782 lines)
- `src/body/lambdas/executor/ecs_entry.py` — ECS entry point
- `src/memory/db/models.py` — Original models
- `src/memory/db/repository.py` — Original asyncpg repository

---

### Task 1: Rename skills→programs and executions→runs in models

**Files:**
- Modify: `src/brain/db/models.py`

**Context:** The user wants a full rename: Skill→Program, Execution→Run, ExecutionStatus→RunStatus. Also add `ComputeTier` enum and new fields to Program (compute_tier, tools) and Run (model_version).

**Step 1: Update models.py**

Rename in `src/brain/db/models.py`:
- `ExecutionStatus` → `RunStatus` (keep same values: running, completed, failed, timeout)
- `Skill` class → `Program` class:
  - `skill_type` → `program_type`
  - Add `compute_tier: ComputeTier = ComputeTier.LAMBDA`
  - Add `tools: list[str] = Field(default_factory=list)`
- `Execution` class → `Run` class:
  - `skill_name` → `program_name`
  - `status: ExecutionStatus` → `status: RunStatus`
  - Add `model_version: str | None = None`
- `Trace` class: `execution_id` → `run_id`
- `Trigger` class: `skill_name` → `program_name`
- Add new enum:
```python
class ComputeTier(str, enum.Enum):
    LAMBDA = "lambda"
    ECS = "ecs"
```

**Step 2: Commit**

```bash
git add src/brain/db/models.py
git commit -m "refactor(brain): rename skills→programs, executions→runs in models"
```

---

### Task 2: Rename skills→programs and executions→runs in schema.sql

**Files:**
- Modify: `src/brain/db/schema.sql`

**Context:** Match the model renames in the database schema.

**Step 1: Update schema.sql**

- Rename table `skills` → `programs`:
  - Column `skill_type` → `program_type`
  - CHECK constraint values stay same (`markdown`, `python`)
  - Add column: `compute_tier TEXT NOT NULL DEFAULT 'lambda' CHECK (compute_tier IN ('lambda', 'ecs'))`
  - Add column: `tools JSONB NOT NULL DEFAULT '[]'`
  - Index: `idx_skills_type` → `idx_programs_type` (on `program_type`)
- Rename table `executions` → `runs`:
  - Column `skill_name` → `program_name`
  - Status CHECK stays same (`running`, `completed`, `failed`, `timeout`)
  - Add column: `model_version TEXT`
  - Indexes: rename `idx_executions_*` → `idx_runs_*`, reference `program_name` instead of `skill_name`
- Table `traces`: `execution_id` → `run_id`, FK reference `runs(id)` instead of `executions(id)`, index renamed
- Table `triggers`: `skill_name` → `program_name`
- Bump schema version to 2: `INSERT INTO schema_version (version) VALUES (2) ON CONFLICT DO NOTHING;`

**Step 2: Update migrations.py**

Update `reset_schema()` DROP statements to use new table names (`programs` instead of `skills`, `runs` instead of `executions`).

**Step 3: Commit**

```bash
git add src/brain/db/schema.sql src/brain/db/migrations.py
git commit -m "refactor(brain): rename skills→programs, executions→runs in schema"
```

---

### Task 3: Rewrite Repository to use RDS Data API

**Files:**
- Rewrite: `src/brain/db/repository.py`

**Context:** Replace asyncpg with boto3 rds-data client. All methods become synchronous. Use named parameters (`:name` syntax). Remove LISTEN/NOTIFY. Apply the skills→programs and executions→runs renames to all method names and SQL.

**Step 1: Rewrite repository.py**

The new Repository class:

```python
class Repository:
    """RDS Data API repository: CRUD for all 12 tables."""

    def __init__(self, client, resource_arn: str, secret_arn: str, database: str) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database

    @classmethod
    def create(cls, resource_arn: str | None = None, secret_arn: str | None = None,
               database: str | None = None) -> Repository:
        """Create from explicit args or env vars."""
        import boto3
        client = boto3.client("rds-data")
        return cls(
            client=client,
            resource_arn=resource_arn or os.environ["DB_RESOURCE_ARN"],
            secret_arn=secret_arn or os.environ["DB_SECRET_ARN"],
            database=database or os.environ.get("DB_NAME", "cogent"),
        )

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
        pass  # no persistent connection to close

    def _execute(self, sql: str, params: list[dict] | None = None) -> dict:
        kwargs = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "includeResultMetadata": True,
        }
        if params:
            kwargs["parameters"] = params
        return self._client.execute_statement(**kwargs)

    def _param(self, name: str, value) -> dict:
        """Build a Data API parameter dict from a Python value."""
        if value is None:
            return {"name": name, "value": {"isNull": True}}
        if isinstance(value, bool):
            return {"name": name, "value": {"booleanValue": value}}
        if isinstance(value, int):
            return {"name": name, "value": {"longValue": value}}
        if isinstance(value, float):
            return {"name": name, "value": {"doubleValue": value}}
        if isinstance(value, Decimal):
            return {"name": name, "value": {"stringValue": str(value)}}
        if isinstance(value, UUID):
            return {"name": name, "value": {"stringValue": str(value)}}
        if isinstance(value, (datetime, date)):
            return {"name": name, "value": {"stringValue": value.isoformat()}}
        if isinstance(value, (dict, list)):
            return {"name": name, "value": {"stringValue": json.dumps(value)}}
        return {"name": name, "value": {"stringValue": str(value)}}

    def _rows_to_dicts(self, response: dict) -> list[dict[str, Any]]:
        """Convert Data API response to list of dicts."""
        columns = [col["name"] for col in response.get("columnMetadata", [])]
        result = []
        for row in response.get("records", []):
            d = {}
            for col_name, cell in zip(columns, row):
                d[col_name] = self._extract_value(cell)
            result.append(d)
        return result

    @staticmethod
    def _extract_value(cell: dict):
        if "isNull" in cell and cell["isNull"]:
            return None
        if "longValue" in cell:
            return cell["longValue"]
        if "doubleValue" in cell:
            return cell["doubleValue"]
        if "booleanValue" in cell:
            return cell["booleanValue"]
        if "stringValue" in cell:
            return cell["stringValue"]
        if "blobValue" in cell:
            return cell["blobValue"]
        if "arrayValue" in cell:
            return cell["arrayValue"]
        return None
```

Port all existing method groups with these changes:
- Drop `async/await` from all methods
- Replace `self._pool.fetchrow(...)` / `self._pool.fetch(...)` / `self._pool.execute(...)` with `self._execute(...)` + `self._rows_to_dicts(...)`
- Replace positional params (`$1, $2`) with named params (`:param_name`)
- Replace `asyncpg.Record` access with dict access
- Rename skill methods → program methods, execution methods → run methods
- Remove `_from_row` methods that reference `asyncpg.Record` — replace with dict-based parsing
- Remove `listen()`, `unlisten()`, `notify_trigger_change()` (no pub/sub in Data API)

**Method rename mapping:**
- `upsert_skill()` → `upsert_program()`
- `list_skills()` → `list_programs()`
- `delete_skill()` → `delete_program()`
- `insert_execution()` → `insert_run()`
- `update_execution()` → `update_run()`
- `query_executions()` → `query_runs()`
- All SQL references: `skills` → `programs`, `skill_name` → `program_name`, `skill_type` → `program_type`, `executions` → `runs`, `execution_id` → `run_id`

**Step 2: Commit**

```bash
git add src/brain/db/repository.py
git commit -m "refactor(brain): rewrite Repository to use RDS Data API"
```

---

### Task 4: Update db/__init__.py and brain/__init__.py exports

**Files:**
- Modify: `src/brain/db/__init__.py`

**Context:** Update exports to reflect renames (Skill→Program, Execution→Run, ExecutionStatus→RunStatus, add ComputeTier).

**Step 1: Update exports**

In `src/brain/db/__init__.py`:
- Replace `Skill` with `Program`
- Replace `Execution` with `Run`
- Replace `ExecutionStatus` with `RunStatus`
- Add `ComputeTier`
- Update `__all__` list

**Step 2: Commit**

```bash
git add src/brain/db/__init__.py
git commit -m "refactor(brain): update db exports for renames"
```

---

### Task 5: Shared Lambda infrastructure

**Files:**
- Create: `src/brain/lambdas/__init__.py`
- Create: `src/brain/lambdas/shared/__init__.py`
- Create: `src/brain/lambdas/shared/config.py`
- Create: `src/brain/lambdas/shared/db.py`
- Create: `src/brain/lambdas/shared/events.py`
- Create: `src/brain/lambdas/shared/logging.py`

**Context:** Port from original `src/body/lambdas/shared/`. These are utility modules used by all Lambda handlers.

**Step 1: Create config.py**

Port `LambdaConfig` from original. Frozen dataclass loading from env vars:

```python
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class LambdaConfig:
    cogent_name: str
    cogent_id: str
    db_cluster_arn: str
    db_secret_arn: str
    db_name: str
    efs_path: str
    event_bus_name: str
    region: str
    executor_function_name: str = ""
    ecs_cluster_arn: str = ""
    ecs_task_definition: str = ""
    ecs_subnets: str = ""
    ecs_security_group: str = ""

_config: LambdaConfig | None = None

def get_config() -> LambdaConfig:
    global _config
    if _config is None:
        _config = LambdaConfig(
            cogent_name=os.environ["COGENT_NAME"],
            cogent_id=os.environ.get("COGENT_ID", os.environ["COGENT_NAME"]),
            db_cluster_arn=os.environ["DB_CLUSTER_ARN"],
            db_secret_arn=os.environ["DB_SECRET_ARN"],
            db_name=os.environ.get("DB_NAME", "cogent"),
            efs_path=os.environ.get("EFS_PATH", "/mnt/cogent"),
            event_bus_name=os.environ.get("EVENT_BUS_NAME", "default"),
            region=os.environ.get("AWS_REGION", "us-east-1"),
            executor_function_name=os.environ.get("EXECUTOR_FUNCTION_NAME", ""),
            ecs_cluster_arn=os.environ.get("ECS_CLUSTER_ARN", ""),
            ecs_task_definition=os.environ.get("ECS_TASK_DEFINITION", ""),
            ecs_subnets=os.environ.get("ECS_SUBNETS", ""),
            ecs_security_group=os.environ.get("ECS_SECURITY_GROUP", ""),
        )
    return _config
```

**Step 2: Create db.py**

Singleton Data API Repository:

```python
from brain.db.repository import Repository
from brain.lambdas.shared.config import get_config

_repo: Repository | None = None

def get_repo() -> Repository:
    global _repo
    if _repo is None:
        config = get_config()
        _repo = Repository.create(
            resource_arn=config.db_cluster_arn,
            secret_arn=config.db_secret_arn,
            database=config.db_name,
        )
    return _repo
```

**Step 3: Create events.py**

Port EventBridge ↔ Event converters from original:

```python
import json
import boto3
from brain.db.models import Event

def to_eventbridge(event: Event, bus_name: str) -> dict:
    """Convert Event model to EventBridge PutEvents entry."""
    return {
        "Source": f"cogent.{event.cogent_id}",
        "DetailType": event.event_type,
        "Detail": json.dumps({
            "cogent_id": event.cogent_id,
            "event_type": event.event_type,
            "source": event.source,
            "payload": event.payload,
            "parent_event_id": event.parent_event_id,
        }),
        "EventBusName": bus_name,
    }

def from_eventbridge(eb_event: dict) -> Event:
    """Convert EventBridge event dict to Event model."""
    detail = eb_event.get("detail", {})
    if isinstance(detail, str):
        detail = json.loads(detail)
    return Event(
        cogent_id=detail.get("cogent_id", ""),
        event_type=detail.get("event_type", eb_event.get("detail-type", "")),
        source=detail.get("source", eb_event.get("source", "")),
        payload=detail.get("payload", {}),
        parent_event_id=detail.get("parent_event_id"),
    )

def put_event(event: Event, bus_name: str) -> None:
    """Publish an event to EventBridge."""
    client = boto3.client("events")
    client.put_events(Entries=[to_eventbridge(event, bus_name)])
```

**Step 4: Create logging.py**

Structured CloudWatch JSON logging:

```python
import json
import logging
import sys

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "cogent_id"):
            log_entry["cogent_id"] = record.cogent_id
        if hasattr(record, "run_id"):
            log_entry["run_id"] = record.run_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

def setup_logging(level: str = "INFO") -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level))
    return root
```

**Step 5: Commit**

```bash
git add src/brain/lambdas/
git commit -m "feat(brain): add shared Lambda infrastructure (config, db, events, logging)"
```

---

### Task 6: Orchestrator handler

**Files:**
- Create: `src/brain/lambdas/orchestrator/__init__.py`
- Create: `src/brain/lambdas/orchestrator/handler.py`

**Context:** Port from original `src/body/lambdas/orchestrator/handler.py`. This is the event router: receives EventBridge events, matches triggers, dispatches to executor Lambda or ECS Fargate.

**Step 1: Create handler.py**

Key components to port:

1. **TriggerCache** — Module-level cache with 60s TTL. Loads enabled triggers from DB, refreshes on TTL expiry.

2. **handler(event, context)** — Main Lambda entry:
   - Parse EventBridge event via `from_eventbridge()`
   - Log event to DB via `repo.append_event()`
   - Load matching triggers from cache
   - For each match:
     - Load program via `repo.get_program()` (was `get_skill`)
     - Check `program.compute_tier`:
       - `LAMBDA` → `lambda_client.invoke(executor_function_name, payload, InvocationType='Event')`
       - `ECS` → `ecs_client.run_task(cluster, task_def, overrides with EXECUTOR_PAYLOAD env var)`
   - Return dispatch summary

3. **Trigger matching** — Match `event.event_type` against `trigger.event_pattern`. Patterns support exact match and prefix glob (`skill:*`).

4. **Cascade guard** — Skip triggers where the trigger's program_name matches the event source (prevents infinite loops from `program:failed:X` re-triggering X).

Changes from original:
- `skill_name` → `program_name` throughout
- `compute_seconds > 600` check replaced by `program.compute_tier == ComputeTier.ECS`
- Uses shared logging module for structured CloudWatch logs
- All DB calls via Data API (synchronous)

**Step 2: Commit**

```bash
git add src/brain/lambdas/orchestrator/
git commit -m "feat(brain): add orchestrator Lambda handler"
```

---

### Task 7: Executor handler (Lambda path)

**Files:**
- Create: `src/brain/lambdas/executor/__init__.py`
- Create: `src/brain/lambdas/executor/handler.py`

**Context:** Port from original `src/body/lambdas/executor/handler.py`. This handles program execution on Lambda using Bedrock converse API with tool use.

**Step 1: Create handler.py**

Key components:

1. **handler(event, context)** — Main Lambda entry:
   - Parse trigger + event from payload
   - Load program from DB
   - Create run record (status=running)
   - Execute program via Bedrock converse API
   - Update run record with results
   - Emit completion/failure events

2. **Bedrock tool-use loop**:
   ```python
   def execute_program(program: Program, event: Event, run: Run, repo: Repository) -> Run:
       bedrock = boto3.client("bedrock-runtime")
       messages = [{"role": "user", "content": [{"text": build_user_prompt(program, event)}]}]
       system = [{"text": program.content}]
       tools = build_tool_config(program.tools)  # mind CLI commands

       while True:
           response = bedrock.converse(
               modelId=program.model_version or "anthropic.claude-sonnet-4-20250514",
               messages=messages,
               system=system,
               toolConfig={"tools": tools} if tools else {},
           )
           output = response["output"]["message"]
           messages.append(output)
           stop_reason = response["stopReason"]

           if stop_reason == "tool_use":
               tool_results = []
               for block in output["content"]:
                   if "toolUse" in block:
                       result = execute_tool(block["toolUse"])
                       tool_results.append({"toolResult": {
                           "toolUseId": block["toolUse"]["toolUseId"],
                           "content": [{"text": result}],
                       }})
               messages.append({"role": "user", "content": tool_results})
           else:
               break

       # Update run with token usage, cost, etc.
       usage = response.get("usage", {})
       run.tokens_input = usage.get("inputTokens", 0)
       run.tokens_output = usage.get("outputTokens", 0)
       run.status = RunStatus.COMPLETED
       return run
   ```

3. **Tool execution** — Each tool in `program.tools` is a mind CLI command. Execute via subprocess: `mind <command> <args>`.

4. **Memory context** — Load relevant memory records based on program config and inject into system prompt.

5. **Conversation support** — Track conversation via context_key, persist messages.

Changes from original:
- Uses Bedrock converse API instead of direct Anthropic SDK
- `skill` → `program`, `execution` → `run` throughout
- Structured CloudWatch logging
- Simplified: removed Python skill execution path (only Bedrock + tools)

**Step 2: Commit**

```bash
git add src/brain/lambdas/executor/
git commit -m "feat(brain): add executor Lambda handler with Bedrock tool-use loop"
```

---

### Task 8: Executor ECS entry point

**Files:**
- Create: `src/brain/lambdas/executor/ecs_entry.py`

**Context:** Port from original `src/body/lambdas/executor/ecs_entry.py`. Entry point for Fargate tasks that runs programs via Claude Code CLI.

**Step 1: Create ecs_entry.py**

```python
"""ECS Fargate entry point — runs programs via Claude Code CLI."""

import json
import os
import subprocess
import sys
import time

from brain.db.models import RunStatus
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import put_event
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()

def main():
    payload_json = os.environ.get("EXECUTOR_PAYLOAD", "{}")
    payload = json.loads(payload_json)

    config = get_config()
    repo = get_repo()

    trigger = payload.get("trigger", {})
    event_data = payload.get("event", {})
    program_name = trigger.get("program_name", "")

    program = repo.get_program(config.cogent_id, program_name)
    if not program:
        logger.error(f"Program not found: {program_name}")
        sys.exit(1)

    # Create run record
    from brain.db.models import Run
    run = Run(cogent_id=config.cogent_id, program_name=program_name)
    run_id = repo.insert_run(run)

    start_time = time.time()

    try:
        # Build Claude Code CLI command
        cmd = ["claude", "--model", program.model_version or "sonnet"]
        if program.tools:
            cmd.extend(["--allowedTools", ",".join(program.tools)])
        cmd.extend(["--prompt", program.content])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

        duration_ms = int((time.time() - start_time) * 1000)
        run.status = RunStatus.COMPLETED if result.returncode == 0 else RunStatus.FAILED
        run.duration_ms = duration_ms
        if result.returncode != 0:
            run.error = result.stderr[:4000]
        repo.update_run(run)

    except Exception as e:
        run.status = RunStatus.FAILED
        run.error = str(e)[:4000]
        run.duration_ms = int((time.time() - start_time) * 1000)
        repo.update_run(run)
        raise

if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/brain/lambdas/executor/ecs_entry.py
git commit -m "feat(brain): add ECS Fargate entry point for Claude Code CLI execution"
```

---

### Task 9: CDK infrastructure — constructs

**Files:**
- Create: `src/brain/cdk/__init__.py`
- Create: `src/brain/cdk/config.py`
- Create: `src/brain/cdk/constructs/__init__.py`
- Create: `src/brain/cdk/constructs/network.py`
- Create: `src/brain/cdk/constructs/database.py`
- Create: `src/brain/cdk/constructs/storage.py`
- Create: `src/brain/cdk/constructs/compute.py`
- Create: `src/brain/cdk/constructs/eventbridge.py`
- Create: `src/brain/cdk/constructs/monitoring.py`

**Context:** Replace the original CloudFormation templates with AWS CDK v2 constructs. Each construct is a self-contained unit.

**Step 1: Create config.py**

```python
from dataclasses import dataclass, field

@dataclass
class BrainConfig:
    cogent_name: str
    region: str = "us-east-1"
    db_min_acu: float = 0.5
    db_max_acu: float = 4.0
    executor_memory_mb: int = 2048
    executor_timeout_s: int = 900
    orchestrator_memory_mb: int = 512
    orchestrator_timeout_s: int = 60
    ecs_cpu: int = 2048       # 2 vCPU
    ecs_memory: int = 4096    # 4 GB
    ecs_timeout_s: int = 3600 # 1 hour
```

**Step 2: Create constructs**

Each construct is a `constructs.Construct` subclass:

- **network.py**: VPC with 2 AZs, private subnets (for Aurora, ECS), public subnets (NAT), security groups
- **database.py**: Aurora Serverless v2, PostgreSQL 15, Data API enabled, Secrets Manager secret, auto-scaling
- **storage.py**: EFS filesystem (for Claude Code sessions, program artifacts), access points
- **compute.py**: Orchestrator Lambda, Executor Lambda, ECS Cluster + Fargate task definition (with EFS mount, Claude Code CLI)
- **eventbridge.py**: Custom event bus, catch-all rule routing to orchestrator Lambda
- **monitoring.py**: CloudWatch log groups, error rate alarms

**Step 3: Commit**

```bash
git add src/brain/cdk/
git commit -m "feat(brain): add CDK constructs (network, database, storage, compute, eventbridge, monitoring)"
```

---

### Task 10: CDK stack and app entry point

**Files:**
- Create: `src/brain/cdk/stack.py`
- Create: `src/brain/cdk/app.py`

**Context:** Compose all constructs into a single BrainStack, and create the CDK app entry point.

**Step 1: Create stack.py**

```python
from aws_cdk import Stack
from constructs import Construct
from brain.cdk.config import BrainConfig
from brain.cdk.constructs.network import NetworkConstruct
from brain.cdk.constructs.database import DatabaseConstruct
from brain.cdk.constructs.storage import StorageConstruct
from brain.cdk.constructs.compute import ComputeConstruct
from brain.cdk.constructs.eventbridge import EventBridgeConstruct
from brain.cdk.constructs.monitoring import MonitoringConstruct

class BrainStack(Stack):
    def __init__(self, scope: Construct, id: str, config: BrainConfig, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.network = NetworkConstruct(self, "Network", config=config)
        self.database = DatabaseConstruct(self, "Database", config=config, vpc=self.network.vpc)
        self.storage = StorageConstruct(self, "Storage", config=config, vpc=self.network.vpc)
        self.compute = ComputeConstruct(self, "Compute", config=config, ...)
        self.eventbridge = EventBridgeConstruct(self, "EventBridge", config=config, ...)
        self.monitoring = MonitoringConstruct(self, "Monitoring", config=config, ...)
```

**Step 2: Create app.py**

```python
import aws_cdk as cdk
from brain.cdk.config import BrainConfig
from brain.cdk.stack import BrainStack

app = cdk.App()
cogent_name = app.node.try_get_context("cogent_name") or "default"
config = BrainConfig(cogent_name=cogent_name)
BrainStack(app, f"cogent-{cogent_name}-brain", config=config)
app.synth()
```

**Step 3: Commit**

```bash
git add src/brain/cdk/stack.py src/brain/cdk/app.py
git commit -m "feat(brain): add CDK stack and app entry point"
```

---

### Task 11: Update CLI for CDK deployment

**Files:**
- Modify: `src/brain/cli.py`
- Modify: `src/brain/update_cli.py`

**Context:** Update the brain CLI to use CDK instead of CloudFormation for create/destroy/update operations.

**Step 1: Update cli.py**

- `brain create` → runs `cdk deploy` with the BrainStack
- `brain destroy` → runs `cdk destroy`
- `brain status` → queries AWS for stack/resource status

**Step 2: Update update_cli.py**

- `update stack` → runs `cdk deploy` instead of CloudFormation update
- `update lambda` → keep direct Lambda code update via boto3
- `update ecs` → keep direct ECS force deployment
- `update rds` → invoke `apply_schema()` via Data API directly (no migrate Lambda needed)
- Remove `update docker` for now (CDK handles container images)
- Remove `update discord` (channel handlers skipped)

**Step 3: Commit**

```bash
git add src/brain/cli.py src/brain/update_cli.py
git commit -m "feat(brain): update CLI for CDK deployment"
```

---

### Task 12: Update pyproject.toml and dependencies

**Files:**
- Modify: `pyproject.toml`

**Context:** Add `aws-cdk-lib` dependency, remove `asyncpg` (replaced by Data API), add `pyright` include for new paths.

**Step 1: Update pyproject.toml**

- Add to dependencies: `"aws-cdk-lib>=2.170.0"`, `"constructs>=10.0"`
- Remove from dependencies: `"asyncpg>=0.30.0"` (replaced by boto3 rds-data)
- Remove from dependencies: `"uvloop>=0.21.0"` (no async event loop needed)
- Add `src/brain/lambdas` and `src/brain/cdk` to pyright include
- Add `src/brain/cdk` to hatch packages

**Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: update dependencies for Data API + CDK, remove asyncpg"
```

---

### Task 13: Lint and final cleanup

**Files:**
- All modified files

**Step 1: Run ruff**

```bash
cd /Users/daveey/code/cogents/cogents.1
ruff check src/brain/ --fix
ruff format src/brain/
```

**Step 2: Run pyright**

```bash
pyright src/brain/
```

Fix any type errors.

**Step 3: Commit fixes**

```bash
git add -A
git commit -m "chore(brain): lint cleanup and type fixes"
```
