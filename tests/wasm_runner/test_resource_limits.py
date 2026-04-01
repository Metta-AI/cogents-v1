"""Tests for resource limits — memory cap, CPU timeout, child cap."""

import pytest

from wasm_runner.shim.child_process import ChildProcessShim
from wasm_runner.types import IsolateConfig, SpawnResult


class TestChildIsolateCap:
    @pytest.mark.asyncio
    async def test_cap_of_1(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1", max_child_isolates=1)
        cp = ChildProcessShim(bridge, audit, config)
        bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="", stderr=""))
        await cp.exec("cmd1")
        with pytest.raises(PermissionError):
            await cp.exec("cmd2")

    @pytest.mark.asyncio
    async def test_cap_of_0_denies_all(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1", max_child_isolates=0)
        cp = ChildProcessShim(bridge, audit, config)
        with pytest.raises(PermissionError):
            await cp.exec("anything")

    @pytest.mark.asyncio
    async def test_default_cap(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1")
        cp = ChildProcessShim(bridge, audit, config)
        for i in range(4):
            bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="", stderr=""))
            await cp.exec(f"cmd{i}")
        assert cp.child_count == 4
        with pytest.raises(PermissionError):
            await cp.exec("cmd5")


class TestIsolateConfigDefaults:
    def test_memory_limit_default(self):
        c = IsolateConfig(process_id="p", run_id="r")
        assert c.memory_limit_mb == 128

    def test_timeout_default(self):
        c = IsolateConfig(process_id="p", run_id="r")
        assert c.timeout_s == 30.0

    def test_max_children_default(self):
        c = IsolateConfig(process_id="p", run_id="r")
        assert c.max_child_isolates == 4
