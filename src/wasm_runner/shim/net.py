"""Network gate — proxied fetch backed by CogOS web_fetch capability."""

from __future__ import annotations

import time

from wasm_runner.bridge.audit import AuditLogger
from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.types import FetchResult, SyscallEvent


class NetworkGate:
    """Proxied network access. All HTTP goes through the capability bridge.

    Direct socket access (TCP/UDP) is denied unconditionally.
    URLs are validated against the bridge's allowlist.
    """

    def __init__(self, bridge: CapabilityBridge, audit: AuditLogger, *, process_id: str = "") -> None:
        self._bridge = bridge
        self._audit = audit
        self._process_id = process_id

    def _emit(self, op: str, args: dict, result: str = "ok") -> None:
        self._audit.log(SyscallEvent(
            op=op, args=args, process_id=self._process_id,
            timestamp_ms=int(time.time() * 1000), result=result,
        ))

    async def fetch(
        self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None,
    ) -> FetchResult:
        try:
            result = await self._bridge.web_fetch(url, method=method, headers=headers, body=body)
        except PermissionError:
            self._emit("fetch", {"url": url, "method": method}, "EPERM")
            raise
        self._emit("fetch", {"url": url, "method": method})
        return result

    async def raw_tcp(self, host: str, port: int) -> None:
        """Always denied."""
        raise PermissionError(f"EPERM: raw TCP not available ({host}:{port})")

    async def raw_udp(self, host: str, port: int) -> None:
        """Always denied."""
        raise PermissionError(f"EPERM: raw UDP not available ({host}:{port})")
