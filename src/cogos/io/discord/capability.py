"""Discord capability — send messages, reactions, threads, DMs via SQS."""

from __future__ import annotations

import json
import logging
import os

import boto3
from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class SendResult(BaseModel):
    channel: str
    content_length: int
    type: str = "message"


class DiscordMessage(BaseModel):
    content: str | None = None
    author: str | None = None
    author_id: str | None = None
    channel_id: str | None = None
    message_id: str | None = None
    is_dm: bool = False
    is_mention: bool = False
    attachments: list[dict] | None = None
    thread_id: str | None = None
    reference_message_id: str | None = None
    event_type: str | None = None


class DiscordError(BaseModel):
    error: str


# ── SQS helpers ──────────────────────────────────────────────


def _get_queue_url() -> str:
    override = os.environ.get("DISCORD_REPLY_QUEUE_URL")
    if override:
        return override
    cogent_name = os.environ.get("COGENT_NAME", "")
    safe_name = cogent_name.replace(".", "-")
    region = os.environ.get("AWS_REGION", "us-east-1")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"https://sqs.{region}.amazonaws.com/{account_id}/cogent-{safe_name}-discord-replies"


def _send_sqs(body: dict) -> None:
    region = os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url()
    client = boto3.client("sqs", region_name=region)
    client.send_message(QueueUrl=url, MessageBody=json.dumps(body))


# ── Capability ───────────────────────────────────────────────


class DiscordCapability(Capability):
    """Send and receive Discord messages.

    Usage:
        discord.send(channel_id, "Hello!")
        discord.react(channel_id, message_id, "👍")
        discord.create_thread(channel_id, "Topic", content="First message")
        discord.dm(user_id, "Private message")
        messages = discord.receive(limit=10)
    """

    def send(
        self,
        channel: str,
        content: str,
        *,
        thread_id: str | None = None,
        reply_to: str | None = None,
        files: list[dict] | None = None,
    ) -> SendResult | DiscordError:
        """Send a message to a Discord channel."""
        if not channel or not content:
            return DiscordError(error="'channel' and 'content' are required")

        body: dict = {"channel": channel, "content": content}
        if thread_id:
            body["thread_id"] = thread_id
        if reply_to:
            body["reply_to"] = reply_to
        if files:
            body["files"] = files

        try:
            _send_sqs(body)
            return SendResult(channel=channel, content_length=len(content))
        except Exception as e:
            return DiscordError(error=str(e))

    def react(
        self,
        channel: str,
        message_id: str,
        emoji: str,
    ) -> SendResult | DiscordError:
        """Add a reaction to a message."""
        if not channel or not message_id or not emoji:
            return DiscordError(error="'channel', 'message_id', and 'emoji' are required")

        try:
            _send_sqs({
                "type": "reaction",
                "channel": channel,
                "message_id": message_id,
                "emoji": emoji,
            })
            return SendResult(channel=channel, content_length=0, type="reaction")
        except Exception as e:
            return DiscordError(error=str(e))

    def create_thread(
        self,
        channel: str,
        thread_name: str,
        content: str = "",
        *,
        message_id: str | None = None,
    ) -> SendResult | DiscordError:
        """Create a new thread in a channel."""
        if not channel or not thread_name:
            return DiscordError(error="'channel' and 'thread_name' are required")

        body: dict = {
            "type": "thread_create",
            "channel": channel,
            "thread_name": thread_name,
        }
        if content:
            body["content"] = content
        if message_id:
            body["message_id"] = message_id

        try:
            _send_sqs(body)
            return SendResult(channel=channel, content_length=len(content), type="thread_create")
        except Exception as e:
            return DiscordError(error=str(e))

    def dm(self, user_id: str, content: str) -> SendResult | DiscordError:
        """Send a direct message to a user."""
        if not user_id or not content:
            return DiscordError(error="'user_id' and 'content' are required")

        try:
            _send_sqs({"type": "dm", "user_id": user_id, "content": content})
            return SendResult(channel=f"dm:{user_id}", content_length=len(content), type="dm")
        except Exception as e:
            return DiscordError(error=str(e))

    def receive(self, limit: int = 10, event_type: str | None = None) -> list[DiscordMessage]:
        """Read recent Discord messages from the event log.

        Args:
            limit: Max messages to return.
            event_type: Filter by event type (discord:dm, discord:mention, discord:message).
                        If None, returns all discord events.
        """
        et = event_type or "discord:%"
        events = self.repo.get_events(event_type=et, limit=limit)
        return [_message_from_event(e) for e in events]

    def __repr__(self) -> str:
        return "<DiscordCapability send() react() create_thread() dm() receive()>"


def _message_from_event(e) -> DiscordMessage:
    p = e.payload or {}
    return DiscordMessage(
        content=p.get("content"),
        author=p.get("author"),
        author_id=p.get("author_id"),
        channel_id=p.get("channel_id"),
        message_id=p.get("message_id"),
        is_dm=p.get("is_dm", False),
        is_mention=p.get("is_mention", False),
        attachments=p.get("attachments"),
        thread_id=p.get("thread_id"),
        reference_message_id=p.get("reference_message_id"),
        event_type=p.get("event_type"),
    )
