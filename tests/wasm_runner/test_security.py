"""Security boundary tests — EPERM, scope enforcement, resource exhaustion."""

import pytest

from wasm_runner.shim.child_process import ChildProcessShim
from wasm_runner.shim.fs import VirtualFS
from wasm_runner.shim.net import NetworkGate
from wasm_runner.shim.path_translator import translate_path
from wasm_runner.types import IsolateConfig, SpawnResult


@pytest.fixture
def vfs(bridge, audit, isolate_config):
    return VirtualFS(bridge, audit, isolate_config)


@pytest.fixture
def gate(bridge, audit):
    return NetworkGate(bridge, audit)


class TestUnmappedSyscalls:
    @pytest.mark.asyncio
    async def test_read_forbidden_path(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("/proc/self/environ")

    @pytest.mark.asyncio
    async def test_write_forbidden_path(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.write_file("/dev/null", b"x")


class TestScopeCannotWiden:
    @pytest.mark.asyncio
    async def test_bridge_prefix_scope(self, vfs, bridge):
        bridge.allowed_prefixes = ["workspace/safe/"]
        with pytest.raises(PermissionError):
            await vfs.read_file("/home/agent/workspace/unsafe/secret.txt")

    @pytest.mark.asyncio
    async def test_bridge_read_only(self, vfs, bridge):
        bridge.allowed_ops = {"read"}
        with pytest.raises(PermissionError):
            await vfs.write_file("/home/agent/workspace/file.txt", b"data")


class TestNoAmbientCapabilities:
    @pytest.mark.asyncio
    async def test_cannot_access_other_process_files(self, bridge, audit):
        """Different config prefix means different namespace."""
        config_a = IsolateConfig(process_id="a", run_id="r1", file_prefix="ns_a/")
        config_b = IsolateConfig(process_id="b", run_id="r1", file_prefix="ns_b/")
        vfs_a = VirtualFS(bridge, audit, config_a)
        vfs_b = VirtualFS(bridge, audit, config_b)
        await vfs_a.write_file("/home/agent/workspace/secret.txt", b"secret")
        # vfs_b's path translation maps to ns_b/ prefix, so it won't find ns_a/ files
        with pytest.raises(FileNotFoundError):
            await vfs_b.read_file("/home/agent/workspace/secret.txt")


class TestResourceExhaustion:
    @pytest.mark.asyncio
    async def test_fork_bomb_hits_child_cap(self, bridge, audit):
        config = IsolateConfig(process_id="p1", run_id="r1", max_child_isolates=2)
        cp = ChildProcessShim(bridge, audit, config)
        bridge.spawn_results.extend([
            SpawnResult(exit_code=0, stdout="", stderr=""),
            SpawnResult(exit_code=0, stdout="", stderr=""),
        ])
        await cp.exec("cmd1")
        await cp.exec("cmd2")
        with pytest.raises(PermissionError):
            await cp.exec("cmd3")
        with pytest.raises(PermissionError):
            await cp.exec("cmd4")


class TestPathTraversalAtFsLevel:
    @pytest.mark.asyncio
    async def test_dotdot_traversal_blocked(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("/home/agent/workspace/../../etc/passwd")

    @pytest.mark.asyncio
    async def test_null_byte_blocked(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("/home/agent/workspace/foo\x00.txt")

    def test_null_byte_in_translator(self):
        with pytest.raises(PermissionError):
            translate_path("/home/agent/workspace/bar\x00baz")

    @pytest.mark.asyncio
    async def test_empty_path_blocked(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("")
