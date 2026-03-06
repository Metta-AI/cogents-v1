from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from brain.db.models import ConversationStatus
from dashboard.db import get_repo
from dashboard.models import StatusResponse

router = APIRouter()

_RANGE_SECONDS = {
    "1m": 60,
    "10m": 600,
    "1h": 3600,
    "24h": 86400,
    "1w": 604800,
}


@router.get("/status", response_model=StatusResponse)
def get_status(name: str, range: str = Query("1h", alias="range")):
    repo = get_repo()

    all_convs = repo.list_conversations()
    active_sessions = sum(1 for c in all_convs if c.status == ConversationStatus.ACTIVE)

    triggers = repo.list_triggers(enabled_only=True)
    alerts = repo.get_unresolved_alerts()
    events = repo.get_events(limit=10000)

    cutoff_secs = _RANGE_SECONDS.get(range, 3600)
    cutoff = datetime.utcnow() - timedelta(seconds=cutoff_secs)
    recent = [e for e in events if e.created_at and e.created_at >= cutoff]

    return StatusResponse(
        cogent_name=name,
        active_sessions=active_sessions,
        total_conversations=len(all_convs),
        trigger_count=len(triggers),
        unresolved_alerts=len(alerts),
        recent_events=len(recent),
    )
