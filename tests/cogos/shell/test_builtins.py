"""Tests for shell builtins."""

from cogos.db.local_repository import LocalRepository
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.builtins import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)

    @reg.register("dummy", help="A dummy command")
    def dummy(state, args):
        return "ok"

    return state, reg


def test_help_lists_commands(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "help")
    assert "help" in output
    assert "dummy" in output


def test_exit_returns_none(tmp_path):
    state, reg = _setup(tmp_path)
    result = reg.dispatch(state, "exit")
    assert result is None
