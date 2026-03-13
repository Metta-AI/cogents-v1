from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from dashboard.app import create_app


class _TraceRepoStub:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.process = Process(
            id=uuid4(),
            name="alpha.worker",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            runner="lambda",
        )
        self.inbound_channel = Channel(
            id=uuid4(),
            name="filesystem-lab:requests",
            channel_type=ChannelType.NAMED,
        )
        self.lifecycle_channel = Channel(
            id=uuid4(),
            name=f"process:{self.process.name}",
            owner_process=self.process.id,
            channel_type=ChannelType.IMPLICIT,
        )
        self.message = ChannelMessage(
            id=uuid4(),
            channel=self.inbound_channel.id,
            sender_process=None,
            payload={"task": "index workspace"},
            created_at=now,
        )
        self.handler = Handler(
            id=uuid4(),
            process=self.process.id,
            channel=self.inbound_channel.id,
            enabled=True,
            created_at=now + timedelta(milliseconds=5),
        )
        self.run = Run(
            id=uuid4(),
            process=self.process.id,
            message=self.message.id,
            status=RunStatus.COMPLETED,
            tokens_in=12,
            tokens_out=34,
            cost_usd=Decimal("0.02"),
            duration_ms=2400,
            result={"ok": True},
            created_at=now + timedelta(seconds=1),
            completed_at=now + timedelta(seconds=2),
        )
        self.delivery = Delivery(
            id=uuid4(),
            message=self.message.id,
            handler=self.handler.id,
            status=DeliveryStatus.DELIVERED,
            run=self.run.id,
            created_at=now + timedelta(milliseconds=50),
        )
        self.lifecycle_message = ChannelMessage(
            id=uuid4(),
            channel=self.lifecycle_channel.id,
            sender_process=self.process.id,
            payload={"type": "process:run:success", "run_id": str(self.run.id)},
            created_at=now + timedelta(seconds=3),
        )

    def list_processes(self, *, limit: int = 1000):
        return [self.process]

    def list_channels(self):
        return [self.inbound_channel, self.lifecycle_channel]

    def list_handlers(self):
        return [self.handler]

    def list_channel_messages(self, channel_id=None, *, limit: int = 100):
        messages = [self.lifecycle_message, self.message]
        if channel_id is not None:
            messages = [message for message in messages if message.channel == channel_id]
        return messages[:limit]

    def list_deliveries(self, *, message_id=None, handler_id=None, run_id=None, limit: int = 500):
        deliveries = [self.delivery]
        if message_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.message == message_id]
        if handler_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.handler == handler_id]
        if run_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.run == run_id]
        return deliveries[:limit]

    def list_runs(self, *, process_id=None, limit: int = 50):
        runs = [self.run]
        if process_id is not None:
            runs = [run for run in runs if run.process == process_id]
        return runs[:limit]

    def get_run(self, run_id):
        return self.run if run_id == self.run.id else None


def test_message_traces_endpoint_returns_channel_delivery_run_graph():
    app = create_app()
    client = TestClient(app)
    repo = _TraceRepoStub()

    with patch("dashboard.routers.traces.get_repo", return_value=repo):
        response = client.get("/api/cogents/test/message-traces?range=1h")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1

    trace = payload["traces"][0]
    assert trace["message"]["channel_name"] == "filesystem-lab:requests"
    assert trace["deliveries"][0]["process_name"] == "alpha.worker"
    assert trace["deliveries"][0]["run"]["id"] == str(repo.run.id)
    assert trace["deliveries"][0]["emitted_messages"][0]["channel_name"] == f"process:{repo.process.name}"


def test_runs_endpoint_maps_message_id_into_legacy_event_field():
    app = create_app()
    client = TestClient(app)
    repo = _TraceRepoStub()

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get("/api/cogents/test/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["runs"][0]["event"] == str(repo.message.id)
