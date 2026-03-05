from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import (
    CronCreate,
    CronItem,
    CronUpdate,
    CronsResponse,
    ToggleRequest,
    ToggleResponse,
)

router = APIRouter(tags=["cron"])


@router.get("/cron", response_model=CronsResponse)
def list_cron(name: str) -> CronsResponse:
    repo = get_repo()
    db_crons = repo.list_cron(enabled_only=False)
    items = [
        CronItem(
            id=str(c.id),
            cron_expression=c.cron_expression,
            event_pattern=c.event_pattern,
            enabled=c.enabled,
            metadata=c.metadata or {},
            created_at=str(c.created_at) if c.created_at else None,
        )
        for c in db_crons
    ]
    return CronsResponse(cogent_name=name, count=len(items), crons=items)


@router.post("/cron", response_model=CronItem)
def create_cron(name: str, body: CronCreate) -> CronItem:
    from brain.db.models import Cron

    repo = get_repo()
    cron = Cron(
        cron_expression=body.cron_expression,
        event_pattern=body.event_pattern,
        enabled=body.enabled,
        metadata=body.metadata or {},
    )
    repo.insert_cron(cron)
    return CronItem(
        id=str(cron.id),
        cron_expression=cron.cron_expression,
        event_pattern=cron.event_pattern,
        enabled=cron.enabled,
        metadata=cron.metadata,
        created_at=str(cron.created_at) if cron.created_at else None,
    )


@router.put("/cron/{cron_id}", response_model=CronItem)
def update_cron(name: str, cron_id: str, body: CronUpdate) -> CronItem:
    repo = get_repo()
    uid = UUID(cron_id)

    # Find existing
    existing = [c for c in repo.list_cron() if c.id == uid]
    if not existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Cron not found")

    cron = existing[0]

    if body.enabled is not None:
        repo.update_cron_enabled(uid, body.enabled)
        cron.enabled = body.enabled

    # For expression/pattern/metadata updates, we delete and re-insert
    if body.cron_expression is not None or body.event_pattern is not None or body.metadata is not None:
        from brain.db.models import Cron

        repo.delete_cron(uid)
        updated = Cron(
            id=uid,
            cron_expression=body.cron_expression if body.cron_expression is not None else cron.cron_expression,
            event_pattern=body.event_pattern if body.event_pattern is not None else cron.event_pattern,
            enabled=body.enabled if body.enabled is not None else cron.enabled,
            metadata=body.metadata if body.metadata is not None else cron.metadata,
        )
        repo.insert_cron(updated)
        cron = updated

    return CronItem(
        id=str(cron.id),
        cron_expression=cron.cron_expression,
        event_pattern=cron.event_pattern,
        enabled=cron.enabled,
        metadata=cron.metadata,
        created_at=str(cron.created_at) if cron.created_at else None,
    )


@router.delete("/cron/{cron_id}")
def delete_cron(name: str, cron_id: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_cron(UUID(cron_id))
    return {"deleted": deleted}


@router.post("/cron/toggle", response_model=ToggleResponse)
def toggle_cron(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = 0
    for cid_str in body.ids:
        if repo.update_cron_enabled(UUID(cid_str), body.enabled):
            count += 1
    return ToggleResponse(updated=count, enabled=body.enabled)
