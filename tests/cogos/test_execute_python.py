"""Tests for direct Python execution (content_type=python)."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.db.models.process import ContentType
from cogos.executor.handler import ExecutorConfig, execute_python
from cogos.runtime.local import run_and_complete


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _make_run(repo: LocalRepository, process: Process) -> Run:
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    return run


def test_execute_python_basic(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="py-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="result = 1 + 2",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = ExecutorConfig(max_turns=1)

    result = execute_python(process, {"payload": {"x": 42}}, run, config, repo)

    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.result is not None
    assert result.snapshot["content_type"] == "python"
    assert result.snapshot["resumed"] is False


def test_execute_python_receives_payload(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="py-payload",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="result = payload['x'] * 2",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    result = execute_python(
        process, {"payload": {"x": 5}}, run, ExecutorConfig(), repo
    )

    assert result.scope_log is not None


def test_execute_python_receives_event(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="py-event",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="got_event = 'payload' in event",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    result = execute_python(
        process, {"payload": {"msg": "hi"}}, run, ExecutorConfig(), repo
    )

    assert result.tokens_in == 0


def test_execute_python_empty_content_raises(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="py-empty",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    try:
        execute_python(process, {}, run, ExecutorConfig(), repo)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "empty" in str(e).lower()


def test_execute_python_syntax_error_propagates(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="py-syntax",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="def broken(:",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    try:
        execute_python(process, {}, run, ExecutorConfig(), repo)
        assert False, "Should have raised"
    except Exception:
        pass  # SandboxExecutor wraps syntax errors


def test_run_and_complete_routes_python(tmp_path):
    """run_and_complete auto-selects execute_python for content_type=PYTHON."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-routed",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="x = 42",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    result = run_and_complete(
        process,
        {"payload": {}},
        run,
        ExecutorConfig(),
        repo,
    )

    stored = repo.get_run(result.id)
    assert stored.status == RunStatus.COMPLETED
    assert stored.snapshot["content_type"] == "python"
    assert repo.get_process(process.id).status == ProcessStatus.COMPLETED


def test_run_and_complete_python_runtime_error_captured_in_output(tmp_path):
    """Sandbox captures exceptions as output, so the run still completes."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-err",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="raise RuntimeError('boom')",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    run_and_complete(
        process,
        {"payload": {}},
        run,
        ExecutorConfig(),
        repo,
    )

    stored = repo.get_run(run.id)
    # Sandbox catches exceptions and returns traceback as output
    assert stored.status == RunStatus.COMPLETED
    assert "boom" in stored.result["output"]


def test_run_and_complete_python_empty_content_fails(tmp_path):
    """Empty content raises ValueError which run_and_complete marks FAILED."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-fail",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        content="",
        content_type=ContentType.PYTHON,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)

    run_and_complete(
        process,
        {"payload": {}},
        run,
        ExecutorConfig(),
        repo,
    )

    stored = repo.get_run(run.id)
    assert stored.status == RunStatus.FAILED
    assert "empty" in (stored.error or "").lower()
    assert repo.get_process(process.id).status == ProcessStatus.DISABLED


def test_content_type_default_is_llm():
    p = Process(name="default-type")
    assert p.content_type == ContentType.LLM


def test_content_type_python_roundtrip():
    p = Process(name="py-rt", content_type=ContentType.PYTHON)
    assert p.content_type == ContentType.PYTHON
    d = p.model_dump()
    assert d["content_type"] == "python"
    restored = Process(**d)
    assert restored.content_type == ContentType.PYTHON
