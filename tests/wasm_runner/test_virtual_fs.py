"""Tests for VirtualFS — POSIX file operations backed by capability bridge."""

import pytest

from wasm_runner.shim.fs import VirtualFS
from wasm_runner.types import IsolateConfig

# All tests use the bridge and audit fixtures from conftest.py


@pytest.fixture
def vfs(bridge, audit, isolate_config):
    return VirtualFS(bridge, audit, isolate_config)


class TestCrudCycle:
    @pytest.mark.asyncio
    async def test_write_then_read(self, vfs, bridge):
        await vfs.write_file("/home/agent/workspace/hello.txt", b"hello world")
        data = await vfs.read_file("/home/agent/workspace/hello.txt")
        assert data == b"hello world"
        # Verify it went through the bridge
        assert "workspace/hello.txt" in bridge.files

    @pytest.mark.asyncio
    async def test_readdir_lists_written_files(self, vfs, bridge):
        bridge.files["workspace/a.txt"] = b"a"
        bridge.files["workspace/b.txt"] = b"b"
        listing = await vfs.readdir("/home/agent/workspace/")
        assert "a.txt" in listing
        assert "b.txt" in listing

    @pytest.mark.asyncio
    async def test_stat_existing_file(self, vfs, bridge):
        bridge.files["workspace/f.txt"] = b"data"
        st = await vfs.stat("/home/agent/workspace/f.txt")
        assert st.is_file is True
        assert st.size == 4

    @pytest.mark.asyncio
    async def test_stat_nonexistent_raises(self, vfs):
        with pytest.raises(FileNotFoundError):
            await vfs.stat("/home/agent/workspace/nope.txt")

    @pytest.mark.asyncio
    async def test_unlink_removes_file(self, vfs, bridge):
        bridge.files["workspace/del.txt"] = b"gone"
        await vfs.unlink("/home/agent/workspace/del.txt")
        assert "workspace/del.txt" not in bridge.files

    @pytest.mark.asyncio
    async def test_mkdir(self, vfs):
        # mkdir is a no-op for key-based stores but should not error
        await vfs.mkdir("/home/agent/workspace/newdir")


class TestEphemeralTmp:
    @pytest.mark.asyncio
    async def test_tmp_write_read(self, vfs):
        await vfs.write_file("/tmp/scratch.txt", b"temp data")
        data = await vfs.read_file("/tmp/scratch.txt")
        assert data == b"temp data"

    @pytest.mark.asyncio
    async def test_tmp_not_persisted_to_bridge(self, vfs, bridge):
        await vfs.write_file("/tmp/local.txt", b"local")
        assert len(bridge.call_log) == 0  # no bridge calls for /tmp

    @pytest.mark.asyncio
    async def test_tmp_readdir(self, vfs):
        await vfs.write_file("/tmp/a.txt", b"a")
        await vfs.write_file("/tmp/b.txt", b"b")
        listing = await vfs.readdir("/tmp/")
        assert "a.txt" in listing
        assert "b.txt" in listing

    @pytest.mark.asyncio
    async def test_tmp_stat(self, vfs):
        await vfs.write_file("/tmp/x.bin", b"\x00\x01\x02")
        st = await vfs.stat("/tmp/x.bin")
        assert st.is_file is True
        assert st.size == 3

    @pytest.mark.asyncio
    async def test_tmp_unlink(self, vfs):
        await vfs.write_file("/tmp/rm.txt", b"bye")
        await vfs.unlink("/tmp/rm.txt")
        with pytest.raises(FileNotFoundError):
            await vfs.read_file("/tmp/rm.txt")


class TestScopeEnforcement:
    @pytest.mark.asyncio
    async def test_read_outside_workspace_raises(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("/etc/passwd")

    @pytest.mark.asyncio
    async def test_write_outside_workspace_raises(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.write_file("/etc/shadow", b"nope")

    @pytest.mark.asyncio
    async def test_traversal_in_read(self, vfs):
        with pytest.raises(PermissionError):
            await vfs.read_file("/home/agent/workspace/../../etc/passwd")


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_read_empty_file(self, vfs, bridge):
        bridge.files["workspace/empty.txt"] = b""
        data = await vfs.read_file("/home/agent/workspace/empty.txt")
        assert data == b""

    @pytest.mark.asyncio
    async def test_write_overwrite(self, vfs, bridge):
        await vfs.write_file("/home/agent/workspace/f.txt", b"v1")
        await vfs.write_file("/home/agent/workspace/f.txt", b"v2")
        data = await vfs.read_file("/home/agent/workspace/f.txt")
        assert data == b"v2"

    @pytest.mark.asyncio
    async def test_readdir_empty(self, vfs):
        listing = await vfs.readdir("/home/agent/workspace/empty_dir/")
        assert listing == []

    @pytest.mark.asyncio
    async def test_binary_roundtrip(self, vfs):
        data = bytes(range(256))
        await vfs.write_file("/home/agent/workspace/bin.dat", data)
        result = await vfs.read_file("/home/agent/workspace/bin.dat")
        assert result == data

    @pytest.mark.asyncio
    async def test_large_file(self, vfs):
        data = b"x" * (10 * 1024 * 1024)  # 10 MB
        await vfs.write_file("/home/agent/workspace/big.bin", data)
        result = await vfs.read_file("/home/agent/workspace/big.bin")
        assert len(result) == 10 * 1024 * 1024
