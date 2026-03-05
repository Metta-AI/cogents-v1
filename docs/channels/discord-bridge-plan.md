# Discord Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the Discord bridge from metta-ai/cogent — a standalone Fargate service that relays Discord messages to EventBridge and SQS replies back to Discord.

**Architecture:** The bridge owns all Discord IO. It connects to Discord Gateway, publishes inbound events to EventBridge, and long-polls an SQS queue for outbound replies. The old DiscordChannel/DiscordSender are removed — the brain communicates with Discord exclusively through EventBridge/SQS. Reply helpers provide a clean API for enqueueing outbound messages.

**Tech Stack:** Python 3.12, discord.py, boto3 (EventBridge + SQS), aiohttp, asyncio

**Design doc:** `docs/channels/discord-bridge-design.md`

---

### Task 1: Remove old Discord listener/sender and update imports

The old DiscordChannel (Channel ABC subclass) and DiscordSender are being replaced by the bridge. Remove them and update all references.

**Files:**
- Delete: `src/channels/discord/listener.py`
- Delete: `src/channels/discord/sender.py`
- Modify: `src/channels/discord/__init__.py`
- Modify: `src/channels/__init__.py`
- Delete: `tests/channels/test_discord.py`
- Modify: `tests/channels/test_integration.py`

**Step 1: Delete the old files**

```bash
rm src/channels/discord/listener.py src/channels/discord/sender.py tests/channels/test_discord.py
```

**Step 2: Update `src/channels/discord/__init__.py`**

Replace contents with:

```python
"""Discord bridge: standalone relay between Discord Gateway and EventBridge/SQS."""
```

**Step 3: Update `src/channels/__init__.py`**

The package no longer exports DiscordChannel. Keep exporting the base types only:

```python
from channels.base import Channel, ChannelMode, InboundEvent

__all__ = ["Channel", "ChannelMode", "InboundEvent"]
```

(This file may already look like this — verify and leave unchanged if so.)

**Step 4: Update `tests/channels/test_integration.py`**

Remove the Discord test and its import. The file should become:

```python
"""Verify all channels can be imported and instantiated."""

from channels.base import Channel, ChannelMode
from channels.github import GitHubChannel
from channels.gmail import GmailChannel
from channels.asana import AsanaChannel
from channels.calendar import CalendarChannel


class TestAllChannelsImport:
    def test_github(self):
        ch = GitHubChannel()
        assert ch.mode == ChannelMode.ON_DEMAND
        assert isinstance(ch, Channel)

    def test_gmail(self):
        ch = GmailChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_asana(self):
        ch = AsanaChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_calendar(self):
        ch = CalendarChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)
```

**Step 5: Run tests to verify nothing is broken**

```bash
pytest tests/channels/ -v
```

