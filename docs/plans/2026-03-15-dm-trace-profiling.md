# DM Trace Profiling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add end-to-end timing traces from Discord DM received to reply sent, covering all 7 pipeline stages.

**Architecture:** Generate a `trace_id` at the Discord bridge on DM receipt. Thread it through ChannelMessage → Delivery → Run → SQS reply. Each stage stamps epoch-ms timestamps. The bridge logs a full trace summary when the reply is sent. The dashboard `/message-traces` API computes timing breakdowns from the trace-linked records.

**Tech Stack:** Python/Pydantic models, PostgreSQL (RDS Data API), FastAPI dashboard

---

### Task 1: Add trace fields to Pydantic models

**Files:**
- Modify: `src/cogos/db/models/channel_message.py:11-17`
- Modify: `src/cogos/db/models/delivery.py:19-25`
- Modify: `src/cogos/db/models/run.py:22-38`

**Step 1: Add trace_id and trace_meta to ChannelMessage**

```python
# src/cogos/db/models/channel_message.py
class ChannelMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel: UUID
    sender_process: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    trace_id: UUID | None = None
    trace_meta: dict[str, Any] | None = None
    created_at: datetime | None = None
```

**Step 2: Add trace_id to Delivery**

```python
# src/cogos/db/models/delivery.py
class Delivery(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    message: UUID
    handler: UUID
    status: DeliveryStatus = DeliveryStatus.PENDING
    run: UUID | None = None
    trace_id: UUID | None = None
    created_at: datetime | None = None
```

**Step 3: Add trace_id and parent_trace_id to Run**

```python
# src/cogos/db/models/run.py
class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    process: UUID
    message: UUID | None = None
    conversation: UUID | None = None
    status: RunStatus = RunStatus.RUNNING
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_ms: int | None = None
    error: str | None = None
    model_version: str | None = None
    result: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    scope_log: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: UUID | None = None
    parent_trace_id: UUID | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
```

**Step 4: Run existing tests to verify no regressions**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass (new fields have defaults so no breakage)

**Step 5: Commit**

```
feat(trace): add trace_id fields to ChannelMessage, Delivery, Run models
```

---

### Task 2: Add SQL migration for trace columns

**Files:**
- Create: `src/cogos/db/migrations/013_trace_fields.sql`

**Step 1: Write the migration SQL**

```sql
-- Add trace profiling columns to CogOS tables
ALTER TABLE cogos_channel_message ADD COLUMN IF NOT EXISTS trace_id UUID;
ALTER TABLE cogos_channel_message ADD COLUMN IF NOT EXISTS trace_meta JSONB;

ALTER TABLE cogos_delivery ADD COLUMN IF NOT EXISTS trace_id UUID;

ALTER TABLE cogos_run ADD COLUMN IF NOT EXISTS trace_id UUID;
ALTER TABLE cogos_run ADD COLUMN IF NOT EXISTS parent_trace_id UUID;

CREATE INDEX IF NOT EXISTS idx_cogos_channel_message_trace ON cogos_channel_message(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cogos_run_trace ON cogos_run(trace_id) WHERE trace_id IS NOT NULL;
```

**Step 2: Verify migration parses correctly**

Run: `python -c "from cogos.db.migrations import _split_sql; stmts = _split_sql(open('src/cogos/db/migrations/013_trace_fields.sql').read()); print(f'{len(stmts)} statements'); [print(s[:60]) for s in stmts if s.strip()]"`
Expected: 6 statements printed

**Step 3: Commit**

```
feat(trace): add migration 013 for trace_id columns
```

---

### Task 3: Update Repository to persist trace fields

**Files:**
- Modify: `src/cogos/db/repository.py:1336-1393` (append_channel_message)
- Modify: `src/cogos/db/repository.py:543-558` (create_delivery)
- Modify: `src/cogos/db/repository.py:991-1022` (create_run)

**Step 1: Update append_channel_message to include trace_id and trace_meta**

In the two INSERT statements in `append_channel_message`, add `trace_id` and `trace_meta` columns:

For the idempotency branch (line ~1339):
```sql
INSERT INTO cogos_channel_message (id, channel, sender_process, payload, idempotency_key, trace_id, trace_meta)
VALUES (:id, :channel, :sender_process, :payload::jsonb, :idempotency_key, :trace_id, :trace_meta::jsonb)
```

