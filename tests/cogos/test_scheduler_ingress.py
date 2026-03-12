from datetime import datetime, timedelta
from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import DeliveryStatus, Event, EventOutboxStatus, Handler, Process, ProcessMode, ProcessStatus, RunStatus
from cogos.runtime.ingress import dispatch_ready_processes, drain_outbox


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(
        name=name,
        mode=ProcessMode.DAEMON,
        status=status,
        runner="lambda",
    )


def test_match_events_remains_per_handler_idempotent(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc1 = _daemon("discord-one")
    repo.upsert_process(proc1)
    repo.create_handler(Handler(process=proc1.id, event_pattern="discord:dm"))

    repo.append_event(Event(event_type="discord:dm", source="discord", payload={"content": "hi"}))
    first = scheduler.match_events()
    assert first.deliveries_created == 1

    proc2 = _daemon("discord-two")
    repo.upsert_process(proc2)
    repo.create_handler(Handler(process=proc2.id, event_pattern="discord:dm"))

    second = scheduler.match_events()
    assert second.deliveries_created == 1
    assert second.deliveries[0].process_id == str(proc2.id)


def test_drain_outbox_and_dispatches_immediately(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    repo.create_handler(Handler(process=proc.id, event_pattern="discord:dm"))
    repo.append_event(Event(event_type="discord:dm", source="discord", payload={"content": "hello"}))

    result = drain_outbox(repo, scheduler)
    assert result.outbox_rows == 1
    assert result.deliveries_created == 1
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE

    class _LambdaClient:
        def __init__(self) -> None:
            self.invocations: list[dict] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {"StatusCode": 202}

    lambda_client = _LambdaClient()
    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        lambda_client,
        "executor-fn",
        result.affected_processes,
    )

    assert dispatched == 1
    assert len(lambda_client.invocations) == 1
    assert len(repo.list_runs(process_id=proc.id)) == 1
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNING
    delivery = next(iter(repo._event_deliveries.values()))
    assert delivery.status == DeliveryStatus.QUEUED


def test_dispatch_rolls_back_failed_invoke(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    repo.create_handler(Handler(process=proc.id, event_pattern="discord:dm"))
    repo.append_event(Event(event_type="discord:dm", source="discord", payload={"content": "hello"}))

    result = drain_outbox(repo, scheduler)

    class _LambdaClient:
        def invoke(self, **_kwargs):
            raise RuntimeError("invoke failed")

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        _LambdaClient(),
        "executor-fn",
        result.affected_processes,
    )

    assert dispatched == 0
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE
    assert len(repo.get_pending_deliveries(proc.id)) == 1
    runs = repo.list_runs(process_id=proc.id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    delivery = next(iter(repo._event_deliveries.values()))
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.run is None


def test_failed_outbox_rows_back_off_before_retry(tmp_path):
    repo = _repo(tmp_path)
    event = Event(event_type="discord:dm", source="discord", payload={"content": "hello"})
    repo.append_event(event)

    [claimed] = repo.claim_event_outbox_batch()
    repo.mark_event_outbox_failed(claimed.id, "boom")

    assert repo.claim_event_outbox_batch() == []

    stored = next(item for item in repo._event_outbox.values() if item.event == event.id)
    stored.claimed_at = datetime.utcnow() - timedelta(seconds=61)
    repo._save()

    retry = repo.claim_event_outbox_batch()
    assert [item.id for item in retry] == [claimed.id]


def test_failed_outbox_rows_stop_after_max_attempts(tmp_path):
    repo = _repo(tmp_path)
    event = Event(event_type="discord:dm", source="discord", payload={"content": "hello"})
    repo.append_event(event)

    item = next(item for item in repo._event_outbox.values() if item.event == event.id)
    item.status = EventOutboxStatus.FAILED
    item.attempt_count = repo._event_outbox_failed_max_attempts
    item.claimed_at = datetime.utcnow() - timedelta(days=1)
    repo._save()

    assert repo.claim_event_outbox_batch() == []
