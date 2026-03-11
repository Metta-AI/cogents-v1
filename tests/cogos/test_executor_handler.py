from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Event, EventDelivery, Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor import handler as executor_handler


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_executor_does_not_create_fallback_run(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)
    monkeypatch.setattr(executor_handler.time, "sleep", lambda *_args, **_kwargs: None)

    result = executor_handler.handler(
        {"process_id": str(process.id), "run_id": str(uuid4())},
        None,
    )

    assert result["statusCode"] == 409
    assert repo.list_runs(process_id=process.id) == []


def test_daemon_returns_to_runnable_when_more_deliveries_wait(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    handler = Handler(process=process.id, event_pattern="discord:dm")
    repo.create_handler(handler)
    event = Event(event_type="discord:dm", source="discord", payload={"content": "hello"})
    repo.append_event(event)
    repo.create_event_delivery(EventDelivery(event=event.id, handler=handler.id))

    run = Run(process=process.id, event=event.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)
    monkeypatch.setattr(
        executor_handler,
        "execute_process",
        lambda process, event_data, run, config, repo, **kwargs: run,
    )

    result = executor_handler.handler(
        {"process_id": str(process.id), "event_id": str(event.id), "run_id": str(run.id)},
        None,
    )

    assert result["statusCode"] == 200
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE
    assert repo.get_run(run.id).status == RunStatus.COMPLETED