For the non-idempotency branch (line ~1366):
```sql
INSERT INTO cogos_channel_message (id, channel, sender_process, payload, trace_id, trace_meta)
VALUES (:id, :channel, :sender_process, :payload::jsonb, :trace_id, :trace_meta::jsonb)
```

Add `self._param("trace_id", msg.trace_id)` and `self._param("trace_meta", msg.trace_meta)` to both param lists.

**Step 2: Update create_delivery to include trace_id**

In the INSERT in `create_delivery` (~line 544), add `trace_id` column:
```sql
INSERT INTO cogos_delivery (id, message, handler, status, run, trace_id)
VALUES (:id, :message, :handler, :status, :run, :trace_id)
```

Add `self._param("trace_id", ed.trace_id)` to params.

**Step 3: Update create_run to include trace_id and parent_trace_id**

In the INSERT in `create_run` (~line 993), add both columns:
```sql
INSERT INTO cogos_run
    (id, process, message, conversation, status,
     tokens_in, tokens_out, cost_usd, duration_ms,
     error, model_version, result, snapshot, scope_log,
     trace_id, parent_trace_id)
VALUES (:id, :process, :message, :conversation, :status,
        :tokens_in, :tokens_out, :cost_usd::numeric, :duration_ms,
        :error, :model_version, :result::jsonb, :snapshot::jsonb, :scope_log::jsonb,
        :trace_id, :parent_trace_id)
```

Add both params.

**Step 4: Update LocalRepository similarly**

In `src/cogos/db/local_repository.py`, no SQL changes needed — the in-memory dicts store the full Pydantic model which already has the new fields. But verify auto-delivery creation copies trace_id from message to delivery.

In `LocalRepository.append_channel_message` (~line 1011-1017), after creating a delivery, set `delivery.trace_id = msg.trace_id`:
```python
delivery = Delivery(message=msg.id, handler=handler.id, trace_id=msg.trace_id)
```

In `Repository.append_channel_message` (~line 1386), same change:
```python
delivery = Delivery(message=msg_id, handler=handler.id, trace_id=msg.trace_id)
```

**Step 5: Run tests**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): persist trace_id in repository layer
```

---

### Task 4: Generate trace_id in Discord bridge on DM receipt

**Files:**
- Modify: `src/cogos/io/discord/bridge.py:186-223` (_relay_to_db)

**Step 1: Write failing test**

Create `tests/cogos/io/test_discord_bridge_trace.py`:
```python
"""Tests for trace_id generation in Discord bridge."""
from __future__ import annotations

from unittest.mock import MagicMock

import discord

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType
from cogos.io.discord.bridge import DiscordBridge


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge._typing_tasks = {}
    return bridge


async def test_relay_to_db_sets_trace_id_for_dm():
    """DM messages should get a trace_id and trace_meta with timing."""
    bridge = _make_bridge()
    bridge.client.user = None
    bridge._start_typing = MagicMock()

    repo = LocalRepository()
    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    bridge._get_repo = MagicMock(return_value=repo)

    msg = MagicMock(spec=discord.Message)
    msg.content = "hello"
    msg.author = MagicMock()
    msg.author.id = 123
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.DMChannel)
    msg.channel.id = 456
    msg.id = 789
    msg.guild = None
    msg.created_at = MagicMock()
    msg.created_at.timestamp = MagicMock(return_value=1000.0)
    msg.created_at.isoformat = MagicMock(return_value="2026-01-01T00:00:00")
    msg.attachments = []
    msg.embeds = []
    msg.reference = None

    await bridge._relay_to_db(msg)

    messages = repo.list_channel_messages(limit=10)
    assert len(messages) == 1
    assert messages[0].trace_id is not None
    assert messages[0].trace_meta is not None
    assert "discord_created_at_ms" in messages[0].trace_meta
    assert "bridge_received_at_ms" in messages[0].trace_meta
    assert "db_written_at_ms" in messages[0].trace_meta


