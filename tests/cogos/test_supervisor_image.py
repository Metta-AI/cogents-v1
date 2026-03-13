"""Tests for the supervisor app image loading and wiring."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_supervisor_loads():
    """The supervisor process should load from the cogent-v1 image."""
    spec = load_image(Path("images/cogent-v1"))

    proc_names = {p["name"] for p in spec.processes}
    assert "supervisor" in proc_names

    supervisor = next(p for p in spec.processes if p["name"] == "supervisor")
    assert supervisor["mode"] == "daemon"
    assert supervisor["content"] == "@{apps/supervisor/supervisor.md}"
    assert "procs" in supervisor["capabilities"]
    assert "alerts" in supervisor["capabilities"]
    assert "channels" in supervisor["capabilities"]


def test_cogent_v1_supervisor_channel():
    """The supervisor:help channel should be defined with schema."""
    spec = load_image(Path("images/cogent-v1"))

    channel_names = {c["name"] for c in spec.channels}
    assert "supervisor:help" in channel_names

    channel = next(c for c in spec.channels if c["name"] == "supervisor:help")
    assert channel.get("schema") == "supervisor-help-request"


def test_cogent_v1_supervisor_schema():
    """The supervisor-help-request schema should be defined."""
    spec = load_image(Path("images/cogent-v1"))

    schema_names = {s["name"] for s in spec.schemas}
    assert "supervisor-help-request" in schema_names


def test_cogent_v1_supervisor_files():
    """The supervisor prompt file should be loaded."""
    spec = load_image(Path("images/cogent-v1"))

    assert "apps/supervisor/supervisor.md" in spec.files
