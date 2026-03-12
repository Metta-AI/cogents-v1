from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Handler
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-handlers"])


# -- Request / response models ------------------------------------------------


class HandlerOut(BaseModel):
    id: str
    process: str
    process_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    enabled: bool
    created_at: str | None = None


class HandlerCreate(BaseModel):
    process: str  # process UUID
    channel: str  # channel UUID
    enabled: bool = True


class HandlersResponse(BaseModel):
    count: int
    handlers: list[HandlerOut]


# -- Helpers -------------------------------------------------------------------


def _to_out(
    h: Handler,
    process_names: dict[UUID, str],
    channel_names: dict[UUID, str],
) -> HandlerOut:
    return HandlerOut(
        id=str(h.id),
        process=str(h.process),
        process_name=process_names.get(h.process),
        channel_id=str(h.channel) if h.channel else None,
        channel_name=channel_names.get(h.channel) if h.channel else None,
        enabled=h.enabled,
        created_at=str(h.created_at) if h.created_at else None,
    )


# -- Routes --------------------------------------------------------------------


@router.get("/handlers", response_model=HandlersResponse)
def list_handlers(
    name: str,
    process: str | None = Query(None, description="Filter by process UUID"),
) -> HandlersResponse:
    repo = get_repo()
    pid = UUID(process) if process else None
    items = repo.list_handlers(process_id=pid)

    # Build process name lookup
    processes = repo.list_processes()
    process_names = {p.id: p.name for p in processes}

    # Build channel name lookup
    channels = repo.list_channels()
    channel_names = {ch.id: ch.name for ch in channels}

    out = [_to_out(h, process_names, channel_names) for h in items]
    return HandlersResponse(count=len(out), handlers=out)


@router.post("/handlers", response_model=HandlerOut)
def create_handler(name: str, body: HandlerCreate) -> HandlerOut:
    repo = get_repo()
    h = Handler(
        process=UUID(body.process),
        channel=UUID(body.channel),
        enabled=body.enabled,
    )
    repo.create_handler(h)

    processes = repo.list_processes()
    process_names = {p.id: p.name for p in processes}
    channels = repo.list_channels()
    channel_names = {ch.id: ch.name for ch in channels}

    return _to_out(h, process_names, channel_names)


@router.delete("/handlers/{handler_id}")
def delete_handler(name: str, handler_id: str) -> dict:
    repo = get_repo()
    if not repo.delete_handler(UUID(handler_id)):
        raise HTTPException(status_code=404, detail="Handler not found")
    return {"deleted": True, "id": handler_id}
