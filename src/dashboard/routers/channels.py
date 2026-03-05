from __future__ import annotations

from fastapi import APIRouter, HTTPException

from brain.db.models import Channel as DbChannel, ChannelType
from dashboard.db import get_repo
from dashboard.models import Channel, ChannelCreate, ChannelUpdate, ChannelsResponse

router = APIRouter(tags=["channels"])


def _db_to_api(ch: DbChannel) -> Channel:
    return Channel(
        name=ch.name,
        type=ch.type.value if ch.type else None,
        enabled=ch.enabled,
        created_at=str(ch.created_at) if ch.created_at else None,
    )


@router.get("/channels", response_model=ChannelsResponse)
def list_channels(name: str) -> ChannelsResponse:
    repo = get_repo()
    db_channels = repo.list_channels()
    channels = [_db_to_api(ch) for ch in db_channels]
    return ChannelsResponse(cogent_name=name, count=len(channels), channels=channels)


@router.post("/channels", response_model=Channel)
def create_channel(name: str, body: ChannelCreate) -> Channel:
    repo = get_repo()
    # Check for duplicate name
    existing = repo.list_channels()
    for ch in existing:
        if ch.name == body.name:
            raise HTTPException(status_code=409, detail=f"Channel '{body.name}' already exists")
    try:
        channel_type = ChannelType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel type: {body.type}")
    db_channel = DbChannel(
        name=body.name,
        type=channel_type,
        enabled=body.enabled,
        config=body.config,
    )
    repo.upsert_channel(db_channel)
    return _db_to_api(db_channel)


@router.put("/channels/{channel_name}", response_model=Channel)
def update_channel(name: str, channel_name: str, body: ChannelUpdate) -> Channel:
    repo = get_repo()
    existing = repo.list_channels()
    target = None
    for ch in existing:
        if ch.name == channel_name:
            target = ch
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")
    if body.type is not None:
        try:
            target.type = ChannelType(body.type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid channel type: {body.type}")
    if body.enabled is not None:
        target.enabled = body.enabled
    if body.config is not None:
        target.config = body.config
    repo.upsert_channel(target)
    return _db_to_api(target)


@router.delete("/channels/{channel_name}")
def delete_channel(name: str, channel_name: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_channel(channel_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")
    return {"deleted": True, "name": channel_name}
