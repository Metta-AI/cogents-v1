"""Tests for shell CLI entry point registration."""

from cli.__main__ import _COMMANDS


def test_shell_in_commands():
    assert "shell" in _COMMANDS
