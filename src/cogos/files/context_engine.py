"""Context engine -- resolves file includes to build full prompt context.

Files in CogOS can declare an ``includes`` list of other file keys. The
context engine recursively resolves those includes, concatenates their
content with section headers, and returns a single string suitable for
injection into an LLM prompt.

Circular includes are detected and reported as errors in the output.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from cogos.files.store import FileStore

if TYPE_CHECKING:
    from cogos.db.models import Process

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

    def generate_full_prompt(self, process: Process) -> str:
        """Build the complete prompt for a process.

        Resolves all attached files (with their includes) and prepends
        them before ``process.content``.  This is the single source of
        truth used by both the executor and the dashboard.
        """
        sections: list[str] = []
        visited: set[str] = set()

        # Resolve each attached file (process.files)
        for fid in process.files or []:
            file = self._store.get_by_id(fid)
            if not file or file.key in visited:
                continue
            visited.add(file.key)
            sections.append(self._resolve_key(file.key, visited=set(visited)))

        # Legacy: single code FK (only if no files list)
        if process.code and not process.files:
            file = self._store.get_by_id(process.code)
            if file and file.key not in visited:
                visited.add(file.key)
                sections.append(self._resolve_key(file.key, visited=set(visited)))

        # Append process.content last
        if process.content:
            sections.append(f"--- content ---\n{process.content}")

        return "\n\n".join(sections) if sections else ""

    def resolve_prompt_tree(self, process: Process) -> list[dict]:
        """Build a structured dependency tree for the process prompt.

        Returns a list of dicts in include-order (deepest deps first):
        ``[{"key": str, "content": str, "is_direct": bool}, ...]``

        Each file appears at most once.  ``is_direct`` is True for files
        explicitly attached to the process (i.e. in ``process.files``).
        The final entry (if ``process.content`` is set) has
        ``key = "<content>"`` and ``is_direct = True``.
        """
        result: list[dict] = []
        seen: set[str] = set()
        direct_keys: set[str] = set()

        # Collect direct file keys
        for fid in process.files or []:
            file = self._store.get_by_id(fid)
            if file:
                direct_keys.add(file.key)

        # Legacy code FK
        if process.code and not process.files:
            file = self._store.get_by_id(process.code)
            if file:
                direct_keys.add(file.key)

        # Resolve each direct file and its includes
        for fid in process.files or []:
            file = self._store.get_by_id(fid)
            if not file or file.key in seen:
                continue
            self._collect_tree(file.key, seen, result, direct_keys)

        if process.code and not process.files:
            file = self._store.get_by_id(process.code)
            if file and file.key not in seen:
                self._collect_tree(file.key, seen, result, direct_keys)

        # Append process.content last
        if process.content:
            result.append({
                "key": "<content>",
                "content": process.content,
                "is_direct": True,
            })

        return result

    def _collect_tree(
        self,
        key: str,
        seen: set[str],
        result: list[dict],
        direct_keys: set[str],
    ) -> None:
        """Recursively collect files in dependency order (deps first)."""
        if key in seen:
            return
        seen.add(key)

        file = self._store.get(key)
        if file is None:
            result.append({"key": key, "content": f"[not found: {key}]", "is_direct": key in direct_keys})
            return

        # Resolve includes first (depth-first)
        for include_key in file.includes:
            self._collect_tree(include_key, seen, result, direct_keys)

        content = self._store.get_content(key) or ""
        result.append({"key": key, "content": content, "is_direct": key in direct_keys})

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
