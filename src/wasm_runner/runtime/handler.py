"""Wasm runner handler — Lambda/local entry point for executing a process in a Wasm isolate."""

from __future__ import annotations

from typing import Any


async def handle_wasm_dispatch(event: dict[str, Any]) -> dict[str, Any]:
    """Handle a wasm dispatch event.

    Receives a dispatch event (process_id, run_id, etc.), boots an isolate,
    executes the process code, and returns the result.
    """
    raise NotImplementedError
