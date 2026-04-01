"""Wasm dispatch — executor registration and dispatch event building."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WasmExecutor:
    """Lightweight executor record for the wasm pool (no pydantic dependency)."""

    executor_id: str = "wasm-pool"
    channel_type: str = "wasm"
    executor_tags: list[str] = field(default_factory=lambda: ["wasm", "python", "javascript"])
    dispatch_type: str = "wasm"
    metadata: dict[str, Any] = field(default_factory=lambda: {"pool": True, "max_isolates": 64})


def register_wasm_executor(repo: Any) -> WasmExecutor:
    """Register the wasm-pool executor with the repository."""
    executor = WasmExecutor()
    repo.register_executor(executor)
    return executor


async def dispatch_wasm(repo: Any, process_id: str, run_id: str) -> dict[str, Any]:
    """Build and fire a wasm dispatch event."""
    return {
        "process_id": process_id,
        "run_id": run_id,
        "dispatch_type": "wasm",
        "dispatched_at_ms": int(time.time() * 1000),
    }
