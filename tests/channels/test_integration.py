"""Verify all channels can be imported and instantiated."""

from channels.base import Channel, ChannelMode
from channels.github import GitHubChannel
from channels.asana import AsanaChannel


class TestAllChannelsImport:
    def test_github(self):
        ch = GitHubChannel()
        assert ch.mode == ChannelMode.ON_DEMAND
        assert isinstance(ch, Channel)

    def test_asana(self):
        ch = AsanaChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)
