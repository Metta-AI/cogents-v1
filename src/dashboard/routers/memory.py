from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from brain.db.models import MemoryScope
from dashboard.db import get_repo
from dashboard.models import MemoryItem, MemoryResponse

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
