# Run Efficiency Improvements

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 efficiency issues identified from analyzing the last 10 production runs: wrong API names in scheduler prompt, no throttle-aware scheduling, wrong model tier for simple tasks, broken `dir()`/`help()` in sandbox, and LLM health checks that should be code-only.

**Architecture:** Each task modifies independent files. Tasks 1-4 are pure code changes. Task 5 converts the discord daemon from LLM to Python executor. All changes are backwards-compatible — the image must be rebooted to pick up prompt/config changes.

**Tech Stack:** Python 3.14, pytest, pydantic, boto3 (Bedrock)

---

### Task 1: Fix Scheduler System Prompt — Use Actual API Names

Every scheduler run wastes 1-5 turns discovering that `match_channel_messages()` doesn't exist and the real method is `scheduler.match_messages()`. The system prompt uses wrong names and doesn't show return types.

**Files:**
- Modify: `images/cogent-v1/cogos/lib/scheduler.md`

**Step 1: Update scheduler.md with correct API**

Replace the full contents of `images/cogent-v1/cogos/lib/scheduler.md` with:

```markdown
You are the CogOS scheduler daemon. The dispatcher runs you every minute via `system:tick:minute`.

## Tick workflow

Execute all four steps in a single `run_code` call:

```python
r1 = scheduler.match_messages()
print(f"Matched {r1.deliveries_created} deliveries")

r2 = scheduler.unblock_processes()
print(f"Unblocked {r2.unblocked_count} processes")

r3 = scheduler.select_processes(slots=3)
print(f"Selected {len(r3.selected)} processes")

for proc in r3.selected:
    r4 = scheduler.dispatch_process(process_id=proc.id)
    print(f"Dispatched {r4.process_name} -> run {r4.run_id}")
```

## API reference

- `scheduler.match_messages() -> MatchResult` — `deliveries_created: int`, `deliveries: list[DeliveryInfo]`
- `scheduler.unblock_processes() -> UnblockResult` — `unblocked_count: int`, `unblocked: list[UnblockInfo]`
- `scheduler.select_processes(slots: int = 1) -> SelectResult` — `selected: list[SelectedProcess]` (each has `.id`, `.name`)
- `scheduler.dispatch_process(process_id: str) -> DispatchResult` — `run_id`, `process_name`

## Rules

- Never skip steps. Always run all four in order.
- Run all four steps in ONE run_code call — do not use separate calls.
- If select_processes returns an empty list, the tick is done — nothing to schedule.
- Report a brief summary of what happened this tick.
```

**Step 2: Run existing scheduler tests**

Run: `pytest tests/cogos/test_scheduler_channels.py tests/cogos/test_scheduler_ingress.py -v`
Expected: All PASS (prompt-only change, no code change)

**Step 3: Commit**

```bash
git add images/cogent-v1/cogos/lib/scheduler.md
git commit -m "fix(scheduler): use correct API names in system prompt to eliminate discovery turns"
```

---

### Task 2: Add Throttle-Aware Scheduling

6 of 10 runs failed with ThrottlingException, each burning 80-106s of pure retry. The system retries every minute with no cooldown. Add: (a) `THROTTLED` run status, (b) throttle detection in executor, (c) cooldown logic in dispatcher.

**Files:**
- Modify: `src/cogos/db/models/run.py`
- Modify: `src/cogos/executor/handler.py` (exception handler ~line 724)
- Modify: `src/cogtainer/lambdas/dispatcher/handler.py`
- Test: `tests/cogos/test_throttle_cooldown.py` (create)

**Step 1: Write the failing test**

Create `tests/cogos/test_throttle_cooldown.py`:

```python
"""Tests for throttle-aware scheduling."""
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Process, ProcessMode, ProcessStatus, Run, RunStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(name=name, mode=ProcessMode.DAEMON, status=status, runner="lambda")


def test_throttled_status_exists():
    """RunStatus.THROTTLED is a valid status."""
    assert RunStatus.THROTTLED == "throttled"


def test_is_throttle_cooldown_active_no_runs(tmp_path):
    """No recent throttled runs means no cooldown."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active
    repo = _repo(tmp_path)
    assert _is_throttle_cooldown_active(repo) is False


def test_is_throttle_cooldown_active_recent_throttle(tmp_path):
    """A recent THROTTLED run triggers cooldown."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active
    repo = _repo(tmp_path)
    proc = _daemon("scheduler", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    run = Run(
        process=proc.id,
        status=RunStatus.THROTTLED,
        error="ThrottlingException",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    )
    repo.create_run(run)

    assert _is_throttle_cooldown_active(repo) is True


def test_is_throttle_cooldown_active_old_throttle(tmp_path):
    """A THROTTLED run older than cooldown window returns False."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active
    repo = _repo(tmp_path)
    proc = _daemon("scheduler", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    run = Run(
        process=proc.id,
        status=RunStatus.THROTTLED,
        error="ThrottlingException",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    repo.create_run(run)

    assert _is_throttle_cooldown_active(repo) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/test_throttle_cooldown.py -v`
