# Task Execution System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the task execution system from `docs/plans/2026-03-05-task-execution-design.md` — new task model, resources, scheduling, and CLI.

**Architecture:** Schema migration adds new columns to tasks, new resources/resource_usage tables. Pydantic models and Repository updated. Mind CLI gets new task/trigger commands. Task loader parses files from `/eggs/ovo/tasks/`. Orchestrator updated to dispatch to ECS based on runner type.

**Tech Stack:** Python 3.12, Pydantic, Click, PostgreSQL (RDS Data API), boto3, YAML

---

### Task 1: Schema migration — update tasks table

**Files:**
- Modify: `src/brain/db/schema.sql`
- Modify: `src/brain/db/migrations.py`

**Step 1: Update schema.sql tasks table**

Replace the tasks table definition in `src/brain/db/schema.sql` (lines 100-117) with:

```sql
-- Work queue
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    program_name    TEXT NOT NULL REFERENCES programs(name),
    content         TEXT NOT NULL DEFAULT '',
    memory_keys     JSONB NOT NULL DEFAULT '[]',
    tools           JSONB NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'runnable'
                    CHECK (status IN ('runnable', 'running', 'completed', 'disabled')),
    priority        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    runner          TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL,
    clear_context   BOOLEAN NOT NULL DEFAULT false,
    resources       JSONB NOT NULL DEFAULT '[]',
    parent_task_id  UUID REFERENCES tasks(id),
    creator         TEXT NOT NULL DEFAULT '',
    source_event    TEXT,
    limits          JSONB NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_task_id) WHERE parent_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks (name);
```

**Step 2: Add resources and resource_usage tables**

Add after the tasks table in `src/brain/db/schema.sql`:

```sql
-- Resource pool and budget tracking
CREATE TABLE IF NOT EXISTS resources (
    name          TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('pool', 'consumable')),
    capacity      DOUBLE PRECISION NOT NULL DEFAULT 1,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resource_usage (
    id            BIGSERIAL PRIMARY KEY,
    resource_name TEXT NOT NULL REFERENCES resources(name),
    run_id        UUID NOT NULL REFERENCES runs(id),
    amount        DOUBLE PRECISION NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_resource_usage_resource ON resource_usage (resource_name);
CREATE INDEX IF NOT EXISTS idx_resource_usage_run ON resource_usage (run_id);
```

**Step 3: Add migration v4**

In `src/brain/db/migrations.py`, add migration 4 to the `MIGRATIONS` dict:

```python
4: """
    -- Add new task columns
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS program_name TEXT NOT NULL DEFAULT 'do-content' REFERENCES programs(name);
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS memory_keys JSONB NOT NULL DEFAULT '[]';
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]';
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS runner TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL;
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS clear_context BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resources JSONB NOT NULL DEFAULT '[]';
    -- Change priority to float
    ALTER TABLE tasks ALTER COLUMN priority TYPE DOUBLE PRECISION;
    -- Change status check constraint
    ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
    ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN ('runnable', 'running', 'completed', 'disabled'));
    -- Update existing statuses
    UPDATE tasks SET status = 'runnable' WHERE status IN ('pending', 'failed');
    -- Add name index
    CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks (name);
    -- Create resources table
    CREATE TABLE IF NOT EXISTS resources (
        name          TEXT PRIMARY KEY,
        resource_type TEXT NOT NULL CHECK (resource_type IN ('pool', 'consumable')),
        capacity      DOUBLE PRECISION NOT NULL DEFAULT 1,
        metadata      JSONB NOT NULL DEFAULT '{}',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    -- Create resource_usage table
    CREATE TABLE IF NOT EXISTS resource_usage (
        id            BIGSERIAL PRIMARY KEY,
        resource_name TEXT NOT NULL REFERENCES resources(name),
        run_id        UUID NOT NULL REFERENCES runs(id),
        amount        DOUBLE PRECISION NOT NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_resource_usage_resource ON resource_usage (resource_name);
    CREATE INDEX IF NOT EXISTS idx_resource_usage_run ON resource_usage (run_id);
    INSERT INTO schema_version (version) VALUES (4) ON CONFLICT DO NOTHING;
""",
```

Also update the schema version in schema.sql from 3 to 4.

Also update `reset_schema` to drop the new tables:
```python
DROP TABLE IF EXISTS resource_usage CASCADE;
DROP TABLE IF EXISTS resources CASCADE;
```

**Step 4: Update test_schema.py**

Add `"resources"` and `"resource_usage"` to `EXPECTED_TABLES` in `tests/dashboard/test_schema.py`.

**Step 5: Run tests**

Run: `pytest tests/dashboard/test_schema.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/brain/db/schema.sql src/brain/db/migrations.py tests/dashboard/test_schema.py
git commit -m "feat(brain): add task execution schema — resources, task columns, migration v4"
```

---

### Task 2: Update Pydantic models

**Files:**
- Modify: `src/brain/db/models.py`
- Modify: `src/brain/db/__init__.py`

**Step 1: Update TaskStatus enum**

Replace `TaskStatus` in `src/brain/db/models.py`:

```python
class TaskStatus(str, enum.Enum):
    RUNNABLE = "runnable"
    RUNNING = "running"
    COMPLETED = "completed"
    DISABLED = "disabled"
```

