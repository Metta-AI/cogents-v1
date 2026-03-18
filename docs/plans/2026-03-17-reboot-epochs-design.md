# Reboot Epochs Design

## Problem

When CogOS reboots, `clear_process_tables()` deletes all processes, runs, handlers,
capabilities, and deliveries. This loses history that could be useful for debugging
and understanding system behavior across reboots.

## Solution

Replace destructive reboot with an **epoch-based** approach:

- Each reboot increments a `reboot_epoch` counter
- All process-table records are stamped with their epoch at creation
- The scheduler and dashboard filter by current epoch by default
- A dashboard toggle reveals pre-reboot data (dimmed)
- A general operations log tracks reboots, reloads, and other system events

## Data Model Changes

### New field on epoch-scoped models

Add `epoch: int` to: Process, Run, Handler, ProcessCapability, Delivery.

Stamped from `repo.reboot_epoch` at creation time.

### New repo-level state

`reboot_epoch: int` — starts at 0, incremented on each reboot.

### New model: `CogosOperation`

```python
class CogosOperation(BaseModel):
    id: UUID
    epoch: int          # epoch AFTER the operation (new epoch for reboots)
    type: str           # "reboot", "reload", etc.
    metadata: dict      # e.g. {"prev_process_count": 42}
    created_at: datetime
```

Stored in `cogos_operation` table / `_operations` dict. Not cleared on reboot.

## Repository Changes

Default epoch filtering on all query methods:

```python
# Normal usage — only current epoch
repo.get_processes()

# Explicit all-epochs access
repo.get_processes(epoch=ALL_EPOCHS)
```

Any query that omits the epoch parameter automatically gets current-epoch data.
This is the safe default — the scheduler and all internal code get filtering for
free without any changes. Only the dashboard "show history" toggle passes
`epoch=ALL_EPOCHS`.

## Reboot Flow

### Current

1. Disable init process
2. `clear_process_tables()` — deletes all records
3. Create fresh init process

### New

1. Disable init process
2. Increment `reboot_epoch`
3. Log: `CogosOperation(type="reboot", epoch=new_epoch, metadata={"prev_process_count": N})`
4. Create fresh init process stamped with new epoch
5. No deletion — old records stay, invisible to scheduler via epoch filter

`clear_process_tables()` is removed entirely.

## API Changes

- Process and run list endpoints gain optional `epoch` query param:
  omitted = current epoch, `"all"` = all epochs
- `cogos-status` respects epoch filter (process counts, recent runs)
- New endpoint: `GET /operations` — returns the operations log

## Dashboard Changes

### Header toggle

Checkbox labeled "Show history" next to the reboot button. When checked, all
data-fetching calls pass `epoch=all`. Ephemeral UI state, defaults to off.

### Row dimming

Rows where `epoch < current_epoch` rendered with `opacity: 0.5`.

Applies to: ProcessesPanel, RunsPanel, trace panel, overview tab.

### Operations log

Section in the overview tab showing recent system operations with timestamps.

## Scope

### Epoch-scoped (filtered)

Processes, runs, handlers, capabilities, deliveries, traces.

### NOT epoch-scoped (unchanged)

Files, coglets, channels, schemas, resources, cron rules, alerts.
