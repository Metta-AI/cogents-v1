# CogOS Transition Plan

Build `src/cogos/` in parallel with the existing codebase. The current system
stays operational while CogOS is built. Once CogOS is functional, the old code
is deleted.

## Approach

Parallel implementation in `src/cogos/`. The existing `src/brain/`,
`src/mind/`, `src/memory/` continue working during the transition. Shared
infrastructure (AWS, CDK, polis) is reused. The dashboard gets new routers
that serve both old and new data during the transition, then old routers are
removed.

## Phase 1: Data Model

Build the new database schema. No execution logic yet — just models,
repository, and migrations.

### 1.1 Models

Create `src/cogos/db/models/` with one file per entity. Each model is a
dataclass or Pydantic model.

| New Model | Source | Changes |
|---|---|---|
| `process.py` | `brain.db.models.Task` | Rename to Process. Add `mode` (daemon/one_shot), `preemptible`, `model`, `model_constraints`. Remove `program_name`. Replace `program_name` FK with `code` FK to File. Add `runnable_since`, `return_schema`, `max_duration_ms`, `max_retries`, `retry_count`, `retry_backoff_ms`. Add SUSPENDED and BLOCKED statuses. |
| `process_capability.py` | New | Join table: process UUID, capability UUID, config dict, delegatable bool. Replaces `tools: list[str]` on Task and Program. |
| `handler.py` | `brain.db.models.Trigger` | Rename to Handler. Simplify: just process FK, event_pattern, enabled. Drop throttle config, priority (priority lives on Process now). |
| `event.py` | `brain.db.models.Event` | Drop `status` field (no proposed/sent lifecycle). Rename `parent_event_id` to `parent_event`. |
| `event_delivery.py` | New | Join table: event UUID, handler UUID, status (pending/delivered/skipped), run UUID. |
| `file.py` | `brain.db.models.Memory` + `MemoryVersion` | Rename Memory -> File, MemoryVersion -> FileVersion. Same structure. |
| `capability.py` | `brain.db.models.Tool` | Rename Tool -> Capability. Add `output_schema`. |
| `run.py` | `brain.db.models.Run` | Add `snapshot`, `result`, `scope_log`. Replace `task_id` with `process` FK. Replace `trigger_id` with `event` FK. Add `suspended` status. |
| `resource.py` | `brain.db.models.Resource` + `ResourceUsage` | Unchanged. |
| `cron.py` | `brain.db.models.Cron` | Rename `event_pattern` to `event_type`. |
| `conversation.py` | `brain.db.models.Conversation` | Unchanged. |
| `channel.py` | `brain.db.models.Channel` | Unchanged. |
| `alert.py` | `brain.db.models.Alert` | Unchanged. |
| `budget.py` | `brain.db.models.Budget` | Unchanged. |
| `trace.py` | `brain.db.models.Trace` | Rename `tool_calls` to `capability_calls`, `memory_ops` to `file_ops`. |

### 1.2 Repository

Create `src/cogos/db/repository.py`. Port methods from
`brain.db.repository.Repository`, adapting to new model names.

**Removed methods** (no longer needed):
- `upsert_program`, `get_program`, `list_programs`, `delete_program`
- `insert_trigger`, `get_trigger`, `list_triggers`, `delete_trigger`,
  `update_trigger_enabled`, `throttle_check`
- `get_proposed_events`, `mark_event_sent`

**Renamed methods:**
- All `task_*` methods -> `process_*`
- All `memory_*` methods -> `file_*`
- All `tool_*` methods -> `capability_*`

**New methods:**
- `create_handler`, `list_handlers`, `delete_handler`, `update_handler_enabled`
- `create_event_delivery`, `get_pending_deliveries`, `mark_delivered`
- `create_process_capability`, `list_process_capabilities`,
  `delete_process_capability`
- `suspend_process`, `resume_process`
- `get_runnable_processes`, `get_blocked_processes`

### 1.3 Database Migration

New PostgreSQL tables alongside existing ones. No destructive changes to
existing tables during transition.

```sql
-- New tables
cogos_process
cogos_process_capability
cogos_handler
cogos_event              -- can share table with existing events
cogos_event_delivery
cogos_file               -- can share table with existing memory
cogos_file_version       -- can share table with existing memory_version
cogos_capability
cogos_run
-- Reuse existing tables
resource, resource_usage, cron, conversation, channel, alert, budget, trace
```

## Phase 2: File Store

Port the memory system to the File abstraction.

| New | Source | Changes |
|---|---|---|
| `src/cogos/files/store.py` | `src/memory/store.py` | Rename MemoryStore -> FileStore. Same API, different names. |
| `src/cogos/files/context_engine.py` | `src/memory/context_engine.py` | Rename references. Resolves file includes to build context. |