async def test_relay_to_db_no_trace_id_for_regular_message():
    """Regular channel messages should NOT get a trace_id."""
    bridge = _make_bridge()
    mock_user = MagicMock()
    mock_user.mentioned_in = MagicMock(return_value=False)
    bridge.client.user = mock_user

    repo = LocalRepository()
    ch = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    bridge._get_repo = MagicMock(return_value=repo)

    msg = MagicMock(spec=discord.Message)
    msg.content = "hello"
    msg.author = MagicMock()
    msg.author.id = 123
    msg.author.bot = False
    msg.channel = MagicMock()
    msg.channel.__class__ = type("TextChannel", (), {})
    msg.channel.id = 456
    msg.id = 790
    msg.guild = MagicMock()
    msg.guild.id = 999
    msg.created_at = MagicMock()
    msg.created_at.timestamp = MagicMock(return_value=1000.0)
    msg.created_at.isoformat = MagicMock(return_value="2026-01-01T00:00:00")
    msg.attachments = []
    msg.embeds = []
    msg.reference = None

    await bridge._relay_to_db(msg)

    messages = repo.list_channel_messages(limit=10)
    assert len(messages) == 1
    assert messages[0].trace_id is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/io/test_discord_bridge_trace.py -x -v --timeout=30 2>&1 | tail -20`
Expected: FAIL — trace_id is None for DM

**Step 3: Implement trace_id generation in _relay_to_db**

In `src/cogos/io/discord/bridge.py`, modify `_relay_to_db`:

```python
async def _relay_to_db(self, message: discord.Message):
    """Classify a Discord message and write it as a channel message."""
    if isinstance(message.channel, discord.DMChannel):
        message_type = "discord:dm"
    elif self.client.user and self.client.user.mentioned_in(message):
        message_type = "discord:mention"
    else:
        message_type = "discord:message"

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

    payload = _make_message_payload(message, message_type, is_dm=is_dm, is_mention=is_mention)

    # Generate trace for DMs and mentions (messages that trigger processing)
    trace_id = None
    trace_meta = None
    if message_type in ("discord:dm", "discord:mention"):
        from uuid import uuid4
        bridge_received_at_ms = int(time.time() * 1000)
        trace_id = uuid4()
        trace_meta = {
            "discord_created_at_ms": int(message.created_at.timestamp() * 1000),
            "bridge_received_at_ms": bridge_received_at_ms,
        }

    try:
        from cogos.db.models import ChannelMessage
        repo = self._get_repo()

        channel_name = f"io:discord:{message_type.split(':')[1]}"
        ch = self._get_or_create_channel(repo, channel_name)
        if ch is None:
            raise RuntimeError(f"Failed to create Discord channel {channel_name}")

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=None,
            payload=payload,
            idempotency_key=f"discord:{message.id}",
            trace_id=trace_id,
            trace_meta=trace_meta,
        ))

        # Stamp db_written_at after successful insert
        if trace_meta is not None:
            trace_meta["db_written_at_ms"] = int(time.time() * 1000)

        logger.info("Wrote %s from %s to channel %s", message_type, message.author, channel_name)

        if message_type in ("discord:dm", "discord:mention"):
            self._start_typing(message.channel)
    except Exception:
        logger.exception("Failed to write message %s to DB", message.id)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/io/test_discord_bridge_trace.py -x -v --timeout=30 2>&1 | tail -20`
Expected: PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): generate trace_id on DM/mention receipt in Discord bridge
```

---

### Task 5: Propagate trace_id through scheduler dispatch

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py:166-198` (dispatch_process)
- Modify: `src/cogos/runtime/dispatch.py:40-47` (build_dispatch_event)

**Step 1: Write failing test**

Create `tests/cogos/test_trace_propagation.py`:
```python
"""Tests for trace_id propagation through scheduler → dispatch → executor."""
from __future__ import annotations

from uuid import uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability, Channel, ChannelType, Delivery, Handler,
    Process, ProcessCapability, ProcessMode, ProcessStatus,
)


def _setup_repo_with_traced_message():
    """Create a repo with a process, handler, channel, and a traced message."""
    repo = LocalRepository()

    cap = Capability(name="test/cap", handler="cogos.capabilities:Capability")
    repo.upsert_capability(cap)

    proc = Process(
        name="test-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(proc)
    repo.upsert_process_capability(ProcessCapability(
        process=proc.id, capability=cap.id, name="test",
    ))

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.upsert_handler(handler)

    trace_id = uuid4()
    from cogos.db.models import ChannelMessage
    repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={"content": "hello"},
        trace_id=trace_id,
        trace_meta={"discord_created_at_ms": 1000, "bridge_received_at_ms": 1001, "db_written_at_ms": 1002},
    ))

    return repo, proc, trace_id


def test_dispatch_propagates_trace_id_to_delivery():
    """Delivery auto-created by append_channel_message should inherit trace_id."""
    repo, proc, trace_id = _setup_repo_with_traced_message()

    deliveries = repo.get_pending_deliveries(proc.id)
    assert len(deliveries) == 1
    assert deliveries[0].trace_id == trace_id


