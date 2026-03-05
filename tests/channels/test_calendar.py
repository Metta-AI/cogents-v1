from channels.base import ChannelMode, InboundEvent
from channels.calendar import CalendarChannel


class TestCalendarChannel:
    def test_mode_is_poll(self):
        ch = CalendarChannel(name="calendar")
        assert ch.mode == ChannelMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = CalendarChannel(name="calendar")
        event = InboundEvent(
            channel="calendar", event_type="event.upcoming",
            payload={"summary": "Standup", "start": "2026-03-04T10:00:00Z"},
            raw_content="Standup",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].payload["summary"] == "Standup"

    async def test_poll_without_client_returns_empty(self):
        ch = CalendarChannel(name="calendar")
        events = await ch.poll()
        assert len(events) == 0
