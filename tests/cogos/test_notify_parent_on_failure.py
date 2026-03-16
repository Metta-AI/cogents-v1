"""Tests for _notify_parent_on_failure in executor handler."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor.handler import _notify_parent_on_failure


def test_sends_failure_message_on_spawn_channel():
    parent_id = uuid4()
    child_id = uuid4()
    run_id = uuid4()

    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(id=run_id, process=child_id, status=RunStatus.FAILED)

    ch = Channel(name=f"spawn:{child_id}→{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    _notify_parent_on_failure(repo, process, run, "something broke")

    repo.get_channel_by_name.assert_called_once_with(f"spawn:{child_id}→{parent_id}")
    repo.append_channel_message.assert_called_once()
    msg = repo.append_channel_message.call_args.args[0]
    assert msg.channel == ch.id
    assert msg.payload["type"] == "child:failed"
    assert msg.payload["process_name"] == "child"
    assert msg.payload["error"] == "something broke"


def test_no_parent_is_noop():
    process = Process(
        name="orphan", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=None,
    )
    run = Run(process=process.id, status=RunStatus.FAILED)
    repo = MagicMock()

    _notify_parent_on_failure(repo, process, run, "error")

    repo.get_channel_by_name.assert_not_called()


def test_no_channel_found_is_noop():
    parent_id = uuid4()
    process = Process(
        name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(process=process.id, status=RunStatus.FAILED)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = None

    _notify_parent_on_failure(repo, process, run, "error")

    repo.append_channel_message.assert_not_called()


def test_error_truncated_to_1000_chars():
    parent_id = uuid4()
    child_id = uuid4()
    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(process=child_id, status=RunStatus.FAILED)
    ch = Channel(name=f"spawn:{child_id}→{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    long_error = "x" * 2000
    _notify_parent_on_failure(repo, process, run, long_error)

    msg = repo.append_channel_message.call_args.args[0]
    assert len(msg.payload["error"]) == 1000
