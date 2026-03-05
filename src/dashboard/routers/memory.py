from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from brain.db.models import MemoryRecord, MemoryScope
from dashboard.db import get_repo
from dashboard.models import MemoryCreate, MemoryItem, MemoryResponse, MemoryUpdate

router = APIRouter(tags=["memory"])


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _derive_group(name: str) -> str:
    if "/" in name:
        return name.rsplit("/", 1)[0]
    if "-" in name:
        return name.split("-", 1)[0]
    return ""


@router.get("/memory", response_model=MemoryResponse)
def list_memory(
    name: str,
    scope: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> MemoryResponse:
    repo = get_repo()
    mem_scope = MemoryScope(scope) if scope else None
    records = repo.query_memory(scope=mem_scope, limit=limit)
    items = [
        MemoryItem(
            id=str(m.id),
            scope=m.scope.value if m.scope else None,
            name=m.name or "",
            group=_derive_group(m.name or ""),
            content=m.content,
            provenance=_try_parse_json(m.provenance) if isinstance(m.provenance, str) else m.provenance,
            created_at=str(m.created_at) if m.created_at else None,
            updated_at=str(m.updated_at) if m.updated_at else None,
        )
        for m in records
    ]
    return MemoryResponse(cogent_name=name, count=len(items), memory=items)


def _record_to_item(m: MemoryRecord) -> MemoryItem:
    return MemoryItem(
        id=str(m.id),
        scope=m.scope.value if m.scope else None,
        name=m.name or "",
        group=_derive_group(m.name or ""),
        content=m.content,
        provenance=_try_parse_json(m.provenance) if isinstance(m.provenance, str) else m.provenance,
        created_at=str(m.created_at) if m.created_at else None,
        updated_at=str(m.updated_at) if m.updated_at else None,
    )


@router.post("/memory", response_model=MemoryItem)
def create_memory(name: str, body: MemoryCreate) -> MemoryItem:
    repo = get_repo()
    record = MemoryRecord(
        scope=MemoryScope(body.scope),
        name=body.name,
        content=body.content,
        provenance=body.provenance or {},
    )
    repo.insert_memory(record)
    return _record_to_item(record)


@router.put("/memory/{memory_id}", response_model=MemoryItem)
def update_memory(name: str, memory_id: str, body: MemoryUpdate) -> MemoryItem:
    repo = get_repo()
    uid = UUID(memory_id)
    existing = repo.get_memory(uid)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Apply updates then delete+re-insert (no update_memory on repo)
    original_created = existing.created_at
    if body.name is not None:
        existing.name = body.name
    if body.content is not None:
        existing.content = body.content
    if body.scope is not None:
        existing.scope = MemoryScope(body.scope)

    repo.delete_memory(uid)
    repo.insert_memory(existing)
    # insert_memory overwrites timestamps; restore original created_at
    existing.created_at = original_created
    existing.updated_at = datetime.utcnow()
    return _record_to_item(existing)


@router.delete("/memory/{memory_id}")
def delete_memory_endpoint(name: str, memory_id: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_memory(UUID(memory_id))
    return {"deleted": deleted}
