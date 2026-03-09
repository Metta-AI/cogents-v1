from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cogos.db.models import Capability
from dashboard.db import get_cogos_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-capabilities"])


# ── Response / request models ──────────────────────────────────────


class CapabilityOut(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    handler: str
    input_schema: dict
    output_schema: dict
    iam_role_arn: str | None = None
    enabled: bool
    metadata: dict
    created_at: str | None = None
    updated_at: str | None = None


class CapabilityUpdate(BaseModel):
    enabled: bool | None = None
    description: str | None = None
    instructions: str | None = None
    handler: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    metadata: dict | None = None


class CapabilitiesResponse(BaseModel):
    count: int
    capabilities: list[CapabilityOut]


# ── Helpers ─────────────────────────────────────────────────────────


def _to_out(c: Capability) -> CapabilityOut:
    return CapabilityOut(
        id=str(c.id),
        name=c.name,
        description=c.description,
        instructions=c.instructions,
        handler=c.handler,
        input_schema=c.input_schema,
        output_schema=c.output_schema,
        iam_role_arn=c.iam_role_arn,
        enabled=c.enabled,
        metadata=c.metadata,
        created_at=str(c.created_at) if c.created_at else None,
        updated_at=str(c.updated_at) if c.updated_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/capabilities", response_model=CapabilitiesResponse)
def list_capabilities(name: str) -> CapabilitiesResponse:
    repo = get_cogos_repo()
    items = repo.list_capabilities()
    out = [_to_out(c) for c in items]
    return CapabilitiesResponse(count=len(out), capabilities=out)


@router.get("/capabilities/{cap_name}")
def get_capability(name: str, cap_name: str) -> dict:
    repo = get_cogos_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")
    return _to_out(c).model_dump()


@router.put("/capabilities/{cap_name}", response_model=CapabilityOut)
def update_capability(name: str, cap_name: str, body: CapabilityUpdate) -> CapabilityOut:
    repo = get_cogos_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")

    if body.enabled is not None:
        c.enabled = body.enabled
    if body.description is not None:
        c.description = body.description
    if body.instructions is not None:
        c.instructions = body.instructions
    if body.handler is not None:
        c.handler = body.handler
    if body.input_schema is not None:
        c.input_schema = body.input_schema
    if body.output_schema is not None:
        c.output_schema = body.output_schema
    if body.metadata is not None:
        c.metadata = body.metadata

    repo.upsert_capability(c)
    return _to_out(c)