**Key change**: Program content (prompts) that currently lives in `programs/`
table gets stored as File entries. The `mind program update` command currently
writes to both the Program table and a `programs/{name}` memory entry. In
CogOS, there's only the File entry.

## Phase 3: Sandbox & Proxy System

Build the new execution environment. This is the biggest new code — the
Agentica-style proxy object model.

### 3.1 Sandbox Executor

Create `src/cogos/sandbox/executor.py`:
- `VariableTable` class managing scope entries
- `ScopeEntry` dataclass (type, context, methods, children)
- `execute_code(code, variable_table)` — runs Python with proxies injected
- Scope lifecycle management (add, release, cascade-release)

### 3.2 Proxy Generator

Create `src/cogos/sandbox/proxy.py`:
- `generate_proxy_class(output_schema)` — reads `methods` from schema,
  creates a Python class with methods that route to capability handlers
- `bind_proxy(proxy_class, context)` — binds instance state to handlers
- Proxy classes are cached per capability for reuse

### 3.3 MCP Server

Create `src/cogos/sandbox/server.py`:
- Wraps `search` and `run_code` as MCP tools
- Reads ProcessCapability bindings for the current process
- Starts alongside Claude Code CLI in ECS containers

### 3.4 Capability Handlers

Port existing tool handlers to the new CapabilityResult return contract:

```python
@dataclass
class CapabilityResult:
    content: Any
    scope: dict | null
    release: list[str] | null
```

Create `src/cogos/capabilities/`:

| Capability | Source | Notes |
|---|---|---|
| `files/read` | New | Returns File proxy with .update(), .versions() |
| `files/write` | New | |
| `files/search` | New | |
| `procs/list` | New | Returns list of Process proxies |
| `procs/get` | New | Returns Process proxy with .kill(), .handlers, .spawn() |
| `procs/spawn` | New | Creates child process, enforces delegatable check |
| `events/emit` | `brain.lambdas.shared.events` | Write to DB instead of EventBridge |
| `events/query` | New | |
| `resources/check` | New | |
| `scheduler/match_events` | Part of `pick-task-to-run` program | Now a capability |
| `scheduler/select_processes` | Part of `pick-task-to-run` program | Softmax sampling logic |
| `scheduler/dispatch_process` | Part of `run-task` program | Lambda/ECS dispatch |
| `scheduler/kill_process` | New | |
| `scheduler/suspend_process` | New | Snapshot + suspend |
| `scheduler/resume_process` | New | Resume from snapshot |

## Phase 4: Executor

Single execution path. No more PROMPT vs PYTHON branch.

### 4.1 Lambda Executor

Create `src/cogos/executor/handler.py`:

Port from `src/brain/lambdas/executor/handler.py` with these changes:
- Remove `execute_python_program()` entirely
- Remove Program loading — load File[process.code] instead
- Remove tool merging from Program + Task — capabilities come from
  ProcessCapability table
- Replace `search_tools` + `execute_code` meta-tools with `search` +
  `run_code` that use the proxy system
- Add snapshot/resume support for preemption
- Add result validation against `process.return_schema`
- Add retry logic (increment retry_count, backoff, DISABLED on exhaust)

**What stays the same:**
- Bedrock converse API call loop
- Token counting and cost tracking
- Run record creation

### 4.2 ECS Executor

Currently in `src/brain/lambdas/executor/handler.py` (ECS branch) and
`src/run/cli.py`. Adapt to:

- Start MCP server from `cogos/sandbox/server.py` in the container
- Pass process prompt as CLAUDE.md / system instructions
- Pass process content as initial message
- Record run on completion

## Phase 5: Scheduler

Convert the current Python programs (`pick-task-to-run`, `run-task`,
`verify-completion`) into a scheduler daemon process + capabilities.

### 5.1 Scheduler Process

Create a File entry (`cogos/scheduler`) with a prompt that orchestrates
scheduling:

```markdown
You are the CogOS scheduler. On each tick:
1. Call match_events() to wake sleeping processes
2. Call unblock_processes() to check blocked processes
3. Call select_processes() to pick what to run
4. Call dispatch_process() for each selected process
```

