from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge._typing_tasks = {}
    return bridge


async def test_handle_dm_stops_typing_on_dm_channel():
    bridge = _make_bridge()
    bridge._stop_typing = MagicMock()

    mock_user = AsyncMock()
    mock_dm_channel = AsyncMock()
    mock_dm_channel.id = 444
    mock_user.create_dm.return_value = mock_dm_channel
    bridge.client.fetch_user = AsyncMock(return_value=mock_user)

    await bridge._handle_dm({"user_id": "777", "content": "hi there"})

    bridge.client.fetch_user.assert_called_once_with(777)
    mock_user.create_dm.assert_called_once()
    bridge._stop_typing.assert_called_once_with(444)
    mock_dm_channel.send.assert_called_once_with("hi there")
