"""Tests for WasmIsolate lifecycle — boot, execute, terminate."""

import pytest

from wasm_runner.runtime.isolate import WasmIsolate
from wasm_runner.types import IsolateConfig, IsolateResult


# We need a concrete (but minimal) implementation to test lifecycle.
# Import the concrete class once it exists; for now this tests the contract.

try:
    from wasm_runner.runtime.sandbox_isolate import SandboxIsolate as ConcreteIsolate
except ImportError:
    ConcreteIsolate = None  # type: ignore[assignment, misc]

pytestmark = pytest.mark.skipif(ConcreteIsolate is None, reason="SandboxIsolate not yet implemented")


@pytest.fixture
def isolate():
    return ConcreteIsolate()


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_boot_execute_terminate(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        assert isolate.is_alive()
        result = await isolate.execute("print('hello')")
        assert isinstance(result, IsolateResult)
        assert result.exit_code == 0
        assert "hello" in result.stdout
        await isolate.terminate()
        assert not isolate.is_alive()

    @pytest.mark.asyncio
    async def test_execute_returns_stderr(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        result = await isolate.execute("import sys; sys.stderr.write('err\\n')")
        assert "err" in result.stderr
        await isolate.terminate()

    @pytest.mark.asyncio
    async def test_execute_captures_exit_code(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        result = await isolate.execute("exit(42)")
        assert result.exit_code == 42
        await isolate.terminate()


class TestTermination:
    @pytest.mark.asyncio
    async def test_terminated_not_alive(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        await isolate.terminate()
        assert not isolate.is_alive()

    @pytest.mark.asyncio
    async def test_double_terminate_noop(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        await isolate.terminate()
        await isolate.terminate()  # should not raise

    @pytest.mark.asyncio
    async def test_execute_after_terminate_raises(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        await isolate.terminate()
        with pytest.raises(RuntimeError):
            await isolate.execute("print('nope')")


class TestResourceLimits:
    @pytest.mark.asyncio
    async def test_timeout_kills_isolate(self, bridge):
        config = IsolateConfig(process_id="p1", run_id="r1", timeout_s=0.1)
        iso = ConcreteIsolate()
        await iso.boot(config, bridge)
        result = await iso.execute("import time; time.sleep(10)")
        assert result.exit_code != 0
        await iso.terminate()

    @pytest.mark.asyncio
    async def test_memory_usage_reported(self, isolate, bridge, isolate_config):
        await isolate.boot(isolate_config, bridge)
        usage = isolate.memory_usage_mb()
        assert isinstance(usage, float)
        assert usage >= 0
        await isolate.terminate()