Expected: All remaining tests pass (the discord-specific tests are gone, integration tests pass without discord).

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor(channels): remove old DiscordChannel/DiscordSender in prep for bridge"
```

---

### Task 2: Reply helpers (`reply.py`)

Port the SQS reply helpers that let the brain/executor enqueue outbound Discord messages. These are used by other services and must exist before the bridge (which consumes from the queue).

**Files:**
- Create: `src/channels/discord/reply.py`
- Create: `tests/channels/test_discord_reply.py`

**Step 1: Write the failing tests**

Create `tests/channels/test_discord_reply.py`:

```python
"""Tests for Discord SQS reply helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from channels.discord.reply import (
    queue_reply,
    queue_reaction,
    queue_thread_create,
    queue_dm,
)


@pytest.fixture
def mock_sqs():
    """Mock SQS client and patch boto3 + STS."""
    sqs = MagicMock()
    with (
        patch("channels.discord.reply.boto3") as mock_boto3,
    ):
        mock_boto3.client.side_effect = lambda service, **kw: (
            sqs if service == "sqs" else MagicMock(get_caller_identity=MagicMock(return_value={"Account": "123456789"}))
        )
        yield sqs


class TestQueueReply:
    async def test_sends_message_to_sqs(self, mock_sqs):
        await queue_reply(
            channel="111",
            content="hello",
            cogent_name="alpha",
            region="us-east-1",
        )
        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        body = json.loads(call_kwargs["MessageBody"])
        assert body["channel"] == "111"
        assert body["content"] == "hello"
        assert "type" not in body  # default message type omitted

    async def test_includes_files_and_thread(self, mock_sqs):
        await queue_reply(
            channel="111",
            content="see attached",
            files=[{"url": "https://example.com/f.png", "filename": "f.png"}],
            thread_id="222",
            reply_to="333",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["files"] == [{"url": "https://example.com/f.png", "filename": "f.png"}]
        assert body["thread_id"] == "222"
        assert body["reply_to"] == "333"

    async def test_queue_url_pattern(self, mock_sqs):
        await queue_reply(channel="111", content="hi", cogent_name="beta.1", region="us-west-2")
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert "cogent-beta-1-discord-replies" in call_kwargs["QueueUrl"]
        assert "us-west-2" in call_kwargs["QueueUrl"]


class TestQueueReaction:
    async def test_sends_reaction(self, mock_sqs):
        await queue_reaction(
            channel="111",
            message_id="999",
            emoji="👍",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "reaction"
        assert body["emoji"] == "👍"
        assert body["message_id"] == "999"


class TestQueueThreadCreate:
    async def test_sends_thread_create(self, mock_sqs):
        await queue_thread_create(
            channel="111",
            thread_name="Discussion",
            content="Let's talk",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "thread_create"
        assert body["thread_name"] == "Discussion"
        assert body["content"] == "Let's talk"


class TestQueueDm:
    async def test_sends_dm(self, mock_sqs):
        await queue_dm(
            user_id="777",
            content="hey there",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "dm"
        assert body["user_id"] == "777"
        assert body["content"] == "hey there"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/channels/test_discord_reply.py -v
```

Expected: FAIL — `channels.discord.reply` does not exist.

**Step 3: Write the implementation**

Create `src/channels/discord/reply.py`:

```python
"""SQS reply queue helpers for sending Discord messages from the brain/executor.

Usage:
    await queue_reply(channel="123", content="Hello!", cogent_name="alpha")
    await queue_reaction(channel="123", message_id="456", emoji="👍", cogent_name="alpha")
    await queue_thread_create(channel="123", thread_name="Topic", cogent_name="alpha")
    await queue_dm(user_id="789", content="Hi!", cogent_name="alpha")
