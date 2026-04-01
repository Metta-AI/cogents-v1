"""Sandbox pool — concrete IsolatePool using SandboxIsolate."""

from __future__ import annotations

import asyncio

from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.runtime.isolate import WasmIsolate
from wasm_runner.runtime.pool import IsolatePool
from wasm_runner.runtime.sandbox_isolate import SandboxIsolate
from wasm_runner.types import IsolateConfig


class SandboxPool(IsolatePool):
    """Concrete pool of SandboxIsolates with capacity limits."""

    def __init__(self, max_isolates: int = 16) -> None:
        self._max = max_isolates
        self._active: set[WasmIsolate] = set()
        self._lock = asyncio.Lock()

    async def acquire(self, config: IsolateConfig, bridge: CapabilityBridge) -> WasmIsolate:
        async with self._lock:
            if len(self._active) >= self._max:
                raise RuntimeError(
                    f"Pool at capacity ({self._max}) — cannot acquire new isolate"
                )
            isolate = SandboxIsolate()
            await isolate.boot(config, bridge)
            self._active.add(isolate)
            return isolate

    async def release(self, isolate: WasmIsolate) -> None:
        async with self._lock:
            if isolate.is_alive():
                await isolate.terminate()
            self._active.discard(isolate)

    def active_count(self) -> int:
        return len(self._active)

    def capacity(self) -> int:
        return self._max