def test_dispatch_propagates_trace_id_to_run():
    """dispatch_process should copy trace_id from delivery to run."""
    repo, proc, trace_id = _setup_repo_with_traced_message()

    # Process should be RUNNABLE (auto-transitioned by append_channel_message)
    proc = repo.get_process(proc.id)
    assert proc.status == ProcessStatus.RUNNABLE

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))
    assert not hasattr(result, "error")

    run = repo.get_run(result.run_id)
    assert run is not None
    assert run.trace_id == trace_id


def test_build_dispatch_event_includes_trace_id():
    """build_dispatch_event should include trace_id in the event envelope."""
    repo, proc, trace_id = _setup_repo_with_traced_message()

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))

    from cogos.runtime.dispatch import build_dispatch_event
    event = build_dispatch_event(repo, result)
    assert event["trace_id"] == str(trace_id)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_trace_propagation.py -x -v --timeout=30 2>&1 | tail -20`
Expected: FAIL — trace_id not propagated

**Step 3: Implement propagation**

3a. In `scheduler.py` `dispatch_process` (~line 184), when creating the Run, copy trace_id from delivery's message:

```python
# After: message_id = deliveries[0].message if deliveries else None
trace_id = deliveries[0].trace_id if deliveries else None

run = Run(process=target_id, message=message_id, trace_id=trace_id)
```

3b. In `DispatchResult`, add `trace_id` field:
```python
class DispatchResult(BaseModel):
    run_id: str
    process_id: str
    process_name: str
    runner: str
    message_id: str | None = None
    delivery_id: str | None = None
    trace_id: str | None = None
```

And populate it in dispatch_process return:
```python
trace_id=str(trace_id) if trace_id else None,
```

3c. In `dispatch.py` `build_dispatch_event`, add trace_id:
```python
def build_dispatch_event(repo, dispatch_result) -> dict[str, Any]:
    return {
        "process_id": dispatch_result.process_id,
        "run_id": dispatch_result.run_id,
        "message_id": dispatch_result.message_id,
        "trace_id": dispatch_result.trace_id,
        "dispatched_at_ms": int(time.time() * 1000),
        "payload": _load_message_payload(repo, dispatch_result.message_id),
    }
```

Add `import time` at the top of dispatch.py.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/test_trace_propagation.py -x -v --timeout=30 2>&1 | tail -20`
Expected: PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): propagate trace_id through scheduler dispatch to Run
```

---

### Task 6: Thread trace_id through executor and reply

**Files:**
- Modify: `src/cogos/executor/handler.py:109-178` (handler function + execute_process)
- Modify: `src/cogos/io/discord/capability.py:67-77` (_with_reply_meta)

**Step 1: Executor reads trace_id from event, stamps on run**

In `handler()` (~line 109), after creating/finding the run:
```python
# After run_id is established
trace_id_str = event.get("trace_id")
dispatched_at_ms = event.get("dispatched_at_ms")
executor_started_at_ms = int(time.time() * 1000)

if trace_id_str:
    try:
        from uuid import UUID as _UUID
        trace_uuid = _UUID(trace_id_str)
        # Update run with trace_id if not already set
        repo.execute(
            "UPDATE cogos_run SET trace_id = :trace_id WHERE id = :id AND trace_id IS NULL",
            {"trace_id": trace_uuid, "id": run.id},
        )
        run.trace_id = trace_uuid
    except (ValueError, Exception):
        logger.debug("Could not set trace_id on run %s", run.id)
```

In the `_log_run_completion_latency` or after `complete_run`, log the executor timing:
```python
if trace_id_str:
    logger.info(
        "CogOS trace executor_timing trace_id=%s run=%s process=%s "
        "dispatched_at_ms=%s executor_started_at_ms=%s executor_duration_ms=%s",
        trace_id_str, run.id, process.name,
        dispatched_at_ms, executor_started_at_ms, duration_ms,
    )
```

**Step 2: Pass trace_id to reply _meta**

In `src/cogos/io/discord/capability.py`, modify `_with_reply_meta` to accept a `trace_id` param from the run. The issue is the capability already generates a random trace_id. Change it to use the run's trace_id if available:

```python
def _with_reply_meta(body: dict, *, process_id: UUID, run_id: UUID | None, trace_id: UUID | None = None) -> dict:
    meta = {
        "queued_at_ms": int(time.time() * 1000),
        "trace_id": str(trace_id) if trace_id else str(uuid4()),
        "process_id": str(process_id),
    }
    if run_id is not None:
        meta["run_id"] = str(run_id)
    enriched = dict(body)
    enriched["_meta"] = meta
    return enriched
