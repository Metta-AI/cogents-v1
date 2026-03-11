from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Event, Handler, Process, ProcessStatus, Run, RunStatus


def test_dispatch_records_delivery_on_run(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="worker", status=ProcessStatus.WAITING)
    repo.upsert_process(proc)
    handler = Handler(process=proc.id, event_pattern="discord:dm")
    repo.create_handler(handler)
    event = Event(event_type="discord:dm", source="discord", payload={"author_id": "u_123"})
    repo.append_event(event)

    scheduler = SchedulerCapability(repo, proc.id)
    match = scheduler.match_events()
    assert match.deliveries_created == 1

    dispatch = scheduler.dispatch_process(str(proc.id))
    run = repo.get_run(UUID(dispatch.run_id))

    assert run is not None
    assert run.delivery is not None
    assert run.event == event.id

    delivery = repo.get_delivery_for_run(run.id)
    assert delivery is not None
    assert delivery.id == run.delivery
    assert delivery.event == event.id
    assert delivery.handler == handler.id
    assert delivery.run == run.id


def test_executor_reuses_dispatched_run(tmp_path, monkeypatch):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="worker", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)
    existing = Run(process=proc.id, status=RunStatus.RUNNING)
    repo.create_run(existing)

    monkeypatch.setattr("cogos.executor.handler.get_config", lambda: object())
    monkeypatch.setattr("cogos.executor.handler.get_repo", lambda config=None: repo)

    def _fake_execute(process, event_data, run, config, repo_arg, *, bedrock_client=None):
        run.tokens_in = 3
        run.tokens_out = 5
        run.result = {"ok": True}
        return run

    monkeypatch.setattr("cogos.executor.handler.execute_process", _fake_execute)

    from cogos.executor.handler import handler

    result = handler({"process_id": str(proc.id), "run_id": str(existing.id)}, None)

    assert result["statusCode"] == 200
    assert result["run_id"] == str(existing.id)
    assert len(repo.list_runs()) == 1

    run = repo.get_run(existing.id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.result == {"ok": True}

