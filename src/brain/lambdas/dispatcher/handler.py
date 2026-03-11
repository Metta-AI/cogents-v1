"""Dispatcher Lambda: runs one CogOS scheduler tick per invocation.

EventBridge fires this every 60s. Each invocation:
1. Generates virtual system:tick:minute (and system:tick:hour on the hour)
2. Matches real events to handlers
3. Selects runnable processes and dispatches executors

Virtual tick events are NOT written to the event log — they match handlers
directly and set processes to RUNNABLE.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.logging import setup_logging
from cogos.runtime.ingress import dispatch_ready_processes, drain_outbox

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point: single-shot scheduler tick."""
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping scheduler tick")
        return {"statusCode": 200, "dispatched": 0}

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    # Heartbeat — lets the dashboard show time-since-last-tick
    try:
        repo.set_meta("scheduler:last_tick")
    except Exception:
        pass

    # 1. Generate virtual system tick events (not written to event log)
    _apply_system_ticks(repo)

    # 2. Drain immediate-event outbox as the primary backstop path
    try:
        outbox_result = drain_outbox(repo, scheduler, batch_size=25)
    except Exception:
        logger.exception("Failed to drain CogOS event outbox")
        from cogos.runtime.ingress import DrainResult
        outbox_result = DrainResult()
    dispatched = 0
    if outbox_result.deliveries_created > 0:
        logger.info(
            "Dispatcher drained %s outbox rows and created %s deliveries",
            outbox_result.outbox_rows,
            outbox_result.deliveries_created,
        )
        dispatched += dispatch_ready_processes(
            repo,
            scheduler,
            lambda_client,
            executor_fn,
            outbox_result.affected_processes,
        )

    # 3. Match remaining legacy/unreconciled events
    match_result = scheduler.match_events(limit=50)
    if match_result.deliveries_created > 0:
        logger.info("Matched %s event deliveries", match_result.deliveries_created)
        dispatched += dispatch_ready_processes(
            repo,
            scheduler,
            lambda_client,
            executor_fn,
            {UUID(info.process_id) for info in match_result.deliveries},
        )

    # 4. Select any remaining runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return {"statusCode": 200, "dispatched": dispatched}

    # 5. Dispatch each selected process
    for proc in select_result.selected:
        try:
            dispatched += dispatch_ready_processes(
                repo,
                scheduler,
                lambda_client,
                executor_fn,
                {UUID(proc.id)},
            )
        except Exception:
            logger.exception("Failed to invoke executor for %s", proc.name)

    if dispatched:
        logger.info("Dispatcher: %s dispatched", dispatched)

    return {"statusCode": 200, "dispatched": dispatched}


def _apply_system_ticks(repo) -> None:
    """Generate virtual system:tick:minute (and :hour) events.

    These match handlers and set processes to RUNNABLE but are never
    written to the cogos_event table.
    """
    from cogos.db.models import ProcessStatus

    now = datetime.now(timezone.utc)
    tick_types = ["system:tick:minute"]
    if now.minute == 0:
        tick_types.append("system:tick:hour")

    for tick_type in tick_types:
        handlers = repo.match_handlers(tick_type)
        for h in handlers:
            proc = repo.get_process(h.process)
            if proc and proc.status == ProcessStatus.WAITING:
                repo.update_process_status(h.process, ProcessStatus.RUNNABLE)
                logger.info(f"System tick {tick_type} -> {proc.name} RUNNABLE")
