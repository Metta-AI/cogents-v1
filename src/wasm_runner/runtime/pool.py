"""Isolate pool — manages multiple Wasm isolates on a single host."""

from __future__ import annotations

from abc import ABC, abstractmethod

from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.runtime.isolate import WasmIsolate
from wasm_runner.types import IsolateConfig


class IsolatePool(ABC):
    """Abstract pool of Wasm isolates with capacity limits."""

    @abstractmethod
    async def acquire(self, config: IsolateConfig, bridge: CapabilityBridge) -> WasmIsolate:
        """Acquire an isolate from the pool. Raises if at capacity."""
        ...

    @abstractmethod
    async def release(self, isolate: WasmIsolate) -> None:
        """Release an isolate back to the pool (terminates it)."""
        ...

    @abstractmethod
    def active_count(self) -> int:
        """Number of currently active isolates."""
        ...

    @abstractmethod
    def capacity(self) -> int:
        """Maximum number of concurrent isolates."""
        ...
