"""E2E test: Discord identity in whoami/profile.md.

Verifies:
1. Bridge writes cogent name + Discord user ID to profile on connect
2. Handler prompt expands profile and can filter by identity
3. Boot produces a profile with identity fields
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
)
from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path))


@pytest.fixture
def file_store(repo):
    return FileStore(repo)


def _grant_read_all(repo, process):
    """Grant a process read access to all files."""
    dir_cap = Capability(name="dir")
    repo.upsert_capability(dir_cap)
    repo.create_process_capability(
        ProcessCapability(
            process=process.id,
            capability=dir_cap.id,
            name="read_all",
            config={"ops": ["read"]},
        ),
    )


# ── Test 1: Bridge writes profile identity ────────────────


def test_bridge_writes_profile_identity(repo, file_store):
    """Bridge._update_profile_identity() writes name and Discord user ID to profile."""
    from cogos.io.discord.bridge import DiscordBridge

    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "dr.alpha"
    bridge._repo = repo

    # Mock Discord client with bot user
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 1234567890
    bridge.client.user.__str__ = lambda self: "dr.alpha#1234"

    bridge._update_profile_identity()

    content = file_store.get_content("whoami/profile.md")
    assert content is not None
    assert "dr.alpha" in content
    assert "1234567890" in content
    assert "dr.alpha#1234" in content


def test_bridge_updates_existing_profile(repo, file_store):
    """Bridge overwrites stale profile with fresh identity."""
    from cogos.io.discord.bridge import DiscordBridge

    # Write stale profile
    file_store.upsert(
        "whoami/profile.md",
        "# Profile\n\n- **Name:** (set on boot)\n- **Discord User ID:** (set on boot)\n",
        source="system",
    )

    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "dr.gamma"
    bridge._repo = repo
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 9876543210
    bridge.client.user.__str__ = lambda self: "dr.gamma#5678"

    bridge._update_profile_identity()

    content = file_store.get_content("whoami/profile.md")
    assert "dr.gamma" in content
    assert "9876543210" in content
    assert "(set on boot)" not in content


# ── Test 2: Handler prompt includes identity ──────────────


def test_handler_prompt_expands_profile_identity(repo, file_store):
    """Handler prompt expands @{whoami/index.md} → @{whoami/profile.md} with identity."""
    # Write identity files
    file_store.upsert(
        "whoami/profile.md",
        "# Profile\n\n"
        "- **Name:** dr.alpha\n"
        "- **Discord User ID:** 111222333\n"
        "- **Discord Username:** dr.alpha#1234\n",
        source="system",
    )
    file_store.upsert(
        "whoami/index.md",
        "# Identity\n\n@{whoami/profile.md}\n\nYou are a cogent.\n",
        source="system",
    )

    # Create handler process with @{whoami/index.md}
    handler = Process(
        name="discord/handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        content="@{whoami/index.md}\n\nYou are the Discord handler.",
    )
    repo.upsert_process(handler)
    _grant_read_all(repo, handler)

    # Expand the prompt
    engine = ContextEngine(file_store)
    prompt = engine.generate_full_prompt(handler)

    # Verify identity is in the expanded prompt
    assert "dr.alpha" in prompt
    assert "111222333" in prompt
    assert "dr.alpha#1234" in prompt
    assert "Discord handler" in prompt


# ── Test 3: Full boot produces profile with identity fields ─


def test_boot_image_creates_profile_template(tmp_path):
    """Booting cogent-v1 image creates whoami/profile.md with identity field placeholders."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"
    assert image_dir.is_dir()

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    # The init process template writes profile.md at first boot.
    # Verify the template in init.py mentions Discord User ID.
    fs = FileStore(repo)
    init_content = fs.get_content("cogos/init.py")
    assert init_content is not None
    assert "Discord User ID" in init_content
    assert "Discord Username" in init_content


# ── Test 4: Handler filters by identity ───────────────────


def test_handler_prompt_has_identity_filtering_instructions(tmp_path):
    """The discord handler prompt tells the LLM to read profile and filter by name."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    fs = FileStore(repo)
    handler_content = fs.get_content("apps/discord/handler/main.md")
    assert handler_content is not None

    # Verify the handler reads identity from profile
    assert "whoami/profile.md" in handler_content or "whoami/index.md" in handler_content
    assert "my_name" in handler_content
    assert "my_discord_id" in handler_content
    assert "Discord User ID" in handler_content


def test_handler_prompt_expansion_includes_full_identity(tmp_path):
    """Full boot + profile write + prompt expansion = identity in handler prompt."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    fs = FileStore(repo)

    # Simulate bridge writing identity (as it would on_ready)
    fs.upsert(
        "whoami/profile.md",
        "# Profile\n\n"
        "- **Name:** dr.beta\n"
        "- **Discord User ID:** 555666777\n"
        "- **Discord Username:** dr.beta#9999\n",
        source="system",
    )

    # The handler process content references @{whoami/index.md}
    handler_content = fs.get_content("apps/discord/handler/main.md")
    assert handler_content is not None

    # Create a process that mimics the handler
    handler = Process(
        name="test-handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        content=handler_content,
    )
    repo.upsert_process(handler)
    _grant_read_all(repo, handler)

    # Expand the prompt
    engine = ContextEngine(fs)
    prompt = engine.generate_full_prompt(handler)

    # Verify identity fields appear in the fully expanded prompt
    assert "dr.beta" in prompt
    assert "555666777" in prompt
    assert "dr.beta#9999" in prompt

    # Verify filtering instructions are present
    assert "my_name" in prompt
    assert "my_discord_id" in prompt
