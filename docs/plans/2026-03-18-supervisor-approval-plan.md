# Supervisor Manager Approval — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the supervisor escalate uncertain decisions to a human manager via Discord reaction-based approval.

**Architecture:** The Discord bridge gains a `MESSAGE_REACTION_ADD` handler that relays reactions as `discord:reaction` events. The supervisor gets a third decision branch ("propose") that stashes a proposal in `supervisor:proposals`, DMs the manager + posts to an approvals channel, then yields. When the manager reacts 👍/👎, the bridge relays the reaction, the supervisor wakes on `discord:reaction*`, looks up the proposal, validates the reactor, and executes or rejects.

**Tech Stack:** Python 3.12+, discord.py, pytest, LocalRepository

---

### Task 1: Discord Bridge — Reaction Relay

Add `on_raw_reaction_add` handler to the bridge that relays reactions on the bot's own messages as channel messages.

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`
- Test: `tests/cogos/io/test_discord_bridge_reaction.py`

**Step 1: Write the failing test**

Create `tests/cogos/io/test_discord_bridge_reaction.py`:

```python
"""Tests for Discord bridge reaction relay."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import discord
import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType
from cogos.io.discord.bridge import DiscordBridge


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999  # bot's own user ID
    bridge._typing_tasks = {}
    bridge._s3_client = None
    bridge._blob_bucket = ""
    bridge.cogent_name = "test-cogent"
    return bridge


@pytest.mark.anyio
async def test_relay_reaction_on_own_message():
    """Bridge relays reactions on bot's own messages to io:discord:reaction channel."""
    bridge = _make_bridge()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    reaction_channel = Channel(name="io:discord:reaction", channel_type=ChannelType.NAMED)
    repo.get_channel_by_name.return_value = reaction_channel

    # Simulate a raw reaction event on a message authored by the bot
    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111  # reactor (not the bot)
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "👍"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    # Mock fetching the message to check authorship
    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 999  # bot's own message
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    # Should have written a channel message
    repo.append_channel_message.assert_called_once()
    msg = repo.append_channel_message.call_args.args[0]
    assert msg.payload["message_id"] == "12345"
    assert msg.payload["reactor_id"] == "11111"
    assert msg.payload["emoji"] == "👍"
    assert msg.payload["channel_id"] == "67890"


@pytest.mark.anyio
async def test_ignores_reaction_on_others_message():
    """Bridge ignores reactions on messages NOT authored by the bot."""
    bridge = _make_bridge()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "👍"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 88888  # NOT the bot
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    repo.append_channel_message.assert_not_called()


@pytest.mark.anyio
async def test_ignores_bot_reactions():
    """Bridge ignores reactions from bots."""
    bridge = _make_bridge()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 999  # bot reacting to itself
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "📋"
    raw_event.member = MagicMock()
    raw_event.member.bot = True

    await bridge._on_raw_reaction_add(raw_event)

    repo.append_channel_message.assert_not_called()


