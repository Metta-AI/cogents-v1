"""Email capability handlers — send, check, search."""

from __future__ import annotations

import logging
import os
from uuid import UUID

from cogos.db.repository import Repository
from cogos.io.email.sender import SesSender
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


def _get_sender() -> SesSender:
    cogent_name = os.environ.get("COGENT_NAME", "")
    domain = os.environ.get("EMAIL_DOMAIN", "softmax-cogents.com")
    region = os.environ.get("AWS_REGION", "us-east-1")
    from_address = f"{cogent_name}@{domain}"
    return SesSender(from_address=from_address, region=region)


def _email_from_event(e) -> dict:
    p = e.payload or {}
    return {
        "from": p.get("from"),
        "to": p.get("to"),
        "subject": p.get("subject"),
        "body": p.get("body"),
        "date": p.get("date"),
        "message_id": p.get("message_id"),
    }


def send(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Send an email via SES."""
    to = args.get("to", "").strip()
    subject = args.get("subject", "").strip()
    body = args.get("body", "")
    reply_to = args.get("reply_to")

    if not to or not subject:
        return CapabilityResult(content={"error": "'to' and 'subject' are required"})

    sender = _get_sender()
    response = sender.send(to=to, subject=subject, body=body, reply_to=reply_to)

    return CapabilityResult(content={
        "message_id": response.get("MessageId", ""),
        "to": to,
        "subject": subject,
    })


def check(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Check recent inbound emails (from events table)."""
    limit = args.get("limit", 10)
    events = repo.get_events(event_type="email:received", limit=limit)
    return CapabilityResult(content=[_email_from_event(e) for e in events])


def search(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Search inbound emails by query (from events table).

    Filters email:received events by matching query terms against
    sender, subject, and body fields.
    """
    query = args.get("query", "").lower()
    limit = args.get("limit", 50)

    events = repo.get_events(event_type="email:received", limit=200)
    results = []
    for e in events:
        p = e.payload or {}
        searchable = " ".join([
            p.get("from", ""),
            p.get("subject", ""),
            p.get("body", ""),
        ]).lower()
        if query in searchable:
            results.append(_email_from_event(e))
            if len(results) >= limit:
                break

    return CapabilityResult(content=results)
