"""Tests for Wasm dispatch — executor registration and routing."""

import pytest

from wasm_runner.dispatch.wasm_dispatch import register_wasm_executor, dispatch_wasm


class FakeRepo:
    """Minimal fake repository for dispatch tests."""

    def __init__(self):
        self.executors: dict[str, dict] = {}

    def register_executor(self, executor):
        self.executors[executor.executor_id] = executor

    def get_executor(self, executor_id: str):
        return self.executors.get(executor_id)


class TestRegisterExecutor:
    def test_creates_record(self):
        repo = FakeRepo()
        executor = register_wasm_executor(repo)
        assert executor is not None
        assert executor.executor_id == "wasm-pool"

    def test_has_wasm_tag(self):
        repo = FakeRepo()
        executor = register_wasm_executor(repo)
        assert "wasm" in executor.executor_tags

    def test_dispatch_type_is_wasm(self):
        repo = FakeRepo()
        executor = register_wasm_executor(repo)
        assert executor.dispatch_type == "wasm"

    def test_is_pool_metadata(self):
        repo = FakeRepo()
        executor = register_wasm_executor(repo)
        assert executor.metadata.get("pool") is True

    def test_registered_in_repo(self):
        repo = FakeRepo()
        register_wasm_executor(repo)
        assert repo.get_executor("wasm-pool") is not None


class TestDispatchEvent:
    @pytest.mark.asyncio
    async def test_event_shape(self):
        repo = FakeRepo()
        register_wasm_executor(repo)
        event = await dispatch_wasm(repo, process_id="proc-1", run_id="run-1")
        assert isinstance(event, dict)
        assert event["process_id"] == "proc-1"
        assert event["run_id"] == "run-1"
        assert event["dispatch_type"] == "wasm"

    @pytest.mark.asyncio
    async def test_event_has_timestamp(self):
        repo = FakeRepo()
        register_wasm_executor(repo)
        event = await dispatch_wasm(repo, process_id="p1", run_id="r1")
        assert "dispatched_at_ms" in event
        assert isinstance(event["dispatched_at_ms"], int)
