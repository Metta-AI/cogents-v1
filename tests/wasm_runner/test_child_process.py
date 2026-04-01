"""Tests for ChildProcessShim — exec via capability bridge with cap on children."""

import pytest

from wasm_runner.shim.child_process import ChildProcessShim
from wasm_runner.types import IsolateConfig, SpawnResult


@pytest.fixture
def child_proc(bridge, audit, isolate_config):
    return ChildProcessShim(bridge, audit, isolate_config)


class TestExecHappy:
    @pytest.mark.asyncio
    async def test_exec_returns_result(self, child_proc, bridge):
        bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="hello\n", stderr=""))
        result = await child_proc.exec("echo", ["hello"])
        assert result.exit_code == 0
        assert result.stdout == "hello\n"

    @pytest.mark.asyncio
    async def test_exec_increments_child_count(self, child_proc, bridge):
        bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="", stderr=""))
        assert child_proc.child_count == 0
        await child_proc.exec("ls")
        assert child_proc.child_count == 1

    @pytest.mark.asyncio
    async def test_exec_with_args(self, child_proc, bridge):
        bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="", stderr=""))
        await child_proc.exec("python", ["-c", "print('hi')"])
        assert bridge.call_log[-1] == ("process_spawn", {"command": "python", "args": ["-c", "print('hi')"]})


class TestChildCap:
    @pytest.mark.asyncio
    async def test_exec_at_cap_raises(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1", max_child_isolates=2)
        cp = ChildProcessShim(bridge, audit, config)
        bridge.spawn_results.extend([
            SpawnResult(exit_code=0, stdout="", stderr=""),
            SpawnResult(exit_code=0, stdout="", stderr=""),
        ])
        await cp.exec("cmd1")
        await cp.exec("cmd2")
        with pytest.raises(PermissionError, match="child"):
            await cp.exec("cmd3")

    @pytest.mark.asyncio
    async def test_default_cap_is_4(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1")
        cp = ChildProcessShim(bridge, audit, config)
        assert config.max_child_isolates == 4
