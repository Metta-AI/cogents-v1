from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from dashboard.db import get_repo
from dashboard.models import Event, EventsResponse, EventTreeResponse

router = APIRouter(tags=["events"])


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _event_to_model(e: Any) -> Event:
    payload = e.payload
    if isinstance(payload, str):
        payload = _try_parse_json(payload)
    return Event(
        id=e.id,
        event_type=e.event_type,
        source=e.source,
        payload=payload,
        parent_event_id=e.parent_event_id,
        created_at=str(e.created_at) if e.created_at else None,
    )


@router.get("/events", response_model=EventsResponse)
def list_events(
    name: str,
    range: str = Query("1h", alias="range"),
    type: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=1000),
) -> EventsResponse:
    repo = get_repo()
    db_events = repo.get_events(event_type=type, limit=limit)
    events = [_event_to_model(e) for e in db_events]
    return EventsResponse(cogent_name=name, count=len(events), events=events)


@router.get("/events/{event_id}/tree", response_model=EventTreeResponse)
def event_tree(name: str, event_id: int) -> EventTreeResponse:
    repo = get_repo()
    db_events = repo.get_event_root(event_id)
    if not db_events:
        return EventTreeResponse(root_event_id=None, count=0, events=[])
    events = [_event_to_model(e) for e in db_events]
    return EventTreeResponse(root_event_id=events[0].id, count=len(events), events=events)