"""

from __future__ import annotations

import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)


def _get_queue_url(cogent_name: str, region: str) -> str:
    """Construct the SQS queue URL for Discord replies.

    Overridable via DISCORD_REPLY_QUEUE_URL env var.
    """
    override = os.environ.get("DISCORD_REPLY_QUEUE_URL")
    if override:
        return override

    safe_name = cogent_name.replace(".", "-")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"https://sqs.{region}.amazonaws.com/{account_id}/cogent-{safe_name}-discord-replies"


def _send(queue_url: str, body: dict, region: str) -> None:
    """Send a message to the SQS queue."""
    client = boto3.client("sqs", region_name=region)
    client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))


async def queue_reply(
    channel: str,
    content: str = "",
    *,
    files: list[dict] | None = None,
    thread_id: str | None = None,
    reply_to: str | None = None,
    cogent_name: str | None = None,
    region: str | None = None,
) -> None:
    """Enqueue a text message (with optional attachments) for Discord delivery."""
    name = cogent_name or os.environ["COGENT_NAME"]
    rgn = region or os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url(name, rgn)

    body: dict = {"channel": channel, "content": content}
    if files:
        body["files"] = files
    if thread_id:
        body["thread_id"] = thread_id
    if reply_to:
        body["reply_to"] = reply_to

    _send(url, body, rgn)
    logger.debug("Queued reply to channel %s (%d chars)", channel, len(content))


async def queue_reaction(
    channel: str,
    message_id: str,
    emoji: str,
    *,
    cogent_name: str | None = None,
    region: str | None = None,
) -> None:
    """Enqueue an emoji reaction on a Discord message."""
    name = cogent_name or os.environ["COGENT_NAME"]
    rgn = region or os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url(name, rgn)

    body = {"type": "reaction", "channel": channel, "message_id": message_id, "emoji": emoji}
    _send(url, body, rgn)
    logger.debug("Queued reaction %s on message %s", emoji, message_id)


async def queue_thread_create(
    channel: str,
    thread_name: str,
    content: str = "",
    *,
    message_id: str | None = None,
    cogent_name: str | None = None,
    region: str | None = None,
) -> None:
    """Enqueue creation of a new Discord thread."""
    name = cogent_name or os.environ["COGENT_NAME"]
    rgn = region or os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url(name, rgn)

    body: dict = {"type": "thread_create", "channel": channel, "thread_name": thread_name}
    if content:
        body["content"] = content
    if message_id:
        body["message_id"] = message_id

    _send(url, body, rgn)
    logger.debug("Queued thread '%s' on channel %s", thread_name, channel)


async def queue_dm(
    user_id: str,
    content: str,
    *,
    cogent_name: str | None = None,
    region: str | None = None,
) -> None:
    """Enqueue a direct message to a Discord user."""
    name = cogent_name or os.environ["COGENT_NAME"]
    rgn = region or os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url(name, rgn)

    body = {"type": "dm", "user_id": user_id, "content": content}
    _send(url, body, rgn)
    logger.debug("Queued DM to user %s", user_id)
```

**Step 4: Run tests**

```bash
pytest tests/channels/test_discord_reply.py -v
```

Expected: All 6 tests pass.

**Step 5: Commit**

```bash
git add src/channels/discord/reply.py tests/channels/test_discord_reply.py
git commit -m "feat(channels): add Discord SQS reply helpers"
```

---

### Task 3: Message chunking utility

The bridge needs to split messages exceeding Discord's 2000 char limit. This is a pure function — easy to test in isolation before the bridge itself.

**Files:**
- Create: `src/channels/discord/chunking.py`
- Create: `tests/channels/test_discord_chunking.py`

**Step 1: Write the failing tests**

Create `tests/channels/test_discord_chunking.py`:

```python
"""Tests for Discord message chunking."""

from channels.discord.chunking import chunk_message, DISCORD_MAX_LENGTH


class TestChunkMessage:
    def test_empty_returns_empty(self):
        assert chunk_message("") == []

    def test_short_message_unchanged(self):
        assert chunk_message("hello") == ["hello"]

    def test_exact_limit_unchanged(self):
        msg = "a" * DISCORD_MAX_LENGTH
        assert chunk_message(msg) == [msg]

    def test_splits_on_newline(self):
        # 1500 chars + newline + 1500 chars = 3001 total
        part1 = "a" * 1500
        part2 = "b" * 1500
        msg = part1 + "\n" + part2
        chunks = chunk_message(msg)
        assert len(chunks) == 2
        assert chunks[0] == part1
        assert chunks[1] == part2

    def test_splits_on_space_when_no_newline(self):
        part1 = "a" * 1500
        part2 = "b" * 1500
        msg = part1 + " " + part2
        chunks = chunk_message(msg)
        assert len(chunks) == 2
        assert chunks[0] == part1

    def test_hard_split_when_no_whitespace(self):
        msg = "a" * 4500
        chunks = chunk_message(msg)
        assert len(chunks) == 3
        assert chunks[0] == "a" * DISCORD_MAX_LENGTH
        assert chunks[1] == "a" * DISCORD_MAX_LENGTH
        assert chunks[2] == "a" * 500

    def test_strips_leading_newlines_after_split(self):
        part1 = "a" * 1999
        msg = part1 + "\n\n\nrest"
        chunks = chunk_message(msg)
        assert chunks[0] == part1
        assert chunks[1] == "rest"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/channels/test_discord_chunking.py -v
```

Expected: FAIL — module not found.

**Step 3: Write the implementation**

Create `src/channels/discord/chunking.py`:

```python
"""Split messages to fit within Discord's 2000-character limit."""

