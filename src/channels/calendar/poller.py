"""Google Calendar channel: polls for upcoming events via Calendar API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class CalendarClient:
    def __init__(self, service_account_key: dict, impersonate_email: str, scopes: list[str] | None = None):
        self._sa_key = service_account_key
        self._impersonate_email = impersonate_email
        self._scopes = scopes or [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ]
        self._service: Any = None

    def _build_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            self._sa_key, scopes=self._scopes, subject=self._impersonate_email,
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def list_upcoming_events(self, calendar_id: str = "primary", time_min: datetime | None = None,
                             time_max: datetime | None = None, max_results: int = 20) -> list[dict[str, Any]]:
        svc = self._ensure_service()
        now = datetime.now(timezone.utc)
        time_min = time_min or now
        time_max = time_max or now + timedelta(minutes=30)
        resp = (
            svc.events().list(
                calendarId=calendar_id, timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(), maxResults=max_results,
                singleEvents=True, orderBy="startTime",
            ).execute()
        )
        return resp.get("items", [])


class CalendarChannel(Channel):
    mode = ChannelMode.POLL

    def __init__(self, name: str = "calendar", client: CalendarClient | None = None, lookahead_minutes: int = 30):
        super().__init__(name)
        self.client = client
        self.lookahead_minutes = lookahead_minutes
        self._seen_event_ids: set[str] = set()
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        if self._pending_events:
            events = list(self._pending_events)
            self._pending_events.clear()
            return events
        if not self.client:
            return []
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(minutes=self.lookahead_minutes)
        try:
            cal_events = self.client.list_upcoming_events(time_min=now, time_max=time_max)
        except Exception:
            logger.exception("Failed to list calendar events")
            return []
        events: list[InboundEvent] = []
        for cal_event in cal_events:
            event_id = cal_event.get("id", "")
            if event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event_id)
            summary = cal_event.get("summary", "(no title)")
            start = cal_event.get("start", {}).get("dateTime") or cal_event.get("start", {}).get("date", "")
            organizer = cal_event.get("organizer", {}).get("email", "")
            event = InboundEvent(
                channel="calendar", event_type="event.upcoming",
                payload={
                    "summary": summary, "start": start,
                    "end": cal_event.get("end", {}).get("dateTime", ""),
                    "location": cal_event.get("location", ""),
                    "description": cal_event.get("description", ""),
                    "attendees": [a.get("email", "") for a in cal_event.get("attendees", [])],
                    "html_link": cal_event.get("htmlLink", ""),
                    "event_id": event_id,
                },
                raw_content=summary, author=organizer,
                external_id=f"calendar:{event_id}",
                external_url=cal_event.get("htmlLink"),
            )
            events.append(event)
        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
