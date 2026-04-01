"""Concurrency tests — parallel isolates, no cross-contamination."""

import asyncio

import pytest

from wasm_runner.shim.fs import VirtualFS
from wasm_runner.types import IsolateConfig

# These are conftest fixtures
# bridge: FakeBridge, audit: FakeAuditLogger


class TestParallelIsolateIsolation:
    @pytest.mark.asyncio
    async def test_16_parallel_vfs_no_cross_contamination(self, bridge, audit):
        """Each VFS writes a unique file, reads it back, verifies isolation."""

        async def worker(i: int):
            config = IsolateConfig(
                process_id=f"proc-{i}",
                run_id=f"run-{i}",
                file_prefix=f"ns_{i}/",
            )
            vfs = VirtualFS(bridge, audit, config)
            path = f"/home/agent/workspace/file_{i}.txt"
            data = f"data-{i}".encode()
            await vfs.write_file(path, data)
            result = await vfs.read_file(path)
            assert result == data, f"Worker {i} got wrong data: {result!r}"

        await asyncio.gather(*[worker(i) for i in range(16)])

    @pytest.mark.asyncio
    async def test_concurrent_tmp_writes_isolated(self, bridge, audit, isolate_config):
        """Multiple VFS instances sharing a config still have isolated /tmp."""
        vfs_a = VirtualFS(bridge, audit, isolate_config)
        vfs_b = VirtualFS(bridge, audit, isolate_config)

        await vfs_a.write_file("/tmp/shared_name.txt", b"from_a")
        await vfs_b.write_file("/tmp/shared_name.txt", b"from_b")

        # Each VFS has its own /tmp
        assert await vfs_a.read_file("/tmp/shared_name.txt") == b"from_a"
        assert await vfs_b.read_file("/tmp/shared_name.txt") == b"from_b"


class TestConcurrentBridgeCalls:
    @pytest.mark.asyncio
    async def test_concurrent_writes_to_different_keys(self, bridge, audit, isolate_config):
        vfs = VirtualFS(bridge, audit, isolate_config)

        async def writer(i: int):
            path = f"/home/agent/workspace/concurrent_{i}.txt"
            await vfs.write_file(path, f"value-{i}".encode())

        await asyncio.gather(*[writer(i) for i in range(10)])

        for i in range(10):
            key = f"workspace/concurrent_{i}.txt"
            assert bridge.files[key] == f"value-{i}".encode()
