"""Shared dispatch-envelope helpers for local and remote runtimes."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID


def _load_message_payload(repo, message_id: str | None) -> dict[str, Any]:
    if not message_id:
        return {}

    msg_uuid = UUID(message_id)

    channel_messages = getattr(repo, "_channel_messages", None)
    if isinstance(channel_messages, dict):
        msg = channel_messages.get(msg_uuid)
        if msg is not None:
            return msg.payload or {}

    try:
        rows = repo.query(
            "SELECT payload FROM cogos_channel_message WHERE id = :id",
            {"id": msg_uuid},
        )
    except Exception:
        return {}

    if not rows:
        return {}

    json_field = getattr(repo, "_json_field", None)
    if callable(json_field):
        return json_field(rows[0], "payload", {})

    payload = rows[0].get("payload")
    return payload if isinstance(payload, dict) else {}


def _resolve_channel_name(repo, message_id: str | None) -> str | None:
    """Look up the channel name for a message."""
    if not message_id:
        return None
    msg_uuid = UUID(message_id)

    # Fast path: local repository in-memory lookup
    channel_messages = getattr(repo, "_channel_messages", None)
    if isinstance(channel_messages, dict):
        msg = channel_messages.get(msg_uuid)
        if msg is not None:
            ch = repo.get_channel(msg.channel)
            return ch.name if ch else None

    # RDS path
    try:
        rows = repo.query(
            """SELECT c.name FROM cogos_channel_message m
               JOIN cogos_channel c ON c.id = m.channel
               WHERE m.id = :id""",
            {"id": msg_uuid},
        )
        return rows[0]["name"] if rows else None
    except Exception:
        return None


def build_dispatch_event(repo, dispatch_result) -> dict[str, Any]:
    """Build the executor event envelope used by both local and prod dispatch."""
    return {
        "process_id": dispatch_result.process_id,
        "run_id": dispatch_result.run_id,
        "message_id": dispatch_result.message_id,
        "trace_id": getattr(dispatch_result, "trace_id", None),
        "dispatched_at_ms": int(time.time() * 1000),
        "channel_name": _resolve_channel_name(repo, dispatch_result.message_id),
        "payload": _load_message_payload(repo, dispatch_result.message_id),
    }
