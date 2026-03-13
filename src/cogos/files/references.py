"""Helpers for extracting file references from file content."""

from __future__ import annotations

import re

_FILE_REFERENCE_RE = re.compile(r"@\{([^}\r\n]+)\}")


def extract_file_references(content: str, *, exclude_key: str | None = None) -> list[str]:
    """Extract unique file keys referenced with ``@{file-key}`` syntax."""
    seen: set[str] = set()
    refs: list[str] = []
    for match in _FILE_REFERENCE_RE.finditer(content or ""):
        key = match.group(1).strip()
        if not key or key == exclude_key or key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs


def merge_file_references(
    content: str,
    includes: list[str] | None = None,
    *,
    exclude_key: str | None = None,
) -> list[str]:
    """Merge explicit includes with content references, preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for key in [*(includes or []), *extract_file_references(content, exclude_key=exclude_key)]:
        cleaned = key.strip()
        if not cleaned or cleaned == exclude_key or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged
