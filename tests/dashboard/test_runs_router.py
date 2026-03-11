from dashboard.routers import runs as runs_router

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Event, Handler, Process, ProcessStatus


def test_run_detail_includes_trigger_context(tmp_path, monkeypatch):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="worker", status=ProcessStatus.WAITING)
    repo.upsert_process(proc)
    handler = Handler(process=proc.id, event_pattern="discord:dm")
    repo.create_handler(handler)
    event = Event(event_type="discord:dm", source="discord", payload={"author_id": "u_123"})
    repo.append_event(event)

    scheduler = SchedulerCapability(repo, proc.id)
    scheduler.match_events()
    dispatch = scheduler.dispatch_process(str(proc.id))

    monkeypatch.setattr(runs_router, "get_repo", lambda: repo)

    detail = runs_router.get_run(name="alpha", run_id=dispatch.run_id)

    assert detail.delivery is not None
    assert detail.trigger is not None
    assert detail.trigger.delivery == detail.delivery
    assert detail.trigger.event is not None
    assert detail.trigger.event.event_type == "discord:dm"
    assert detail.trigger.event.source == "discord"
    assert detail.trigger.handler is not None
    assert detail.trigger.handler.id == str(handler.id)
    assert detail.trigger.handler.event_pattern == "discord:dm"
