"""Proxy object generation from capability output_schema.

Generates Python classes with methods that route to capability handlers.
For MVP, we use simple callable wrappers rather than full schema-driven generation.
"""

from __future__ import annotations

from typing import Any, Callable


class CapabilityProxy:
    """Base proxy object returned by capability calls.

    Attributes are set dynamically from the result content.
    Methods are bound to capability handlers.
    """

    def __init__(self, content: dict[str, Any] | None = None, methods: dict[str, Callable] | None = None) -> None:
        self._content = content or {}
        self._methods = methods or {}
        for key, value in self._content.items():
            if not key.startswith("_"):
                setattr(self, key, value)

    def __repr__(self) -> str:
        return f"<Proxy {self._content}>"

    def __getattr__(self, name: str) -> Any:
        if name in self._methods:
            return self._methods[name]
        raise AttributeError(f"Proxy has no attribute or method '{name}'")


def make_namespace_proxy(name: str, handler: Callable) -> Callable:
    """Create a simple callable proxy for a capability namespace.

    For the MVP, capabilities are exposed as simple callables:
    files.read(key) -> content
    procs.list() -> [...]
    events.emit(type, payload) -> event_id
    """
    proxy = handler
    proxy.__name__ = name
    return proxy