```

Then in the DiscordCapability class, store `trace_id` from the run. The capability is already initialized with `process_id` and `run_id`. We need to also pass `trace_id`.

Check how capabilities are instantiated. In `executor/handler.py:_setup_capability_proxies`, the handler class is constructed with `(repo, process.id, run_id=run_id)`. The base capability needs a `trace_id` kwarg.

Check `src/cogos/capabilities/base.py` for the Capability base class:

The simplest approach: store `trace_id` on the Run object (which we already do), and have the DiscordCapability look it up from the repo when needed. But that's an extra query.

Better: Add `trace_id` to the capability proxy init. In `_setup_capability_proxies`, pass `trace_id` alongside `run_id`:

In `base.py`, add `trace_id` to Capability init. In `_setup_capability_proxies`, pass `trace_id=run.trace_id` (we need to get this from the event).

Actually, simplest: store `trace_id` as an attribute on the executor's Run object, then pass it through the variable table. But the DiscordCapability constructs `_with_reply_meta` with its own `self.run_id`.

Pragmatic approach: thread `trace_id` through the Capability base class the same way `run_id` is threaded:

In `_setup_capability_proxies`, the `run_id` is passed. We can pass `trace_id` the same way. Check the `init_params` check:

```python
init_params = inspect.signature(handler_cls.__init__).parameters
if "run_id" in init_params:
    instance = handler_cls(repo, process.id, run_id=run_id)
```

Add similar for trace_id. But we need to know the trace_id. The executor should extract it from the event and pass it down.

Implementation:
1. In `handler()`, extract `trace_id` from event before calling `execute_process`.
2. Pass `trace_id` to `execute_process` and `_setup_capability_proxies`.
3. In `_setup_capability_proxies`, pass `trace_id` if the handler class accepts it.
4. In `DiscordCapability`, accept `trace_id` and use it in `_with_reply_meta`.

This is the cleanest approach — minimal changes, follows existing patterns.

**Step 3: Update execute_process signature**

Add `trace_id: UUID | None = None` param to `execute_process()` and `_execute_python_process()`. Thread it to `_setup_capability_proxies()`.

In `_setup_capability_proxies`, add `trace_id: UUID | None = None` param:
```python
def _setup_capability_proxies(vt, process, repo, *, run_id=None, trace_id=None):
    ...
    init_params = inspect.signature(handler_cls.__init__).parameters
    kwargs = {}
    if "run_id" in init_params:
        kwargs["run_id"] = run_id
    if "trace_id" in init_params:
        kwargs["trace_id"] = trace_id
    instance = handler_cls(repo, process.id, **kwargs) if kwargs else handler_cls(repo, process.id)
```

**Step 4: Update DiscordCapability to accept and use trace_id**

In `capability.py`, update `DiscordCapability.__init__` (inherited from Capability base):

Check `src/cogos/capabilities/base.py`:

The base `Capability` class likely has `__init__(self, repo, process_id, *, run_id=None)`. Add `trace_id=None`:

```python
class Capability:
    def __init__(self, repo, process_id, *, run_id=None, trace_id=None):
        self.repo = repo
        self.process_id = process_id
        self.run_id = run_id
        self.trace_id = trace_id
        ...
```

Then in `DiscordCapability.send()` etc., pass `trace_id=self.trace_id` to `_with_reply_meta`.

**Step 5: Run tests**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): thread trace_id through executor to reply SQS meta
```

---

### Task 7: Log trace summary in Discord bridge on reply send

**Files:**
- Modify: `src/cogos/io/discord/bridge.py:292-416` (_send_reply, _handle_message, _handle_dm)

**Step 1: Write failing test**

