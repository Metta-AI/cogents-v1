"""Child process shim — exec/spawn backed by CogOS procs capability."""

from __future__ import annotations

import time

from wasm_runner.bridge.audit import AuditLogger
from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.types import IsolateConfig, SpawnResult, SyscallEvent


class ChildProcessShim:
    """Allows the isolate to spawn sub-isolates up to a cap.

    exec() translates to bridge.process_spawn(). The number of
    children is tracked and capped at config.max_child_isolates.
    """

    def __init__(self, bridge: CapabilityBridge, audit: AuditLogger, config: IsolateConfig) -> None:
        self._bridge = bridge
        self._audit = audit
        self._config = config
        self._child_count = 0

    def _emit(self, op: str, args: dict, result: str = "ok") -> None:
        self._audit.log(SyscallEvent(
            op=op, args=args, process_id=self._config.process_id,
            timestamp_ms=int(time.time() * 1000), result=result,
        ))

    async def exec(self, command: str, args: list[str] | None = None) -> SpawnResult:
        if self._child_count >= self._config.max_child_isolates:
            self._emit("process.exec", {"command": command}, "EPERM")
            raise PermissionError(
                f"EPERM: child isolate cap reached ({self._config.max_child_isolates})"
            )
        args = args or []
        result = await self._bridge.process_spawn(command, args)
        self._child_count += 1
        self._emit("process.exec", {"command": command, "args": args})
        return result

    @property
    def child_count(self) -> int:
        return self._child_count
