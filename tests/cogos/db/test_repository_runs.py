from __future__ import annotations

import pytest

from cogos.db.models import Process, ProcessMode, Run, RunStatus
from cogos.db.sqlite_repository import SqliteBackend
from cogos.db.unified_repository import UnifiedRepository


@pytest.fixture
def repo(tmp_path):
    return UnifiedRepository(SqliteBackend(str(tmp_path)))


def test_complete_run_updates_snapshot_when_provided(repo):
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    run = Run(process=p.id)
    repo.create_run(run)

    result = repo.complete_run(
        run.id,
        status=RunStatus.COMPLETED,
        snapshot={"final_key": "/proc/x/final.json"},
    )
    assert result is True

    got = repo.get_run(run.id)
    assert got is not None
    assert got.status == RunStatus.COMPLETED
    assert got.snapshot == {"final_key": "/proc/x/final.json"}
