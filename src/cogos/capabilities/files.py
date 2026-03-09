"""File capabilities — read, write, search files in the versioned store."""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.db.repository import Repository
from cogos.files.store import FileStore
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


def read(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Read a file by key and return its active content."""
    key = args.get("key", "")
    if not key:
        return CapabilityResult(content={"error": "key is required"})

    store = FileStore(repo)
    f = store.get(key)
    if f is None:
        return CapabilityResult(content={"error": f"file '{key}' not found"})

    fv = repo.get_active_file_version(f.id)
    if fv is None:
        return CapabilityResult(content={"error": f"no active version for '{key}'"})

    return CapabilityResult(
        content={
            "id": str(f.id),
            "key": f.key,
            "version": fv.version,
            "content": fv.content,
            "read_only": fv.read_only,
            "source": fv.source,
        },
    )


def write(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Write content to a file, creating it or adding a new version."""
    key = args.get("key", "")
    content = args.get("content", "")
    if not key:
        return CapabilityResult(content={"error": "key is required"})

    source = args.get("source", "agent")
    read_only = args.get("read_only", False)
    includes = args.get("includes")

    store = FileStore(repo)
    result = store.upsert(
        key,
        content,
        source=source,
        read_only=read_only,
        includes=includes,
    )

    if result is None:
        return CapabilityResult(content={"key": key, "changed": False})

    from cogos.db.models import File, FileVersion

    if isinstance(result, File):
        return CapabilityResult(
            content={"id": str(result.id), "key": key, "version": 1, "created": True},
        )

    # FileVersion
    return CapabilityResult(
        content={
            "id": str(result.file_id),
            "key": key,
            "version": result.version,
            "created": False,
        },
    )


def search(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Search for files by key prefix."""
    prefix = args.get("prefix")
    limit = args.get("limit", 50)

    store = FileStore(repo)
    files = store.list_files(prefix=prefix, limit=limit)

    return CapabilityResult(
        content=[
            {"id": str(f.id), "key": f.key}
            for f in files
        ],
    )
