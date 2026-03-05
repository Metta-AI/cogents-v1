"""Gmail outbound: send emails via Gmail API."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any


class GmailSender:
    def __init__(self, client: Any):
        self._client = client

    def send_email(self, to: str, subject: str, body: str) -> dict:
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc = self._client._ensure_service()
        return svc.users().messages().send(userId="me", body={"raw": raw}).execute()
