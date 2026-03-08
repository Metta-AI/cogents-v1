# Trigger Auto-Throttling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add sliding-window rate limiting to triggers so events above a threshold are rejected, with state transitions emitting `trigger:throttle:on/off` events.

**Architecture:** Throttle config lives in `TriggerConfig` (JSONB). Sliding window state (`throttle_timestamps`, `throttle_rejected`, `throttle_active`) lives as columns on the trigger row. The orchestrator does an atomic DB check-and-update per matched trigger before dispatching.

**Tech Stack:** Python, Pydantic, PostgreSQL (RDS Data API), FastAPI

---

### Task 1: Add throttle fields to models

**Files:**
- Modify: `src/brain/db/models.py:214-229`

**Step 1: Add throttle settings to TriggerConfig**

In `src/brain/db/models.py`, add two fields to `TriggerConfig`:

```python
class TriggerConfig(BaseModel):
    retry_max_attempts: int = 1
    retry_backoff: Literal["none", "linear", "exponential"] = "none"
    retry_backoff_base_seconds: float = 5.0
    on_failure: str | None = None
    max_events: int = 0
    throttle_window_seconds: int = 60
```

**Step 2: Add throttle state fields to Trigger and add ThrottleResult**

In `src/brain/db/models.py`, add three fields to `Trigger`:

```python
class Trigger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    program_name: str
    event_pattern: str
    priority: int = 10
    config: TriggerConfig = Field(default_factory=TriggerConfig)
    enabled: bool = True
    throttle_timestamps: list[float] = Field(default_factory=list)
    throttle_rejected: int = 0
    throttle_active: bool = False
    created_at: datetime | None = None
```

Add `ThrottleResult` after the `Trigger` class:

```python
class ThrottleResult(BaseModel):
    allowed: bool
    state_changed: bool
    throttle_active: bool
```

**Step 3: Export ThrottleResult from `src/brain/db/__init__.py`**

Add `ThrottleResult` to the imports and `__all__` list.

**Step 4: Run existing tests to confirm no breakage**

Run: `pytest tests/dashboard/test_models.py -v`
Expected: All pass (defaults are backward-compatible)

**Step 5: Commit**

```
feat(triggers): add throttle fields to TriggerConfig and Trigger models
```

---

### Task 2: Add throttle_check to LocalRepository

**Files:**
- Modify: `src/brain/db/local_repository.py:285-319`
- Create: `tests/brain/test_trigger_throttle.py`

**Step 1: Write failing tests**

Create `tests/brain/test_trigger_throttle.py`:

```python
"""Tests for trigger throttle_check on LocalRepository."""

from __future__ import annotations

import time

from brain.db.local_repository import LocalRepository
from brain.db.models import Trigger, TriggerConfig


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(data_dir=str(tmp_path))


def _make_trigger(max_events: int = 3, window: int = 60) -> Trigger:
    return Trigger(
        program_name="test-prog",
        event_pattern="test:event",
        config=TriggerConfig(max_events=max_events, throttle_window_seconds=window),
    )


class TestThrottleCheckBasic:
    def test_no_throttle_when_max_events_zero(self, tmp_path):
        """max_events=0 means no throttle — always allowed."""
        repo = _repo(tmp_path)
        t = Trigger(program_name="p", event_pattern="e", config=TriggerConfig(max_events=0))
        repo.insert_trigger(t)
        result = repo.throttle_check(t.id, 0, 60)
        assert result.allowed is True
        assert result.state_changed is False

    def test_allows_under_limit(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=3)
        repo.insert_trigger(t)

        for _ in range(3):
            result = repo.throttle_check(t.id, 3, 60)
            assert result.allowed is True

    def test_rejects_at_limit(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=2)
        repo.insert_trigger(t)

        repo.throttle_check(t.id, 2, 60)
        repo.throttle_check(t.id, 2, 60)
        result = repo.throttle_check(t.id, 2, 60)
        assert result.allowed is False

    def test_rejected_counter_increments(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)

        repo.throttle_check(t.id, 1, 60)  # allowed
        repo.throttle_check(t.id, 1, 60)  # rejected
        repo.throttle_check(t.id, 1, 60)  # rejected

        trigger = repo.get_trigger(t.id)
        assert trigger.throttle_rejected == 2


class TestThrottleStateTransitions:
    def test_transition_to_throttled(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)

        r1 = repo.throttle_check(t.id, 1, 60)
        assert r1.allowed is True
        assert r1.state_changed is False
        assert r1.throttle_active is False

        r2 = repo.throttle_check(t.id, 1, 60)
        assert r2.allowed is False
        assert r2.state_changed is True
        assert r2.throttle_active is True

    def test_no_state_change_when_already_throttled(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)

        repo.throttle_check(t.id, 1, 60)  # allowed
        repo.throttle_check(t.id, 1, 60)  # rejected, state_changed=True
        r3 = repo.throttle_check(t.id, 1, 60)  # rejected again
        assert r3.allowed is False
        assert r3.state_changed is False
        assert r3.throttle_active is True


class TestThrottleWindowExpiry:
    def test_window_expiry_allows_again(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1, window=1)
        repo.insert_trigger(t)

        repo.throttle_check(t.id, 1, 1)  # allowed
        r2 = repo.throttle_check(t.id, 1, 1)  # rejected
        assert r2.allowed is False

        time.sleep(1.1)

        r3 = repo.throttle_check(t.id, 1, 1)
        assert r3.allowed is True
        assert r3.state_changed is True  # transitioned off
        assert r3.throttle_active is False

    def test_old_timestamps_pruned(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=2, window=1)
        repo.insert_trigger(t)

        repo.throttle_check(t.id, 2, 1)
        repo.throttle_check(t.id, 2, 1)
        # At limit now

        time.sleep(1.1)
        # Both timestamps expired — should allow 2 more
        r1 = repo.throttle_check(t.id, 2, 1)
        assert r1.allowed is True
        r2 = repo.throttle_check(t.id, 2, 1)
        assert r2.allowed is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_trigger_throttle.py -v`
