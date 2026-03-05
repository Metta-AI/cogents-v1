# Body Port Design — Lambda, ECS, EventBridge, CDK

## Overview

Port the cogent body system (lambda handlers, ECS compute, EventBridge routing) into `src/brain/`. Replace CloudFormation with CDK. Replace asyncpg with RDS Data API everywhere. Rename skills→programs, executions→runs.

## Scope

**Porting:**
- Orchestrator handler (event routing + trigger matching + dispatch)
- Executor handler (program execution via Bedrock converse API on Lambda, Claude Code CLI on ECS)
- Shared Lambda infrastructure (config, DB singleton, EventBridge converters, CloudWatch logging)
- CDK infrastructure (single stack, modular constructs)
- ECS Fargate task definition + entry point

**Skipping (for now):**
- API handler (observability REST API)
- Reconciler handler (cron trigger sync)
- Migrate handler (existing migrations.py suffices)
- Channel handlers (discord_bridge, github_ingestion, gmail_poller, asana_poller)

## Key Architectural Changes from Original

1. **Data API everywhere** — Replace asyncpg with boto3 `rds-data` client. Repository becomes synchronous. Remove asyncpg dependency.
2. **CDK instead of CloudFormation** — Single `BrainStack` with modular constructs.
3. **skills→programs** — Full rename across models, schema, repository, triggers, handlers.
4. **executions→runs** — Full rename across models, schema, repository, handlers.
5. **Program-defined compute tier** — Each program specifies `compute_tier: lambda | ecs` instead of inferring from duration.
6. **Program-defined tools** — Programs list their available tools (mind CLI commands).
7. **Bedrock converse API** — Lambda executor uses Bedrock (not Anthropic SDK) for tool-use loop.
8. **Claude Code CLI on ECS** — Fargate tasks run `claude` CLI instead of API calls.
9. **CloudWatch structured logging** — JSON format with correlation IDs.

## Module Structure

```
src/brain/
├── __init__.py              # (existing) Public API exports
├── cli.py                   # (existing) Brain CLI group
├── update_cli.py            # (existing) Update subcommands — update for CDK
├── db/
│   ├── __init__.py          # (modify) Update exports for renames
│   ├── schema.sql           # (modify) Rename skills→programs, executions→runs
│   ├── models.py            # (modify) Skill→Program, Execution→Run, add fields
│   ├── repository.py        # (rewrite) Data API backend, sync, renamed methods
│   └── migrations.py        # (modify) Data API instead of asyncpg
├── lambdas/
│   ├── __init__.py
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── config.py        # LambdaConfig dataclass (env vars, resource ARNs)
│   │   ├── db.py            # Data API Repository singleton (warm cached)
│   │   ├── events.py        # EventBridge ↔ Event model converters
│   │   └── logging.py       # CloudWatch structured JSON logging
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── handler.py       # Event routing + trigger matching + dispatch
│   └── executor/
│       ├── __init__.py
│       ├── handler.py       # Program execution (Lambda — Bedrock tool-use loop)
│       └── ecs_entry.py     # Program execution (Fargate — Claude Code CLI)
└── cdk/
    ├── __init__.py
    ├── app.py               # CDK app entry point
    ├── stack.py             # BrainStack (top-level)
    ├── constructs/
    │   ├── __init__.py
    │   ├── network.py       # VPC, subnets, security groups
    │   ├── database.py      # Aurora Serverless v2, Data API enabled
    │   ├── storage.py       # EFS, S3 buckets
    │   ├── compute.py       # Lambda functions, ECS cluster/tasks
    │   ├── eventbridge.py   # Event bus, rules
    │   └── monitoring.py    # CloudWatch alarms, dashboards
    └── config.py            # Stack configuration (cogent name, region, etc.)
```

## Data Model Changes

### Renames

| Old | New |
|-----|-----|
| `Skill` model | `Program` model |
| `skill_name` fields | `program_name` fields |
| `skill_type` field | `program_type` field |
| `skills` DB table | `programs` DB table |
| `Execution` model | `Run` model |
| `execution_id` fields | `run_id` fields |
| `executions` DB table | `runs` DB table |
| `ExecutionStatus` enum | `RunStatus` enum |
| `upsert_skill()` | `upsert_program()` |
| `list_skills()` | `list_programs()` |
| `insert_execution()` | `insert_run()` |
| `update_execution()` | `update_run()` |
| `query_executions()` | `query_runs()` |

### New Fields on Program

```python
class ComputeTier(str, enum.Enum):
    LAMBDA = "lambda"
    ECS = "ecs"

class Program(BaseModel):
    # ... existing fields renamed from Skill ...
    compute_tier: ComputeTier = ComputeTier.LAMBDA
    tools: list[str] = Field(default_factory=list)  # mind CLI command names
```

### New Fields on Run

```python
class Run(BaseModel):
    # ... existing fields renamed from Execution ...
    model_version: str | None = None  # Bedrock model ID used
```

## Repository Rewrite — Data API

### Current (asyncpg, async)

```python
class Repository:
    def __init__(self, pool: asyncpg.Pool) -> None: ...

    @classmethod
    async def create(cls, dsn: str) -> Repository: ...

    async def append_event(self, event: Event) -> int:
        row = await self.pool.fetchrow(
            "INSERT INTO events (event_type, source, payload) VALUES ($1, $2, $3) RETURNING id",
            event.event_type, event.source, json.dumps(event.payload)
        )
        return row["id"]
```

### New (Data API, sync)

