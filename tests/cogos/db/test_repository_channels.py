from __future__ import annotations

import pytest

from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.db.sqlite_repository import SqliteBackend
from cogos.db.unified_repository import UnifiedRepository


@pytest.fixture
def repo(tmp_path):
    return UnifiedRepository(SqliteBackend(str(tmp_path)))


def test_list_channel_messages_allows_null_sender_process(repo):
    ch = Channel(name="test", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    msg = ChannelMessage(channel=ch.id, sender_process=None, payload={"content": "hello"})
    repo.append_channel_message(msg)

    messages = repo.list_channel_messages(ch.id)
    assert len(messages) == 1
    assert messages[0].channel == ch.id
    assert messages[0].sender_process is None
    assert messages[0].payload == {"content": "hello"}
