"""Tests for scheduler idle timeout reaping."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_reap_idle_daemon(tmp_path):
    """Daemon with idle_timeout_ms whose last run completed long ago gets reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="idle-child",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
        idle_timeout_ms=60_000,  # 1 minute
    )
    repo.upsert_process(proc)

    # Create a completed run from 2 minutes ago
    run = Run(process=proc.id, status=RunStatus.COMPLETED)
    run_id = repo.create_run(run)
    repo.complete_run(run_id, status=RunStatus.COMPLETED, duration_ms=100)

    # Backdate the run's created_at
    r = repo.get_run(run_id)
    r.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    repo._runs[run_id] = r

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 1
    assert repo.get_process(proc.id).status == ProcessStatus.COMPLETED


def test_no_reap_active_daemon(tmp_path):
    """Daemon with recent activity should NOT be reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="active-child",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
        idle_timeout_ms=300_000,  # 5 minutes
    )
    repo.upsert_process(proc)

    run = Run(process=proc.id, status=RunStatus.COMPLETED)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.COMPLETED, duration_ms=100)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
    assert repo.get_process(proc.id).status == ProcessStatus.WAITING


def test_no_reap_without_idle_timeout(tmp_path):
    """Daemon without idle_timeout_ms should never be reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="permanent",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(proc)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
