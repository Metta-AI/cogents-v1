from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Handler
from dashboard.db import get_cogos_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-handlers"])


# ── Request / response models ──────────────────────────────────────


class HandlerOut(BaseModel):
    id: str
    process: str
    event_pattern: str
    enabled: bool
    created_at: str | None = None


class HandlerCreate(BaseModel):
    process: str  # process UUID
    event_pattern: str
    enabled: bool = True


class HandlersResponse(BaseModel):
    count: int
    handlers: list[HandlerOut]


# ── Helpers ─────────────────────────────────────────────────────────


def _to_out(h: Handler) -> HandlerOut:
    return HandlerOut(
        id=str(h.id),
        process=str(h.process),
        event_pattern=h.event_pattern,
        enabled=h.enabled,
        created_at=str(h.created_at) if h.created_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/handlers", response_model=HandlersResponse)
def list_handlers(
    name: str,
    process: str | None = Query(None, description="Filter by process UUID"),
) -> HandlersResponse:
    repo = get_cogos_repo()
    pid = UUID(process) if process else None
    items = repo.list_handlers(process_id=pid)
    out = [_to_out(h) for h in items]
    return HandlersResponse(count=len(out), handlers=out)


@router.post("/handlers", response_model=HandlerOut)
def create_handler(name: str, body: HandlerCreate) -> HandlerOut:
    repo = get_cogos_repo()
    h = Handler(
        process=UUID(body.process),
        event_pattern=body.event_pattern,
        enabled=body.enabled,
    )
    repo.create_handler(h)
    return _to_out(h)


@router.delete("/handlers/{handler_id}")
def delete_handler(name: str, handler_id: str) -> dict:
    repo = get_cogos_repo()
    if not repo.delete_handler(UUID(handler_id)):
        raise HTTPException(status_code=404, detail="Handler not found")
    return {"deleted": True, "id": handler_id}
