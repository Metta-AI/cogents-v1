# Trigger Auto-Throttling Design

## Summary

Add sliding-window rate limiting to triggers. When a trigger exceeds `max_events` within `throttle_window_seconds`, the orchestrator rejects further dispatches until the window clears. State is stored in the DB for global enforcement across concurrent Lambda instances. State transitions emit `trigger:throttle:on` and `trigger:throttle:off` events.

## Data Model Changes

### TriggerConfig (config JSONB — no schema migration)

```python
class TriggerConfig(BaseModel):
    retry_max_attempts: int = 1
    retry_backoff: Literal["none", "linear", "exponential"] = "none"
    retry_backoff_base_seconds: float = 5.0
    on_failure: str | None = None
    # Throttle settings
    max_events: int = 0              # 0 = no throttle
    throttle_window_seconds: int = 60
```

### Trigger model — new fields

```python
class Trigger(BaseModel):
    # ... existing fields ...
    throttle_timestamps: list[float] = []   # epoch timestamps in sliding window
    throttle_rejected: int = 0              # cumulative rejected count
    throttle_active: bool = False           # current throttle state
```

### DB migration (version 7)

```sql
ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_timestamps JSONB NOT NULL DEFAULT '[]';
ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_rejected INTEGER NOT NULL DEFAULT 0;
ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_active BOOLEAN NOT NULL DEFAULT false;
```

## Orchestrator Changes

### Throttle check — single atomic SQL per matched trigger

The orchestrator calls a repo method that does an atomic UPDATE + RETURNING to check-and-update the sliding window in one round-trip:

```sql
UPDATE triggers
SET
    throttle_timestamps = CASE
        WHEN (SELECT count(*) FROM jsonb_array_elements_text(
            (SELECT jsonb_agg(t)
             FROM jsonb_array_elements_text(throttle_timestamps) AS t
             WHERE t::float > :cutoff)
        )) >= :max_events
        THEN (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
              FROM jsonb_array_elements_text(throttle_timestamps) AS t
              WHERE t::float > :cutoff)
        ELSE (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
              FROM jsonb_array_elements_text(throttle_timestamps) AS t
              WHERE t::float > :cutoff) || to_jsonb(:now::text)
    END,
    throttle_rejected = CASE
        WHEN (SELECT count(*) FROM jsonb_array_elements_text(
            (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
             FROM jsonb_array_elements_text(throttle_timestamps) AS t
             WHERE t::float > :cutoff)
        )) >= :max_events
        THEN throttle_rejected + 1
        ELSE throttle_rejected
    END,
    throttle_active = (SELECT count(*) FROM jsonb_array_elements_text(
        (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
         FROM jsonb_array_elements_text(throttle_timestamps) AS t
         WHERE t::float > :cutoff)
    )) >= :max_events
WHERE id = :id
RETURNING throttle_active,
    (SELECT throttle_active FROM triggers WHERE id = :id) AS prev_throttle_active;
```

Parameters:
- `:cutoff` = `now - throttle_window_seconds` (epoch float)
- `:max_events` = from trigger config
- `:now` = current epoch float
- `:id` = trigger UUID

### Repository method

```python
def throttle_check(self, trigger_id: UUID, max_events: int, window_seconds: int) -> ThrottleResult:
    """Atomically check and update the trigger's sliding window.

    Returns ThrottleResult with:
        allowed: bool — whether the event should be dispatched
        state_changed: bool — whether throttle_active flipped
        throttle_active: bool — current throttle state
    """
```

### Orchestrator dispatch loop

```python
for trigger in matched:
    # Cascade guard (existing)
    if brain_event.source and brain_event.source == trigger.program_name:
        continue

    # Throttle check
    max_events = trigger.config.max_events
    if max_events > 0:
        result = repo.throttle_check(
            trigger.id, max_events, trigger.config.throttle_window_seconds
        )
        if not result.allowed:
            logger.info(f"Throttled trigger {trigger.id} for {trigger.program_name}")
            if result.state_changed:
                put_event(Event(
                    event_type="trigger:throttle:on",
                    source="orchestrator",
                    payload={"trigger_id": str(trigger.id), "program_name": trigger.program_name},
                ), config.bus_name)
            continue
        if result.state_changed:
            put_event(Event(
                event_type="trigger:throttle:off",
                source="orchestrator",
                payload={"trigger_id": str(trigger.id), "program_name": trigger.program_name},
            ), config.bus_name)

    # ... existing dispatch logic ...
```

## Dashboard Changes

### Dashboard Trigger model — expose throttle state

```python
class Trigger(BaseModel):
    # ... existing fields ...
    max_events: int = 0
    throttle_window_seconds: int = 60
    throttle_rejected: int = 0
    throttle_active: bool = False
```

### TriggerCreate / TriggerUpdate — accept throttle config

```python
class TriggerCreate(BaseModel):
    # ... existing fields ...
    max_events: int = 0
    throttle_window_seconds: int = 60

class TriggerUpdate(BaseModel):
    # ... existing fields ...
    max_events: int | None = None
    throttle_window_seconds: int | None = None
```

## Events Emitted

| Event Type | When | Payload |
|---|---|---|
| `trigger:throttle:on` | Trigger transitions from active to throttled | `{trigger_id, program_name}` |
| `trigger:throttle:off` | Trigger transitions from throttled to active | `{trigger_id, program_name}` |

## Files to Change

1. `src/brain/db/models.py` — TriggerConfig + Trigger fields
2. `src/brain/db/schema.sql` — add columns (for fresh deploys)
3. `src/brain/db/migrations.py` — migration v7
4. `src/brain/db/repository.py` — `throttle_check()`, update `_trigger_from_row()`, update `insert_trigger()`
5. `src/brain/lambdas/orchestrator/handler.py` — throttle check in dispatch loop
6. `src/dashboard/models.py` — expose throttle fields
7. `src/dashboard/routers/triggers.py` — pass throttle config on create/update
