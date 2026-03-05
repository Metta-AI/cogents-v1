from __future__ import annotations

from fastapi import APIRouter, Query

from brain.db.models import ConversationStatus
from dashboard.db import get_repo
from dashboard.models import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def get_status(name: str, range: str = Query("1h", alias="range")):
    repo = get_repo()

    all_convs = repo.list_conversations()
    active_sessions = sum(1 for c in all_convs if c.status == ConversationStatus.ACTIVE)

    triggers = repo.list_triggers(enabled_only=True)
    alerts = repo.get_unresolved_alerts()
    events = repo.get_events(limit=10000)

    return StatusResponse(
        cogent_name=name,
        active_sessions=active_sessions,
        total_conversations=len(all_convs),
        trigger_count=len(triggers),
        unresolved_alerts=len(alerts),
        recent_events=len(events),
    )
