from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from cogos.db.models import ChannelMessage, Delivery, Run
from dashboard.db import get_repo

router = APIRouter(tags=["message-traces"])

TraceRange = Literal["1m", "10m", "1h", "24h", "1w"]

_RANGE_TO_DELTA: dict[TraceRange, timedelta] = {
    "1m": timedelta(minutes=1),
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "1w": timedelta(weeks=1),
}


class TraceMessageOut(BaseModel):
    id: str
    channel_id: str
    channel_name: str
    sender_process: str | None = None
    sender_process_name: str | None = None
    payload: dict[str, Any]
    created_at: str | None = None


class TraceRunOut(BaseModel):
    id: str
    process: str
    process_name: str | None = None
    runner: str | None = None
    status: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int | None = None
    error: str | None = None
    model_version: str | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    completed_at: str | None = None


class TraceDeliveryOut(BaseModel):
    id: str
    handler_id: str
    status: str
    created_at: str | None = None
    process_id: str | None = None
    process_name: str | None = None
    run: TraceRunOut | None = None
    emitted_messages: list[TraceMessageOut] = Field(default_factory=list)


class MessageTraceOut(BaseModel):
    message: TraceMessageOut
    deliveries: list[TraceDeliveryOut]


class MessageTracesResponse(BaseModel):
    count: int
    traces: list[MessageTraceOut]


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    normalized = _as_utc(dt)
    return normalized.isoformat() if normalized else None


def _message_sort_key(msg: ChannelMessage) -> datetime:
    return _as_utc(msg.created_at) or datetime.min.replace(tzinfo=timezone.utc)

def _message_out(
    message: ChannelMessage,
    *,
    channel_names: dict[UUID, str],
    process_names: dict[UUID, str],
) -> TraceMessageOut:
    return TraceMessageOut(
        id=str(message.id),
        channel_id=str(message.channel),
        channel_name=channel_names.get(message.channel, str(message.channel)),
        sender_process=str(message.sender_process) if message.sender_process else None,
        sender_process_name=process_names.get(message.sender_process) if message.sender_process else None,
        payload=message.payload or {},
        created_at=_iso(message.created_at),
    )


def _run_out(
    run: Run,
    *,
    process_names: dict[UUID, str],
    process_runners: dict[UUID, str],
) -> TraceRunOut:
    return TraceRunOut(
        id=str(run.id),
        process=str(run.process),
        process_name=process_names.get(run.process),
        runner=process_runners.get(run.process),
        status=run.status.value,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_usd=float(run.cost_usd if isinstance(run.cost_usd, Decimal) else Decimal(str(run.cost_usd))),
        duration_ms=run.duration_ms,
        error=run.error,
        model_version=run.model_version,
        result=run.result,
        created_at=_iso(run.created_at),
        completed_at=_iso(run.completed_at),
    )


def _emitted_messages_for_run(
    run: Run,
    source_message_id: UUID,
    all_messages: list[ChannelMessage],
) -> list[ChannelMessage]:
    if run.created_at is None:
        return []

    start = _as_utc(run.created_at)
    completed = _as_utc(run.completed_at)
    end = completed + timedelta(seconds=5) if completed else None

    emitted = []
    for message in all_messages:
        if message.id == source_message_id:
            continue
        if message.sender_process != run.process:
            continue

        created_at = _as_utc(message.created_at)
        if created_at is None or created_at < start:
            continue
        if end is not None and created_at > end:
            continue

        emitted.append(message)

    emitted.sort(key=_message_sort_key)
    return emitted


@router.get("/message-traces", response_model=MessageTracesResponse)
def list_message_traces(
    name: str,
    range: TraceRange = Query("1h"),
    limit: int = Query(50, ge=1, le=200),
) -> MessageTracesResponse:
    repo = get_repo()

    cutoff = datetime.now(timezone.utc) - _RANGE_TO_DELTA[range]
    fetch_limit = max(limit * 10, 500)

    processes = repo.list_processes(limit=1000)
    channels = repo.list_channels()
    handlers = repo.list_handlers()
    messages = repo.list_channel_messages(limit=fetch_limit)
    deliveries = repo.list_deliveries(limit=max(fetch_limit * 2, 1000))
    runs = repo.list_runs(limit=max(fetch_limit * 2, 1000))

    process_names = {process.id: process.name for process in processes}
    process_runners = {process.id: process.runner for process in processes}
    channel_names = {channel.id: channel.name for channel in channels}
    handlers_by_id = {handler.id: handler for handler in handlers}
    runs_by_id = {run.id: run for run in runs}

    deliveries_by_message: dict[UUID, list[Delivery]] = {}
    for delivery in deliveries:
        deliveries_by_message.setdefault(delivery.message, []).append(delivery)

    candidate_messages = []
    for message in messages:
        created_at = _as_utc(message.created_at)
        if created_at is not None and created_at < cutoff:
            continue
        if message.sender_process is None or deliveries_by_message.get(message.id):
            candidate_messages.append(message)

    candidate_messages.sort(key=_message_sort_key, reverse=True)

    traces = []
    for message in candidate_messages[:limit]:
        delivery_items = []
        message_deliveries = sorted(
            deliveries_by_message.get(message.id, []),
            key=lambda delivery: _as_utc(delivery.created_at) or datetime.min.replace(tzinfo=timezone.utc),
        )
        for delivery in message_deliveries:
            handler = handlers_by_id.get(delivery.handler)
            process_id = handler.process if handler else None
            run = runs_by_id.get(delivery.run) if delivery.run else None
            if delivery.run is not None and run is None:
                run = repo.get_run(delivery.run)
                if run is not None:
                    runs_by_id[run.id] = run

            emitted_messages = []
            if run is not None:
                emitted_messages = [
                    _message_out(
                        emitted,
                        channel_names=channel_names,
                        process_names=process_names,
                    )
                    for emitted in _emitted_messages_for_run(run, message.id, messages)
                ]

            delivery_items.append(
                TraceDeliveryOut(
                    id=str(delivery.id),
                    handler_id=str(delivery.handler),
                    status=delivery.status.value,
                    created_at=_iso(delivery.created_at),
                    process_id=str(process_id) if process_id else None,
                    process_name=process_names.get(process_id) if process_id else None,
                    run=_run_out(run, process_names=process_names, process_runners=process_runners) if run else None,
                    emitted_messages=emitted_messages,
                )
            )

        traces.append(
            MessageTraceOut(
                message=_message_out(
                    message,
                    channel_names=channel_names,
                    process_names=process_names,
                ),
                deliveries=delivery_items,
            )
        )

    return MessageTracesResponse(count=len(traces), traces=traces)
