"""Executor registry API — register, heartbeat, list, and manage channel executors."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from dashboard.db import get_repo

router = APIRouter(tags=["executors"])


# ── Request / Response Models ─────────────────────────────────


class RegisterRequest(BaseModel):
    executor_id: str
    channel_type: str = "claude-code"
    capabilities: list[str] = []
    metadata: dict[str, Any] = {}


class RegisterResponse(BaseModel):
    executor_id: str
    heartbeat_interval_s: int = 30
    status: str = "registered"


class HeartbeatRequest(BaseModel):
    status: str = "idle"  # "idle" | "busy"
    current_run_id: str | None = None
    resource_usage: dict[str, Any] | None = None


class HeartbeatResponse(BaseModel):
    ok: bool


class RunCompleteRequest(BaseModel):
    executor_id: str
    status: str  # "completed" | "failed" | "timeout"
    output: dict[str, Any] | None = None
    tokens_used: dict[str, int] | None = None
    duration_ms: int | None = None
    error: str | None = None


class ExecutorItem(BaseModel):
    id: str
    executor_id: str
    channel_type: str = "claude-code"
    capabilities: list[str] = []
    metadata: dict[str, Any] = {}
    status: str = "idle"
    current_run_id: str | None = None
    last_heartbeat_at: str | None = None
    registered_at: str | None = None


class ExecutorsResponse(BaseModel):
    cogent_name: str
    count: int = 0
    executors: list[ExecutorItem] = []


# ── Token Validation ──────────────────────────────────────────


def _validate_executor_token(repo, authorization: str | None) -> bool:
    """Validate a Bearer token against stored executor token hashes."""
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    token = parts[1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return repo.get_executor_token_by_hash(token_hash) is not None


# ── Endpoints ─────────────────────────────────────────────────


@router.get("/executors", response_model=ExecutorsResponse)
def list_executors(name: str, status: str | None = None):
    """List all registered executors."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()
    filter_status = ExecutorStatus(status) if status else None
    executors = repo.list_executors(status=filter_status)
    items = [
        ExecutorItem(
            id=str(e.id),
            executor_id=e.executor_id,
            channel_type=e.channel_type,
            capabilities=e.capabilities,
            metadata=e.metadata,
            status=e.status.value,
            current_run_id=str(e.current_run_id) if e.current_run_id else None,
            last_heartbeat_at=str(e.last_heartbeat_at) if e.last_heartbeat_at else None,
            registered_at=str(e.registered_at) if e.registered_at else None,
        )
        for e in executors
    ]
    return ExecutorsResponse(cogent_name=name, count=len(items), executors=items)


@router.get("/executors/{executor_id}", response_model=ExecutorItem)
def get_executor(name: str, executor_id: str):
    """Get a single executor by its executor_id."""
    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    return ExecutorItem(
        id=str(e.id),
        executor_id=e.executor_id,
        channel_type=e.channel_type,
        capabilities=e.capabilities,
        metadata=e.metadata,
        status=e.status.value,
        current_run_id=str(e.current_run_id) if e.current_run_id else None,
        last_heartbeat_at=str(e.last_heartbeat_at) if e.last_heartbeat_at else None,
        registered_at=str(e.registered_at) if e.registered_at else None,
    )


@router.post("/executors/register", response_model=RegisterResponse)
def register_executor(
    name: str,
    body: RegisterRequest,
    authorization: str | None = Header(None),
):
    """Register a channel executor with the cogent."""
    from cogos.db.models import Executor

    repo = get_repo()
    if not _validate_executor_token(repo, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing executor token")

    executor = Executor(
        executor_id=body.executor_id,
        channel_type=body.channel_type,
        capabilities=body.capabilities,
        metadata=body.metadata,
    )
    repo.register_executor(executor)

    return RegisterResponse(
        executor_id=body.executor_id,
        heartbeat_interval_s=30,
        status="registered",
    )


@router.post("/executors/{executor_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    name: str,
    executor_id: str,
    body: HeartbeatRequest,
    authorization: str | None = Header(None),
):
    """Send a heartbeat from an executor."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()
    if not _validate_executor_token(repo, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing executor token")

    status = ExecutorStatus(body.status) if body.status in ("idle", "busy") else ExecutorStatus.IDLE
    run_id = UUID(body.current_run_id) if body.current_run_id else None

    found = repo.heartbeat_executor(
        executor_id,
        status=status,
        current_run_id=run_id,
        resource_usage=body.resource_usage,
    )
    if not found:
        raise HTTPException(status_code=404, detail="executor not found")

    return HeartbeatResponse(ok=True)


@router.post("/executors/{executor_id}/drain")
def drain_executor(name: str, executor_id: str):
    """Stop dispatching to an executor (mark it stale so it drains)."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    repo.update_executor_status(executor_id, ExecutorStatus.STALE)
    return {"ok": True, "executor_id": executor_id, "status": "stale"}


@router.delete("/executors/{executor_id}")
def remove_executor(name: str, executor_id: str):
    """Remove an executor from the registry."""
    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    repo.delete_executor(executor_id)
    return {"ok": True, "executor_id": executor_id}


@router.post("/runs/{run_id}/complete")
def complete_run(
    name: str,
    run_id: str,
    body: RunCompleteRequest,
    authorization: str | None = Header(None),
):
    """Report run completion from a channel executor."""
    from cogos.db.models import ExecutorStatus, RunStatus

    repo = get_repo()
    if not _validate_executor_token(repo, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing executor token")

    run_uuid = UUID(run_id)
    status_map = {
        "completed": RunStatus.COMPLETED,
        "failed": RunStatus.FAILED,
        "timeout": RunStatus.TIMEOUT,
    }
    run_status = status_map.get(body.status, RunStatus.FAILED)

    tokens_in = (body.tokens_used or {}).get("input", 0)
    tokens_out = (body.tokens_used or {}).get("output", 0)

    repo.complete_run(
        run_uuid,
        status=run_status,
        error=body.error,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=body.duration_ms,
    )

    # Release executor back to idle
    repo.update_executor_status(body.executor_id, ExecutorStatus.IDLE)

    return {"ok": True, "run_id": run_id, "status": body.status}
