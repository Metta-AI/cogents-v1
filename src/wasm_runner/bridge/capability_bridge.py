"""Capability bridge — maps POSIX-shaped ops to CogOS capability API calls."""

from __future__ import annotations

from abc import ABC, abstractmethod

from wasm_runner.types import FetchResult, SpawnResult


class CapabilityBridge(ABC):
    """Abstract bridge between POSIX shim and CogOS capabilities.

    Every method maps to a CogOS capability call, authenticated by process_id.
    Implementations handle HTTP transport, scope enforcement is server-side.
    """

    @abstractmethod
    async def files_read(self, key: str) -> bytes:
        """Read a file by CogOS key. Raises PermissionError if denied."""
        ...

    @abstractmethod
    async def files_write(self, key: str, data: bytes) -> None:
        """Write a file by CogOS key. Raises PermissionError if denied."""
        ...

    @abstractmethod
    async def files_search(self, prefix: str) -> list[str]:
        """List file keys matching prefix. Raises PermissionError if denied."""
        ...

    @abstractmethod
    async def files_delete(self, key: str) -> None:
        """Delete a file by CogOS key. Raises PermissionError if denied."""
        ...

    @abstractmethod
    async def web_fetch(
        self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None,
    ) -> FetchResult:
        """Fetch a URL. Raises PermissionError if URL is denied."""
        ...

    @abstractmethod
    async def process_spawn(self, command: str, args: list[str]) -> SpawnResult:
        """Spawn a child process/sub-isolate. Raises PermissionError if denied."""
        ...

    @abstractmethod
    async def channel_send(self, channel: str, message: str) -> None:
        """Send a message to a CogOS channel."""
        ...
