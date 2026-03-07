from __future__ import annotations

from fastapi import APIRouter

from brain.db.models import ResourceType
from dashboard.db import get_repo
from dashboard.models import ResourceItem, ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(name: str) -> ResourcesResponse:
    repo = get_repo()
    resources = repo.list_resources()
    items: list[ResourceItem] = []
    for r in resources:
        if r.resource_type == ResourceType.POOL:
            used = float(repo.get_pool_usage(r.name))
        else:
            used = repo.get_consumable_usage(r.name)
        items.append(
            ResourceItem(
                name=r.name,
                resource_type=r.resource_type.value,
                capacity=r.capacity,
                used=used,
                metadata=r.metadata,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )
    return ResourcesResponse(
        cogent_name=name,
        count=len(items),
        resources=items,
    )