from __future__ import annotations

DISCORD_MAX_LENGTH = 2000


def chunk_message(content: str) -> list[str]:
    """Split content into chunks that fit Discord's message limit.

    Prefers splitting on newlines, then spaces, then hard cuts.
    """
    if not content:
        return []
    if len(content) <= DISCORD_MAX_LENGTH:
        return [content]

    chunks: list[str] = []
    while content:
        if len(content) <= DISCORD_MAX_LENGTH:
            chunks.append(content)
            break

        split_at = content.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if split_at <= 0:
            split_at = content.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if split_at <= 0:
            split_at = DISCORD_MAX_LENGTH

        chunks.append(content[:split_at])
        content = content[split_at:].lstrip("\n")

    return chunks
```

**Step 4: Run tests**

```bash
pytest tests/channels/test_discord_chunking.py -v
```

Expected: All 7 tests pass.

**Step 5: Commit**

```bash
git add src/channels/discord/chunking.py tests/channels/test_discord_chunking.py
git commit -m "feat(channels): add Discord message chunking utility"
```

---

### Task 4: Discord Bridge service (`bridge.py`)

The main bridge service. Connects to Discord Gateway, relays inbound messages to EventBridge with rich metadata, and long-polls SQS for outbound replies.

**Files:**
- Create: `src/channels/discord/bridge.py`
- Create: `tests/channels/test_discord_bridge.py`

**Reference:** The original bridge is at `/Users/daveey/code/cogents.3/src/body/lambdas/discord_bridge/bridge.py` (468 lines). Port it with these changes:
- Use `channels.access.get_channel_token()` for token (already exists in cogents.2)
- Import `chunk_message` from `channels.discord.chunking` (Task 3)
- Keep the same `_get_queue_url` pattern as `reply.py` for SQS URL

**Step 1: Write the failing tests**

Create `tests/channels/test_discord_bridge.py`:

```python
"""Tests for the Discord bridge service."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from channels.discord.bridge import DiscordBridge, _make_event_detail
from channels.discord.chunking import DISCORD_MAX_LENGTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_discord_message(
    content="hello",
    author_name="testuser",
    author_id=42,
    channel_id=100,
    message_id=999,
    guild_id=200,
    is_dm=False,
    is_mention=False,
    attachments=None,
    embeds=None,
    reference=None,
):
    """Build a mock discord.Message."""
    msg = MagicMock()
    msg.content = content
    msg.id = message_id
    msg.created_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"
    msg.jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    msg.author = MagicMock()
    msg.author.__str__ = lambda self: author_name
    msg.author.id = author_id

    msg.channel = MagicMock()
    msg.channel.id = channel_id

    if is_dm:
        import discord
        msg.channel.__class__ = discord.DMChannel
        msg.guild = None
    else:
        msg.guild = MagicMock()
        msg.guild.id = guild_id

    msg.attachments = attachments or []
    msg.embeds = embeds or []
    msg.reference = reference

    return msg, is_mention


# ---------------------------------------------------------------------------
# Tests: event detail construction
# ---------------------------------------------------------------------------

class TestMakeEventDetail:
    def test_basic_message_fields(self):
        msg, _ = _make_discord_message()
        detail = _make_event_detail(msg, "discord:channel.message", is_dm=False, is_mention=False)
        assert detail["source"] == "discord"
        assert detail["payload"]["content"] == "hello"
        assert detail["payload"]["author"] == "testuser"
        assert detail["payload"]["event_type"] == "discord:channel.message"

    def test_dm_fields(self):
        msg, _ = _make_discord_message(is_dm=True)
        detail = _make_event_detail(msg, "discord:dm", is_dm=True, is_mention=False)
        assert detail["payload"]["is_dm"] is True
        assert detail["payload"]["guild_id"] is None

    def test_attachment_metadata(self):
        att = MagicMock()
        att.url = "https://cdn.discord.com/file.png"
        att.filename = "file.png"
        att.content_type = "image/png"
        att.size = 1024
        att.width = 100
        att.height = 200
        msg, _ = _make_discord_message(attachments=[att])
        detail = _make_event_detail(msg, "discord:channel.message", is_dm=False, is_mention=False)
        atts = detail["payload"]["attachments"]
        assert len(atts) == 1
        assert atts[0]["is_image"] is True
        assert atts[0]["width"] == 100


# ---------------------------------------------------------------------------
# Tests: bridge inbound
# ---------------------------------------------------------------------------

class TestBridgeInbound:
    @pytest.fixture
    def bridge(self):
        """Create a bridge with mocked AWS and Discord clients."""
        with (
            patch("channels.discord.bridge.get_channel_token", return_value="fake-token"),
            patch("channels.discord.bridge.boto3") as mock_boto3,
        ):
            eb = MagicMock()
            eb.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{}]}
            sqs = MagicMock()
            mock_boto3.client.side_effect = lambda svc, **kw: eb if svc == "events" else sqs

            b = DiscordBridge.__new__(DiscordBridge)
            b.cogent_name = "test"
            b.bot_token = "fake-token"
            b.event_bus_name = "cogent-test-bus"
            b.reply_queue_url = ""
            b.region = "us-east-1"
            b._eb_client = eb
            b._sqs_client = sqs
            b._typing_tasks = {}
            b.client = MagicMock()
            b.client.user = MagicMock()
            b.client.user.id = 1
            b.client.user.mentioned_in = MagicMock(return_value=False)
            yield b

    async def test_relay_publishes_to_eventbridge(self, bridge):
        msg, _ = _make_discord_message()
        # Patch isinstance check for DMChannel
        with patch("channels.discord.bridge.isinstance", side_effect=lambda obj, cls: False):
            pass
        bridge.client.user.mentioned_in.return_value = False
        await bridge._relay_to_eventbridge(msg)
        bridge._eb_client.put_events.assert_called_once()
        entry = bridge._eb_client.put_events.call_args[1]["Entries"][0]
        assert entry["DetailType"] == "discord:channel.message"
        assert entry["EventBusName"] == "cogent-test-bus"


# ---------------------------------------------------------------------------
# Tests: bridge outbound
# ---------------------------------------------------------------------------

class TestBridgeOutbound:
    async def test_handle_message_sends_text(self):
        """Verify _handle_message sends content to the channel."""
        from channels.discord.bridge import DiscordBridge

        bridge = MagicMock(spec=DiscordBridge)
        bridge._stop_typing = MagicMock()
        bridge._download_files = AsyncMock(return_value=[])

        channel = AsyncMock()
        channel.id = 100

        body = {"content": "hi there", "channel": "100"}
        await DiscordBridge._handle_message(bridge, body, channel)
        channel.send.assert_called()

    async def test_handle_reaction(self):
        """Verify _handle_reaction adds emoji to message."""
        from channels.discord.bridge import DiscordBridge

        bridge = MagicMock(spec=DiscordBridge)
        channel = AsyncMock()
        fetched_msg = AsyncMock()
        channel.fetch_message.return_value = fetched_msg

        body = {"message_id": "999", "emoji": "👍"}
        await DiscordBridge._handle_reaction(bridge, body, channel)
        fetched_msg.add_reaction.assert_called_once_with("👍")
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/channels/test_discord_bridge.py -v
```

Expected: FAIL — `channels.discord.bridge` does not exist.

**Step 3: Write the implementation**

Create `src/channels/discord/bridge.py`:

```python
"""Discord bridge: bidirectional relay between Discord Gateway and EventBridge/SQS.

