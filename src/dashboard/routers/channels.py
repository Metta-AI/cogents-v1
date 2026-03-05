from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import Channel, ChannelsResponse

router = APIRouter(tags=["channels"])


@router.get("/channels", response_model=ChannelsResponse)
def list_channels(name: str) -> ChannelsResponse:
    repo = get_repo()
    db_channels = repo.list_channels()
    channels = [
        Channel(
            name=ch.name,
            type=ch.type.value if ch.type else None,
            enabled=ch.enabled,
            created_at=str(ch.created_at) if ch.created_at else None,
        )
        for ch in db_channels
    ]
    return ChannelsResponse(cogent_name=name, count=len(channels), channels=channels)
