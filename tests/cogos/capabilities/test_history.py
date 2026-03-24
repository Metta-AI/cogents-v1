"""Tests for HistoryCapability."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.history import (
    HistoryCapability,
    HistoryError,
    ProcessHistory,
    _resolve_since,
)
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.db.models.run import Run, RunStatus


@pytest.fixture
def repo():
    r = MagicMock()
    r.reboot_epoch = 0
    return r


@pytest.fixture
def pid():
    return uuid4()


def _make_proc(name="worker-1"):
    return Process(name=name, mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)


def _make_run(process_id=None, status=RunStatus.COMPLETED, error=None, duration_ms=100):
    r = Run(process=process_id or uuid4(), status=status, duration_ms=duration_ms, error=error)
    r.created_at = "2026-03-17T12:00:00"  # type: ignore[assignment]
    return r


class TestHistoryProcess:
    def test_process_by_name(self, repo, pid):
        proc = _make_proc()
        repo.get_process_by_name.return_value = proc
        cap = HistoryCapability(repo, pid)
        h = cap.process(name="worker-1")
        assert isinstance(h, ProcessHistory)

    def test_process_by_id(self, repo, pid):
        proc = _make_proc()
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        h = cap.process(id=str(proc.id))
        assert isinstance(h, ProcessHistory)

    def test_process_not_found(self, repo, pid):
        repo.get_process_by_name.return_value = None
        cap = HistoryCapability(repo, pid)
        result = cap.process(name="missing")
        assert isinstance(result, HistoryError)
        assert "not found" in result.error

    def test_process_no_args(self, repo, pid):
        cap = HistoryCapability(repo, pid)
        result = cap.process()
        assert isinstance(result, HistoryError)

    def test_process_runs(self, repo, pid):
        proc = _make_proc()
        repo.get_process_by_name.return_value = proc
        run = _make_run(process_id=proc.id)
        repo.list_runs.return_value = [run]
        repo.get_process.return_value = proc

        cap = HistoryCapability(repo, pid)
        h = cap.process(name="worker-1")
        assert not isinstance(h, HistoryError)
        runs = h.runs(limit=5)
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].process_name == "worker-1"

    def test_process_files(self, repo, pid):
        proc = _make_proc()
        repo.get_process_by_name.return_value = proc
        repo.list_file_mutations.return_value = [
            {"key": "src/main.py", "version": 2, "created_at": "2026-03-17T12:00:00Z"}
        ]
        cap = HistoryCapability(repo, pid)
        h = cap.process(name="worker-1")
        assert not isinstance(h, HistoryError)
        files = h.files(run_id=str(uuid4()))
        assert len(files) == 1
        assert files[0].key == "src/main.py"
        assert files[0].version == 2

    def test_process_scope_restricts_access(self, repo, pid):
        other_proc = _make_proc("secret")
        repo.get_process_by_name.return_value = other_proc
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(process_ids=[str(pid)])
        result = scoped.process(name="secret")
        assert isinstance(result, HistoryError)
        assert "denied" in result.error

    def test_process_scope_allows_own(self, repo, pid):
        proc = _make_proc()
        repo.get_process_by_name.return_value = proc
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(process_ids=[str(proc.id)])
        h = scoped.process(name="worker-1")
        assert isinstance(h, ProcessHistory)


class TestHistoryQuery:
    def test_query_all(self, repo, pid):
        proc = _make_proc()
        run = _make_run(process_id=proc.id, status=RunStatus.FAILED, error="boom")
        repo.list_runs.return_value = [run]
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        results = cap.query(status="failed")
        assert len(results) == 1
        assert results[0].error == "boom"
        assert results[0].process_name == "worker-1"

    def test_query_with_process_glob(self, repo, pid):
        proc = _make_proc()
        run = _make_run(process_id=proc.id, status=RunStatus.FAILED)
        repo.list_runs_by_process_glob.return_value = [run]
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        results = cap.query(process_name="worker-*")
        assert len(results) == 1
        repo.list_runs_by_process_glob.assert_called_once()

    def test_query_scope_filters_pids(self, repo, pid):
        allowed_proc = _make_proc("allowed")
        blocked_proc = _make_proc("blocked")
        run1 = _make_run(process_id=allowed_proc.id)
        run2 = _make_run(process_id=blocked_proc.id)
        repo.list_runs.return_value = [run1, run2]
        repo.get_process.side_effect = lambda pid: allowed_proc if pid == allowed_proc.id else blocked_proc
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(process_ids=[str(allowed_proc.id)])
        results = scoped.query()
        assert len(results) == 1
        assert results[0].process_name == "allowed"

    def test_failed_shorthand(self, repo, pid):
        repo.list_runs.return_value = []
        cap = HistoryCapability(repo, pid)
        results = cap.failed()
        assert results == []
        # Verify it passed status="failed"
        repo.list_runs.assert_called_once()
        call_kwargs = repo.list_runs.call_args[1]
        assert call_kwargs["status"] == "failed"

    def test_query_denied_without_op(self, repo, pid):
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(ops=["process"])
        with pytest.raises(PermissionError):
            scoped.query()

    def test_process_denied_without_op(self, repo, pid):
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(ops=["query"])
        with pytest.raises(PermissionError):
            scoped.process(name="worker")


class TestResolveSince:
    def test_relative_minutes(self):
        result = _resolve_since("5m")
        # Should be a valid ISO timestamp
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None
        # Should be roughly 5 minutes ago
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        assert 290 < diff < 310  # 5 min +/- 10s

    def test_relative_seconds(self):
        result = _resolve_since("30s")
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result)
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        assert 25 < diff < 35

    def test_relative_hours(self):
        result = _resolve_since("1h")
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result)
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        assert 3590 < diff < 3610

    def test_relative_days(self):
        result = _resolve_since("2d")
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result)
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        assert 172790 < diff < 172810

    def test_iso_passthrough(self):
        ts = "2026-03-17T12:00:00+00:00"
        assert _resolve_since(ts) == ts

    def test_query_resolves_relative_since(self, repo, pid):
        """query() converts relative since values before passing to repo."""
        repo.list_runs.return_value = []
        cap = HistoryCapability(repo, pid)
        cap.query(status="failed", since="5m")
        call_kwargs = repo.list_runs.call_args[1]
        # Should be an ISO timestamp, not "5m"
        assert call_kwargs["since"] != "5m"
        from datetime import datetime
        datetime.fromisoformat(call_kwargs["since"])  # should not raise


class TestNarrowing:
    def test_narrow_ops_intersection(self, repo, pid):
        cap = HistoryCapability(repo, pid)
        scoped1 = cap.scope(ops=["query", "process"])
        scoped2 = scoped1.scope(ops=["process"])
        # Should only have "process"
        with pytest.raises(PermissionError):
            scoped2.query()

    def test_narrow_process_ids_intersection(self, repo, pid):
        pid1, pid2, pid3 = str(uuid4()), str(uuid4()), str(uuid4())
        cap = HistoryCapability(repo, pid)
        scoped1 = cap.scope(process_ids=[pid1, pid2])
        scoped2 = scoped1.scope(process_ids=[pid2, pid3])
        # Only pid2 should remain
        assert scoped2._scope["process_ids"] == sorted([pid2])
