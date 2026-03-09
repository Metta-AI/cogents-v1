"""Event model — append-only signal log."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_event: UUID | None = None  # FK -> Event.id (causal chain)
    created_at: datetime | None = None
