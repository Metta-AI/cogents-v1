"""Handler model — binds a process to a channel subscription.

Handlers are still part of the channel-based runtime, but their role is
smaller than in the old event-pattern model. Channels carry durable typed
messages; handlers are the wakeup bindings that tell CogOS which processes
should receive deliveries from which channels.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Handler(BaseModel):
    """Process-to-channel subscription used for wakeup and delivery tracking."""

    id: UUID = Field(default_factory=uuid4)
    epoch: int = 0
    process: UUID  # FK -> Process.id
    channel: UUID | None = None  # FK -> Channel.id; None only in legacy compatibility paths
    enabled: bool = True
    created_at: datetime | None = None
