"""Scheduler capabilities — event matching, process selection, dispatch."""

from __future__ import annotations

import logging
import math
import random
from uuid import UUID

from cogos.db.models import EventDelivery, ProcessStatus, RunStatus
from cogos.db.repository import Repository
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


# ─── match_events ────────────────────────────────────────────────────

def match_events(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Find undelivered events, match to handlers, create EventDelivery rows.

    For each event that has no delivery record yet, find enabled handlers whose
    pattern matches the event_type and create a pending EventDelivery.  Mark
    the handler's process as RUNNABLE if it is currently WAITING.
    """
    limit = args.get("limit", 200)

    # Get recent events that might still need delivery.
    events = repo.get_events(limit=limit)

    created = []
    for event in events:
        # Check if this event already has deliveries.
        existing = repo.query(
            "SELECT id FROM cogos_event_delivery WHERE event = :event_id",
            {"event_id": event.id},
        )
        if existing:
            continue

        # Find matching handlers.
        handlers = repo.match_handlers(event.event_type)
        for handler in handlers:
            delivery = EventDelivery(
                event=event.id,
                handler=handler.id,
            )
            delivery_id = repo.create_event_delivery(delivery)

            # Wake the handler's process if it is WAITING.
            proc = repo.get_process(handler.process)
            if proc and proc.status == ProcessStatus.WAITING:
                repo.update_process_status(handler.process, ProcessStatus.RUNNABLE)

            created.append({
                "delivery_id": str(delivery_id),
                "event_id": str(event.id),
                "event_type": event.event_type,
                "handler_id": str(handler.id),
                "process_id": str(handler.process),
            })

    return CapabilityResult(
        content={"deliveries_created": len(created), "deliveries": created},
    )


# ─── select_processes ────────────────────────────────────────────────

def _effective_priority(proc, now_ts: float) -> float:
    """Compute effective priority with starvation aging."""
    base = proc.priority
    if proc.runnable_since:
        wait_seconds = now_ts - proc.runnable_since.timestamp()
        # Add 0.1 priority per minute of waiting.
        base += 0.1 * (wait_seconds / 60.0)
    return base


def select_processes(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Softmax sample from RUNNABLE processes by effective priority.

    Returns a list of process IDs selected for dispatch, up to the requested
    slot count.
    """
    import time

    slots = args.get("slots", 1)
    now_ts = time.time()

    runnable = repo.get_runnable_processes(limit=200)
    if not runnable:
        return CapabilityResult(content={"selected": []})

    # Compute effective priorities.
    priorities = [_effective_priority(p, now_ts) for p in runnable]

    # Softmax sampling.
    max_p = max(priorities) if priorities else 0
    exps = [math.exp(p - max_p) for p in priorities]
    total = sum(exps)
    weights = [e / total for e in exps]

    # Sample without replacement up to min(slots, len(runnable)).
    n_select = min(slots, len(runnable))
    selected_indices: list[int] = []
    remaining_indices = list(range(len(runnable)))
    remaining_weights = list(weights)

    for _ in range(n_select):
        if not remaining_indices:
            break
        total_w = sum(remaining_weights)
        if total_w <= 0:
            break
        normalised = [w / total_w for w in remaining_weights]
        chosen = random.choices(remaining_indices, weights=normalised, k=1)[0]
        selected_indices.append(chosen)
        idx_pos = remaining_indices.index(chosen)
        remaining_indices.pop(idx_pos)
        remaining_weights.pop(idx_pos)

    selected = []
    for idx in selected_indices:
        p = runnable[idx]
        selected.append({
            "id": str(p.id),
            "name": p.name,
            "priority": p.priority,
            "effective_priority": priorities[idx],
        })

    return CapabilityResult(content={"selected": selected})


# ─── dispatch_process ────────────────────────────────────────────────

def dispatch_process(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Invoke the executor for a process: transition to RUNNING and create a Run."""
    from cogos.db.models import Run

    proc_id_str = args.get("process_id", "")
    if not proc_id_str:
        return CapabilityResult(content={"error": "process_id is required"})

    target_id = UUID(proc_id_str)
    proc = repo.get_process(target_id)
    if proc is None:
        return CapabilityResult(content={"error": "process not found"})

    if proc.status != ProcessStatus.RUNNABLE:
        return CapabilityResult(
            content={"error": f"process is {proc.status.value}, expected runnable"},
        )

    # Transition to RUNNING.
    repo.update_process_status(target_id, ProcessStatus.RUNNING)

    # Find the triggering event from pending deliveries.
    deliveries = repo.get_pending_deliveries(target_id)
    event_id = deliveries[0].event if deliveries else None

    # Create a Run record.
    run = Run(process=target_id, event=event_id)
    run_id = repo.create_run(run)

    # Mark the first pending delivery as delivered.
    if deliveries:
        repo.mark_delivered(deliveries[0].id, run_id)

    return CapabilityResult(
        content={
            "run_id": str(run_id),
            "process_id": str(target_id),
            "process_name": proc.name,
            "runner": proc.runner,
            "event_id": str(event_id) if event_id else None,
        },
    )


# ─── unblock_processes ───────────────────────────────────────────────

def unblock_processes(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Check BLOCKED processes and move them to RUNNABLE if resources are available."""
    blocked = repo.list_processes(status=ProcessStatus.BLOCKED)
    unblocked = []

    for proc in blocked:
        if not proc.resources:
            # No resource constraints — unblock immediately.
            repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
            unblocked.append({"id": str(proc.id), "name": proc.name})
            continue

        # Check each required resource.
        all_available = True
        for resource_id in proc.resources:
            rows = repo.query(
                """SELECT COALESCE(SUM(amount), 0) AS used
                   FROM cogos_resource_usage ru
                   JOIN cogos_run r ON r.id = ru.run
                   WHERE ru.resource = :resource_id AND r.status = 'running'""",
                {"resource_id": resource_id},
            )
            used = float(rows[0]["used"]) if rows else 0.0

            res_rows = repo.query(
                "SELECT capacity FROM cogos_resource WHERE id = :id",
                {"id": resource_id},
            )
            capacity = float(res_rows[0]["capacity"]) if res_rows else 0.0

            if used >= capacity:
                all_available = False
                break

        if all_available:
            repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
            unblocked.append({"id": str(proc.id), "name": proc.name})

    return CapabilityResult(
        content={"unblocked_count": len(unblocked), "unblocked": unblocked},
    )


# ─── kill_process ────────────────────────────────────────────────────

def kill_process(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Force-terminate a process by setting its status to DISABLED."""
    proc_id_str = args.get("process_id", "")
    if not proc_id_str:
        return CapabilityResult(content={"error": "process_id is required"})

    target_id = UUID(proc_id_str)
    proc = repo.get_process(target_id)
    if proc is None:
        return CapabilityResult(content={"error": "process not found"})

    previous_status = proc.status.value
    repo.update_process_status(target_id, ProcessStatus.DISABLED)

    # If the process had a running run, mark it failed.
    runs = repo.list_runs(process_id=target_id, limit=1)
    if runs and runs[0].status == RunStatus.RUNNING:
        repo.complete_run(runs[0].id, status=RunStatus.FAILED, error="killed by scheduler")

    return CapabilityResult(
        content={
            "process_id": str(target_id),
            "name": proc.name,
            "previous_status": previous_status,
            "new_status": ProcessStatus.DISABLED.value,
        },
    )
