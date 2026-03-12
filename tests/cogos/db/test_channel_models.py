"""Tests for channel and schema data models."""
from uuid import uuid4

from cogos.db.models import Channel, ChannelMessage, ChannelType, Schema


def test_schema_defaults():
    s = Schema(name="metrics", definition={"fields": {"value": "number"}})
    assert s.name == "metrics"
    assert s.id is not None
    assert s.file_id is None


def test_channel_defaults():
    pid = uuid4()
    ch = Channel(name="process:worker", owner_process=pid, channel_type=ChannelType.IMPLICIT)
    assert ch.channel_type == ChannelType.IMPLICIT
    assert ch.auto_close is False
    assert ch.closed_at is None


def test_channel_message_defaults():
    cid = uuid4()
    pid = uuid4()
    msg = ChannelMessage(channel=cid, sender_process=pid, payload={"body": "hi"})
    assert msg.payload == {"body": "hi"}
    assert msg.id is not None
