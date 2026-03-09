from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Process, ProcessMode, ProcessStatus
from dashboard.db import get_cogos_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-processes"])


# ── Response / request models ──────────────────────────────────────


class ProcessSummary(BaseModel):
    id: str
    name: str
    mode: str
    status: str
    priority: float
    runner: str
    model: str | None = None
    preemptible: bool = False
    retry_count: int = 0
    max_retries: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ProcessDetail(BaseModel):
    id: str
    name: str
    mode: str
    content: str
    code: str | None = None
    priority: float
    resources: list[str]
    runner: str
    status: str
    runnable_since: str | None = None
    parent_process: str | None = None
    preemptible: bool
    model: str | None = None
    model_constraints: dict
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int
    retry_count: int
    retry_backoff_ms: int | None = None
    clear_context: bool
    metadata: dict
    created_at: str | None = None
    updated_at: str | None = None


class ProcessCreate(BaseModel):
    name: str
    mode: str = "one_shot"
    content: str = ""
    priority: float = 0.0
    runner: str = "lambda"
    status: str = "waiting"
    model: str | None = None
    model_constraints: dict | None = None
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int = 0
    preemptible: bool = False
    clear_context: bool = False
    metadata: dict | None = None


class ProcessUpdate(BaseModel):
    name: str | None = None
    mode: str | None = None
    content: str | None = None
    priority: float | None = None
    runner: str | None = None
    status: str | None = None
    model: str | None = None
    model_constraints: dict | None = None
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int | None = None
    preemptible: bool | None = None
    clear_context: bool | None = None
    metadata: dict | None = None


class ProcessesResponse(BaseModel):
    cogent_name: str
    count: int
    processes: list[ProcessDetail]


# ── Helpers ─────────────────────────────────────────────────────────


def _summary(p: Process) -> ProcessSummary:
    return ProcessSummary(
        id=str(p.id),
        name=p.name,
        mode=p.mode.value,
        status=p.status.value,
        priority=p.priority,
        runner=p.runner,
        model=p.model,
        preemptible=p.preemptible,
        retry_count=p.retry_count,
        max_retries=p.max_retries,
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


def _detail(p: Process) -> ProcessDetail:
    return ProcessDetail(
        id=str(p.id),
        name=p.name,
        mode=p.mode.value,
        content=p.content,
        code=str(p.code) if p.code else None,
        priority=p.priority,
        resources=[str(r) for r in p.resources],
        runner=p.runner,
        status=p.status.value,
        runnable_since=str(p.runnable_since) if p.runnable_since else None,
        parent_process=str(p.parent_process) if p.parent_process else None,
        preemptible=p.preemptible,
        model=p.model,
        model_constraints=p.model_constraints,
        return_schema=p.return_schema,
        max_duration_ms=p.max_duration_ms,
        max_retries=p.max_retries,
        retry_count=p.retry_count,
        retry_backoff_ms=p.retry_backoff_ms,
        clear_context=p.clear_context,
        metadata=p.metadata,
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/processes", response_model=ProcessesResponse)
def list_processes(
    name: str,
    status: str | None = Query(None, description="Filter by process status"),
) -> ProcessesResponse:
    repo = get_cogos_repo()
    ps = ProcessStatus(status) if status else None
    procs = repo.list_processes(status=ps)

    # Annotate with run counts
    all_runs = repo.list_runs(limit=10000)
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    windows = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    run_counts: dict[str, dict[str, dict[str, int]]] = {}
    for r in all_runs:
        pid = str(r.process)
        if pid not in run_counts:
            run_counts[pid] = {k: {"runs": 0, "failed": 0} for k in windows}
        run_time = r.created_at or r.completed_at
        is_failed = r.status and r.status.value in ("failed", "timeout")
        if run_time:
            age = now - run_time
            for label, window in windows.items():
                if age <= window:
                    run_counts[pid][label]["runs"] += 1
                    if is_failed:
                        run_counts[pid][label]["failed"] += 1

    details = [_detail(p) for p in procs]

    return ProcessesResponse(cogent_name=name, count=len(details), processes=details)


@router.get("/processes/{process_id}")
def get_process(name: str, process_id: str) -> dict:
    repo = get_cogos_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    runs = repo.list_runs(process_id=p.id, limit=50)
    run_list = [
        {
            "id": str(r.id),
            "status": r.status.value,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "cost_usd": float(r.cost_usd),
            "duration_ms": r.duration_ms,
            "error": r.error,
            "result": r.result,
            "created_at": str(r.created_at) if r.created_at else None,
            "completed_at": str(r.completed_at) if r.completed_at else None,
        }
        for r in runs
    ]
    return {"process": _detail(p).model_dump(), "runs": run_list}


@router.post("/processes", response_model=ProcessDetail)
def create_process(name: str, body: ProcessCreate) -> ProcessDetail:
    repo = get_cogos_repo()
    p = Process(
        name=body.name,
        mode=ProcessMode(body.mode),
        content=body.content,
        priority=body.priority,
        runner=body.runner,
        status=ProcessStatus(body.status),
        model=body.model,
        model_constraints=body.model_constraints or {},
        return_schema=body.return_schema,
        max_duration_ms=body.max_duration_ms,
        max_retries=body.max_retries,
        preemptible=body.preemptible,
        clear_context=body.clear_context,
        metadata=body.metadata or {},
    )
    repo.upsert_process(p)
    return _detail(p)


@router.put("/processes/{process_id}", response_model=ProcessDetail)
def update_process(name: str, process_id: str, body: ProcessUpdate) -> ProcessDetail:
    repo = get_cogos_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    if body.name is not None:
        p.name = body.name
    if body.mode is not None:
        p.mode = ProcessMode(body.mode)
    if body.content is not None:
        p.content = body.content
    if body.priority is not None:
        p.priority = body.priority
    if body.runner is not None:
        p.runner = body.runner
    if body.status is not None:
        p.status = ProcessStatus(body.status)
    if body.model is not None:
        p.model = body.model
    if body.model_constraints is not None:
        p.model_constraints = body.model_constraints
    if body.return_schema is not None:
        p.return_schema = body.return_schema
    if body.max_duration_ms is not None:
        p.max_duration_ms = body.max_duration_ms
    if body.max_retries is not None:
        p.max_retries = body.max_retries
    if body.preemptible is not None:
        p.preemptible = body.preemptible
    if body.clear_context is not None:
        p.clear_context = body.clear_context
    if body.metadata is not None:
        p.metadata = body.metadata

    repo.upsert_process(p)
    return _detail(p)


@router.delete("/processes/{process_id}")
def delete_process(name: str, process_id: str) -> dict:
    repo = get_cogos_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")
    repo.execute(
        "DELETE FROM cogos_process WHERE id = :id",
        {"id": UUID(process_id)},
    )
    return {"deleted": True, "id": process_id}
