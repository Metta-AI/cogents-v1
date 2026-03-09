"""Trace model — detailed execution audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Trace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run: UUID  # FK -> Run.id
    capability_calls: list[dict[str, Any]] = Field(default_factory=list)
    file_ops: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str | None = None
    created_at: datetime | None = None