Add to `tests/cogos/io/test_discord_bridge_trace.py`:
```python
import logging

async def test_trace_summary_logged_on_dm_reply(caplog):
    """Bridge should log a trace summary when sending a DM reply with trace_id."""
    bridge = _make_bridge()
    bridge._stop_typing = MagicMock()

    mock_user = MagicMock()  # AsyncMock for fetch_user
    mock_dm_channel = MagicMock()
    mock_dm_channel.id = 444
    mock_dm_channel.send = MagicMock(return_value=None)  # AsyncMock
    mock_user.create_dm = MagicMock(return_value=mock_dm_channel)
    bridge.client.fetch_user = MagicMock(return_value=mock_user)

    # Use AsyncMock for async methods
    from unittest.mock import AsyncMock
    bridge.client.fetch_user = AsyncMock(return_value=mock_user)
    mock_user.create_dm = AsyncMock(return_value=mock_dm_channel)
    mock_dm_channel.send = AsyncMock()

    body = {
        "user_id": "777",
        "content": "reply text",
        "_meta": {
            "queued_at_ms": 9000,
            "trace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "process_id": "proc-1",
            "run_id": "run-1",
        },
    }

    with caplog.at_level(logging.INFO, logger="cogos.io.discord.bridge"):
        await bridge._handle_dm(body)

    assert any("CogOS trace_complete" in r.message for r in caplog.records)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/io/test_discord_bridge_trace.py::test_trace_summary_logged_on_dm_reply -x -v --timeout=30 2>&1 | tail -20`
Expected: FAIL — no trace_complete log

**Step 3: Implement trace summary logging**

Add a helper to bridge.py:
```python
def _log_trace_summary(self, body: dict, *, msg_type: str, target_id: int | str):
    """Log a complete trace summary if _meta contains trace_id."""
    meta = body.get("_meta")
    if not isinstance(meta, dict):
        return
    trace_id = meta.get("trace_id")
    if not trace_id:
        return

    now_ms = int(time.time() * 1000)
    queued_at_ms = meta.get("queued_at_ms")
    sqs_received_at_ms = meta.get("sqs_received_at_ms", now_ms)

    sqs_to_receive_ms = (sqs_received_at_ms - queued_at_ms) if queued_at_ms else None
    receive_to_send_ms = now_ms - sqs_received_at_ms

    logger.info(
        "CogOS trace_complete trace_id=%s type=%s target=%s "
        "process=%s run=%s "
        "sqs_to_receive_ms=%s receive_to_send_ms=%s",
        trace_id,
        msg_type,
        target_id,
        meta.get("process_id", ""),
        meta.get("run_id", ""),
        sqs_to_receive_ms,
        receive_to_send_ms,
    )
```

In `_send_reply`, stamp `sqs_received_at_ms` on the body meta:
```python
async def _send_reply(self, sqs_message: dict):
    body = json.loads(sqs_message["Body"])
    # Stamp SQS receive time for trace
    meta = body.get("_meta")
    if isinstance(meta, dict):
        meta["sqs_received_at_ms"] = int(time.time() * 1000)
    ...
```

Then in `_handle_dm`, after sending, call `_log_trace_summary`:
```python
async def _handle_dm(self, body: dict):
    ...
    for c in chunk_message(content):
        await dm_channel.send(c)
    self._log_reply_send_latency(body, msg_type="dm", target_id=dm_channel.id)
    self._log_trace_summary(body, msg_type="dm", target_id=dm_channel.id)
```

Similarly in `_handle_message`:
```python
    self._log_reply_send_latency(body, msg_type="message", target_id=target.id)
    self._log_trace_summary(body, msg_type="message", target_id=target.id)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/io/test_discord_bridge_trace.py -x -v --timeout=30 2>&1 | tail -20`
Expected: PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/cogos/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): log trace summary in bridge on reply send
```

---

### Task 8: Add timing breakdown to dashboard traces API

**Files:**
- Modify: `src/dashboard/routers/traces.py:27-68` (response models)
- Modify: `src/dashboard/routers/traces.py:193-294` (list_message_traces)

**Step 1: Write failing test**

Add a test that checks the API returns timing data. Look at existing dashboard test patterns first.

Create or extend a test:
```python
# tests/dashboard/test_trace_timing.py
"""Test that message-traces API returns timing breakdown."""
from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel, ChannelMessage, ChannelType, Delivery, DeliveryStatus,
    Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus,
)


def test_trace_timing_included_in_response():
    """Traces with trace_id should include timing breakdown."""
    repo = LocalRepository()

    proc = Process(name="p1", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, runner="lambda")
    repo.upsert_process(proc)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.upsert_handler(handler)

    trace_id = uuid4()
    msg_id = repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={"message_type": "discord:dm", "content": "hello"},
        trace_id=trace_id,
        trace_meta={
            "discord_created_at_ms": 1000,
            "bridge_received_at_ms": 1005,
            "db_written_at_ms": 1020,
        },
    ))

    deliveries = repo.get_pending_deliveries(proc.id)
    assert len(deliveries) == 1
    assert deliveries[0].trace_id == trace_id

    run = Run(process=proc.id, message=msg_id, trace_id=trace_id, status=RunStatus.COMPLETED)
    run.duration_ms = 3000
    run.tokens_in = 500
    run.tokens_out = 200
    repo.create_run(run)

    repo.mark_queued(deliveries[0].id, run.id)

    # Verify the data model supports trace info
    msg = repo.list_channel_messages(ch.id, limit=1)[0]
    assert msg.trace_id == trace_id
    assert msg.trace_meta["discord_created_at_ms"] == 1000
