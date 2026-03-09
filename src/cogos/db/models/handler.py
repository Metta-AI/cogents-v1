"""Handler model — binds a process to an event pattern."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Handler(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    process: UUID  # FK -> Process.id
    event_pattern: str
    enabled: bool = True
    created_at: datetime | None = None
