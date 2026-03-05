from channels.base import ChannelMode, InboundEvent
from channels.gmail import GmailChannel


class TestGmailChannel:
    def test_mode_is_poll(self):
        ch = GmailChannel(name="gmail")
        assert ch.mode == ChannelMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = GmailChannel(name="gmail")
        event = InboundEvent(
            channel="gmail", event_type="email.general",
            payload={"subject": "Hello"}, raw_content="Hello body",
            author="human@example.com", external_id="gmail:msg-123",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].author == "human@example.com"

    async def test_poll_without_client_returns_empty(self):
        ch = GmailChannel(name="gmail")
        events = await ch.poll()
        assert len(events) == 0