**Step 2: Update Task model**

Replace the `Task` model:

```python
class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    program_name: str = "do-content"
    content: str = ""
    memory_keys: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.RUNNABLE
    priority: float = 0.0
    runner: str | None = None
    clear_context: bool = False
    resources: list[str] = Field(default_factory=list)
    parent_task_id: UUID | None = None
    creator: str = ""
    source_event: str | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
```

**Step 3: Add Resource and ResourceUsage models**

Add after Trigger/Cron models:

```python
class ResourceType(str, enum.Enum):
    POOL = "pool"
    CONSUMABLE = "consumable"


class Resource(BaseModel):
    name: str
    resource_type: ResourceType = ResourceType.POOL
    capacity: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ResourceUsage(BaseModel):
    id: int | None = None
    resource_name: str
    run_id: UUID
    amount: float
    created_at: datetime | None = None
```

**Step 4: Update `__init__.py`**

Add `Resource`, `ResourceType`, `ResourceUsage` to imports and `__all__` in `src/brain/db/__init__.py`.

**Step 5: Run tests**

Run: `pytest tests/dashboard/test_models.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/brain/db/models.py src/brain/db/__init__.py
git commit -m "feat(brain): update Task model, add Resource/ResourceUsage models"
```

---

### Task 3: Update Repository — task CRUD

**Files:**
- Modify: `src/brain/db/repository.py`

**Step 1: Update create_task**

Replace `create_task` method to include new columns:

```python
def create_task(self, task: Task) -> UUID:
    response = self._execute(
        """INSERT INTO tasks (id, name, description, program_name, content,
                              memory_keys, tools, status, priority, runner,
                              clear_context, resources, parent_task_id,
                              creator, source_event, limits, metadata)
           VALUES (:id, :name, :description, :program_name, :content,
                   :memory_keys::jsonb, :tools::jsonb, :status, :priority, :runner,
                   :clear_context, :resources::jsonb, :parent_task_id,
                   :creator, :source_event, :limits::jsonb, :metadata::jsonb)
           RETURNING id, created_at, updated_at""",
        [
            self._param("id", task.id),
            self._param("name", task.name),
            self._param("description", task.description),
            self._param("program_name", task.program_name),
            self._param("content", task.content),
            self._param("memory_keys", task.memory_keys),
            self._param("tools", task.tools),
            self._param("status", task.status.value),
            self._param("priority", task.priority),
            self._param("runner", task.runner),
            self._param("clear_context", task.clear_context),
            self._param("resources", task.resources),
            self._param("parent_task_id", task.parent_task_id),
            self._param("creator", task.creator),
            self._param("source_event", task.source_event),
            self._param("limits", task.limits),
            self._param("metadata", task.metadata),
        ],
    )
    row = self._first_row(response)
    if row:
        task.created_at = datetime.fromisoformat(row["created_at"])
        task.updated_at = datetime.fromisoformat(row["updated_at"])
        return UUID(row["id"])
    raise RuntimeError("Failed to create task")
```

**Step 2: Add upsert_task**

Add a new method for task loading (upsert by name):

```python
def upsert_task(self, task: Task, *, update_priority: bool = False) -> UUID:
    """Upsert task by name. Priority preserved unless update_priority=True."""
    priority_clause = "priority = EXCLUDED.priority," if update_priority else ""
    response = self._execute(
        f"""INSERT INTO tasks (id, name, description, program_name, content,
                              memory_keys, tools, status, priority, runner,
                              clear_context, resources, parent_task_id,
                              creator, source_event, limits, metadata)
           VALUES (:id, :name, :description, :program_name, :content,
                   :memory_keys::jsonb, :tools::jsonb, :status, :priority, :runner,
                   :clear_context, :resources::jsonb, :parent_task_id,
                   :creator, :source_event, :limits::jsonb, :metadata::jsonb)
           ON CONFLICT (name) DO UPDATE SET
               description = EXCLUDED.description,
               program_name = EXCLUDED.program_name,
               content = EXCLUDED.content,
               memory_keys = EXCLUDED.memory_keys,
               tools = EXCLUDED.tools,
               {priority_clause}
               runner = EXCLUDED.runner,
               clear_context = EXCLUDED.clear_context,
               resources = EXCLUDED.resources,
               limits = EXCLUDED.limits,
               metadata = EXCLUDED.metadata,
               updated_at = now()
           RETURNING id, created_at, updated_at""",
        [
            self._param("id", task.id),
            self._param("name", task.name),
            self._param("description", task.description),
            self._param("program_name", task.program_name),
            self._param("content", task.content),
            self._param("memory_keys", task.memory_keys),
            self._param("tools", task.tools),
            self._param("status", task.status.value),
            self._param("priority", task.priority),
            self._param("runner", task.runner),
            self._param("clear_context", task.clear_context),
            self._param("resources", task.resources),
            self._param("parent_task_id", task.parent_task_id),
            self._param("creator", task.creator),
            self._param("source_event", task.source_event),
            self._param("limits", task.limits),
            self._param("metadata", task.metadata),
        ],
    )
    row = self._first_row(response)
    if row:
        task.created_at = datetime.fromisoformat(row["created_at"])
        task.updated_at = datetime.fromisoformat(row["updated_at"])
        return UUID(row["id"])
    raise RuntimeError("Failed to upsert task")
```