Expected: FAIL — `RunStatus.THROTTLED` doesn't exist yet

**Step 3: Add THROTTLED status to RunStatus**

In `src/cogos/db/models/run.py`, add after line 19 (`SUSPENDED = "suspended"`):

```python
    THROTTLED = "throttled"
```

**Step 4: Mark throttled runs in executor exception handler**

In `src/cogos/executor/handler.py`, in the exception handler (around line 724), detect ThrottlingException and set the status appropriately. Find the block that starts with `except Exception as exc:` after the main converse loop, and add throttle detection before the `raise`:

Replace (around line 724-753):
```python
    except Exception as exc:
        _publish_process_io(repo, process, "stderr", f"[{process.name}] {exc}")
```

With:
```python
    except Exception as exc:
        _publish_process_io(repo, process, "stderr", f"[{process.name}] {exc}")
        # Detect throttling so dispatcher can apply cooldown
        exc_str = str(exc)
        if "ThrottlingException" in exc_str or "Too many tokens" in exc_str:
            run.status = RunStatus.THROTTLED
```

This sets the run status before it gets persisted by the caller (`handler()` function at the top).

Also need to make the caller (`handler()`) respect the status the inner function set. Find `_complete_run` call for failed runs — look at `handler()` around line 310-340 where it catches exceptions and completes the run. The status needs to use `run.status` if it was set to THROTTLED.

In `src/cogos/executor/handler.py`, find the `except Exception as e:` block in the outer `handler()` function (around line 300-340). Find where it calls `repo.complete_run(... status=RunStatus.FAILED ...)` and change it to respect the inner status:

Replace:
```python
        repo.complete_run(
            run_id,
            status=RunStatus.FAILED,
```

With:
```python
        # Preserve THROTTLED status set by execute_process
        final_status = run.status if run.status == RunStatus.THROTTLED else RunStatus.FAILED
        repo.complete_run(
            run_id,
            status=final_status,
```

**Step 5: Add cooldown check to dispatcher**

In `src/cogtainer/lambdas/dispatcher/handler.py`, add a helper function after the imports and before `handler()`:

```python
_THROTTLE_COOLDOWN_MS = 300_000  # 5 minutes


def _is_throttle_cooldown_active(repo) -> bool:
    """Check if any recent run was throttled, indicating we should back off."""
    from cogos.db.models import RunStatus
    recent = repo.list_recent_failed_runs(max_age_ms=_THROTTLE_COOLDOWN_MS)
    return any(r.status == RunStatus.THROTTLED for r in recent)
```

Then in `handler()`, add a cooldown check after the heartbeat block (after line 52) and before the reap block (line 54):

```python
    # 0. Check throttle cooldown — skip LLM dispatch if recently throttled
    if _is_throttle_cooldown_active(repo):
        logger.info("Throttle cooldown active — skipping LLM dispatch this tick")
        return {"statusCode": 200, "dispatched": 0, "throttle_cooldown": True}
```

Note: The `list_recent_failed_runs` method already exists and queries runs with status in (FAILED, TIMEOUT). We need it to also include THROTTLED. Check the repository method.

**Step 6: Update list_recent_failed_runs to include THROTTLED**

In `src/cogos/db/repository.py`, find `list_recent_failed_runs` (around line 1112). The SQL query filters on status. Add THROTTLED:

Find the query string that has `'failed'` and `'timeout'` and add `'throttled'` to the IN clause.

**Step 7: Run tests**

Run: `pytest tests/cogos/test_throttle_cooldown.py -v`
Expected: All PASS

**Step 8: Run existing tests to verify no regression**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: All PASS

**Step 9: Commit**

```bash
git add src/cogos/db/models/run.py src/cogos/executor/handler.py src/cogtainer/lambdas/dispatcher/handler.py tests/cogos/test_throttle_cooldown.py src/cogos/db/repository.py
git commit -m "feat(scheduler): throttle-aware scheduling with 5-min cooldown after ThrottlingException"
```

---

### Task 3: Use Haiku for Simple Daemon Tasks

