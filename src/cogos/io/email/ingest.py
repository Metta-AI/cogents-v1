"""Email ingest endpoint — receives parsed emails from Cloudflare Email Worker."""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from cogos.db.models import Event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["email-ingest"])


class IngestPayload(BaseModel):
    event_type: str = "email:received"
    source: str = "cloudflare-email-worker"
    payload: dict


def _verify_ingest_token(token: str) -> bool:
    expected = os.environ.get("EMAIL_INGEST_SECRET", "")
    if not expected:
        logger.warning("EMAIL_INGEST_SECRET not set — rejecting all ingest requests")
        return False
    return hmac.compare_digest(token, expected)


@router.post("/ingest/email")
async def ingest_email(request: Request, body: IngestPayload):
    """Receive an email event from Cloudflare Email Worker.

    Inserts into the cogos_event table. The scheduler picks it up
    and matches it to handlers with pattern 'email:received'.
    """
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not _verify_ingest_token(token):
        raise HTTPException(status_code=401, detail="Invalid ingest token")

    from dashboard.db import get_cogos_repo

    repo = get_cogos_repo()

    event = Event(
        event_type=body.event_type,
        source=body.source,
        payload=body.payload,
    )
    event_id = repo.append_event(event)
    logger.info(
        "Ingested email event %s from=%s subject=%s",
        event_id,
        body.payload.get("from"),
        body.payload.get("subject"),
    )
    return {"event_id": str(event_id)}
