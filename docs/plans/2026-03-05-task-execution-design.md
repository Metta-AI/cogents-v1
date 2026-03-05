# Task Execution System Design

## Overview

Tasks become the primary unit of work. Every task references a program and carries content, tools, and memory. A cron-driven scheduler picks runnable tasks via softmax sampling over priority, dispatches them to Lambda or ECS runners, and a completion verifier evaluates results.

## Task Model

```sql
CREATE TABLE tasks (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    program_name   TEXT NOT NULL REFERENCES programs(name),
    content        TEXT NOT NULL DEFAULT '',
    memory_keys    JSONB NOT NULL DEFAULT '[]',
    tools          JSONB NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'runnable'
                   CHECK (status IN ('runnable', 'running', 'completed', 'disabled')),
    priority       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    runner         TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL,
    clear_context  BOOLEAN NOT NULL DEFAULT false,
    resources      JSONB NOT NULL DEFAULT '[]',
    parent_task_id UUID REFERENCES tasks(id),
    creator        TEXT NOT NULL DEFAULT '',
    source_event   TEXT,
    limits         JSONB NOT NULL DEFAULT '{}',
    metadata       JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ
);
```

### Fields

- **program_name**: program to execute. Every task references a program.
- **content**: payload/instructions passed to the program. For `do-content`, this is the prompt itself.
- **memory_keys**: merged with the program's `memory_keys` at execution time.
- **tools**: merged with the program's `tools` at execution time.
- **status**: `runnable` (ready for scheduling), `running`, `completed`, `disabled` (manually excluded). Tasks are born `runnable` unless explicitly disabled.
- **priority**: floating-point. Higher = more likely to be scheduled. Tuned at runtime.
- **runner**: `lambda`, `ecs`, or NULL (fall back to program's default runner).
- **clear_context**: if false (default), ECS runs use task ID as session ID, resuming the Claude Code conversation from S3. If true, each run starts a fresh session.
- **resources**: additional custom resources this task requires beyond the auto-inferred runner slot (e.g., `["gpu"]`).

## Resource Model

```sql
CREATE TABLE resources (
    name          TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('pool', 'consumable')),
    capacity      DOUBLE PRECISION NOT NULL DEFAULT 1,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE resource_usage (
    id            BIGSERIAL PRIMARY KEY,
    resource_name TEXT NOT NULL REFERENCES resources(name),
    run_id        UUID NOT NULL REFERENCES runs(id),
    amount        DOUBLE PRECISION NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Resource Types

- **Pool** (e.g., `ecs`, `lambda`, `concurrent-tasks`): capacity is a concurrency limit. Running tasks hold slots; slots are released on task completion or failure. Availability = `capacity - count(running tasks consuming this resource)`.
- **Consumable** (e.g., `tokens`, `cost`): capacity is a budget. Usage is recorded per run in `resource_usage` and summed permanently. Availability = `capacity - SUM(resource_usage.amount)`. Per-task usage is computed by joining through `runs.task_id`.

### Resource Consumption

Every running task automatically consumes:
1. A `concurrent-tasks` pool slot
2. A pool slot for its runner type (`ecs` or `lambda`)

Additionally, tasks consume any custom resources listed in their `resources` field.

## Scheduling Loop

Driven by a cron entry that fires a `scheduler:tick` event every 10-30 seconds.

### pick-task-to-run (Python program, stored at `/vsm/s1/pick-task-to-run`)

1. Query all tasks with `status = 'runnable'`.
2. For each pool resource, count currently `running` tasks consuming it.
3. For each consumable resource, sum usage from `resource_usage`.
4. Filter to tasks whose required resources (runner slot + `concurrent-tasks` + custom `resources`) all have available capacity.
5. Read temperature from memory at `/vsm/s1/task-priority-temperature`.
6. Apply softmax over priorities of filtered tasks with that temperature.
7. Sample tasks up to available resource slots.
8. For each sampled task, emit a `task:dispatch` event with the task ID in the payload.

### run-task (Python program, stored at `/vsm/s1/run-task`)

Triggered by `task:dispatch`:

1. Load the task.
2. Set task status to `running`.
3. Resolve runner: task's `runner` field, falling back to program's runner field.
4. Merge tools: program tools + task tools.
5. Merge memory_keys: program memory_keys + task memory_keys.
6. Dispatch to Lambda or ECS executor.
7. For ECS: if `clear_context` is false, pass task ID as session ID so Claude Code resumes the session from S3.

## Execution

### Lambda Runner

Executes via Bedrock Converse API (as today). Program content + task content merged. Merged tools and memory provided as context.

### ECS Runner

Launches Fargate task with Claude Code CLI. Session management:
- Default (`clear_context = false`): session ID = task ID. Downloads existing session from S3 on start, uploads on completion. Retries resume the conversation.
- `clear_context = true`: fresh session each run, no session ID passed.

All logs go to CloudWatch. Sessions uploaded to S3 on completion.

### Events Emitted

Both runners emit on completion:
- `run:finished` — always, with run ID and task ID
- `run:succeeded` — if the run completed without error
- `run:failed` — if the run errored or timed out

## Completion Verification

### verify-completion (Prompt program)

Triggered by `run:succeeded`:

1. Load the task (content, description, metadata) and the run result.
2. LLM evaluates: was the task completed to the user's satisfaction?
3. **Completed**: set task status to `completed`.
4. **Retryable failure**: set task status back to `runnable`. Log failure reason in task metadata so the next run has context.
5. **Not retryable**: keep task `runnable` but emit `task:stuck` event, which triggers a stuck task alert.

### run:failed Handler

Hard errors (crashes, timeouts):
- Return task to `runnable`, log error in metadata.
- If repeated failures detected, emit `task:stuck`.

## Task File Formats

Task definitions live in `/eggs/ovo/tasks/`, scanned recursively through subdirectories.

### Markdown (.md)

- Task name derived from path: `/eggs/ovo/tasks/reviews/daily-pr-check.md` becomes `reviews/daily-pr-check`.
- Program is always `/vsm/s1/do-content`.
- File body becomes the task's `content` field.
- Optional YAML frontmatter overrides: `priority`, `runner`, `memory_keys`, `tools`, `clear_context`, `description`, `resources`, `limits`, `metadata`, `disabled`.

```markdown
---
priority: 5.0
memory_keys: ["/repo/context"]
---
Review open PRs in the repo and summarize findings.
```

### YAML (.yaml, .yml)

Single task (top-level object) or multiple tasks (top-level `tasks` list). All fields explicit.

```yaml
tasks:
  - name: daily-code-review
    program_name: do_content
    content: Review open PRs and summarize findings.
    priority: 5.0
    runner: ecs
    memory_keys: ["/repo/context"]
    tools: ["memory", "event"]
```

### Python (.py)

Must define `task: Task` or `tasks: list[Task]` at module level using the Pydantic model. Single or multiple tasks.

## Task Loading

Invoked via `cogent <name> tasks load` or as part of `brain update`.

1. Recursively scan `/eggs/ovo/tasks/` for `.md`, `.yaml`, `.yml`, `.py`.
2. Parse all task definitions.
3. **Validate**: check that each task's `program_name` exists in programs table and all `memory_keys` exist in memory table. If any are missing, **fail the entire load** with a clear error listing what's missing. Pass `--force` to skip validation.
4. **Upsert by name**: create new tasks, update existing ones.
5. **Priority preserved** on update unless `--update-priority` is passed.
6. Fields updated on match: `program_name`, `content`, `memory_keys`, `tools`, `runner`, `clear_context`, `description`, `resources`, `limits`, `metadata`.
7. Fields preserved on match: `priority` (unless flagged), `status`, `created_at`, `parent_task_id`, `creator`.
8. Tasks in the DB but not in files are left alone (no auto-delete).
9. Report: created N, updated N, unchanged N.

## System Bootstrap

Components bootstrapped per cogent:

| Component | Type | Description |
|-----------|------|-------------|
| `pick-task-to-run` | Program (python) | Softmax scheduler |
| `run-task` | Program (python) | Task dispatcher |
| `do-content` | Program (prompt) | Executes task content directly |
| `verify-completion` | Program (prompt) | Evaluates run results |
| `scheduler:tick` | Cron (10-30s) | Fires scheduler event |
| `scheduler:tick → pick-task-to-run` | Trigger | Wires cron to scheduler |
| `task:dispatch → run-task` | Trigger | Wires dispatch to runner |
| `run:succeeded → verify-completion` | Trigger | Wires success to verifier |
| `run:failed → handle-run-failure` | Trigger | Wires failures to handler |
| `/vsm/s1/task-priority-temperature` | Memory | Softmax temperature config |
| `ecs` | Resource (pool) | ECS concurrency limit |
| `lambda` | Resource (pool) | Lambda concurrency limit |
| `concurrent-tasks` | Resource (pool) | Total task concurrency limit |
