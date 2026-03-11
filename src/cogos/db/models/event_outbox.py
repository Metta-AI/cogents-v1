"""Event outbox model for immediate CogOS wakeups."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventOutboxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class EventOutbox(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    event: UUID
    status: EventOutboxStatus = EventOutboxStatus.PENDING
    attempt_count: int = 0
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
