"""Sandbox isolate — concrete WasmIsolate using restricted Python exec.

This is a development/test implementation. The production implementation
will use wasmtime-py for real Wasm execution.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import sys
import time
import traceback

from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.runtime.isolate import WasmIsolate
from wasm_runner.types import IsolateConfig, IsolateResult

_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=32)


class SandboxIsolate(WasmIsolate):
    """Concrete isolate using restricted Python exec for testing."""

    def __init__(self) -> None:
        self._alive = False
        self._config: IsolateConfig | None = None
        self._bridge: CapabilityBridge | None = None
        self._memory_usage: float = 0.0

    async def boot(self, config: IsolateConfig, bridge: CapabilityBridge) -> None:
        self._config = config
        self._bridge = bridge
        self._alive = True
        self._memory_usage = 1.0  # baseline MB

    async def execute(self, code: str, entrypoint: str = "main") -> IsolateResult:
        if not self._alive:
            raise RuntimeError("Isolate is not alive — call boot() first or it was terminated")

        assert self._config is not None
        start = time.monotonic()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(_THREAD_POOL, self._run_code_sync, code, stdout_buf, stderr_buf),
                timeout=self._config.timeout_s,
            )
        except asyncio.TimeoutError:
            stderr_buf.write("Timeout: execution exceeded limit\n")
            exit_code = -1
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
        except Exception:
            stderr_buf.write(traceback.format_exc())
            exit_code = 1

        duration_ms = (time.monotonic() - start) * 1000
        return IsolateResult(
            exit_code=exit_code,
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            syscall_log=[],
            memory_peak_mb=self._memory_usage,
            duration_ms=duration_ms,
        )

    def _run_code_sync(self, code: str, stdout_buf: io.StringIO, stderr_buf: io.StringIO) -> None:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            exec(code, {"__builtins__": __builtins__})  # noqa: S102
        except SystemExit:
            raise  # re-raise so execute() can catch it
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    async def terminate(self) -> None:
        self._alive = False
        self._memory_usage = 0.0

    def memory_usage_mb(self) -> float:
        return self._memory_usage

    def is_alive(self) -> bool:
        return self._alive
