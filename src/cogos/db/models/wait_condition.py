from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WaitConditionStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class WaitConditionType(str, enum.Enum):
    WAIT = "wait"
    WAIT_ANY = "wait_any"
    WAIT_ALL = "wait_all"


class WaitCondition(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run: UUID | None = None
    process: UUID | None = None
    type: WaitConditionType
    status: WaitConditionStatus = WaitConditionStatus.PENDING
    pending: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