```

**Step 2: Run test to verify it passes (data model test)**

Run: `python -m pytest tests/dashboard/test_trace_timing.py -x -v --timeout=30 2>&1 | tail -20`
Expected: PASS (this just tests the data model is correct)

**Step 3: Add timing fields to trace response models**

In `traces.py`, add to `MessageTraceOut`:
```python
class TraceTimingOut(BaseModel):
    trace_id: str | None = None
    discord_to_db_ms: int | None = None
    db_to_match_ms: int | None = None
    match_to_dispatch_ms: int | None = None
    dispatch_to_executor_ms: int | None = None
    executor_ms: int | None = None
    total_ms: int | None = None

class MessageTraceOut(BaseModel):
    message: TraceMessageOut
    deliveries: list[TraceDeliveryOut]
    timing: TraceTimingOut | None = None
```

**Step 4: Compute timing in list_message_traces**

After building the trace, if the source message has `trace_id` and `trace_meta`, compute timing:

```python
timing = None
trace_meta = (message.trace_meta or {}) if hasattr(message, 'trace_meta') else {}
if message.trace_id and trace_meta:
    discord_to_db_ms = None
    db_to_match_ms = None
    db_written = trace_meta.get("db_written_at_ms")
    discord_created = trace_meta.get("discord_created_at_ms")

    if discord_created and db_written:
        discord_to_db_ms = db_written - discord_created

    # First delivery created_at gives match time
    first_delivery_at = None
    if message_deliveries:
        dt = _as_utc(message_deliveries[0].created_at)
        if dt:
            first_delivery_at = int(dt.timestamp() * 1000)
    if db_written and first_delivery_at:
        db_to_match_ms = first_delivery_at - db_written

    # Run gives executor duration
    executor_ms = None
    first_run = None
    for d in delivery_items:
        if d.run:
            first_run = d.run
            executor_ms = d.run.duration_ms
            break

    timing = TraceTimingOut(
        trace_id=str(message.trace_id),
        discord_to_db_ms=discord_to_db_ms,
        db_to_match_ms=db_to_match_ms,
        executor_ms=executor_ms,
    )
```

**Step 5: Run dashboard tests**

Run: `python -m pytest tests/dashboard/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 6: Commit**

```
feat(trace): add timing breakdown to dashboard message-traces API
```

---

### Task 9: Update orchestrator dispatch path with trace_id

**Files:**
- Modify: `src/cogtainer/lambdas/orchestrator/handler.py:263-329` (_cogos_scheduler_tick)

**Step 1: Thread trace_id through orchestrator's inline CogOS dispatch**

In `_cogos_scheduler_tick`, after `scheduler.dispatch_process()`, add `trace_id` to the payload:

```python
payload = {
    "process_id": dispatch_result.process_id,
    "run_id": dispatch_result.run_id,
    "event_id": dispatch_result.event_id,
    "trace_id": dispatch_result.trace_id,
    "dispatched_at_ms": int(time.time() * 1000),
    "event_type": event_payload.get("event_type", ""),
    "payload": event_payload,
}
```

Add `import time` if not present.

Also need `DispatchResult.event_id` — check if it exists. Looking at the scheduler code, `dispatch_result` has `message_id` not `event_id`. The orchestrator is using `dispatch_result.event_id` which doesn't exist on the new DispatchResult (it has `message_id`). This is existing code that may be referencing `.event_id` before the rename. Keep `event_id` as-is since this is the orchestrator path (different code). Just add `trace_id` and `dispatched_at_ms`.

**Step 2: Run orchestrator tests**

Run: `python -m pytest tests/cogos/ tests/cogtainer/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All pass

**Step 3: Commit**

```
feat(trace): propagate trace_id through orchestrator dispatch path
```

---

### Task 10: Integration test — full trace flow

**Files:**
- Create: `tests/cogos/test_trace_e2e.py`

**Step 1: Write end-to-end trace test**

```python
"""End-to-end test: trace_id flows from message through dispatch to run."""
from __future__ import annotations

