"""Context engine -- resolves file includes to build full prompt context.

Files in CogOS can declare an ``includes`` list of other file keys. The
context engine recursively resolves those includes, concatenates their
content with section headers, and returns a single string suitable for
injection into an LLM prompt.

Circular includes are detected and reported as errors in the output.
"""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


class ContextEngine:
    """Resolves file includes into a single concatenated context string."""

    def __init__(self, file_store: FileStore) -> None:
        self._store = file_store

    def resolve(self, key: str) -> str:
        """Resolve a file by *key*, recursively expanding includes.

        Returns the fully assembled context string.
        Raises ``ValueError`` if the root file is not found.
        """
        file = self._store.get(key)
        if file is None:
            raise ValueError(f"File not found: {key}")
        return self._resolve_key(key, visited=set())

    def resolve_by_id(self, file_id: UUID) -> str:
        """Resolve a file by *file_id*, recursively expanding includes.

        Returns the fully assembled context string.
        Raises ``ValueError`` if the root file is not found.
        """
        file = self._store.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File not found: {file_id}")
        return self._resolve_key(file.key, visited=set())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_key(self, key: str, *, visited: set[str]) -> str:
        """Recursively resolve *key* and its includes.

        *visited* tracks keys already seen on the current resolution path
        to detect circular references.
        """
        if key in visited:
            msg = f"[circular include: {key}]"
            logger.warning("Circular include detected: %s", key)
            return msg

        visited.add(key)

        file = self._store.get(key)
        if file is None:
            msg = f"[include not found: {key}]"
            logger.warning("Included file not found: %s", key)
            return msg

        content = self._store.get_content(key) or ""

        # Resolve includes depth-first, prepending them before main content.
        sections: list[str] = []
        for include_key in file.includes:
            section = self._resolve_key(include_key, visited=set(visited))
            sections.append(section)

        # Build the output with a header for the current file.
        parts: list[str] = []

        # Prepend resolved includes.
        if sections:
            parts.extend(sections)

        # Main content with a section header.
        header = f"--- {key} ---"
        parts.append(f"{header}\n{content}")

        return "\n\n".join(parts)
