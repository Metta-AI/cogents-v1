"""Process capabilities — list, get, and spawn processes."""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.db.repository import Repository
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


def _process_summary(p: Process) -> dict:
    """Return a serialisable summary of a process."""
    return {
        "id": str(p.id),
        "name": p.name,
        "mode": p.mode.value,
        "status": p.status.value,
        "priority": p.priority,
        "runner": p.runner,
        "parent_process": str(p.parent_process) if p.parent_process else None,
    }


def list_procs(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """List processes, optionally filtering by status."""
    status_str = args.get("status")
    limit = args.get("limit", 200)

    status = ProcessStatus(status_str) if status_str else None
    processes = repo.list_processes(status=status, limit=limit)

    return CapabilityResult(
        content=[_process_summary(p) for p in processes],
    )


def get_proc(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Get details of a process by name or ID."""
    name = args.get("name")
    proc_id = args.get("id")

    if proc_id:
        proc = repo.get_process(UUID(proc_id))
    elif name:
        proc = repo.get_process_by_name(name)
    else:
        return CapabilityResult(content={"error": "name or id is required"})

    if proc is None:
        return CapabilityResult(content={"error": "process not found"})

    return CapabilityResult(
        content={
            "id": str(proc.id),
            "name": proc.name,
            "mode": proc.mode.value,
            "status": proc.status.value,
            "priority": proc.priority,
            "runner": proc.runner,
            "content": proc.content,
            "code": str(proc.code) if proc.code else None,
            "parent_process": str(proc.parent_process) if proc.parent_process else None,
            "preemptible": proc.preemptible,
            "model": proc.model,
            "max_retries": proc.max_retries,
            "retry_count": proc.retry_count,
            "created_at": proc.created_at.isoformat() if proc.created_at else None,
            "updated_at": proc.updated_at.isoformat() if proc.updated_at else None,
        },
    )


def spawn(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Spawn a child one_shot process under the calling process."""
    name = args.get("name", "")
    if not name:
        return CapabilityResult(content={"error": "name is required"})

    content = args.get("content", "")
    code = args.get("code")
    priority = args.get("priority", 0.0)
    runner = args.get("runner", "lambda")
    model = args.get("model")

    child = Process(
        name=name,
        mode=ProcessMode.ONE_SHOT,
        content=content,
        code=UUID(code) if code else None,
        priority=priority,
        runner=runner,
        status=ProcessStatus.RUNNABLE,
        parent_process=process_id,
        model=model,
    )

    child_id = repo.upsert_process(child)

    return CapabilityResult(
        content={
            "id": str(child_id),
            "name": name,
            "status": ProcessStatus.RUNNABLE.value,
            "parent_process": str(process_id),
        },
    )
