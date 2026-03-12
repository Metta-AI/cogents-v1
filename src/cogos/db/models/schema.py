"""Schema model — declarative message type definitions."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Schema(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    definition: dict[str, Any] = Field(default_factory=dict)
    file_id: UUID | None = None  # FK -> File.id
    created_at: datetime | None = None
