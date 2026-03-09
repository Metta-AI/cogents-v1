"""Event capabilities — emit and query events."""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.db.models import Event
from cogos.db.repository import Repository
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


def emit(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Emit a new event into the append-only log."""
    event_type = args.get("event_type", "")
    if not event_type:
        return CapabilityResult(content={"error": "event_type is required"})

    payload = args.get("payload", {})
    parent_event = args.get("parent_event")

    event = Event(
        event_type=event_type,
        source=f"process:{process_id}",
        payload=payload,
        parent_event=UUID(parent_event) if parent_event else None,
    )

    event_id = repo.append_event(event)

    return CapabilityResult(
        content={
            "id": str(event_id),
            "event_type": event_type,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    )


def query(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Query events, optionally filtering by type."""
    event_type = args.get("event_type")
    limit = args.get("limit", 100)

    events = repo.get_events(event_type=event_type, limit=limit)

    return CapabilityResult(
        content=[
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "source": e.source,
                "payload": e.payload,
                "parent_event": str(e.parent_event) if e.parent_event else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    )