The discord orchestrator and scheduler use sonnet-4.5 ($0.032/run, 75-102s) for tasks that haiku ($0.012/run, 15s) handles well. Set model explicitly on these processes.

**Files:**
- Modify: `images/cogent-v1/cogos/init.py` (scheduler spawn, line 21)
- Modify: `images/cogent-v1/apps/discord/init/cog.py` (discord cog, line 17)

**Step 1: Set haiku model on scheduler process**

In `images/cogent-v1/cogos/init.py`, change the `procs.spawn("scheduler", ...)` call (line 21-26) to include a model parameter:

```python
    r = procs.spawn("scheduler",
        mode="daemon",
        content=scheduler_data.content,
        priority=100.0,
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        capabilities={"scheduler": None, "channels": None},
        subscribe="system:tick:minute")
```

**Step 2: Set haiku model on discord cog**

In `images/cogent-v1/apps/discord/init/cog.py`, add `model` to the `make_default_coglet()` call (line 17):

```python
cog.make_default_coglet(
    entrypoint="main.md",
    mode="daemon",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    files={"main.md": _read("discord.md")},
    ...
```

**Step 3: Run tests**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: All PASS (image config only, no code behavior change)

**Step 4: Commit**

```bash
git add images/cogent-v1/cogos/init.py images/cogent-v1/apps/discord/init/cog.py
git commit -m "perf: use haiku for scheduler and discord orchestrator (3x cheaper, 5x faster)"
```

---

### Task 4: Fix dir() and help() in Sandbox

The sandbox blocks `dir()` because it collides with the `dir` capability namespace (a file directory capability). But the model tries `dir(scheduler)` to discover APIs, fails, and wastes turns. Fix: add a safe `dir()` that works on capability objects, and fix the `help()` builtin.

The `help()` method exists on each Capability subclass via `Capability.help()`. But the builtin `help()` is not available. The model tries `scheduler.help()` which works but `print(dir(scheduler))` fails.

**Files:**
- Modify: `src/cogos/sandbox/executor.py` (add safe dir/help to builtins)
- Modify: `tests/cogos/test_sandbox_builtins.py` (update dir test, add help test)

**Step 1: Write failing tests**

Add to `tests/cogos/test_sandbox_builtins.py`:

```python
def test_safe_dir_lists_public_methods():
    """dir() on a capability object lists its public methods."""
    from unittest.mock import MagicMock
    from uuid import uuid4
    from cogos.capabilities.scheduler import SchedulerCapability

    repo = MagicMock()
    cap = SchedulerCapability(repo, uuid4())

    vt = VariableTable()
    vt.set("scheduler", cap)
    executor = SandboxExecutor(vt)
    result = executor.execute("print(dir(scheduler))")
    assert "match_messages" in result
    assert "select_processes" in result
    assert "__" not in result  # no dunders


def test_safe_dir_on_builtin_types():
    """dir() on strings/lists shows public methods."""
    result = _run("print(dir('hello'))")
    assert "upper" in result
    assert "__" not in result


def test_safe_help_on_capability():
    """help(obj) prints the capability help text."""
    from unittest.mock import MagicMock
    from uuid import uuid4
    from cogos.capabilities.scheduler import SchedulerCapability

    repo = MagicMock()
    cap = SchedulerCapability(repo, uuid4())

    vt = VariableTable()
    vt.set("scheduler", cap)
    executor = SandboxExecutor(vt)
    result = executor.execute("help(scheduler)")
    assert "match_messages" in result
    assert "MatchResult" in result
```

Also update the existing `test_safe_builtins_blocks_dir` test — it should now PASS instead of expecting an error:

Replace the existing test:
```python
def test_safe_builtins_blocks_dir():
    """dir() is excluded because it collides with the dir capability namespace."""
    result = _run("print(dir([]))")
    assert "Error" in result or "error" in result.lower()
```

With:
```python
def test_safe_dir_filters_dunders():
    """dir() works but filters out dunder attributes."""
    result = _run("print(dir([]))")
    assert "append" in result
    assert "__" not in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cogos/test_sandbox_builtins.py -v`
Expected: New tests FAIL, modified test FAILS

**Step 3: Implement safe dir() and help()**

In `src/cogos/sandbox/executor.py`, add two helper functions after `_safe_getattr` (after line 33):

```python
def _safe_dir(obj=None):
    """dir() that filters out dunder attributes for sandbox safety."""
    if obj is None:
        return []
    return [name for name in dir(obj) if not name.startswith("_")]


def _safe_help(obj=None):
    """help() that prints capability help or public methods."""
    if obj is None:
        print("Use help(object) to see available methods.")
        return
    if hasattr(obj, "help") and callable(obj.help) and not isinstance(obj, type):
        print(obj.help())
        return
    methods = _safe_dir(obj)
    type_name = type(obj).__name__
    print(f"{type_name} methods: {', '.join(methods)}")
```

