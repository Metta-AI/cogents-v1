"""Tests for the newsfromthefront app image loading and wiring."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_newsfromthefront_prompts_load():
    """The newsfromthefront processes should point at existing app-scoped prompt files."""
    spec = load_image(Path("images/cogent-v1"))

    expected_prompts = {
        "newsfromthefront-researcher": "apps/newsfromthefront/researcher.md",
        "newsfromthefront-analyst": "apps/newsfromthefront/analyst.md",
        "newsfromthefront-test": "apps/newsfromthefront/test.md",
        "newsfromthefront-backfill": "apps/newsfromthefront/backfill.md",
    }

    for process_name, prompt_key in expected_prompts.items():
        process = next(p for p in spec.processes if p["name"] == process_name)
        assert process["content"] == f"@{{{prompt_key}}}"
        assert prompt_key in spec.files


def test_cogent_v1_newsfromthefront_whoami_is_app_scoped():
    """The app identity file should not collide with the image-level whoami key."""
    spec = load_image(Path("images/cogent-v1"))

    assert "whoami/index.md" in spec.files
    assert "apps/newsfromthefront/whoami/index.md" in spec.files
