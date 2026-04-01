"""Tests for audit logging — every syscall emits a SyscallEvent."""

import pytest

from wasm_runner.shim.fs import VirtualFS
from wasm_runner.shim.net import NetworkGate
from wasm_runner.shim.child_process import ChildProcessShim
from wasm_runner.types import FetchResult, SpawnResult


@pytest.fixture
def vfs(bridge, audit, isolate_config):
    return VirtualFS(bridge, audit, isolate_config)


@pytest.fixture
def gate(bridge, audit):
    return NetworkGate(bridge, audit)


@pytest.fixture
def child_proc(bridge, audit, isolate_config):
    return ChildProcessShim(bridge, audit, isolate_config)


class TestFsSyscallEvents:
    @pytest.mark.asyncio
    async def test_read_emits_event(self, vfs, bridge, audit):
        bridge.files["workspace/f.txt"] = b"data"
        await vfs.read_file("/home/agent/workspace/f.txt")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fs.readFile"
        assert events[0].result == "ok"

    @pytest.mark.asyncio
    async def test_write_emits_event(self, vfs, audit):
        await vfs.write_file("/home/agent/workspace/f.txt", b"data")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fs.writeFile"

    @pytest.mark.asyncio
    async def test_readdir_emits_event(self, vfs, audit):
        await vfs.readdir("/home/agent/workspace/")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fs.readdir"

    @pytest.mark.asyncio
    async def test_unlink_emits_event(self, vfs, bridge, audit):
        bridge.files["workspace/x.txt"] = b""
        await vfs.unlink("/home/agent/workspace/x.txt")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fs.unlink"

    @pytest.mark.asyncio
    async def test_stat_emits_event(self, vfs, bridge, audit):
        bridge.files["workspace/s.txt"] = b"x"
        await vfs.stat("/home/agent/workspace/s.txt")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fs.stat"


class TestFetchSyscallEvents:
    @pytest.mark.asyncio
    async def test_fetch_emits_event(self, gate, audit):
        await gate.fetch("https://example.com")
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "fetch"
        assert events[0].result == "ok"


class TestDeniedCallsLogged:
    @pytest.mark.asyncio
    async def test_denied_read_logged(self, vfs, audit):
        try:
            await vfs.read_file("/etc/passwd")
        except PermissionError:
            pass
        events = audit.events()
        assert len(events) == 1
        assert events[0].result == "EPERM"

    @pytest.mark.asyncio
    async def test_denied_fetch_logged(self, gate, bridge, audit):
        bridge.allowed_urls = {"https://ok.com"}
        try:
            await gate.fetch("https://denied.com")
        except PermissionError:
            pass
        events = audit.events()
        assert len(events) == 1
        assert events[0].result == "EPERM"


class TestEventFields:
    @pytest.mark.asyncio
    async def test_required_fields_present(self, vfs, bridge, audit, isolate_config):
        bridge.files["workspace/t.txt"] = b"x"
        await vfs.read_file("/home/agent/workspace/t.txt")
        event = audit.events()[0]
        assert event.process_id == isolate_config.process_id
        assert isinstance(event.timestamp_ms, int)
        assert event.timestamp_ms > 0
        assert isinstance(event.args, dict)
        assert event.op == "fs.readFile"
        assert event.result == "ok"


class TestSyscallOrdering:
    @pytest.mark.asyncio
    async def test_ordering_matches_execution(self, vfs, bridge, audit):
        bridge.files["workspace/a.txt"] = b"a"
        await vfs.write_file("/home/agent/workspace/b.txt", b"b")
        await vfs.read_file("/home/agent/workspace/a.txt")
        await vfs.readdir("/home/agent/workspace/")
        events = audit.events()
        ops = [e.op for e in events]
        assert ops == ["fs.writeFile", "fs.readFile", "fs.readdir"]


class TestChildProcessAudit:
    @pytest.mark.asyncio
    async def test_exec_emits_event(self, child_proc, bridge, audit):
        bridge.spawn_results.append(SpawnResult(exit_code=0, stdout="", stderr=""))
        await child_proc.exec("echo", ["hi"])
        events = audit.events()
        assert len(events) == 1
        assert events[0].op == "process.exec"
        assert events[0].result == "ok"
