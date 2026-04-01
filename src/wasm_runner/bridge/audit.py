"""Audit logger — records every POSIX-to-capability syscall."""

from __future__ import annotations

from abc import ABC, abstractmethod

from wasm_runner.types import SyscallEvent


class AuditLogger(ABC):
    """Abstract audit logger. Every host function call emits a SyscallEvent."""

    @abstractmethod
    def log(self, event: SyscallEvent) -> None:
        """Record a syscall event."""
        ...

    @abstractmethod
    def events(self) -> list[SyscallEvent]:
        """Return all recorded events (for testing / result collection)."""
        ...
