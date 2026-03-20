"""CogtainerRuntime — abstract interface for cogent lifecycle and I/O."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CogtainerRuntime(ABC):
    """Abstract base for cogtainer runtimes (local, AWS, Docker, etc.)."""

    @abstractmethod
    def get_repository(self, cogent_name: str) -> Any:
        """Return a database repository for the given cogent."""

    @abstractmethod
    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        """Call the LLM and return a Bedrock-format response."""

    @abstractmethod
    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        """Store a blob and return the storage key."""

    @abstractmethod
    def get_file(self, cogent_name: str, key: str) -> bytes:
        """Retrieve a blob by key."""

    @abstractmethod
    def emit_event(self, cogent_name: str, event: dict) -> None:
        """Route an event from the given cogent."""

    @abstractmethod
    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        """Launch an executor for the given process."""

    @abstractmethod
    def list_cogents(self) -> list[str]:
        """Return names of all cogents managed by this cogtainer."""

    @abstractmethod
    def create_cogent(self, name: str) -> None:
        """Provision a new cogent."""

    @abstractmethod
    def destroy_cogent(self, name: str) -> None:
        """Remove a cogent and all its data."""