Note: This requires a UNIQUE constraint on `tasks.name`. Add to schema.sql:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_unique_name ON tasks (name);
```

**Step 3: Add get_task_by_name**

```python
def get_task_by_name(self, name: str) -> Task | None:
    response = self._execute(
        "SELECT * FROM tasks WHERE name = :name",
        [self._param("name", name)],
    )
    row = self._first_row(response)
    return self._task_from_row(row) if row else None
```

**Step 4: Update _task_from_row**

Update to parse new columns:

```python
def _task_from_row(self, row: dict) -> Task:
    metadata = row.get("metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    limits = row.get("limits", {})
    if isinstance(limits, str):
        limits = json.loads(limits)
    memory_keys = row.get("memory_keys", [])
    if isinstance(memory_keys, str):
        memory_keys = json.loads(memory_keys)
    tools = row.get("tools", [])
    if isinstance(tools, str):
        tools = json.loads(tools)
    resources = row.get("resources", [])
    if isinstance(resources, str):
        resources = json.loads(resources)
    return Task(
        id=UUID(row["id"]),
        name=row["name"],
        description=row.get("description", ""),
        program_name=row.get("program_name", "do-content"),
        content=row.get("content", ""),
        memory_keys=memory_keys,
        tools=tools,
        status=TaskStatus(row["status"]),
        priority=float(row.get("priority", 0)),
        runner=row.get("runner"),
        clear_context=row.get("clear_context", False),
        resources=resources,
        parent_task_id=UUID(row["parent_task_id"]) if row.get("parent_task_id") else None,
        creator=row.get("creator", ""),
        source_event=row.get("source_event"),
        limits=limits,
        metadata=metadata,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None,
    )
```

**Step 5: Commit**

```bash
git add src/brain/db/repository.py src/brain/db/schema.sql
git commit -m "feat(brain): update task CRUD with new columns, add upsert_task"
```

---

### Task 4: Repository — resource CRUD

**Files:**
- Modify: `src/brain/db/repository.py`

**Step 1: Add resource methods**

Add a RESOURCES section to the repository:

```python
# ═══════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════

def upsert_resource(self, resource: Resource) -> str:
    response = self._execute(
        """INSERT INTO resources (name, resource_type, capacity, metadata)
           VALUES (:name, :resource_type, :capacity, :metadata::jsonb)
           ON CONFLICT (name) DO UPDATE SET
               resource_type = EXCLUDED.resource_type,
               capacity = EXCLUDED.capacity,
               metadata = EXCLUDED.metadata
           RETURNING name, created_at""",
        [
            self._param("name", resource.name),
            self._param("resource_type", resource.resource_type.value),
            self._param("capacity", resource.capacity),
            self._param("metadata", resource.metadata),
        ],
    )
    row = self._first_row(response)
    if row:
        resource.created_at = datetime.fromisoformat(row["created_at"])
        return row["name"]
    raise RuntimeError("Failed to upsert resource")

def get_resource(self, name: str) -> Resource | None:
    response = self._execute(
        "SELECT * FROM resources WHERE name = :name",
        [self._param("name", name)],
    )
    row = self._first_row(response)
    return self._resource_from_row(row) if row else None

def list_resources(self) -> list[Resource]:
    response = self._execute("SELECT * FROM resources ORDER BY name")
    return [self._resource_from_row(r) for r in self._rows_to_dicts(response)]

def delete_resource(self, name: str) -> bool:
    response = self._execute(
        "DELETE FROM resources WHERE name = :name",
        [self._param("name", name)],
    )
    return response.get("numberOfRecordsUpdated", 0) == 1

def _resource_from_row(self, row: dict) -> Resource:
    metadata = row.get("metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return Resource(
        name=row["name"],
        resource_type=ResourceType(row["resource_type"]),
        capacity=float(row.get("capacity", 1)),
        metadata=metadata,
        created_at=datetime.fromisoformat(row["created_at"]),
    )
```

**Step 2: Add resource_usage methods**

```python
# ═══════════════════════════════════════════════════════════
# RESOURCE USAGE
# ═══════════════════════════════════════════════════════════

def insert_resource_usage(self, usage: ResourceUsage) -> int:
    response = self._execute(
        """INSERT INTO resource_usage (resource_name, run_id, amount)
           VALUES (:resource_name, :run_id, :amount)
           RETURNING id, created_at""",
        [
            self._param("resource_name", usage.resource_name),
            self._param("run_id", usage.run_id),
            self._param("amount", usage.amount),
        ],
    )
    row = self._first_row(response)
    if row:
        usage.id = int(row["id"])
        usage.created_at = datetime.fromisoformat(row["created_at"])
        return usage.id
    raise RuntimeError("Failed to insert resource usage")

def get_consumable_usage(self, resource_name: str) -> float:
    """Get total consumed amount for a consumable resource."""
    response = self._execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM resource_usage WHERE resource_name = :name",
        [self._param("name", resource_name)],
    )
    row = self._first_row(response)
    return float(row["total"]) if row else 0.0

