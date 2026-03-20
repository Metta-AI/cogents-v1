"""Email sender — outbound email via the CogtainerRuntime."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SesSender:
    """Send email via the CogtainerRuntime.send_email() method."""

    def __init__(self, from_address: str, region: str = "us-east-1", runtime: Any = None):
        self._from = from_address
        self._region = region
        self._runtime = runtime

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> dict:
        message_id = self._runtime.send_email(
            source=self._from,
            to=to,
            subject=subject,
            body=body,
            reply_to=reply_to,
        )
        logger.info("Sent email to=%s subject=%r message_id=%s", to, subject, message_id)
        return {"MessageId": message_id}