Expected: FAIL — `throttle_check` doesn't exist yet

**Step 3: Implement throttle_check on LocalRepository**

In `src/brain/db/local_repository.py`, add after `update_trigger_enabled`:

```python
    def throttle_check(self, trigger_id: UUID, max_events: int, window_seconds: int) -> "ThrottleResult":
        from brain.db.models import ThrottleResult

        trigger = self._triggers.get(trigger_id)
        if not trigger:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        if max_events <= 0:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        now = time.time()
        cutoff = now - window_seconds
        prev_active = trigger.throttle_active

        # Prune expired timestamps
        trigger.throttle_timestamps = [ts for ts in trigger.throttle_timestamps if ts > cutoff]

        if len(trigger.throttle_timestamps) >= max_events:
            # Reject
            trigger.throttle_rejected += 1
            trigger.throttle_active = True
            self._save()
            return ThrottleResult(
                allowed=False,
                state_changed=prev_active != trigger.throttle_active,
                throttle_active=True,
            )

        # Allow
        trigger.throttle_timestamps.append(now)
        trigger.throttle_active = False
        self._save()
        return ThrottleResult(
            allowed=True,
            state_changed=prev_active != trigger.throttle_active,
            throttle_active=False,
        )
```

Add `import time` at the top of `local_repository.py`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_trigger_throttle.py -v`
Expected: All pass

**Step 5: Commit**

```
feat(triggers): implement throttle_check on LocalRepository with tests
```

---

### Task 3: Add throttle_check to Repository (RDS Data API)

**Files:**
- Modify: `src/brain/db/repository.py:1289-1361`

**Step 1: Add throttle_check method to Repository**

After `_trigger_from_row`, add:

```python
    def throttle_check(self, trigger_id: UUID, max_events: int, window_seconds: int) -> "ThrottleResult":
        from brain.db.models import ThrottleResult

        if max_events <= 0:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        import time
        now = time.time()
        cutoff = now - window_seconds

        # Atomic: prune window, check count, update state, return prev+current
        sql = """
            WITH prev AS (
                SELECT throttle_active AS prev_active FROM triggers WHERE id = :id
            )
            UPDATE triggers
            SET
                throttle_timestamps = CASE
                    WHEN (SELECT count(*) FROM jsonb_array_elements_text(
                        (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                         FROM jsonb_array_elements_text(throttle_timestamps) AS t
                         WHERE t::double precision > :cutoff)
                    )) >= :max_events
                    THEN (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                          FROM jsonb_array_elements_text(throttle_timestamps) AS t
                          WHERE t::double precision > :cutoff)
                    ELSE (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                          FROM jsonb_array_elements_text(throttle_timestamps) AS t
                          WHERE t::double precision > :cutoff) || to_jsonb(:now::text)
                END,
                throttle_rejected = CASE
                    WHEN (SELECT count(*) FROM jsonb_array_elements_text(
                        (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                         FROM jsonb_array_elements_text(throttle_timestamps) AS t
                         WHERE t::double precision > :cutoff)
                    )) >= :max_events
                    THEN throttle_rejected + 1
                    ELSE throttle_rejected
                END,
                throttle_active = (SELECT count(*) FROM jsonb_array_elements_text(
                    (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                     FROM jsonb_array_elements_text(throttle_timestamps) AS t
                     WHERE t::double precision > :cutoff)
                )) >= :max_events
            WHERE id = :id
            RETURNING throttle_active, (SELECT prev_active FROM prev) AS prev_throttle_active
        """
        response = self._execute(sql, [
            self._param("id", trigger_id),
            self._param("cutoff", cutoff),
            self._param("max_events", max_events),
            self._param("now", now),
        ])
        row = self._first_row(response)
        if not row:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        active = row.get("throttle_active", False)
        prev = row.get("prev_throttle_active", False)
        return ThrottleResult(
            allowed=not active,
            state_changed=active != prev,
            throttle_active=active,
        )
