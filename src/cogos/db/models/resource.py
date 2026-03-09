"""Resource and ResourceUsage models — pool and consumable limits."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ResourceType(str, enum.Enum):
    POOL = "pool"
    CONSUMABLE = "consumable"


class Resource(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    resource_type: ResourceType = ResourceType.POOL
    capacity: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ResourceUsage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    resource: UUID  # FK -> Resource.id
    run: UUID  # FK -> Run.id
    amount: float = 0.0
    created_at: datetime | None = None
