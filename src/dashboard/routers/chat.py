"""Chat routes — dashboard-to-cogent messaging via Discord channel pipeline."""

from __future__ import annotations

import logging
import os
import time
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel

from cogos.db.models import ChannelMessage
from cogos.db.models.channel import Channel, ChannelType
from dashboard.db import get_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: str
    source: str
    content: str
    author: str | None = None
    timestamp: float
    type: str = "message"


class ChatSendResult(BaseModel):
    ok: bool
    message_id: str


def _ensure_channel(repo, name: str) -> Channel | None:
    ch = repo.get_channel_by_name(name)
    if ch is None:
        ch = Channel(name=name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        ch = repo.get_channel_by_name(name)
    return ch


@router.post("/chat", response_model=ChatSendResult, status_code=201)
def send_chat_message(name: str, body: ChatMessageIn) -> ChatSendResult:
    repo = get_repo()
    cogent_name = os.environ.get("COGENT_NAME", name)
    dm_channel_name = f"io:discord:{cogent_name}:dm"
    ch = _ensure_channel(repo, dm_channel_name)
    if ch is None:
        return ChatSendResult(ok=False, message_id="")

    message_id = str(uuid4())
    payload = {
        "content": body.content,
        "author": "dashboard-user",
        "author_id": "dashboard",
        "message_id": message_id,
        "is_dm": True,
        "source": "dashboard",
        "timestamp": str(int(time.time() * 1000)),
    }

    msg = ChannelMessage(channel=ch.id, payload=payload)
    repo.append_channel_message(msg)
    return ChatSendResult(ok=True, message_id=message_id)


@router.get("/chat/messages", response_model=list[ChatMessageOut])
def get_chat_messages(
    name: str,
    limit: int = Query(50, ge=1, le=200),
    after: float = Query(0),
) -> list[ChatMessageOut]:
    repo = get_repo()
    cogent_name = os.environ.get("COGENT_NAME", name)

    messages: list[ChatMessageOut] = []

    dm_ch = repo.get_channel_by_name(f"io:discord:{cogent_name}:dm")
    if dm_ch:
        for msg in repo.list_channel_messages(dm_ch.id, limit=limit):
            p = msg.payload
            if p.get("source") != "dashboard":
                continue
            ts_raw = p.get("timestamp")
            ts = float(ts_raw) / 1000 if ts_raw else (msg.created_at.timestamp() if msg.created_at else 0)
            if ts <= after:
                continue
            messages.append(ChatMessageOut(
                id=str(msg.id),
                source="user",
                content=p.get("content", ""),
                author=p.get("author"),
                timestamp=ts,
            ))

    replies_ch = repo.get_channel_by_name(f"io:discord:{cogent_name}:replies")
    if replies_ch:
        for msg in repo.list_channel_messages(replies_ch.id, limit=limit):
            p = msg.payload
            content = p.get("content", "")
            if not content:
                continue
            ts_raw = p.get("_meta", {}).get("queued_at_ms") or p.get("timestamp")
            ts = float(ts_raw) / 1000 if ts_raw else (msg.created_at.timestamp() if msg.created_at else 0)
            if ts <= after:
                continue
            msg_type = p.get("type", "message")
            messages.append(ChatMessageOut(
                id=str(msg.id),
                source="cogent",
                content=content,
                author=cogent_name,
                timestamp=ts,
                type=msg_type,
            ))

    messages.sort(key=lambda m: m.timestamp)
    return messages[-limit:]
