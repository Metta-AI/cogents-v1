from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import ToggleRequest, ToggleResponse, Trigger, TriggersResponse

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
            )
        )

    return TriggersResponse(cogent_name=name, count=len(triggers), triggers=triggers)


@router.post("/triggers/toggle", response_model=ToggleResponse)
def toggle_triggers(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = 0
    for tid_str in body.ids:
        from uuid import UUID
        if repo.update_trigger_enabled(UUID(tid_str), body.enabled):
            count += 1
    return ToggleResponse(updated=count, enabled=body.enabled)
