"""Gmail channel: polls for new emails via Gmail API with service account credentials."""

from __future__ import annotations

import base64
import logging
from email.utils import parseaddr
from typing import Any

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class GmailClient:
    def __init__(self, service_account_key: dict, impersonate_email: str, scopes: list[str]):
        self._sa_key = service_account_key
        self._impersonate_email = impersonate_email
        self._scopes = scopes
        self._service: Any = None

    def _build_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            self._sa_key, scopes=self._scopes, subject=self._impersonate_email,
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def get_profile(self) -> dict[str, Any]:
        svc = self._ensure_service()
        return svc.users().getProfile(userId="me").execute()

    def list_messages(self, query: str = "", max_results: int = 20) -> list[dict[str, str]]:
        svc = self._ensure_service()
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return resp.get("messages", [])

    def get_message(self, msg_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        return svc.users().messages().get(userId="me", id=msg_id, format="full").execute()

    def get_message_metadata(self, msg_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        return (
            svc.users().messages()
            .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
            .execute()
        )


def _extract_headers(msg: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for h in msg.get("payload", {}).get("headers", []):
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date", "message-id"):
            headers[name] = h.get("value", "")
    return headers


def _extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            if sub.get("mimeType") == "text/plain" and sub.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(sub["body"]["data"]).decode("utf-8", errors="replace")
    return msg.get("snippet", "")


class GmailChannel(Channel):
    mode = ChannelMode.POLL

    def __init__(self, name: str = "gmail", client: GmailClient | None = None):
        super().__init__(name)
        self.client = client
        self._seen_msg_ids: set[str] = set()
        self._initialized = False
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        if self._pending_events:
            events = list(self._pending_events)
            self._pending_events.clear()
            return events
        if not self.client:
            return []
        if not self._initialized:
            try:
                existing = self.client.list_messages(query="is:inbox", max_results=50)
                self._seen_msg_ids = {m["id"] for m in existing}
                profile = self.client.get_profile()
                logger.info("Gmail connected as %s, seeded %d existing messages", profile.get("emailAddress"), len(self._seen_msg_ids))
                self._initialized = True
            except Exception:
                logger.exception("Failed to initialize Gmail channel")
                return []
        events: list[InboundEvent] = []
        try:
            messages = self.client.list_messages(query="is:inbox is:unread", max_results=20)
        except Exception:
            logger.exception("Failed to list Gmail messages")
            return []
        for stub in messages:
            msg_id = stub["id"]
            if msg_id in self._seen_msg_ids:
                continue
            self._seen_msg_ids.add(msg_id)
            try:
                msg = self.client.get_message(msg_id)
            except Exception:
                logger.exception("Failed to fetch message %s", msg_id)
                continue
            headers = _extract_headers(msg)
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "unknown")
            _, sender_email = parseaddr(sender)
            body = _extract_body(msg)
            message_id = headers.get("message-id", msg_id)
            event = InboundEvent(
                channel="gmail", event_type="email",
                payload={"subject": subject, "sender": sender, "sender_email": sender_email,
                         "to": headers.get("to", ""), "date": headers.get("date", ""),
                         "thread_id": stub.get("threadId", ""), "message_id": msg_id,
                         "labels": msg.get("labelIds", [])},
                raw_content=body, author=sender, external_id=f"gmail:{message_id}",
            )
            events.append(event)
        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