Create a Process record:
- mode: daemon
- code: FK to the scheduler prompt File
- handler on: `scheduler:tick`
- capabilities: all scheduler/* capabilities

### 5.2 Bootstrap

The scheduler process must exist before anything else can run. Create a
bootstrap script (`src/cogos/cli/bootstrap.py`) that:

1. Creates the scheduler prompt File
2. Creates all built-in Capability records
3. Creates the scheduler Process with capability bindings and handler
4. Creates the `scheduler:tick` Cron entry
5. Creates default Resource records (lambda pool, ecs pool, budget)

## Phase 6: CLI

Create `src/cogos/cli/` to replace `src/mind/cli.py`.

| New Command | Replaces | Changes |
|---|---|---|
| `cogos process list/get/create/update/disable/enable` | `mind task *` | Renamed. Add --mode, --model, --preemptible flags |
| `cogos process spawn` | New | Create child process |
| `cogos process kill` | New | Force-terminate |
| `cogos handler list/add/remove/enable/disable` | `mind trigger *` | Simplified — just process FK + pattern |
| `cogos file list/get/create/update/delete` | `mind memory *` + `memory *` | Unified. Replaces both mind memory and memory CLI |
| `cogos file load [dir]` | `mind memory update` + `mind program update` | Single command loads all files from disk |
| `cogos capability list/get/enable/disable` | `mind tool *` | Renamed |
| `cogos capability load [dir]` | `mind tool update` | Load capability definitions from disk |
| `cogos event list/emit/show/trace` | `mind event *` | Unchanged semantics |
| `cogos resource list/add/delete` | `mind resource *` | Unchanged |
| `cogos cron list/add/delete/enable/disable` | `mind cron *` | Unchanged |
| `cogos run list/show` | New | Query run history |
| `cogos bootstrap` | New | Initialize scheduler, built-in capabilities, defaults |
| `cogos status` | `mind status` (if exists) | Show process states, resource usage, pending events |

### Loader Changes

| New | Source | Changes |
|---|---|---|
| `src/cogos/cli/file_loader.py` | `src/mind/memory_loader.py` + `src/mind/program.py` | Unified. All .md and .py files in a directory become File entries. No more program vs memory distinction. |
| `src/cogos/cli/capability_loader.py` | `src/mind/tool_loader.py` | Rename Tool -> Capability. Same scan logic. |
| `src/cogos/cli/process_loader.py` | `src/mind/task_loader.py` | Rename Task -> Process. Add mode, model, preemptible fields. Replace program_name with code FK. |

## Phase 7: Dashboard

### 7.1 Backend Routers

Create new routers in `src/cogos/dashboard/routers/` or add to existing
`src/dashboard/routers/`.

| New Router | Replaces | Changes |
|---|---|---|
| `processes.py` | `tasks.py` + `programs.py` | Unified. Process list with mode, status, capabilities. No separate program view. |
| `handlers.py` | `triggers.py` | Simplified. Process FK + pattern. |
| `files.py` | `memory.py` | Renamed. Same versioned browser UI. |
| `capabilities.py` | `tools.py` | Renamed. Add output_schema display. |
| `events.py` | `events.py` | Drop proposed/sent status. Add delivery tracking. |
| `runs.py` | `sessions.py` | Renamed. Add result, snapshot, scope_log views. |
| `resources.py` | `resources.py` | Unchanged. |
| `cron.py` | `cron.py` | Unchanged. |
| `channels.py` | `channels.py` | Unchanged. |
| `alerts.py` | `alerts.py` | Unchanged. |

### 7.2 Dashboard Models

Create `src/cogos/dashboard/models.py` or update `src/dashboard/models.py`
with new Pydantic response models matching the new entity names.

### 7.3 Frontend

Update `dashboard/frontend/src/`:

| New Panel | Replaces | Changes |
|---|---|---|
| `ProcessesPanel.tsx` | `ProgramsPanel.tsx` + `TasksPanel.tsx` | Unified view. Shows mode, status, capabilities, handlers. Expandable to show run history. |
| `HandlersPanel.tsx` | `TriggersPanel.tsx` | Simplified. |
| `FilesPanel.tsx` | `MemoryPanel.tsx` | Renamed. Same version browser. |
| `CapabilitiesPanel.tsx` | `ToolsPanel.tsx` | Renamed. |
| `EventsPanel.tsx` | `EventsPanel.tsx` | Add delivery status column. |
| `RunsPanel.tsx` | `SessionsPanel.tsx` | Renamed. Add result viewer, scope log. |

Update `Sidebar.tsx` with new tab names. Update `lib/types.ts` and
`lib/api.ts` with new endpoints.

## Phase 8: Infrastructure

### 8.1 Lambda Changes

| Current | New | Change |
|---|---|---|
| Dispatcher Lambda | Delete | Scheduler capability replaces it |
| Orchestrator Lambda | Delete | Scheduler capability replaces it |
| Executor Lambda | `cogos-executor` | Single execution path, proxy system |
| Sandbox Lambda | Keep or inline | May inline into executor if sandbox is just a library |

### 8.2 CDK Updates

Update CDK stack to:
- Remove dispatcher Lambda + EventBridge rules
- Remove orchestrator Lambda + EventBridge triggers
- Update executor Lambda to use `cogos.executor.handler`
- Keep ECS task definition, update entrypoint
- Keep RDS, secrets, ECR, Route53

### 8.3 EventBridge

Remove all EventBridge rules and targets. Events are now just DB records
matched by the scheduler.

## Phase 9: Data Migration

One-time migration script to populate CogOS tables from existing data.

```python
# migrate.py
def migrate():
    # 1. Programs -> Files
    for program in old_repo.list_programs():
        file = file_store.create(f"programs/{program.name}", program.content)

    # 2. Tasks -> Processes
    for task in old_repo.list_tasks():
        process = Process(
            name=task.name,
            mode="one_shot",  # or "daemon" if it had triggers
            content=task.content,
            code=file_store.get(f"programs/{task.program_name}").id,
            priority=task.priority,
            runner=task.runner or "lambda",
            status=map_status(task.status),
            ...
        )
        new_repo.create_process(process)

        # Migrate tools -> ProcessCapability
        for tool_name in task.tools + program.tools:
            cap = new_repo.get_capability_by_name(tool_name)
            new_repo.create_process_capability(process.id, cap.id)

    # 3. Triggers -> Handlers
    for trigger in old_repo.list_triggers():
        # Find or create a daemon process for this trigger's program
        handler = Handler(
            process=process_id,
            event_pattern=trigger.event_pattern,
            enabled=trigger.enabled,
        )
        new_repo.create_handler(handler)

    # 4. Tools -> Capabilities
    for tool in old_repo.list_tools():
        cap = Capability(
            name=tool.name,
            handler=tool.handler,
            input_schema=tool.input_schema,
            output_schema=None,  # fill in later
            instructions=tool.instructions,
            ...
        )
        new_repo.upsert_capability(cap)

    # 5. Memory -> Files (already exists, just ensure naming)
    # Memory entries carry over as-is since File = Memory renamed

    # 6. Events, Runs, Resources, Cron, etc. carry over with minimal changes
```

## Phase 10: Cleanup

Once CogOS is operational and validated:

### Delete

```
src/brain/lambdas/dispatcher/
src/brain/lambdas/orchestrator/
src/brain/db/models.py          (replaced by cogos/db/models/)
src/brain/db/repository.py      (replaced by cogos/db/repository.py)
src/mind/                       (replaced by cogos/cli/)
src/memory/                     (replaced by cogos/files/)
src/dashboard/routers/programs.py
src/dashboard/routers/triggers.py
src/dashboard/routers/sessions.py  (replaced by runs.py)
eggs/ovo/programs/              (prompts now in File store)
```

### Keep (shared)

```
src/polis/                      (infrastructure management)
src/channels/                   (external integrations)
src/run/cli.py                  (ECS shell access)
src/cli/                        (top-level CLI entry)
```

### Drop DB Tables

```sql
DROP TABLE program;
DROP TABLE trigger;
-- Keep everything else, rename if desired
```

## Execution Order

| Phase | Dependency | Estimated Scope |
|---|---|---|
| 1. Data Model | None | Models + repository + migrations |
| 2. File Store | Phase 1 | Port memory store, small |
| 3. Sandbox & Proxies | Phase 1 | New code, largest phase |
| 4. Executor | Phase 1, 2, 3 | Port + simplify executor |
| 5. Scheduler | Phase 1, 3, 4 | Convert programs to capabilities |
| 6. CLI | Phase 1, 2 | Port + rename CLI commands |
| 7. Dashboard | Phase 1, 6 | Port routers + frontend panels |
| 8. Infrastructure | Phase 4, 5 | CDK updates, remove Lambdas |
| 9. Data Migration | Phase 1-8 | One-time script |
| 10. Cleanup | Phase 9 | Delete old code |

Phases 1-2 and 6 can run in parallel with Phase 3. Phase 7 (dashboard) can
start as soon as Phase 1 is done (backend routers) and continue in parallel.

## File Structure

```
src/cogos/
  __init__.py
  db/
    __init__.py
    models/
      __init__.py
      process.py
      process_capability.py
      handler.py
      file.py
      capability.py
      event.py
      event_delivery.py
      run.py
      resource.py
      cron.py
      conversation.py
      channel.py
      alert.py
      budget.py
      trace.py
    repository.py
    migrations/
      001_create_tables.sql
  executor/
    __init__.py
    handler.py
  sandbox/
    __init__.py
    executor.py
    proxy.py
    server.py
  capabilities/
    __init__.py
    files.py
    procs.py
    events.py
    resources.py
    scheduler.py
  files/
    __init__.py
    store.py
    context_engine.py
  cli/
    __init__.py
    __main__.py
    process.py
    handler.py
    file.py
    capability.py
    event.py
    resource.py
    cron.py
    run.py
    bootstrap.py
    file_loader.py
    capability_loader.py
    process_loader.py
  dashboard/
    __init__.py
    models.py
    routers/
      __init__.py
      processes.py
      handlers.py
      files.py
      capabilities.py
      events.py
      runs.py
      resources.py
      cron.py
      conversations.py
      channels.py
      alerts.py
      status.py
```
