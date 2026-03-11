"""Immediate CogOS ingress: drain the event outbox and dispatch runnable work."""

from __future__ import annotations

import os
from uuid import UUID

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.logging import setup_logging
from cogos.runtime.ingress import dispatch_ready_processes, drain_outbox

logger = setup_logging()


def handler(event: dict, context) -> dict:
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping ingress wake")
        return {"statusCode": 200, "dispatched": 0, "outbox_rows": 0}

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    try:
        repo.set_meta("scheduler:last_ingress")
    except Exception:
        pass

    try:
        result = drain_outbox(repo, scheduler, batch_size=25)
    except Exception:
        logger.exception("Failed to drain CogOS event outbox")
        return {"statusCode": 200, "dispatched": 0, "outbox_rows": 0, "failures": 1}
    if not result.outbox_rows:
        return {"statusCode": 200, "dispatched": 0, "outbox_rows": 0}

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        lambda_client,
        executor_fn,
        result.affected_processes,
    )

    logger.info(
        "Ingress drained %s outbox rows, created %s deliveries, dispatched %s",
        result.outbox_rows,
        result.deliveries_created,
        dispatched,
    )
    return {
        "statusCode": 200,
        "outbox_rows": result.outbox_rows,
        "deliveries_created": result.deliveries_created,
        "dispatched": dispatched,
        "failures": result.failures,
    }
