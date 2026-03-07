from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from dashboard.db import get_repo
from dashboard.models import (
    ToggleRequest,
    ToggleResponse,
    Trigger,
    TriggerCreate,
    TriggerUpdate,
    TriggersResponse,
)

router = APIRouter(tags=["triggers"])


@router.get("/triggers", response_model=TriggersResponse)
def list_triggers(name: str) -> TriggersResponse:
    repo = get_repo()
    db_triggers = repo.list_triggers(enabled_only=False)
    all_runs = repo.query_runs(limit=10000)

    triggers = []
    for t in db_triggers:
        prog = t.program_name or ""
        pattern = t.event_pattern or ""
        trigger_name = f"{prog}:{pattern}" if pattern else prog

        prog_runs = [r for r in all_runs if r.program_name == prog]

        triggers.append(
            Trigger(
                id=str(t.id),
                name=trigger_name,
                event_pattern=t.event_pattern,
                program_name=t.program_name,
                priority=t.priority,
                enabled=t.enabled,
                created_at=str(t.created_at) if t.created_at else None,
                fired_1m=len(prog_runs),
                fired_5m=len(prog_runs),
                fired_1h=len(prog_runs),
                fired_24h=len(prog_runs),
                max_events=t.config.max_events,
                throttle_window_seconds=t.config.throttle_window_seconds,
                throttle_rejected=t.throttle_rejected,
                throttle_active=t.throttle_active,
            )
        )

    return TriggersResponse(cogent_name=name, count=len(triggers), triggers=triggers)


@router.post("/triggers", response_model=Trigger)
def create_trigger(name: str, body: TriggerCreate) -> Trigger:
    from brain.db.models import Trigger as DbTrigger, TriggerConfig

    repo = get_repo()
    db_trigger = DbTrigger(
        program_name=body.program_name,
        event_pattern=body.event_pattern,
        priority=body.priority,
        enabled=body.enabled,
        config=TriggerConfig(
            max_events=body.max_events,
            throttle_window_seconds=body.throttle_window_seconds,
        ),
    )
    repo.insert_trigger(db_trigger)
    return Trigger(
        id=str(db_trigger.id),
        name=f"{db_trigger.program_name}:{db_trigger.event_pattern}",
        event_pattern=db_trigger.event_pattern,
        program_name=db_trigger.program_name,
        priority=db_trigger.priority,
        enabled=db_trigger.enabled,
        created_at=str(db_trigger.created_at) if db_trigger.created_at else None,
        max_events=body.max_events,
        throttle_window_seconds=body.throttle_window_seconds,
    )


@router.put("/triggers/{trigger_id}", response_model=Trigger)
def update_trigger(name: str, trigger_id: str, body: TriggerUpdate) -> Trigger:
    from brain.db.models import Trigger as DbTrigger, TriggerConfig

    repo = get_repo()
    tid = UUID(trigger_id)
    existing = repo.get_trigger(tid)
    if not existing:
        raise HTTPException(status_code=404, detail="Trigger not found")

    program_name = body.program_name if body.program_name is not None else existing.program_name
    event_pattern = body.event_pattern if body.event_pattern is not None else existing.event_pattern
    priority = body.priority if body.priority is not None else existing.priority

    config = existing.config
    if body.max_events is not None:
        config.max_events = body.max_events
    if body.throttle_window_seconds is not None:
        config.throttle_window_seconds = body.throttle_window_seconds

    repo.delete_trigger(tid)
    new_trigger = DbTrigger(
        id=tid,
        program_name=program_name,
        event_pattern=event_pattern,
        priority=priority,
        enabled=existing.enabled,
        created_at=existing.created_at,
        config=config,
    )
    repo.insert_trigger(new_trigger)
    return Trigger(
        id=str(new_trigger.id),
        name=f"{new_trigger.program_name}:{new_trigger.event_pattern}",
        event_pattern=new_trigger.event_pattern,
        program_name=new_trigger.program_name,
        priority=new_trigger.priority,
        enabled=new_trigger.enabled,
        created_at=str(new_trigger.created_at) if new_trigger.created_at else None,
        max_events=new_trigger.config.max_events,
        throttle_window_seconds=new_trigger.config.throttle_window_seconds,
        throttle_rejected=existing.throttle_rejected,
        throttle_active=existing.throttle_active,
    )


@router.delete("/triggers/{trigger_id}")
def delete_trigger(name: str, trigger_id: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_trigger(UUID(trigger_id))
    return {"deleted": deleted}


@router.post("/triggers/toggle", response_model=ToggleResponse)
def toggle_triggers(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = 0
    for tid_str in body.ids:
        if repo.update_trigger_enabled(UUID(tid_str), body.enabled):
            count += 1
    return ToggleResponse(updated=count, enabled=body.enabled)