Runs as a standalone service (ECS Fargate). Connects to the Discord gateway,
relays inbound messages to EventBridge, and long-polls an SQS queue for
outbound replies to send back to Discord.

Supports:
  - Inbound: text, attachments (images/files), threads, embeds, reply refs
  - Outbound: text, file uploads, thread replies, reactions, DMs, thread creation
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os

import aiohttp
import boto3
import discord

from channels.access import get_channel_token
from channels.discord.chunking import chunk_message

logger = logging.getLogger(__name__)


def _make_event_detail(
    message: discord.Message,
    event_type: str,
    *,
    is_dm: bool,
    is_mention: bool,
) -> dict:
    """Build the EventBridge detail dict from a Discord message."""
    attachments = []
    for a in message.attachments:
        attachments.append({
            "url": a.url,
            "filename": a.filename,
            "content_type": a.content_type,
            "size": a.size,
            "is_image": a.content_type.startswith("image/") if a.content_type else False,
            "width": a.width,
            "height": a.height,
        })

    thread_id = None
    parent_channel_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
        parent_channel_id = str(message.channel.parent_id)

    embeds = []
    for e in message.embeds:
        embed_data: dict = {"type": e.type}
        if e.title:
            embed_data["title"] = e.title
        if e.description:
            embed_data["description"] = e.description
        if e.url:
            embed_data["url"] = e.url
        if e.image:
            embed_data["image_url"] = e.image.url
        embeds.append(embed_data)

    return {
        "event_id": str(message.id),
        "payload": {
            "content": message.content,
            "author": str(message.author),
            "author_id": str(message.author.id),
            "channel_id": str(message.channel.id),
            "guild_id": str(message.guild.id) if message.guild else None,
            "message_id": str(message.id),
            "event_type": event_type,
            "is_dm": is_dm,
            "is_mention": is_mention,
            "attachments": attachments,
            "thread_id": thread_id,
            "parent_channel_id": parent_channel_id,
            "embeds": embeds,
            "reference_message_id": (
                str(message.reference.message_id) if message.reference else None
            ),
        },
        "source": "discord",
        "context_key": f"discord:{message.channel.id}:{message.author.id}",
        "created_at": message.created_at.isoformat(),
    }


