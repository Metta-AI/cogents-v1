"""Tests for IsolatePool — acquire/release, capacity management."""

import asyncio

import pytest

try:
    from wasm_runner.runtime.sandbox_pool import SandboxPool as ConcretePool
except ImportError:
    ConcretePool = None  # type: ignore[assignment, misc]

from wasm_runner.types import IsolateConfig

pytestmark = pytest.mark.skipif(ConcretePool is None, reason="SandboxPool not yet implemented")


@pytest.fixture
def pool():
    return ConcretePool(max_isolates=4)


@pytest.fixture
def config():
    return IsolateConfig(process_id="p1", run_id="r1")


class TestAcquireRelease:
    @pytest.mark.asyncio
    async def test_acquire_returns_isolate(self, pool, config, bridge):
        iso = await pool.acquire(config, bridge)
        assert iso.is_alive()
        await pool.release(iso)

    @pytest.mark.asyncio
    async def test_release_decrements_count(self, pool, config, bridge):
        iso = await pool.acquire(config, bridge)
        assert pool.active_count() == 1
        await pool.release(iso)
        assert pool.active_count() == 0

    @pytest.mark.asyncio
    async def test_capacity_reported(self, pool):
        assert pool.capacity() == 4


class TestCapacityLimits:
    @pytest.mark.asyncio
    async def test_acquire_at_capacity_raises(self, bridge):
        pool = ConcretePool(max_isolates=2)
        config = IsolateConfig(process_id="p1", run_id="r1")
        iso1 = await pool.acquire(config, bridge)
        iso2 = await pool.acquire(config, bridge)
        with pytest.raises(RuntimeError, match="capacity"):
            await pool.acquire(config, bridge)
        await pool.release(iso1)
        await pool.release(iso2)


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_acquire_release(self, bridge):
        pool = ConcretePool(max_isolates=16)

        async def worker(i: int):
            config = IsolateConfig(process_id=f"p{i}", run_id=f"r{i}")
            iso = await pool.acquire(config, bridge)
            await asyncio.sleep(0.01)
            await pool.release(iso)

        await asyncio.gather(*[worker(i) for i in range(16)])
        assert pool.active_count() == 0


class TestCrashRecovery:
    @pytest.mark.asyncio
    async def test_crash_does_not_leak_slot(self, pool, config, bridge):
        iso = await pool.acquire(config, bridge)
        # Simulate crash by terminating directly
        await iso.terminate()
        await pool.release(iso)
        assert pool.active_count() == 0
        # Should be able to acquire again
        iso2 = await pool.acquire(config, bridge)
        await pool.release(iso2)


class TestActiveCount:
    @pytest.mark.asyncio
    async def test_tracks_accurately(self, pool, bridge):
        configs = [IsolateConfig(process_id=f"p{i}", run_id=f"r{i}") for i in range(3)]
        isolates = []
        for c in configs:
            isolates.append(await pool.acquire(c, bridge))
        assert pool.active_count() == 3
        await pool.release(isolates[0])
        assert pool.active_count() == 2
        await pool.release(isolates[1])
        await pool.release(isolates[2])
        assert pool.active_count() == 0
