"""Cron model — scheduled event emitter."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Cron(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    expression: str  # cron expression
    event_type: str  # event to emit on each tick
    payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime | None = None