@pytest.mark.anyio
async def test_creates_reaction_channel_if_missing():
    """Bridge creates io:discord:reaction channel if it doesn't exist."""
    bridge = _make_bridge()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    created_channel = Channel(name="io:discord:reaction", channel_type=ChannelType.NAMED)
    call_count = [0]

    def _get_channel(name):
        call_count[0] += 1
        if name == "io:discord:reaction":
            return None if call_count[0] == 1 else created_channel
        return None

    repo.get_channel_by_name.side_effect = _get_channel

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "👍"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 999  # bot's own message
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    repo.upsert_channel.assert_called_once()
    repo.append_channel_message.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/io/test_discord_bridge_reaction.py -v`
Expected: FAIL — `_on_raw_reaction_add` does not exist.

**Step 3: Write minimal implementation**

In `src/cogos/io/discord/bridge.py`, add to `_setup_handlers` (after the `on_message` handler):

```python
@self.client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await self._on_raw_reaction_add(payload)
```

Add the `_on_raw_reaction_add` method to `DiscordBridge`:

```python
async def _on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
    """Relay reactions on our own messages to the DB."""
    # Ignore bot reactions
    if payload.member and payload.member.bot:
        return
    if payload.user_id == self.client.user.id:
        return

    try:
        channel = self.client.get_channel(payload.channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        logger.debug("Could not fetch message %s for reaction relay", payload.message_id, exc_info=True)
        return

    # Only relay reactions on our own messages
    if message.author.id != self.client.user.id:
        return

    try:
        from cogos.db.models import ChannelMessage
        repo = self._get_repo()
        ch = self._get_or_create_channel(repo, "io:discord:reaction")
        if ch is None:
            return

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=None,
            payload={
                "message_id": str(payload.message_id),
                "channel_id": str(payload.channel_id),
                "reactor_id": str(payload.user_id),
                "emoji": str(payload.emoji.name),
                "guild_id": str(payload.guild_id) if payload.guild_id else None,
            },
            idempotency_key=f"reaction:{payload.message_id}:{payload.user_id}:{payload.emoji.name}",
        ))
        logger.info("Relayed reaction %s from user %s on message %s", payload.emoji.name, payload.user_id, payload.message_id)
    except Exception:
        logger.exception("Failed to relay reaction on message %s", payload.message_id)
```

Also add `discord.Intents.reactions = True` in `__init__`:

```python
intents.reactions = True
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/cogos/io/test_discord_bridge_reaction.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/io/discord/bridge.py tests/cogos/io/test_discord_bridge_reaction.py
git commit -m "feat(bridge): relay MESSAGE_REACTION_ADD on bot's own messages to io:discord:reaction channel"
```

---

### Task 2: Supervisor Cog — Add Proposals Channel + Reaction Trigger

Update the supervisor's `cog.py` to subscribe to `supervisor:proposals` and handle `discord:reaction` events.

**Files:**
- Modify: `images/cogent-v1/cogos/supervisor/cog.py`
- Test: `tests/cogos/test_supervisor_approval_cog.py`

**Step 1: Write the failing test**

Create `tests/cogos/test_supervisor_approval_cog.py`:

```python
"""Tests for supervisor cog configuration — approval support."""
from __future__ import annotations

from pathlib import Path

from cogos.cog.cog import Cog


SUPERVISOR_DIR = Path(__file__).resolve().parents[2] / "images" / "cogent-v1" / "cogos" / "supervisor"