class DiscordBridge:
    """Relays Discord messages to EventBridge and SQS replies back to Discord."""

    def __init__(self):
        self.cogent_name = os.environ["COGENT_NAME"]
        self.bot_token = self._get_bot_token()
        self.event_bus_name = os.environ.get(
            "EVENT_BUS_NAME",
            f"cogent-{self.cogent_name.replace('.', '-')}-bus",
        )
        self.reply_queue_url = os.environ.get(
            "DISCORD_REPLY_QUEUE_URL",
            os.environ.get("REPLY_QUEUE_URL", ""),
        )
        self.region = os.environ.get("AWS_REGION", "us-east-1")

        self._eb_client = boto3.client("events", region_name=self.region)
        self._sqs_client = boto3.client("sqs", region_name=self.region)
        self._typing_tasks: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _get_bot_token(self) -> str:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return token
        token = get_channel_token(self.cogent_name, "discord")
        if not token:
            raise RuntimeError(
                f"No Discord token for {self.cogent_name}. "
                "Set DISCORD_BOT_TOKEN or provision via channels CLI."
            )
        return token

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    def _setup_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bridge connected as %s", self.client.user)
            self.client.loop.create_task(self._poll_replies())

        @self.client.event
        async def on_message(message: discord.Message):
            if message.author == self.client.user:
                return
            await self._relay_to_eventbridge(message)

    async def _relay_to_eventbridge(self, message: discord.Message):
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        if is_dm:
            event_type = "discord:dm"
        elif is_mention:
            event_type = "discord:mention"
        else:
            event_type = "discord:channel.message"

        detail = _make_event_detail(message, event_type, is_dm=is_dm, is_mention=is_mention)

        try:
            response = self._eb_client.put_events(
                Entries=[{
                    "Source": f"cogent.{self.cogent_name}",
                    "DetailType": event_type,
                    "Detail": json.dumps(detail),
                    "EventBusName": self.event_bus_name,
                }]
            )
            failed = response.get("FailedEntryCount", 0)
            if failed:
                entries = response.get("Entries", [])
                err = entries[0].get("ErrorMessage", "unknown") if entries else "unknown"
                logger.error("EventBridge put failed for message %s: %s", message.id, err)
            else:
                logger.debug("Relayed %s from %s", event_type, message.author)
                if event_type in ("discord:dm", "discord:mention"):
                    self._start_typing(message.channel)
        except Exception:
            logger.exception("Failed to relay message %s to EventBridge", message.id)

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    def _start_typing(self, channel: discord.abc.Messageable):
        channel_id = channel.id
        old = self._typing_tasks.pop(channel_id, None)
        if old and not old.done():
            old.cancel()

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(300)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Typing indicator error for channel %s", channel_id, exc_info=True)

        self._typing_tasks[channel_id] = asyncio.create_task(_keep_typing())

    def _stop_typing(self, channel_id: int):
        task = self._typing_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # SQS reply poller
    # ------------------------------------------------------------------

    async def _poll_replies(self):
        if not self.reply_queue_url:
            logger.warning("No reply queue URL set, reply polling disabled")
            return

        logger.info("Starting SQS reply poller on %s", self.reply_queue_url)
        loop = asyncio.get_event_loop()

        while True:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self._sqs_client.receive_message(
                        QueueUrl=self.reply_queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,
                    ),
                )
                for msg in response.get("Messages", []):
                    try:
                        await self._send_reply(msg)
                    except Exception:
                        logger.exception("Failed to send reply: %s", msg.get("MessageId"))
                        continue
                    try:
                        self._sqs_client.delete_message(
                            QueueUrl=self.reply_queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                    except Exception:
                        logger.exception("Failed to delete SQS message %s", msg.get("MessageId"))
            except Exception:
                logger.exception("Reply poll error")
                await asyncio.sleep(5)

    async def _send_reply(self, sqs_message: dict):
        body = json.loads(sqs_message["Body"])
        msg_type = body.get("type", "message")

        if msg_type == "dm":
            await self._handle_dm(body)
            return

        channel_id = int(body["channel"])
        self._stop_typing(channel_id)

        channel = self.client.get_channel(channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)
        if channel is None:
            logger.error("Could not find Discord channel %s", channel_id)
            return

        if msg_type == "reaction":
            await self._handle_reaction(body, channel)
        elif msg_type == "thread_create":
            await self._handle_thread_create(body, channel)
        else:
            await self._handle_message(body, channel)

    async def _handle_message(self, body: dict, channel):
        content = body.get("content", "")
        file_specs = body.get("files") or []
        thread_id = body.get("thread_id")
        reply_to = body.get("reply_to")

        target = channel
        if thread_id:
            thread = self.client.get_channel(int(thread_id))
            if thread is None:
                try:
                    thread = await self.client.fetch_channel(int(thread_id))
                except Exception:
                    logger.warning("Could not find thread %s, falling back to channel", thread_id)
            if thread:
                target = thread

        reference = None
        if reply_to:
            reference = discord.MessageReference(message_id=int(reply_to), channel_id=target.id)

        discord_files = await self._download_files(file_specs)

        if discord_files:
            first_chunk = content[:2000] if content else None
            await target.send(content=first_chunk, files=discord_files, reference=reference)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for chunk in chunk_message(remaining):
                await target.send(chunk)
        elif content:
            chunks = chunk_message(content)
            await target.send(chunks[0], reference=reference)
            for chunk in chunks[1:]:
                await target.send(chunk)

        logger.debug("Sent reply to channel %s (%d chars, %d files)", channel.id, len(content), len(discord_files))

    async def _handle_reaction(self, body: dict, channel):
        message_id = body.get("message_id")
        emoji = body.get("emoji")
        if not message_id or not emoji:
            logger.warning("Reaction missing message_id or emoji: %s", body)
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
        except Exception:
            logger.exception("Failed to add reaction %s to message %s", emoji, message_id)

    async def _handle_thread_create(self, body: dict, channel):
        thread_name = body.get("thread_name", "Thread")
        message_id = body.get("message_id")
        content = body.get("content", "")

        try:
            if message_id:
                message = await channel.fetch_message(int(message_id))
                thread = await message.create_thread(name=thread_name)
            else:
                thread = await channel.create_thread(
                    name=thread_name, type=discord.ChannelType.public_thread,
                )
            if content:
                for chunk in chunk_message(content):
                    await thread.send(chunk)
        except Exception:
            logger.exception("Failed to create thread '%s' in channel %s", thread_name, channel.id)

    async def _handle_dm(self, body: dict):
        user_id = body.get("user_id")
        content = body.get("content", "")
        if not user_id or not content:
            logger.warning("DM missing user_id or content: %s", body)
            return
        try:
            user = await self.client.fetch_user(int(user_id))
            dm_channel = await user.create_dm()
            for chunk in chunk_message(content):
                await dm_channel.send(chunk)
            logger.debug("Sent DM to user %s (%d chars)", user_id, len(content))
        except Exception:
            logger.exception("Failed to send DM to user %s", user_id)

    async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
        if not file_specs:
            return []

        files = []
        async with aiohttp.ClientSession() as session:
            for spec in file_specs:
                url = spec.get("url")
                filename = spec.get("filename", "file")
                if not url:
                    continue
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            logger.warning("Failed to download %s: HTTP %d", url, resp.status)
                            continue
                        data = await resp.read()
                        files.append(discord.File(io.BytesIO(data), filename=filename))
                except Exception:
                    logger.exception("Failed to download file: %s", url)
        return files

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        self.client.run(self.bot_token, log_handler=None)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bridge = DiscordBridge()
    bridge.run()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/channels/test_discord_bridge.py -v
```

Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/channels/discord/bridge.py tests/channels/test_discord_bridge.py
git commit -m "feat(channels): add Discord bridge service"
```

---

### Task 5: Dockerfile and pyproject.toml wiring

Add the Dockerfile for Fargate deployment and the `discord-bridge` console script entry point.

**Files:**
- Create: `src/channels/discord/Dockerfile`
- Modify: `pyproject.toml:36-39` (add script entry point)

**Step 1: Create the Dockerfile**

Create `src/channels/discord/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

CMD ["discord-bridge"]
```

**Step 2: Add script entry point to `pyproject.toml`**

In the `[project.scripts]` section, add:

```
discord-bridge = "channels.discord.bridge:main"
```

So it becomes:

```toml
[project.scripts]
cogent = "cli.__main__:main"
mind = "mind.cli:mind"
polis = "polis.cli:polis"
discord-bridge = "channels.discord.bridge:main"
```

**Step 3: Verify the entry point resolves**

```bash
python -c "from channels.discord.bridge import main; print('OK')"
```

Expected: prints `OK`.

**Step 4: Run all channel tests**

```bash
pytest tests/channels/ -v
```

Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/channels/discord/Dockerfile pyproject.toml
git commit -m "feat(channels): add Discord bridge Dockerfile and entry point"
```

---

### Task 6: Update discord `__init__.py` exports and final integration

Update the discord package exports to expose the bridge and reply helpers. Verify everything works together.

**Files:**
- Modify: `src/channels/discord/__init__.py`

**Step 1: Update `src/channels/discord/__init__.py`**

```python
"""Discord bridge: standalone relay between Discord Gateway and EventBridge/SQS."""

from channels.discord.bridge import DiscordBridge
from channels.discord.reply import queue_reply, queue_reaction, queue_thread_create, queue_dm
from channels.discord.chunking import chunk_message

__all__ = [
    "DiscordBridge",
    "queue_reply",
    "queue_reaction",
    "queue_thread_create",
    "queue_dm",
    "chunk_message",
]
```

**Step 2: Run all tests**

```bash
pytest tests/channels/ -v
```

Expected: All tests pass.

**Step 3: Verify imports work**

```bash
python -c "from channels.discord import DiscordBridge, queue_reply, chunk_message; print('All imports OK')"
```

Expected: prints `All imports OK`.

**Step 4: Commit**

```bash
git add src/channels/discord/__init__.py
git commit -m "feat(channels): wire up Discord bridge package exports"
```
