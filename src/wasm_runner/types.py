"""Shared types for the Wasm Runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SyscallEvent:
    """Audit record for a single POSIX-to-capability call."""

    op: str  # "fs.readFile", "fetch", "process.spawn", ...
    args: dict[str, Any]
    process_id: str
    timestamp_ms: int
    result: str  # "ok" | "EPERM" | "error"


@dataclass(frozen=True)
class IsolateConfig:
    """Configuration for booting a single Wasm isolate."""

    process_id: str
    run_id: str
    memory_limit_mb: int = 128
    timeout_s: float = 30.0
    max_child_isolates: int = 4
    env: dict[str, str] = field(default_factory=dict)
    file_prefix: str = "workspace/"  # CogOS file key prefix


@dataclass(frozen=True)
class IsolateResult:
    """Result of executing code in a Wasm isolate."""

    exit_code: int
    stdout: str
    stderr: str
    syscall_log: list[SyscallEvent]
    memory_peak_mb: float
    duration_ms: float


@dataclass(frozen=True)
class StatResult:
    """Synthesized stat result for virtual filesystem."""

    size: int
    is_file: bool
    is_directory: bool


@dataclass(frozen=True)
class FetchResult:
    """Result of a proxied fetch call."""

    status: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class SpawnResult:
    """Result of a child process spawn."""

    exit_code: int
    stdout: str
    stderr: str


# Sentinel for ephemeral /tmp paths
EPHEMERAL = "__EPHEMERAL__"
