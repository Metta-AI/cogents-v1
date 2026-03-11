"""Dispatcher Lambda: runs the CogOS scheduler tick every second.

Loops for ~55 seconds (leaving margin before the next 1-minute invocation),
matching events to handlers, selecting runnable processes, and invoking the
executor for each.
"""

from __future__ import annotations

import json
import logging
import os
import time

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()

# How long to loop before returning (seconds).  EventBridge fires us every
# 60 s, so 55 s keeps a comfortable margin.
_LOOP_DURATION = 55


def handler(event: dict, context) -> dict:
    """Lambda entry point: tick the scheduler every second for ~55 s."""
    from uuid import UUID
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        cogos_repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping scheduler tick")
        return {"statusCode": 200, "ticks": 0, "dispatched": 0}

    scheduler = SchedulerCapability(cogos_repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
    executor_fn = f"cogent-{safe_name}-executor"

    total_dispatched = 0
    ticks = 0
    deadline = time.monotonic() + _LOOP_DURATION

    while time.monotonic() < deadline:
        dispatched = _tick(scheduler, cogos_repo, lambda_client, executor_fn)
        total_dispatched += dispatched
        ticks += 1

        remaining = deadline - time.monotonic()
        if remaining > 1:
            time.sleep(1)
        else:
            break

    if total_dispatched:
        logger.info(f"Dispatcher: {ticks} ticks, {total_dispatched} dispatched")

    return {
        "statusCode": 200,
        "ticks": ticks,
        "dispatched": total_dispatched,
    }


def _tick(scheduler, repo, lambda_client, executor_fn: str) -> int:
    """Single scheduler tick: match events → select processes → dispatch."""
    from uuid import UUID

    # Heartbeat — lets the dashboard show time-since-last-tick
    try:
        repo.set_meta("scheduler:last_tick")
    except Exception:
        pass  # non-critical

    # 1. Match events to handlers
    match_result = scheduler.match_events(limit=50)
    if match_result.deliveries_created > 0:
        logger.info(f"CogOS: matched {match_result.deliveries_created} event deliveries")

    # 2. Select runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return 0

    # 3. Dispatch each selected process
    dispatched = 0
    for proc in select_result.selected:
        dispatch_result = scheduler.dispatch_process(process_id=proc.id)
        if hasattr(dispatch_result, "error"):
            logger.warning(f"CogOS: dispatch failed for {proc.name}: {dispatch_result.error}")
            continue

        # Get the event payload for the executor
        event_payload = {}
        if dispatch_result.event_id:
            rows = repo._rows_to_dicts(repo._execute(
                "SELECT payload FROM cogos_event WHERE id = :id",
                [repo._param("id", UUID(dispatch_result.event_id))],
            ))
            if rows:
                raw = rows[0].get("payload", "{}")
                event_payload = json.loads(raw) if isinstance(raw, str) else (raw or {})

        payload = {
            "process_id": dispatch_result.process_id,
            "event_id": dispatch_result.event_id,
            "event_type": event_payload.get("event_type", ""),
            "payload": event_payload,
        }

        try:
            lambda_client.invoke(
                FunctionName=executor_fn,
                InvocationType="Event",  # async
                Payload=json.dumps(payload),
            )
            dispatched += 1
            logger.info(f"CogOS: dispatched {proc.name} (run={dispatch_result.run_id})")
        except Exception:
            logger.exception(f"CogOS: failed to invoke executor for {proc.name}")

    return dispatched
