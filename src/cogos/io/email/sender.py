"""SES email sender — outbound email via AWS SES."""

from __future__ import annotations

import logging

import boto3

logger = logging.getLogger(__name__)


class SesSender:
    """Send email via AWS SES. Uses IAM auth from the execution environment."""

    def __init__(self, from_address: str, region: str = "us-east-1"):
        self._from = from_address
        self._client = boto3.client("ses", region_name=region)

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> dict:
        kwargs: dict = {
            "Source": self._from,
            "Destination": {"ToAddresses": [to]},
            "Message": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]
        response = self._client.send_email(**kwargs)
        logger.info("Sent email to=%s subject=%r message_id=%s", to, subject, response.get("MessageId"))
        return response
