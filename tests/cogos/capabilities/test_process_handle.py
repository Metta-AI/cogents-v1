"""Tests for ProcessHandle — send, recv, kill, status, wait."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.process_handle import ProcessHandle
from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def parent_id():
    return uuid4()


@pytest.fixture
def child_process():
    return Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)


class TestSendRecv:
    def test_send(self, repo, parent_id, child_process):
        send_ch = Channel(name=f"spawn:{parent_id}\u2192{child_process.id}",
                          owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name=f"spawn:{child_process.id}\u2192{parent_id}",
                          owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.append_channel_message.return_value = uuid4()

        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        result = handle.send({"body": "task"})
        assert "id" in result
        repo.append_channel_message.assert_called_once()

    def test_send_no_channel(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        result = handle.send({"body": "task"})
        assert "error" in result

    def test_recv(self, repo, parent_id, child_process):
        send_ch = Channel(name="s", owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name="r", owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=recv_ch.id, sender_process=child_process.id, payload={"result": "done"}),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        msgs = handle.recv()
        assert len(msgs) == 1

    def test_recv_no_channel(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.recv() == []


class TestKillAndStatus:
    def test_kill(self, repo, parent_id, child_process):
        repo.get_process.return_value = child_process
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        result = handle.kill()
        repo.update_process_status.assert_called_once_with(child_process.id, ProcessStatus.DISABLED)
        assert result["new_status"] == "disabled"

    def test_status(self, repo, parent_id, child_process):
        repo.get_process.return_value = child_process
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.status() == "runnable"


class TestWait:
    def test_wait_returns_spec(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        spec = handle.wait()
        assert spec["type"] == "wait"
        assert spec["process_ids"] == [str(child_process.id)]

    def test_wait_any(self, repo, parent_id):
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1, send_channel=None, recv_channel=None)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2, send_channel=None, recv_channel=None)
        spec = ProcessHandle.wait_any([h1, h2])
        assert spec["type"] == "wait_any"
        assert len(spec["process_ids"]) == 2

    def test_wait_all(self, repo, parent_id):
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1, send_channel=None, recv_channel=None)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2, send_channel=None, recv_channel=None)
        spec = ProcessHandle.wait_all([h1, h2])
        assert spec["type"] == "wait_all"
        assert len(spec["process_ids"]) == 2