```

**Step 2: Update `_trigger_from_row` to include new fields**

```python
    def _trigger_from_row(self, row: dict) -> Trigger:
        config = row.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        timestamps = row.get("throttle_timestamps", [])
        if isinstance(timestamps, str):
            timestamps = json.loads(timestamps)
        return Trigger(
            id=UUID(row["id"]),
            program_name=row["program_name"],
            event_pattern=row.get("event_pattern", ""),
            priority=row.get("priority", 10),
            config=TriggerConfig(**config) if config else TriggerConfig(),
            enabled=row.get("enabled", True),
            throttle_timestamps=[float(t) for t in timestamps],
            throttle_rejected=row.get("throttle_rejected", 0),
            throttle_active=row.get("throttle_active", False),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
```

**Step 3: Update `insert_trigger` to include new columns**

Update the INSERT SQL to include the three new columns:

```sql
INSERT INTO triggers (id, program_name, event_pattern, priority, config, enabled,
                      throttle_timestamps, throttle_rejected, throttle_active)
VALUES (:id, :program_name, :event_pattern, :priority, :config::jsonb, :enabled,
        :throttle_timestamps::jsonb, :throttle_rejected, :throttle_active)
RETURNING id, created_at
```

Add parameters:
```python
self._param("throttle_timestamps", trigger.throttle_timestamps),
self._param("throttle_rejected", trigger.throttle_rejected),
self._param("throttle_active", trigger.throttle_active),
```

**Step 4: Run tests**

Run: `pytest tests/ -v -k trigger`
Expected: All pass

**Step 5: Commit**

```
feat(triggers): add throttle_check to RDS Data API Repository
```

---

### Task 4: Schema and migration

**Files:**
- Modify: `src/brain/db/schema.sql:59-68`
- Modify: `src/brain/db/migrations.py:126-195`

**Step 1: Update schema.sql for fresh deploys**

Add three columns to the triggers CREATE TABLE:

```sql
CREATE TABLE IF NOT EXISTS triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_name    TEXT NOT NULL REFERENCES programs(name),
    event_pattern   TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 10,
    config          JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    throttle_timestamps JSONB NOT NULL DEFAULT '[]',
    throttle_rejected   INTEGER NOT NULL DEFAULT 0,
    throttle_active     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Step 2: Add migration v7**

In `migrations.py` MIGRATIONS dict, add:

```python
    7: [
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_timestamps JSONB NOT NULL DEFAULT '[]'",
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_rejected INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_active BOOLEAN NOT NULL DEFAULT false",
        "INSERT INTO schema_version (version) VALUES (7) ON CONFLICT DO NOTHING",
    ],
```

**Step 3: Commit**

```
feat(triggers): add throttle columns to schema and migration v7
```

---

### Task 5: Orchestrator throttle check

**Files:**
- Modify: `src/brain/lambdas/orchestrator/handler.py:54-153`

**Step 1: Add throttle check to the dispatch loop**

In `handler.py`, import `Event` and `put_event`:

```python
from brain.db.models import Event as BrainEvent, TaskStatus, Trigger
from brain.lambdas.shared.events import from_eventbridge, put_event
```

In the `for trigger in matched:` loop, after the cascade guard and before the session_id line, add:

```python
            # Throttle check
            max_events = trigger.config.max_events
            if max_events > 0:
                result = repo.throttle_check(
                    trigger.id, max_events, trigger.config.throttle_window_seconds
                )
                if not result.allowed:
                    logger.info(f"Throttled trigger {trigger.id} for {trigger.program_name}")
                    if result.state_changed:
                        put_event(
                            BrainEvent(
                                event_type="trigger:throttle:on",
                                source="orchestrator",
                                payload={"trigger_id": str(trigger.id),
                                         "program_name": trigger.program_name},
                                parent_event_id=event_id,
                            ),
                            config.event_bus_name,
                        )
                    continue
                if result.state_changed:
                    put_event(
                        BrainEvent(
                            event_type="trigger:throttle:off",
                            source="orchestrator",
                            payload={"trigger_id": str(trigger.id),
                                     "program_name": trigger.program_name},
                            parent_event_id=event_id,
                        ),
                        config.event_bus_name,
                    )
```

**Step 2: Check the config object for `event_bus_name` field**

Read `src/brain/lambdas/shared/config.py` to find the correct field name for the EventBridge bus. Use whatever field name exists there (likely `bus_name` or `event_bus_name`).

**Step 3: Commit**

```
feat(triggers): add throttle check to orchestrator dispatch loop
```

---

### Task 6: Dashboard models and router

**Files:**
- Modify: `src/dashboard/models.py:98-130`
- Modify: `src/dashboard/routers/triggers.py`

**Step 1: Add throttle fields to dashboard Trigger model**

In `src/dashboard/models.py`, add to `Trigger`:

```python
class Trigger(BaseModel):
    id: str
    name: str = ""
    event_pattern: str | None = None
    program_name: str | None = None
    priority: int | None = None
    enabled: bool = True
    created_at: str | None = None
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0
    max_events: int = 0
    throttle_window_seconds: int = 60
    throttle_rejected: int = 0
    throttle_active: bool = False
```

**Step 2: Add throttle config to TriggerCreate and TriggerUpdate**

```python
class TriggerCreate(BaseModel):
    program_name: str
    event_pattern: str
    priority: int = 10
    enabled: bool = True
    metadata: dict[str, Any] = {}
    max_events: int = 0
    throttle_window_seconds: int = 60

class TriggerUpdate(BaseModel):
    program_name: str | None = None
    event_pattern: str | None = None
    priority: int | None = None
    max_events: int | None = None
    throttle_window_seconds: int | None = None
```

**Step 3: Update triggers router to pass throttle config**

In `src/dashboard/routers/triggers.py`:

- In `list_triggers`: populate throttle fields from DB trigger:
  ```python
  max_events=t.config.max_events,
  throttle_window_seconds=t.config.throttle_window_seconds,
  throttle_rejected=t.throttle_rejected,
  throttle_active=t.throttle_active,
  ```

- In `create_trigger`: pass config with throttle settings:
  ```python
  db_trigger = DbTrigger(
      program_name=body.program_name,
      event_pattern=body.event_pattern,
      priority=body.priority,
      enabled=body.enabled,
      config=TriggerConfig(max_events=body.max_events,
                           throttle_window_seconds=body.throttle_window_seconds),
  )
  ```
  Import `TriggerConfig` from `brain.db.models`.

- In `update_trigger`: preserve/update throttle config:
  ```python
  config = existing.config
  if body.max_events is not None:
      config.max_events = body.max_events
  if body.throttle_window_seconds is not None:
      config.throttle_window_seconds = body.throttle_window_seconds
  ```
  Pass `config=config` when creating `new_trigger`.

- In all response builders, add throttle fields to returned `Trigger`.

**Step 4: Run dashboard tests**

Run: `pytest tests/dashboard/ -v`
Expected: All pass

**Step 5: Commit**

```
feat(triggers): expose throttle config and state in dashboard API
```

---

### Task 7: Final validation

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Commit (if any remaining changes)**

```
chore(triggers): final cleanup for trigger throttling
```