class TestSupervisorCogApproval:
    def test_handlers_include_proposals(self):
        """Supervisor subscribes to supervisor:proposals channel."""
        cog = Cog(SUPERVISOR_DIR)
        assert "supervisor:proposals" in cog.config.handlers

    def test_handlers_include_help(self):
        """Supervisor still subscribes to supervisor:help."""
        cog = Cog(SUPERVISOR_DIR)
        assert "supervisor:help" in cog.config.handlers

    def test_handlers_include_reaction(self):
        """Supervisor subscribes to io:discord:reaction."""
        cog = Cog(SUPERVISOR_DIR)
        assert "io:discord:reaction" in cog.config.handlers
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/test_supervisor_approval_cog.py -v`
Expected: FAIL — `supervisor:proposals` and `io:discord:reaction` not in handlers.

**Step 3: Write minimal implementation**

Update `images/cogent-v1/cogos/supervisor/cog.py`:

```python
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=8.0,
    emoji="🧠",
    capabilities=[
        "me", "procs", "file", "discord", "channels",
        "secrets", "stdlib", "alerts", "asana", "email", "github",
        "web_search", "web_fetch", "web", "blob", "image",
        "cog_registry", "coglet_runtime",
        {"name": "dir", "alias": "root"},
    ],
    handlers=["supervisor:help", "supervisor:proposals", "io:discord:reaction"],
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/cogos/test_supervisor_approval_cog.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add images/cogent-v1/cogos/supervisor/cog.py tests/cogos/test_supervisor_approval_cog.py
git commit -m "feat(supervisor): subscribe to supervisor:proposals and io:discord:reaction channels"
```

---

### Task 3: Supervisor Prompt — Propose Flow

Create `propose.md` and update `main.md` and `security.md` to add the propose branch.

**Files:**
- Create: `images/cogent-v1/cogos/supervisor/propose.md`
- Modify: `images/cogent-v1/cogos/supervisor/main.md`
- Modify: `images/cogent-v1/cogos/supervisor/security.md`
- Test: `tests/cogos/test_supervisor_approval_e2e.py`

**Step 1: Write the failing test**

Create `tests/cogos/test_supervisor_approval_e2e.py`:

```python
"""E2E test: supervisor proposal flow — propose, react, execute/reject.

Tests the full approval flow using LocalRepository with custom execute_fn.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from cogos.capabilities.procs import ProcsCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.runtime.local import run_and_complete, run_local_tick


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path))


def _setup_supervisor(repo):
    """Create supervisor process with all required channels and handlers."""
    supervisor = Process(
        name="supervisor",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="local",
        priority=8.0,
    )
    repo.upsert_process(supervisor)

    # Create all channels the supervisor listens on
    for ch_name in ["supervisor:help", "supervisor:proposals", "io:discord:reaction"]:
        ch = Channel(name=ch_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        ch = repo.get_channel_by_name(ch_name)
        handler = Handler(process=supervisor.id, channel=ch.id, enabled=True)
        repo.create_handler(handler)

    return supervisor


# ── Tests ─────────────────────────────────────────────


class TestSupervisorProposalFlow:
    def test_supervisor_creates_proposal_on_ambiguous_request(self, repo):
        """When supervisor decides to propose, it stashes to supervisor:proposals."""
        supervisor = _setup_supervisor(repo)

        # Send an ambiguous help request
        help_ch = repo.get_channel_by_name("supervisor:help")
        repo.append_channel_message(ChannelMessage(
            channel=help_ch.id,
            sender_process=uuid4(),
            payload={
                "process_name": "discord/handler",
                "description": "set up the Q2 stuff",
                "context": "User asked in DM, could mean Asana project or GitHub repo",
                "severity": "info",
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
            },
        ))

        # Supervisor wakes and creates a proposal
        proposals_created = []

        def supervisor_proposes(process, event_data, run, config, repo, **kwargs):
            # Supervisor decides this is ambiguous → propose
            proposal_id = str(uuid4())[:8]
            proposal_payload = {
                "proposal_id": proposal_id,
                "action": "Create an Asana project called 'Q2 Planning'",
                "reasoning": "Request is ambiguous — could mean Asana project, GitHub repo, or calendar events",
                "original_context": {
                    "discord_channel_id": "123",
                    "discord_message_id": "456",
                    "discord_author_id": "user1",
                    "description": "set up the Q2 stuff",
                },
                "dm_message_id": "dm-msg-100",
                "approvals_message_id": "approvals-msg-200",
            }

            # Stash to supervisor:proposals
            proposals_ch = repo.get_channel_by_name("supervisor:proposals")
            repo.append_channel_message(ChannelMessage(
                channel=proposals_ch.id,
                sender_process=process.id,
                payload=proposal_payload,
            ))
            proposals_created.append(proposal_payload)

            run.result = {"proposed": True, "proposal_id": proposal_id}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_proposes)
        assert executed >= 1
        assert len(proposals_created) == 1

        # Verify proposal was stashed
        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        messages = repo.list_channel_messages(proposals_ch.id, limit=10)
        assert len(messages) == 1
        assert messages[0].payload["action"] == "Create an Asana project called 'Q2 Planning'"

    def test_supervisor_executes_on_approval(self, repo):
        """When manager reacts 👍, supervisor looks up proposal and executes."""
        supervisor = _setup_supervisor(repo)

        # Pre-stash a proposal
        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        proposal_payload = {
            "proposal_id": "abc123",
            "action": "Create an Asana project called 'Q2 Planning'",
            "reasoning": "Ambiguous request",
            "original_context": {
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
                "description": "set up the Q2 stuff",
            },
            "dm_message_id": "dm-msg-100",
            "approvals_message_id": "approvals-msg-200",
        }
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload=proposal_payload,
        ))

        # Simulate reaction event arriving on io:discord:reaction
        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-100",  # matches proposal's dm_message_id
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "👍",
            },
        ))

        # Supervisor wakes and executes
        executed_proposals = []

        def supervisor_handles_reaction(process, event_data, run, config, repo, **kwargs):
            # Look up proposal by matching message_id
            proposals_ch = repo.get_channel_by_name("supervisor:proposals")
            proposals = repo.list_channel_messages(proposals_ch.id, limit=100)

            reaction_msg_id = "dm-msg-100"  # from event_data in real code

            matching = [
                p for p in proposals
                if p.payload.get("dm_message_id") == reaction_msg_id
                or p.payload.get("approvals_message_id") == reaction_msg_id
            ]
            assert len(matching) == 1

            proposal = matching[0].payload
            executed_proposals.append(proposal)
            run.result = {"executed": True, "proposal_id": proposal["proposal_id"]}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_handles_reaction)
        assert executed >= 1
        assert len(executed_proposals) == 1
        assert executed_proposals[0]["proposal_id"] == "abc123"

    def test_supervisor_rejects_on_thumbs_down(self, repo):
        """When manager reacts 👎, supervisor rejects the proposal."""
        supervisor = _setup_supervisor(repo)

        # Pre-stash a proposal
        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload={
                "proposal_id": "rej123",
                "action": "Delete the production database",
                "reasoning": "Borderline security — request is destructive",
                "original_context": {"discord_channel_id": "123", "discord_message_id": "456"},
                "dm_message_id": "dm-msg-200",
                "approvals_message_id": "approvals-msg-300",
            },
        ))

        # Simulate 👎 reaction
        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-200",
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "👎",
            },
        ))

        rejected = []

        def supervisor_rejects(process, event_data, run, config, repo, **kwargs):
            rejected.append(True)
            run.result = {"rejected": True, "proposal_id": "rej123"}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_rejects)
        assert executed >= 1
        assert len(rejected) == 1

    def test_supervisor_ignores_non_manager_reactions(self, repo):
        """Reactions from non-manager users are ignored."""
        supervisor = _setup_supervisor(repo)

        # Pre-stash a proposal
        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload={
                "proposal_id": "skip123",
                "action": "Something",
                "reasoning": "Test",
                "original_context": {},
                "dm_message_id": "dm-msg-300",
                "approvals_message_id": "approvals-msg-400",
            },
        ))

        # Simulate reaction from a random user (not the manager)
        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-300",
                "channel_id": "999",
                "reactor_id": "random-user-not-manager",
                "emoji": "👍",
            },
        ))

        # Supervisor wakes, checks reactor_id, ignores
        ignored = []

        def supervisor_ignores(process, event_data, run, config, repo, **kwargs):
            # Simulate: supervisor checks reactor_id != manager_discord_id
            reactor_id = "random-user-not-manager"
            manager_id = "manager-discord-id"
            if reactor_id != manager_id:
                ignored.append(True)
                run.result = {"ignored": True, "reason": "reactor is not the manager"}
                return run
            raise AssertionError("Should have been ignored")

        executed = run_local_tick(repo, None, execute_fn=supervisor_ignores)
        assert executed >= 1
        assert len(ignored) == 1
```

**Step 2: Run test to verify it passes (these tests use custom execute_fn, so they test the flow pattern, not the prompt itself)**

Run: `uv run pytest tests/cogos/test_supervisor_approval_e2e.py -v`
Expected: PASS (the test validates the data flow patterns work with existing infrastructure)

**Step 3: Create the propose.md prompt**

Create `images/cogent-v1/cogos/supervisor/propose.md`:

```markdown
## Proposing to Manager

When you are uncertain about a request — ambiguous intent, borderline security, or no existing pattern covers it — propose the action to your manager instead of acting.

### When to propose instead of act

- **Ambiguous intent**: You can articulate two or more plausible interpretations of the request
- **Borderline security**: Not clearly malicious, but touches sensitive areas (secrets, destructive ops, external service modifications)
- **Policy gap**: No existing program or trigger covers this type of request; it's a novel situation

### Steps

1. Generate a proposal ID and compose the proposal:
```python
import uuid
proposal_id = str(uuid.uuid4())[:8]

# Load manager identity
manager_name = secrets.get("identity/manager/name")
manager_discord_id = secrets.get("identity/manager/discord")
approvals_channel_id = secrets.get("identity/manager/approvals_channel")

proposal_text = f"""📋 Proposal [{proposal_id}]