Then add them to `_SAFE_BUILTINS` dict. Add after the `"callable": callable,` line (line 79):

```python
    "dir": _safe_dir,
    "help": _safe_help,
```

**Step 4: Run tests**

Run: `pytest tests/cogos/test_sandbox_builtins.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/cogos/sandbox/executor.py tests/cogos/test_sandbox_builtins.py
git commit -m "feat(sandbox): add safe dir() and help() builtins to eliminate API discovery waste"
```

---

### Task 5: Make Discord Health Check Non-LLM

The discord daemon's most common task is checking if the handler is alive — a deterministic status check. Convert it from LLM executor to Python executor. This eliminates a $0.032 LLM call and 100s of latency per health check.

The discord daemon still needs LLM for diagnosis (step 3) when the handler is unhealthy. Strategy: make the common path (healthy handler) a Python executor process, and only escalate to supervisor if unhealthy.

**Files:**
- Create: `images/cogent-v1/apps/discord/discord.py` (Python executor script)
- Modify: `images/cogent-v1/apps/discord/init/cog.py` (switch to python executor)
- Keep: `images/cogent-v1/apps/discord/discord.md` (referenced for handler creation)

**Step 1: Create Python executor script**

Create `images/cogent-v1/apps/discord/discord.py`:

```python
# Discord cog orchestrator — Python executor (no LLM needed for health checks).
#
# This runs every activation. The common path (handler healthy) completes
# instantly with zero LLM tokens. Only escalates if something is wrong.

h = procs.get(name="discord/handler")
has_handler = hasattr(h, 'status') and callable(h.status)

if not has_handler:
    # Bootstrap: create the handler coglet
    handler_prompt = file.read("apps/discord/handler/main.md").content
    test_content_result = file.read("apps/discord/handler/test_main.py")
    test_content = test_content_result.content if hasattr(test_content_result, 'content') else ""
    cog.make_coglet(
        name="handler",
        test_command="pytest test_main.py -v",
        files={"main.md": handler_prompt, "test_main.py": test_content},
        entrypoint="main.md",
        mode="daemon",
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        capabilities=[
            "discord", "channels", "stdlib", "procs", "file",
            "image", "blob", "secrets",
            {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
        ],
        idle_timeout_ms=300000,
    )
    h2 = cog.make_coglet("handler")
    coglet_runtime.run(h2, procs, subscribe=[
        "io:discord:dm", "io:discord:mention", "io:discord:message",
    ])
    print("Handler created and started")
    exit()

# Health check
status = h.status()
if status == "waiting" or status == "running":
    print(f"Handler is {status}. No action needed.")
    exit()

# Handler is unhealthy — escalate to supervisor for LLM-powered diagnosis
channels.send("supervisor:help", {
    "type": "discord:handler_unhealthy",
    "handler_status": status,
    "message": f"Discord handler is {status} — needs diagnosis and possible restart",
})
print(f"Handler is {status} — escalated to supervisor")
```

**Step 2: Update cog.py to use Python executor**

In `images/cogent-v1/apps/discord/init/cog.py`, change the entrypoint and add executor:

```python
cog = add_cog("discord")
cog.make_default_coglet(
    entrypoint="main.py",
    mode="daemon",
    executor="python",
    files={"main.py": _read("discord.py"), "main.md": _read("discord.md")},
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "stdlib", "cog", "coglet_runtime", "image", "blob", "secrets",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
    ],
    handlers=[
        "discord-cog:review",
        "system:tick:hour",
    ],
    priority=5.0,
)
```

**Step 3: Run tests**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: All PASS

**Step 4: Commit**

```bash
git add images/cogent-v1/apps/discord/discord.py images/cogent-v1/apps/discord/init/cog.py
git commit -m "perf(discord): switch health check to Python executor (zero LLM tokens, instant)"
```

---

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Scheduler turns per tick | 4-14 | 1-2 |
| Scheduler cost per tick | $0.035-0.058 | ~$0.005 (haiku + fewer turns) |
| Discord health check cost | $0.032 (sonnet) | $0 (Python executor) |
| Discord health check time | 102s | <1s |
| Throttled run waste | 80-106s × N retries | 0s (5-min cooldown) |
| Failed runs from throttling | 60% of runs | ~0% (cooldown prevents cascading) |
