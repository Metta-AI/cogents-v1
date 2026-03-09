"""Channel model — external integrations."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelType(str, enum.Enum):
    DISCORD = "discord"
    GITHUB = "github"
    EMAIL = "email"
    ASANA = "asana"
    CLI = "cli"


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: ChannelType
    name: str
    external_id: str | None = None
    secret_arn: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime | None = None
