from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import DeliveryStatus, Event, EventDelivery, Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor import handler as executor_handler


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_executor_recreates_missing_dispatch_run(monkeypatch, tmp_path):
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
    monkeypatch.setattr(
        executor_handler,
        "execute_process",
        lambda process, event_data, run, config, repo, **kwargs: run,
    )
    missing_run_id = uuid4()

    result = executor_handler.handler(
        {"process_id": str(process.id), "run_id": str(missing_run_id)},
        None,
    )

    assert result["statusCode"] == 200
    runs = repo.list_runs(process_id=process.id)
    assert len(runs) == 1
    assert runs[0].id == missing_run_id
    assert runs[0].status == RunStatus.COMPLETED


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
    current_event = Event(event_type="discord:dm", source="discord", payload={"content": "hello"})
    queued_event = Event(event_type="discord:dm", source="discord", payload={"content": "next"})
    repo.append_event(current_event)
    repo.append_event(queued_event)
    current_delivery_id, _ = repo.create_event_delivery(EventDelivery(event=current_event.id, handler=handler.id))
    repo.create_event_delivery(EventDelivery(event=queued_event.id, handler=handler.id))

    run = Run(process=process.id, event=current_event.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    repo.mark_queued(current_delivery_id, run.id)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)
    monkeypatch.setattr(
        executor_handler,
        "execute_process",
        lambda process, event_data, run, config, repo, **kwargs: run,
    )

    result = executor_handler.handler(
        {"process_id": str(process.id), "event_id": str(current_event.id), "run_id": str(run.id)},
        None,
    )

    assert result["statusCode"] == 200
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE
    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo._event_deliveries[current_delivery_id].status == DeliveryStatus.DELIVERED