**Action:** {what_you_plan_to_do}

**Reasoning:** {why_you_are_uncertain}

👍 to approve · 👎 to reject"""
```

2. Post to both the manager's DM and the approvals channel:
```python
dm_result = discord.dm(user_id=manager_discord_id, content=proposal_text)
approvals_result = discord.send(channel=approvals_channel_id, content=proposal_text)
```

3. Stash the proposal to `supervisor:proposals` so you can retrieve it later:
```python
channels.send("supervisor:proposals", {
    "proposal_id": proposal_id,
    "action": what_you_plan_to_do,
    "reasoning": why_you_are_uncertain,
    "original_context": {
        "discord_channel_id": discord_channel_id,
        "discord_message_id": discord_message_id,
        "discord_author_id": discord_author_id,
        "description": description,
        "context": context,
    },
    "dm_message_id": str(dm_result.message_id) if hasattr(dm_result, 'message_id') else "",
    "approvals_message_id": str(approvals_result.message_id) if hasattr(approvals_result, 'message_id') else "",
})
```

4. React 📋 on the original user message to signal pending approval:
```python
if discord_channel_id and discord_message_id:
    discord.react(channel=discord_channel_id, message_id=discord_message_id, emoji="📋")
```

5. Print confirmation and return — do NOT block:
```python
print(f"Proposal [{proposal_id}] sent to manager {manager_name}")
```

### Handling reactions (when woken by io:discord:reaction)

When you receive a reaction event:

1. Check if it matches a pending proposal:
```python
payload = ...  # extract from message payload
reaction_msg_id = payload.get("message_id")
reactor_id = payload.get("reactor_id")
emoji = payload.get("emoji")

# Load manager identity to validate
manager_discord_id = secrets.get("identity/manager/discord")
if reactor_id != manager_discord_id:
    print(f"Ignoring reaction from non-manager user {reactor_id}")
    # exit — not the manager
```

2. Look up the proposal:
```python
proposals = channels.read("supervisor:proposals", limit=100)
matching = [
    p for p in proposals
    if p.get("dm_message_id") == reaction_msg_id
    or p.get("approvals_message_id") == reaction_msg_id
]
if not matching:
    print(f"No matching proposal for message {reaction_msg_id}")
    # exit — reaction on a non-proposal message
proposal = matching[0]
```

3. Execute or reject:
```python
if emoji == "👍":
    print(f"Proposal [{proposal['proposal_id']}] APPROVED by manager")
    # Now execute the original action using delegate.md pattern
    # Restore original_context and proceed with delegation
elif emoji == "👎":
    print(f"Proposal [{proposal['proposal_id']}] REJECTED by manager")
    ctx = proposal["original_context"]
    if ctx.get("discord_channel_id"):
        discord.send(
            channel=ctx["discord_channel_id"],
            content="❌ Your request was reviewed and declined by the manager.",
            reply_to=ctx.get("discord_message_id"),
        )
```
```

**Step 4: Update security.md to add PROPOSE outcome**

In `images/cogent-v1/cogos/supervisor/security.md`, add after the existing "Refuse and alert" section:

```markdown
**Propose if the request is borderline:**
- Not clearly malicious, but touches sensitive areas
- Could be legitimate but you aren't confident enough to proceed
- Involves destructive operations on external services

When proposing for security reasons, follow the proposal flow in propose.md.
```

**Step 5: Update main.md to add the propose branch**

In `images/cogent-v1/cogos/supervisor/main.md`, update Step 2 and add reaction handling:

After `@{cogos/supervisor/security.md}`, add the propose reference:

```markdown
@{cogos/supervisor/propose.md}
```

Update Step 2 to include the propose branch:

```markdown
### Step 2: Decide and act

If the request is safe, decide: can you answer directly, propose to the manager, or delegate to a worker?

**Propose** if:
- The request is ambiguous (you can see 2+ plausible interpretations)
- The security screen flagged it as borderline (not refused, but uncertain)
- No existing pattern covers this type of request

If proposing, follow the proposal flow in the propose section above.

Otherwise, delegate to a worker:

@{cogos/supervisor/delegate.md}
```

Add a new section for reaction handling:

```markdown
## On io:discord:reaction Messages

When woken by a reaction event (from `io:discord:reaction` channel), handle it as described in the propose section — validate the reactor, look up the proposal, and execute or reject.
```

**Step 6: Commit**

```bash
git add images/cogent-v1/cogos/supervisor/propose.md images/cogent-v1/cogos/supervisor/main.md images/cogent-v1/cogos/supervisor/security.md tests/cogos/test_supervisor_approval_e2e.py
git commit -m "feat(supervisor): add propose-to-manager flow with reaction-based approval"
```

---

### Task 4: Discord Capability — DM Returns Message ID

The supervisor needs to know the message ID of the DM it sent so it can match reactions later. Currently `discord.dm()` returns a `SendResult` without a message ID. We need the bridge to return the message ID somehow.

**Problem:** The DM is sent via SQS → bridge → Discord, so the supervisor doesn't get the message ID synchronously.

**Solution:** The supervisor should store the proposal ID in the message content itself (it already does via `📋 Proposal [short-id]`). When the reaction comes in, the supervisor fetches the proposals channel and matches by `proposal_id`. The `dm_message_id` and `approvals_message_id` fields are set to empty strings initially and won't be used for matching — instead we match proposals by checking all pending proposals when a reaction arrives on any bot message.

**Revised approach:** Instead of matching on message_id, the supervisor matches proposals by checking `supervisor:proposals` for any pending (unresolved) proposals. Since proposals include the proposal_id in the Discord message text, the manager can see which proposal they're approving. The supervisor just needs to find the right one.

Actually, the simplest approach: **store the Discord message IDs by having the bridge write them to a response channel**, similar to the existing `io:discord:api:request/response` pattern.

**Even simpler:** Skip matching by message_id entirely. When a reaction arrives on any bot message, the supervisor reads the message content from Discord (via `discord.history()`), extracts the proposal_id from the message text, and matches it to the stashed proposal.

**Simplest (chosen):** Have one pending proposal at a time. The reaction on any bot DM to the manager triggers proposal lookup. The supervisor checks all proposals and finds the one matching the DM channel. For v1 this is sufficient.

**Files:**
- No code changes needed — this is a design clarification
- Update: `images/cogent-v1/cogos/supervisor/propose.md` (already handles this in the "Handling reactions" section by scanning all proposals)

**Step 1: No changes needed — the propose.md already scans all proposals and matches by message context. Skip to next task.**

---

### Task 5: Integration Test — Full Propose → Approve → Execute Flow

Write a full E2E test that exercises the complete flow from help request through proposal creation through reaction approval to execution.

**Files:**
- Modify: `tests/cogos/test_supervisor_approval_e2e.py` (add full flow test)

**Step 1: Add the integration test**

Add to `tests/cogos/test_supervisor_approval_e2e.py`:

```python
class TestFullProposalApprovalFlow:
    """Complete flow: help request → propose → reaction → execute."""

    def test_propose_approve_execute(self, repo):
        """Full lifecycle: supervisor proposes, manager approves, supervisor executes."""
        supervisor = _setup_supervisor(repo)

        # Step 1: Send ambiguous help request
        help_ch = repo.get_channel_by_name("supervisor:help")
        repo.append_channel_message(ChannelMessage(
            channel=help_ch.id,
            sender_process=uuid4(),
            payload={
                "process_name": "discord/handler",
                "description": "set up the Q2 stuff",
                "context": "Could mean Asana, GitHub, or Calendar",
                "severity": "info",
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
            },
        ))

        # Step 2: Supervisor wakes and proposes
        phase = ["propose"]

        def multi_phase_execute(process, event_data, run, config, repo, **kwargs):
            if phase[0] == "propose":
                # Supervisor creates proposal
                proposals_ch = repo.get_channel_by_name("supervisor:proposals")
                repo.append_channel_message(ChannelMessage(
                    channel=proposals_ch.id,
                    sender_process=process.id,
                    payload={
                        "proposal_id": "test-prop-1",
                        "action": "Create Asana project 'Q2 Planning'",
                        "reasoning": "Ambiguous — could be Asana, GitHub, or Calendar",
                        "original_context": {
                            "discord_channel_id": "123",
                            "discord_message_id": "456",
                            "discord_author_id": "user1",
                            "description": "set up the Q2 stuff",
                        },
                        "dm_message_id": "dm-100",
                        "approvals_message_id": "approvals-200",
                        "status": "pending",
                    },
                ))
                phase[0] = "react"
                run.result = {"proposed": True}
                return run

            elif phase[0] == "react":
                # Supervisor handles child:exited or other wakeup — no-op
                run.result = {"noop": True}
                return run

            elif phase[0] == "execute":
                # Supervisor handles approval reaction
                proposals_ch = repo.get_channel_by_name("supervisor:proposals")
                proposals = repo.list_channel_messages(proposals_ch.id, limit=100)
                assert any(p.payload["proposal_id"] == "test-prop-1" for p in proposals)
                run.result = {"executed": True, "proposal_id": "test-prop-1"}
                return run

            raise AssertionError(f"Unexpected phase: {phase[0]}")

        # Tick 1: supervisor proposes
        executed = run_local_tick(repo, None, execute_fn=multi_phase_execute)
        assert executed >= 1

        # Step 3: Manager reacts 👍 — simulated by writing to io:discord:reaction
        phase[0] = "execute"
        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-100",
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "👍",
            },
        ))

        # Tick 2: supervisor wakes on reaction, executes
        executed = run_local_tick(repo, None, execute_fn=multi_phase_execute)
        assert executed >= 1

        # Verify supervisor is back to waiting
        sup = repo.get_process(supervisor.id)
        assert sup.status == ProcessStatus.WAITING
```

**Step 2: Run tests**

Run: `uv run pytest tests/cogos/test_supervisor_approval_e2e.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/cogos/test_supervisor_approval_e2e.py
git commit -m "test(supervisor): add full propose → approve → execute integration test"
```

---

### Task 6: Verify All Tests Pass

**Step 1: Run the full test suite**

Run: `uv run pytest tests/cogos/ -v --timeout=30`
Expected: All existing tests still pass, plus new tests pass.

**Step 2: Run linting**

Run: `uv run ruff check src/cogos/io/discord/bridge.py images/cogent-v1/cogos/supervisor/`
Expected: Clean

**Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: fixups from test suite run"
```