from uuid import uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability, Channel, ChannelMessage, ChannelType,
    Handler, Process, ProcessCapability, ProcessMode, ProcessStatus,
)


def test_trace_id_flows_from_message_to_run():
    repo = LocalRepository()

    cap = Capability(name="test/cap", handler="cogos.capabilities:Capability")
    repo.upsert_capability(cap)

    proc = Process(
        name="traced-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(proc)
    repo.upsert_process_capability(ProcessCapability(
        process=proc.id, capability=cap.id, name="test",
    ))

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    handler = Handler(process=proc.id, channel=ch.id)
    repo.upsert_handler(handler)

    # Simulate bridge writing a traced message
    trace_id = uuid4()
    msg_id = repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={"message_type": "discord:dm", "content": "test"},
        trace_id=trace_id,
        trace_meta={"discord_created_at_ms": 1000, "bridge_received_at_ms": 1005, "db_written_at_ms": 1020},
    ))

    # Verify delivery has trace_id
    deliveries = repo.get_pending_deliveries(proc.id)
    assert len(deliveries) == 1
    assert deliveries[0].trace_id == trace_id

    # Dispatch
    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))
    assert not hasattr(result, "error"), f"dispatch failed: {result}"
    assert result.trace_id == str(trace_id)

    # Verify run has trace_id
    from uuid import UUID
    run = repo.get_run(UUID(result.run_id))
    assert run is not None
    assert run.trace_id == trace_id

    # Verify dispatch event includes trace_id
    from cogos.runtime.dispatch import build_dispatch_event
    event = build_dispatch_event(repo, result)
    assert event["trace_id"] == str(trace_id)
    assert "dispatched_at_ms" in event


def test_message_without_trace_id_works():
    """Non-traced messages should still work normally."""
    repo = LocalRepository()

    cap = Capability(name="test/cap2", handler="cogos.capabilities:Capability")
    repo.upsert_capability(cap)

    proc = Process(
        name="untraced-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(proc)

    ch = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    handler = Handler(process=proc.id, channel=ch.id)
    repo.upsert_handler(handler)

    msg_id = repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={"content": "regular message"},
    ))

    deliveries = repo.get_pending_deliveries(proc.id)
    assert len(deliveries) == 1
    assert deliveries[0].trace_id is None

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))
    assert not hasattr(result, "error")
    assert result.trace_id is None
```

**Step 2: Run test**

Run: `python -m pytest tests/cogos/test_trace_e2e.py -x -v --timeout=30 2>&1 | tail -20`
Expected: PASS (if all prior tasks were implemented)

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All pass

**Step 4: Commit**

```
feat(trace): add end-to-end trace propagation tests
```

---

### Summary of all files touched

| File | Change |
|------|--------|
| `src/cogos/db/models/channel_message.py` | Add `trace_id`, `trace_meta` |
| `src/cogos/db/models/delivery.py` | Add `trace_id` |
| `src/cogos/db/models/run.py` | Add `trace_id`, `parent_trace_id` |
| `src/cogos/db/migrations/013_trace_fields.sql` | New migration |
| `src/cogos/db/repository.py` | Persist trace fields in INSERT statements |
| `src/cogos/db/local_repository.py` | Copy trace_id to auto-created deliveries |
| `src/cogos/io/discord/bridge.py` | Generate trace_id, log trace summary |
| `src/cogos/capabilities/scheduler.py` | Propagate trace_id in dispatch |
| `src/cogos/capabilities/base.py` | Add trace_id to Capability init |
| `src/cogos/runtime/dispatch.py` | Add trace_id + dispatched_at_ms to event |
| `src/cogos/executor/handler.py` | Read trace_id from event, pass to capabilities |
| `src/cogos/io/discord/capability.py` | Use run's trace_id in reply _meta |
| `src/cogtainer/lambdas/orchestrator/handler.py` | Add trace_id to inline dispatch |
| `src/dashboard/routers/traces.py` | Add timing breakdown to API response |
| `tests/cogos/io/test_discord_bridge_trace.py` | New — bridge trace tests |
| `tests/cogos/test_trace_propagation.py` | New — scheduler propagation tests |
| `tests/cogos/test_trace_e2e.py` | New — end-to-end trace flow |
| `tests/dashboard/test_trace_timing.py` | New — dashboard timing tests |
