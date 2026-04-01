"""Wasm isolate — single isolate lifecycle management."""

from __future__ import annotations

from abc import ABC, abstractmethod

from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.types import IsolateConfig, IsolateResult


class WasmIsolate(ABC):
    """Abstract Wasm isolate — boots, executes code, and terminates."""

    @abstractmethod
    async def boot(self, config: IsolateConfig, bridge: CapabilityBridge) -> None:
        """Initialize the isolate with config and capability bridge."""
        ...

    @abstractmethod
    async def execute(self, code: str, entrypoint: str = "main") -> IsolateResult:
        """Execute code in the isolate. Returns result with stdout/stderr/syscall log."""
        ...

    @abstractmethod
    async def terminate(self) -> None:
        """Destroy the isolate and release resources. Idempotent."""
        ...

    @abstractmethod
    def memory_usage_mb(self) -> float:
        """Current memory usage in MB."""
        ...

    @abstractmethod
    def is_alive(self) -> bool:
        """Whether the isolate is still running."""
        ...
