"""Schema management routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cogos.db.models import Schema
from dashboard.db import get_repo

router = APIRouter(tags=["schemas"])


class SchemaOut(BaseModel):
    id: str
    name: str
    definition: dict
    file_id: str | None = None
    created_at: str | None = None


class SchemasResponse(BaseModel):
    count: int
    schemas: list[SchemaOut]


def _to_out(s: Schema) -> SchemaOut:
    return SchemaOut(
        id=str(s.id),
        name=s.name,
        definition=s.definition,
        file_id=str(s.file_id) if s.file_id else None,
        created_at=str(s.created_at) if s.created_at else None,
    )


@router.get("/schemas", response_model=SchemasResponse)
def list_schemas(name: str) -> SchemasResponse:
    repo = get_repo()
    items = repo.list_schemas()
    out = [_to_out(s) for s in items]
    return SchemasResponse(count=len(out), schemas=out)


@router.get("/schemas/{schema_name}", response_model=SchemaOut)
def get_schema(name: str, schema_name: str) -> SchemaOut:
    repo = get_repo()
    s = repo.get_schema_by_name(schema_name)
    if not s:
        raise HTTPException(status_code=404, detail="Schema not found")
    return _to_out(s)