def get_pool_usage(self, resource_name: str) -> int:
    """Get count of running tasks that consume this pool resource.

    A task consumes a pool resource if:
    - resource_name matches its runner type, OR
    - resource_name is 'concurrent-tasks', OR
    - resource_name is in the task's resources array
    """
    response = self._execute(
        """SELECT COUNT(*) as cnt FROM tasks
           WHERE status = 'running'
           AND (
               runner = :name
               OR :name = 'concurrent-tasks'
               OR resources::jsonb ? :name
           )""",
        [self._param("name", resource_name)],
    )
    row = self._first_row(response)
    return int(row["cnt"]) if row else 0
```

**Step 3: Update imports in repository.py**

Add `Resource`, `ResourceType`, `ResourceUsage` to the imports from `brain.db.models`.

**Step 4: Commit**

```bash
git add src/brain/db/repository.py
git commit -m "feat(brain): add resource and resource_usage repository methods"
```

---

### Task 5: Update Mind CLI — task commands

**Files:**
- Modify: `src/mind/cli.py`

**Step 1: Rewrite task create command**

Replace the task create command with new fields:

```python
@task.command("create")
@click.argument("name")
@click.option("--program", "program_name", default="do-content")
@click.option("--content", default="")
@click.option("--content-file", type=click.Path(exists=True))
@click.option("--description", "-d", default="")
@click.option("--priority", "-p", type=float, default=0.0)
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default=None)
@click.option("--clear-context", is_flag=True, default=False)
@click.option("--memory-keys", default="", help="Comma-separated memory keys")
@click.option("--tools", default="", help="Comma-separated tools")
@click.option("--resources", default="", help="Comma-separated extra resources")
@click.option("--parent", type=str, default=None, help="Parent task ID")
@click.option("--creator", default="cli")
@click.option("--disabled", is_flag=True, default=False)
@click.option("--limits", default="{}", help="JSON limits")
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def task_create(
    ctx: click.Context,
    name: str,
    program_name: str,
    content: str,
    content_file: str | None,
    description: str,
    priority: float,
    runner: str | None,
    clear_context: bool,
    memory_keys: str,
    tools: str,
    resources: str,
    parent: str | None,
    creator: str,
    disabled: bool,
    limits: str,
    metadata_json: str,
) -> None:
    """Create a task."""
    if content_file:
        content = Path(content_file).read_text()

    memory_keys_list = [s.strip() for s in memory_keys.split(",") if s.strip()] if memory_keys else []
    tools_list = [s.strip() for s in tools.split(",") if s.strip()] if tools else []
    resources_list = [s.strip() for s in resources.split(",") if s.strip()] if resources else []

    t = Task(
        name=name,
        program_name=program_name,
        content=content,
        description=description,
        priority=priority,
        runner=runner,
        clear_context=clear_context,
        memory_keys=memory_keys_list,
        tools=tools_list,
        resources=resources_list,
        status=TaskStatus.DISABLED if disabled else TaskStatus.RUNNABLE,
        parent_task_id=UUID(parent) if parent else None,
        creator=creator,
        limits=json.loads(limits),
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    task_id = repo.create_task(t)
    _output({"id": str(task_id), "name": name, "status": "created"}, use_json=ctx.obj["json"])
```

**Step 2: Update task list command**

Update status choices and output fields:

```python
@task.command("list")
@click.option("--status", type=click.Choice(["runnable", "running", "completed", "disabled"]), default=None)
@click.option("--limit", type=int, default=50)
@click.pass_context
def task_list(ctx: click.Context, status: str | None, limit: int) -> None:
    """List tasks."""
    repo = _repo()
    task_status = TaskStatus(status) if status else None
    tasks = repo.list_tasks(status=task_status, limit=limit)
    data = [
        {
            "id": str(t.id),
            "name": t.name,
            "status": t.status.value,
            "priority": t.priority,
            "program": t.program_name,
            "runner": t.runner or "default",
        }
        for t in tasks
    ]
    _output(data, use_json=ctx.obj["json"])
```

**Step 3: Update task update command**

Add more update options:

```python
@task.command("update")
@click.argument("task_id")
@click.option("--status", type=click.Choice(["runnable", "running", "completed", "disabled"]))
@click.option("--priority", type=float, default=None)
@click.option("--content", default=None)
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default=None)
@click.option("--metadata", "metadata_json", default=None, help="JSON metadata to merge")
@click.pass_context
def task_update(ctx: click.Context, task_id: str, status: str | None, priority: float | None,
                content: str | None, runner: str | None, metadata_json: str | None) -> None:
    """Update a task."""
    repo = _repo()
    t = repo.get_task(UUID(task_id))
    if not t:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)

    if status:
        t.status = TaskStatus(status)
    if priority is not None:
        t.priority = priority
    if content is not None:
        t.content = content
    if runner is not None:
        t.runner = runner
    if metadata_json is not None:
        t.metadata.update(json.loads(metadata_json))

    if status == "completed":
        repo.update_task_status(UUID(task_id), TaskStatus.COMPLETED)
    else:
        repo.update_task_status(UUID(task_id), t.status)

    updates = {k: v for k, v in [("status", status), ("priority", priority),
               ("content", content), ("runner", runner)] if v is not None}
    _output({"id": task_id, **updates}, use_json=ctx.obj["json"])
