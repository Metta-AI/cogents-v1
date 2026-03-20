"""Asana auto-accept Lambda — processes Asana invite emails and accepts them.

Triggered by SQS when an email from Asana is received by the cogent's SES address.
Extracts the accept link from the HTML body and hits it to complete onboarding.
"""

import json
import logging
import os
import re
from typing import Any

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")

_dynamo_table: Any = None


def _get_dynamo_table():
    global _dynamo_table
    if _dynamo_table is None:
        _dynamo_table = boto3.resource("dynamodb").Table(DYNAMO_TABLE)
    return _dynamo_table


def _extract_accept_link(html_body: str) -> str | None:
    """Extract Asana invitation accept link from email HTML body."""
    pattern = r'href="(https://app\.asana\.com/[^"]*)"'
    for m in re.finditer(pattern, html_body):
        url = m.group(1)
        if "accept" in url or "invitation" in url:
            return url
    return None


def _auto_accept(link: str) -> bool:
    """Hit the accept link to complete the Asana invitation."""
    resp = requests.get(link, allow_redirects=True)
    return resp.status_code < 400


def handler(event, context):
    """SQS Lambda handler — processes Asana invite emails."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            cogent_name = body.get("cogent_name")
            sender = body.get("from", "")
            subject = body.get("subject", "")
            html_body = body.get("html_body", "")

            if "asana.com" not in sender.lower():
                logger.info("Skipping non-Asana email from=%s cogent=%s", sender, cogent_name)
                continue

            link = _extract_accept_link(html_body)
            if not link:
                logger.warning("No accept link found in Asana email cogent=%s subject=%s", cogent_name, subject)
                continue

            logger.info("Auto-accepting Asana invite cogent=%s link=%s", cogent_name, link)
            if _auto_accept(link):
                logger.info("Asana invite accepted cogent=%s", cogent_name)
                _get_dynamo_table().update_item(
                    Key={"cogent_name": cogent_name},
                    UpdateExpression="SET asana_status = :s",
                    ExpressionAttributeValues={":s": "active"},
                )
            else:
                logger.error("Failed to accept Asana invite cogent=%s", cogent_name)

        except Exception:
            logger.exception("Error processing Asana invite record")