```python
class Repository:
    def __init__(self, client, resource_arn: str, secret_arn: str, database: str) -> None:
        self.client = client  # boto3 rds-data client
        self.resource_arn = resource_arn
        self.secret_arn = secret_arn
        self.database = database

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

    def _execute(self, sql: str, params: list[dict] | None = None) -> dict:
        """Execute a statement via Data API."""
        kwargs = {
            "resourceArn": self.resource_arn,
            "secretArn": self.secret_arn,
            "database": self.database,
            "sql": sql,
        }
        if params:
            kwargs["parameters"] = params
        return self.client.execute_statement(**kwargs)

    def append_event(self, event: Event) -> int:
        resp = self._execute(
            "INSERT INTO events (event_type, source, payload) VALUES (:event_type, :source, :payload::jsonb) RETURNING id",
            [
                {"name": "event_type", "value": {"stringValue": event.event_type}},
                {"name": "source", "value": {"stringValue": event.source}},
                {"name": "payload", "value": {"stringValue": json.dumps(event.payload)}},
            ]
        )
        return resp["records"][0][0]["longValue"]
```

### Key Changes

- **Synchronous** — All methods drop `async/await`
- **Named parameters** — `:name` syntax instead of `$1, $2`
- **Data API parameter format** — `[{"name": ..., "value": {"stringValue": ...}}]`
- **Remove LISTEN/NOTIFY** — Data API doesn't support pub/sub
- **Remove connection pool** — Each call is HTTP, no pool management
- **Remove asyncpg dependency** — Only boto3 needed
- **Context manager still works** — `__enter__`/`__exit__` (sync) for cleanup

## Lambda Handlers

### Orchestrator (`lambdas/orchestrator/handler.py`)

```
EventBridge event → handler(event, context)
  1. Convert EB event → Event model (via shared/events.py)
  2. Load triggers (warm cache, TTL-based refresh)
  3. Match event_type against trigger patterns
  4. For each match:
     a. Log event to DB (repo.append_event)
     b. Load program (repo.get_program)
     c. If program.compute_tier == LAMBDA:
        → boto3 lambda.invoke(executor_function_arn, payload)
     d. If program.compute_tier == ECS:
        → boto3 ecs.run_task(cluster, task_def, overrides with event payload)
  5. Return dispatch summary
```

### Executor — Lambda path (`lambdas/executor/handler.py`)

```
Lambda invoke → handler(event, context)
  1. Parse trigger + event from payload
  2. Load program from DB
  3. Create run record (status=running)
  4. Build Bedrock converse request:
     - model_id from program or default
     - system prompt from program.content
     - tools from program.tools → tool definitions
  5. Tool-use loop:
     a. Call bedrock.converse(messages, tools, system)
     b. If response has tool_use:
        - Execute mind CLI command (subprocess)
        - Append tool result to messages
        - Go to (a)
     c. If response is end_turn:
        - Extract final text
        - Break
  6. Update run record (status=completed, tokens, cost, duration)
  7. Emit result events if specified
```

### Executor — ECS path (`lambdas/executor/ecs_entry.py`)

```
Fargate task → main()
  1. Parse trigger + event from env/EFS
  2. Load program from DB
  3. Create run record (status=running)
  4. Run Claude Code CLI:
     - claude --model <model> --prompt <program.content> --allowedTools <tools>
  5. Capture output
  6. Update run record (status=completed, tokens, cost, duration)
```

## CDK Infrastructure

### BrainStack (`cdk/stack.py`)

Single stack composed of modular constructs, parameterized by cogent name.

### Constructs

**`network.py`** — VPC with 2 private subnets (for Aurora, ECS), 2 public subnets (for NAT), security groups.

**`database.py`** — Aurora Serverless v2 cluster, PostgreSQL 15, Data API enabled, auto-scaling (0.5-4 ACU), secret in Secrets Manager.

**`storage.py`** — EFS filesystem for Claude Code sessions and program artifacts. S3 bucket for deployment assets.

**`compute.py`**:
- Orchestrator Lambda: 512MB, 60s timeout, EventBridge trigger
- Executor Lambda: 2048MB, 900s timeout, invoked by orchestrator
- ECS Cluster (Fargate)
- ECS Task Definition: 2vCPU, 4GB RAM, EFS mount, Claude Code CLI installed

**`eventbridge.py`** — Custom event bus, rule routing all events to orchestrator Lambda.

**`monitoring.py`** — CloudWatch log groups (JSON structured), error rate alarms, Lambda duration alarms.

### Config (`cdk/config.py`)

```python
@dataclass
class BrainConfig:
    cogent_name: str
    region: str = "us-east-1"
    db_min_acu: float = 0.5
    db_max_acu: float = 4.0
    executor_memory_mb: int = 2048
    executor_timeout_s: int = 900
    ecs_cpu: int = 2048       # 2 vCPU
    ecs_memory: int = 4096    # 4 GB
```

## Implementation Order

1. **Rename skills→programs, executions→runs** in existing code (models, schema, repository, exports)
2. **Rewrite Repository** to use Data API (drop asyncpg)
3. **Update migrations.py** for Data API
4. **Shared Lambda infrastructure** (config, db singleton, events, logging)
5. **Orchestrator handler**
6. **Executor handler** (Lambda path with Bedrock tool-use loop)
7. **Executor ECS entry** (Fargate path with Claude Code CLI)
8. **CDK constructs** (network, database, storage, compute, eventbridge, monitoring)
9. **CDK stack + app** (compose constructs)
10. **Update CLI** (brain update commands for CDK deploy)
