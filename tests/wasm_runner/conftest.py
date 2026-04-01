"""Shared fixtures for Wasm Runner tests.

All fakes are in-memory — no real Wasm, no network, no database.
"""

from __future__ import annotations

import pytest

from wasm_runner.bridge.audit import AuditLogger
from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.types import (
    FetchResult,
    IsolateConfig,
    SpawnResult,
    SyscallEvent,
)


# ── Fake Capability Bridge ──────────────────────────────────────


class FakeBridge(CapabilityBridge):
    """In-memory bridge that records all calls and returns canned data."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.fetch_responses: dict[str, FetchResult] = {}
        self.spawn_results: list[SpawnResult] = []
        self.sent_messages: list[tuple[str, str]] = []
        self.call_log: list[tuple[str, dict]] = []
        # Scope controls for testing
        self.allowed_prefixes: list[str] | None = None  # None = all allowed
        self.allowed_ops: set[str] | None = None  # None = all allowed
        self.allowed_urls: set[str] | None = None  # None = all allowed
        self.deny_all: bool = False

    def _check_prefix(self, key: str) -> None:
        if self.deny_all:
            raise PermissionError(f"EPERM: access denied for {key!r}")
        if self.allowed_prefixes is not None:
            if not any(key.startswith(p) for p in self.allowed_prefixes):
                raise PermissionError(f"Key {key!r} outside allowed prefixes")

    def _check_op(self, op: str) -> None:
        if self.deny_all:
            raise PermissionError(f"EPERM: operation {op!r} denied")
        if self.allowed_ops is not None and op not in self.allowed_ops:
            raise PermissionError(f"Operation {op!r} not permitted")

    async def files_read(self, key: str) -> bytes:
        self.call_log.append(("files_read", {"key": key}))
        self._check_op("read")
        self._check_prefix(key)
        if key not in self.files:
            raise FileNotFoundError(f"File not found: {key}")
        return self.files[key]

    async def files_write(self, key: str, data: bytes) -> None:
        self.call_log.append(("files_write", {"key": key, "data_len": len(data)}))
        self._check_op("write")
        self._check_prefix(key)
        self.files[key] = data

    async def files_search(self, prefix: str) -> list[str]:
        self.call_log.append(("files_search", {"prefix": prefix}))
        self._check_op("search")
        self._check_prefix(prefix)
        return [k for k in sorted(self.files) if k.startswith(prefix)]

    async def files_delete(self, key: str) -> None:
        self.call_log.append(("files_delete", {"key": key}))
        self._check_op("write")
        self._check_prefix(key)
        if key in self.files:
            del self.files[key]
        self.deleted_keys.append(key)

    async def web_fetch(
        self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None,
    ) -> FetchResult:
        self.call_log.append(("web_fetch", {"url": url, "method": method}))
        if self.allowed_urls is not None and url not in self.allowed_urls:
            raise PermissionError(f"EPERM: URL {url!r} not in allowlist")
        if url in self.fetch_responses:
            return self.fetch_responses[url]
        return FetchResult(status=200, body=b"OK", headers={})

    async def process_spawn(self, command: str, args: list[str]) -> SpawnResult:
        self.call_log.append(("process_spawn", {"command": command, "args": args}))
        if self.spawn_results:
            return self.spawn_results.pop(0)
        return SpawnResult(exit_code=0, stdout="", stderr="")

    async def channel_send(self, channel: str, message: str) -> None:
        self.call_log.append(("channel_send", {"channel": channel, "message": message}))
        self.sent_messages.append((channel, message))


# ── Fake Audit Logger ───────────────────────────────────────────


class FakeAuditLogger(AuditLogger):
    """Collects SyscallEvents in a list for assertion."""

    def __init__(self) -> None:
        self._events: list[SyscallEvent] = []

    def log(self, event: SyscallEvent) -> None:
        self._events.append(event)

    def events(self) -> list[SyscallEvent]:
        return list(self._events)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def audit() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def isolate_config() -> IsolateConfig:
    return IsolateConfig(
        process_id="proc-001",
        run_id="run-001",
        memory_limit_mb=128,
        timeout_s=30.0,
        max_child_isolates=4,
        env={"HOME": "/home/agent", "USER": "agent"},
        file_prefix="workspace/",
    )