```

**Step 4: Add task disable/enable commands**

```python
@task.command("disable")
@click.argument("task_id")
@click.pass_context
def task_disable(ctx: click.Context, task_id: str) -> None:
    """Disable a task."""
    repo = _repo()
    if repo.update_task_status(UUID(task_id), TaskStatus.DISABLED):
        _output({"id": task_id, "status": "disabled"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)

@task.command("enable")
@click.argument("task_id")
@click.pass_context
def task_enable(ctx: click.Context, task_id: str) -> None:
    """Enable a task (set to runnable)."""
    repo = _repo()
    if repo.update_task_status(UUID(task_id), TaskStatus.RUNNABLE):
        _output({"id": task_id, "status": "runnable"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)
```

**Step 5: Commit**

```bash
git add src/mind/cli.py
git commit -m "feat(mind): update task CLI with new fields, add enable/disable"
```

---

### Task 6: Add resource CLI commands

**Files:**
- Modify: `src/mind/cli.py`

**Step 1: Add resource group and commands**

Add after the cron section in `src/mind/cli.py`:

```python
# ═══════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════

@mind.group()
def resource() -> None:
    """Manage resources."""

@resource.command("create")
@click.argument("name")
@click.option("--type", "resource_type", type=click.Choice(["pool", "consumable"]), required=True)
@click.option("--capacity", type=float, required=True)
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def resource_create(ctx: click.Context, name: str, resource_type: str, capacity: float,
                    metadata_json: str) -> None:
    """Create or update a resource."""
    from brain.db.models import Resource, ResourceType
    r = Resource(
        name=name,
        resource_type=ResourceType(resource_type),
        capacity=capacity,
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    repo.upsert_resource(r)
    _output({"name": name, "type": resource_type, "capacity": capacity, "status": "created"},
            use_json=ctx.obj["json"])

@resource.command("list")
@click.pass_context
def resource_list(ctx: click.Context) -> None:
    """List all resources."""
    repo = _repo()
    resources = repo.list_resources()
    data = [
        {"name": r.name, "type": r.resource_type.value, "capacity": r.capacity}
        for r in resources
    ]
    _output(data, use_json=ctx.obj["json"])

@resource.command("show")
@click.argument("name")
@click.pass_context
def resource_show(ctx: click.Context, name: str) -> None:
    """Show a resource's details and current usage."""
    repo = _repo()
    r = repo.get_resource(name)
    if not r:
        click.echo(f"Resource '{name}' not found.", err=True)
        sys.exit(1)
    data = r.model_dump(mode="json")
    if r.resource_type.value == "pool":
        data["used"] = repo.get_pool_usage(name)
    else:
        data["used"] = repo.get_consumable_usage(name)
    data["available"] = r.capacity - data["used"]
    _output(data, use_json=ctx.obj["json"])

@resource.command("delete")
@click.argument("name")
@click.pass_context
def resource_delete(ctx: click.Context, name: str) -> None:
    """Delete a resource."""
    repo = _repo()
    if repo.delete_resource(name):
        _output({"name": name, "status": "deleted"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Resource '{name}' not found.", err=True)
        sys.exit(1)
```

**Step 2: Commit**

```bash
git add src/mind/cli.py
git commit -m "feat(mind): add resource CLI commands"
```

---

### Task 7: Task file loader

**Files:**
- Create: `src/mind/task_loader.py`

**Step 1: Create task_loader.py**

```python
"""Load task definitions from /eggs/ovo/tasks/ in .md, .yaml, and .py formats."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

from brain.db.models import Task, TaskStatus


def load_tasks_from_dir(tasks_dir: Path) -> list[Task]:
    """Recursively scan tasks_dir for .md, .yaml, .yml, .py and parse tasks."""
    tasks: list[Task] = []
    if not tasks_dir.is_dir():
        return tasks

    for path in sorted(tasks_dir.rglob("*")):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix == ".md":
            tasks.append(_load_markdown(path, tasks_dir))
        elif suffix in (".yaml", ".yml"):
            tasks.extend(_load_yaml(path))
        elif suffix == ".py":
            tasks.extend(_load_python(path))

    return tasks


def _load_markdown(path: Path, tasks_dir: Path) -> Task:
    """Parse a markdown task file. Name = relative path without .md extension."""
    rel = path.relative_to(tasks_dir).with_suffix("")
    name = str(rel)

    text = path.read_text()
    frontmatter: dict[str, Any] = {}
    content = text

    # Parse YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            content = parts[2].strip()

    status = TaskStatus.DISABLED if frontmatter.pop("disabled", False) else TaskStatus.RUNNABLE

    return Task(
        name=name,
        program_name=frontmatter.pop("program_name", "do-content"),
        content=content,
        description=frontmatter.pop("description", ""),
        priority=float(frontmatter.pop("priority", 0.0)),
        runner=frontmatter.pop("runner", None),
        clear_context=frontmatter.pop("clear_context", False),
        memory_keys=frontmatter.pop("memory_keys", []),
        tools=frontmatter.pop("tools", []),
        resources=frontmatter.pop("resources", []),
        limits=frontmatter.pop("limits", {}),
        metadata=frontmatter.pop("metadata", {}),
        status=status,
        creator="file",
    )


def _load_yaml(path: Path) -> list[Task]:
    """Parse a YAML task file. Single task or list under 'tasks' key."""
    data = yaml.safe_load(path.read_text())
    if data is None:
        return []

    if isinstance(data, dict) and "tasks" in data:
        return [_task_from_dict(d) for d in data["tasks"]]
    elif isinstance(data, dict):
        return [_task_from_dict(data)]
    elif isinstance(data, list):
        return [_task_from_dict(d) for d in data]
    return []


def _task_from_dict(d: dict) -> Task:
    """Build a Task from a dict (YAML parsed)."""
    disabled = d.pop("disabled", False)
    status = TaskStatus.DISABLED if disabled else TaskStatus.RUNNABLE
    return Task(
        name=d["name"],
        program_name=d.get("program_name", "do-content"),
        content=d.get("content", ""),
        description=d.get("description", ""),
        priority=float(d.get("priority", 0.0)),
        runner=d.get("runner"),
        clear_context=d.get("clear_context", False),
        memory_keys=d.get("memory_keys", []),
        tools=d.get("tools", []),
        resources=d.get("resources", []),
        limits=d.get("limits", {}),
        metadata=d.get("metadata", {}),
        status=status,
        creator="file",
    )


def _load_python(path: Path) -> list[Task]:
    """Load tasks from a Python module that defines task or tasks."""
    spec = importlib.util.spec_from_file_location("_task_module", path)
    if not spec or not spec.loader:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules["_task_module"] = module
    spec.loader.exec_module(module)
    del sys.modules["_task_module"]

    if hasattr(module, "tasks"):
        return list(module.tasks)
    elif hasattr(module, "task"):
        return [module.task]
    return []
```

**Step 2: Commit**

```bash
git add src/mind/task_loader.py
git commit -m "feat(mind): add task file loader for .md, .yaml, .py formats"
```

---

### Task 8: Task load CLI command

**Files:**
- Modify: `src/mind/cli.py`

**Step 1: Add task load command**

Add to the task group in `src/mind/cli.py`:

```python
@task.command("load")
@click.argument("tasks_dir", type=click.Path(exists=True))
@click.option("--update-priority", is_flag=True, help="Overwrite priority on existing tasks")
@click.option("--force", is_flag=True, help="Skip validation of programs and memory keys")
@click.pass_context
def task_load(ctx: click.Context, tasks_dir: str, update_priority: bool, force: bool) -> None:
    """Load tasks from directory (recursive .md, .yaml, .py)."""
    from mind.task_loader import load_tasks_from_dir

    tasks = load_tasks_from_dir(Path(tasks_dir))
    if not tasks:
        click.echo("No tasks found.")
        return

    repo = _repo()

    # Validate programs and memory keys exist
    if not force:
        errors = []
        for t in tasks:
            prog = repo.get_program(t.program_name)
            if not prog:
                errors.append(f"Task '{t.name}': program '{t.program_name}' not found")
            for key in t.memory_keys:
                records = repo.get_memories_by_names([key])
                if not records:
                    errors.append(f"Task '{t.name}': memory key '{key}' not found")
        if errors:
            click.echo("Validation failed:", err=True)
            for e in errors:
                click.echo(f"  {e}", err=True)
            click.echo("Use --force to skip validation.", err=True)
            sys.exit(1)

    created = 0
    updated = 0
    unchanged = 0

    for t in tasks:
        existing = repo.get_task_by_name(t.name)
        if existing:
            # Preserve status, priority (unless flagged), creator, parent
            t.status = existing.status
            t.creator = existing.creator
            t.parent_task_id = existing.parent_task_id
            if not update_priority:
                t.priority = existing.priority
            repo.upsert_task(t, update_priority=update_priority)
            updated += 1
        else:
            repo.create_task(t)
            created += 1

    _output(
        {"created": created, "updated": updated, "unchanged": unchanged, "total": len(tasks)},
        use_json=ctx.obj["json"],
    )
```

**Step 2: Commit**

```bash
git add src/mind/cli.py
git commit -m "feat(mind): add task load command with validation"
```

---

### Task 9: Wire mind CLI into cogent CLI

**Files:**
- Modify: `src/cli/__main__.py`

**Step 1: Add mind to known commands and register**

In `src/cli/__main__.py`, add `"mind"` to `_COMMANDS` set:

```python
_COMMANDS = {"dashboard", "brain", "memory", "mind", "--help", "-h"}
```

And register the mind CLI group:

```python
from mind.cli import mind  # noqa: E402

main.add_command(mind)
```

**Step 2: Commit**

```bash
git add src/cli/__main__.py
git commit -m "feat(cli): wire mind CLI into cogent main CLI"
```

---

### Task 10: Update orchestrator to dispatch Lambda vs ECS

**Files:**
- Modify: `src/brain/lambdas/orchestrator/handler.py`

**Step 1: Update dispatch logic**

Currently the orchestrator always dispatches to Lambda. Update to check the program's metadata for runner type, and the event payload for task-level runner override.

In the trigger dispatch loop (around line 121), replace the Lambda-only dispatch:

```python
# Determine runner type
runner = None
# Check if event payload has a task with runner override
task_runner = brain_event.payload.get("runner") if brain_event.payload else None
if task_runner:
    runner = task_runner
elif program.metadata.get("runner"):
    runner = program.metadata["runner"]

if runner == "ecs":
    _dispatch_ecs(config, ecs_client, payload, trigger.program_name)
else:
    _dispatch_lambda(config, lambda_client, payload, trigger.program_name)
```

**Step 2: Update ECS dispatch to pass session ID**

In `_dispatch_ecs`, add session ID support:

```python
def _dispatch_ecs(config, ecs_client, payload: str, program_name: str,
                  session_id: str | None = None):
    """Run executor as ECS Fargate task for heavy compute."""
    subnets = [s.strip() for s in config.ecs_subnets.split(",") if s.strip()]

    env_vars = [{"name": "EXECUTOR_PAYLOAD", "value": payload}]
    if session_id:
        env_vars.append({"name": "CLAUDE_CODE_SESSION", "value": session_id})

    ecs_client.run_task(
        cluster=config.ecs_cluster_arn,
        taskDefinition=config.ecs_task_definition,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [config.ecs_security_group],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "Executor",
                    "environment": env_vars,
                }
            ]
        },
    )
    logger.info(f"Dispatched to ECS: {program_name}")
```

And update the call site to pass session_id from the event payload (task_id when clear_context is false).

**Step 3: Commit**

```bash
git add src/brain/lambdas/orchestrator/handler.py
git commit -m "feat(brain): dispatch to ECS or Lambda based on runner type"
```

---

### Task 11: Update ECS executor to use task context

**Files:**
- Modify: `src/brain/lambdas/executor/ecs_entry.py`

**Step 1: Update to merge task content and memory**

Update `main()` to handle task-aware execution:

```python
# After loading the program, check for task context in payload
task_id = payload.get("task", {}).get("id")
task_content = payload.get("task", {}).get("content", "")
task_memory_keys = payload.get("task", {}).get("memory_keys", [])
task_tools = payload.get("task", {}).get("tools", [])
clear_context = payload.get("task", {}).get("clear_context", False)

# Session management: use task_id as session_id unless clear_context
if task_id and not clear_context:
    session_id = task_id
elif not session_id:
    session_id = str(run_id)

# Merge tools
all_tools = list(set((program.tools or []) + task_tools))

# Build prompt: program content + task content
prompt = program.content
if task_content:
    prompt += f"\n\n{task_content}"
if event_data.get("payload"):
    prompt += f"\n\nEvent context:\n{json.dumps(event_data['payload'], indent=2)}"

# Link run to task
if task_id:
    run.task_id = UUID(task_id) if isinstance(task_id, str) else task_id
```

**Step 2: Commit**

```bash
git add src/brain/lambdas/executor/ecs_entry.py
git commit -m "feat(brain): ECS executor supports task context, session resumption"
```

---

### Task 12: Update Lambda executor to use task context

**Files:**
- Modify: `src/brain/lambdas/executor/handler.py`

**Step 1: Update handler to merge task data**

Same pattern as ECS — extract task fields from payload, merge tools and memory_keys:

```python
# After loading program, in handler()
task_data = event.get("task", {})
task_id_str = task_data.get("id")
task_content = task_data.get("content", "")
task_memory_keys = task_data.get("memory_keys", [])
task_tools = task_data.get("tools", [])

if task_id_str:
    run.task_id = UUID(task_id_str)

# In execute_program(), merge memory keys and tools
# Pass task data through to execute_program
```

Update `execute_program` signature to accept task data and merge:

```python
def execute_program(program: Program, event_data: dict, run: Run, config,
                    task_data: dict | None = None) -> Run:
    # ... existing code ...
    # Merge task memory keys with program memory keys
    extra_memory_keys = task_data.get("memory_keys", []) if task_data else []
    # Pass to context engine (extend program.memory_keys temporarily)
    if extra_memory_keys:
        program = program.model_copy(update={"memory_keys": program.memory_keys + extra_memory_keys})

    # Merge task tools
    extra_tools = task_data.get("tools", []) if task_data else []
    if extra_tools:
        program = program.model_copy(update={"tools": list(set(program.tools + extra_tools))})

    # Prepend task content to user message
    task_content = task_data.get("content", "") if task_data else ""
    if task_content:
        user_text = f"Task:\n{task_content}\n\n{user_text}"
```

**Step 2: Commit**

```bash
git add src/brain/lambdas/executor/handler.py
git commit -m "feat(brain): Lambda executor supports task context merging"
```

---

### Task 13: Update dashboard models and routes

**Files:**
- Modify: `src/dashboard/models.py`
- Modify: `src/dashboard/routers/tasks.py`

**Step 1: Update dashboard Task model**

Update the `Task` model in `src/dashboard/models.py` to include new fields:

```python
class Task(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    program_name: str | None = None
    content: str | None = None
    status: str | None = None
    priority: float | None = None
    runner: str | None = None
    clear_context: bool | None = None
    memory_keys: list[str] | None = None
    tools: list[str] | None = None
    resources: list[str] | None = None
    creator: str | None = None
    parent_task_id: str | None = None
    source_event: str | None = None
    limits: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
```

**Step 2: Update tasks router queries**

Update the SELECT queries in `src/dashboard/routers/tasks.py` to include new columns:

```python
"SELECT id::text, name, description, program_name, content, status, priority, "
"runner, clear_context, memory_keys, tools, resources, creator, "
"parent_task_id::text, source_event, limits, metadata, "
"created_at::text, updated_at::text, completed_at::text "
```

**Step 3: Commit**

```bash
git add src/dashboard/models.py src/dashboard/routers/tasks.py
git commit -m "feat(dashboard): update task model and routes for new fields"
```

---

### Task 14: Add tests for task loader

**Files:**
- Create: `tests/mind/__init__.py` (empty)
- Create: `tests/mind/test_task_loader.py`

**Step 1: Write tests**

```python
"""Tests for the task file loader."""

import textwrap
from pathlib import Path

from brain.db.models import TaskStatus
from mind.task_loader import load_tasks_from_dir


def test_load_markdown_simple(tmp_path: Path):
    """A plain .md file becomes a task with do-content program."""
    (tmp_path / "check-stuff.md").write_text("Do the thing.\n")
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.name == "check-stuff"
    assert t.program_name == "do-content"
    assert t.content == "Do the thing."
    assert t.status == TaskStatus.RUNNABLE


def test_load_markdown_with_frontmatter(tmp_path: Path):
    """Frontmatter overrides defaults."""
    (tmp_path / "review.md").write_text(textwrap.dedent("""\
        ---
        priority: 5.0
        runner: ecs
        memory_keys: ["/repo/context"]
        ---
        Review open PRs.
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.priority == 5.0
    assert t.runner == "ecs"
    assert t.memory_keys == ["/repo/context"]
    assert t.content == "Review open PRs."


def test_load_markdown_subdirectory(tmp_path: Path):
    """Subdirectory paths become task name prefixes."""
    sub = tmp_path / "reviews"
    sub.mkdir()
    (sub / "daily.md").write_text("Check PRs.\n")
    tasks = load_tasks_from_dir(tmp_path)
    assert tasks[0].name == "reviews/daily"


def test_load_yaml_single(tmp_path: Path):
    """A YAML file with a single task object."""
    (tmp_path / "task.yaml").write_text(textwrap.dedent("""\
        name: deploy-check
        program_name: do-content
        content: Check deployments
        priority: 3.0
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].name == "deploy-check"
    assert tasks[0].priority == 3.0


def test_load_yaml_multiple(tmp_path: Path):
    """A YAML file with a tasks list."""
    (tmp_path / "tasks.yml").write_text(textwrap.dedent("""\
        tasks:
          - name: task-a
            content: Do A
          - name: task-b
            content: Do B
            priority: 2.0
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 2
    assert tasks[0].name == "task-a"
    assert tasks[1].name == "task-b"
    assert tasks[1].priority == 2.0


def test_load_disabled_task(tmp_path: Path):
    """A disabled task gets DISABLED status."""
    (tmp_path / "off.md").write_text(textwrap.dedent("""\
        ---
        disabled: true
        ---
        This task is off.
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert tasks[0].status == TaskStatus.DISABLED


def test_load_empty_dir(tmp_path: Path):
    """Empty directory returns no tasks."""
    assert load_tasks_from_dir(tmp_path) == []


def test_load_nonexistent_dir(tmp_path: Path):
    """Non-existent directory returns no tasks."""
    assert load_tasks_from_dir(tmp_path / "nope") == []
```

**Step 2: Run tests**

Run: `pytest tests/mind/test_task_loader.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/mind/
git commit -m "test(mind): add task loader tests"
```

---

### Task 15: Update test_schema.py and test_models.py for new tables/models

**Files:**
- Modify: `tests/dashboard/test_schema.py`
- Modify: `tests/dashboard/test_models.py`

**Step 1: Update test_schema.py**

Already covered in Task 1 Step 4 — verify `resources` and `resource_usage` are in `EXPECTED_TABLES`.

**Step 2: Update test_models.py if needed**

Check if `test_models.py` has any Task-specific assertions that reference old fields (like `TaskStatus.PENDING`). Update them to use `TaskStatus.RUNNABLE`.

**Step 3: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: update tests for new task statuses and resource tables"
```

---

### Task 16: Add runner field to programs table

The design says tasks fall back to the program's runner. Currently programs don't have a `runner` field.

**Files:**
- Modify: `src/brain/db/schema.sql`
- Modify: `src/brain/db/models.py`
- Modify: `src/brain/db/repository.py`
- Modify: `src/brain/db/migrations.py`

**Step 1: Add runner column to programs**

In schema.sql, add to programs table:
```sql
runner TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL,
```

In migration v4, add:
```sql
ALTER TABLE programs ADD COLUMN IF NOT EXISTS runner TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL;
```

**Step 2: Update Program model**

Add `runner: str | None = None` to the Program model in models.py.

**Step 3: Update repository**

Update `upsert_program` to include `runner`. Update `_program_from_row` to parse `runner`.

**Step 4: Update program CLI**

Add `--runner` option to `program create` and `program update` in `src/mind/cli.py`.

**Step 5: Commit**

```bash
git add src/brain/db/schema.sql src/brain/db/models.py src/brain/db/repository.py src/brain/db/migrations.py src/mind/cli.py
git commit -m "feat(brain): add runner field to programs table"
```

---

### Task 17: Final integration — run all tests

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS

**Step 2: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix: address test failures from task execution refactor"
```
