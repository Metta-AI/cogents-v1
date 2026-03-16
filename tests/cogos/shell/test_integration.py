"""Integration test — full registry, realistic workflow."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessMode, ProcessStatus
from cogos.files.store import FileStore
from cogos.shell.commands import ShellState, build_registry


def test_full_workflow(tmp_path):
    repo = LocalRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "You are a helpful assistant.")
    fs.create("config/system.yaml", "debug: true")
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    repo.upsert_process(Process(
        name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, runner="lambda",
    ))

    state = ShellState(cogent_name="dr.alpha", repo=repo, cwd="")
    reg = build_registry()

    # File navigation
    assert reg.dispatch(state, "pwd") == "/"
    assert "prompts/" in reg.dispatch(state, "ls")
    reg.dispatch(state, "cd prompts")
    assert state.cwd == "prompts/"
    assert "init.md" in reg.dispatch(state, "ls")
    assert "helpful assistant" in reg.dispatch(state, "cat init.md")

    # Go back
    reg.dispatch(state, "cd /")
    assert state.cwd == ""

    # Process management
    assert "init" in reg.dispatch(state, "ps")
    reg.dispatch(state, 'spawn worker --content "do stuff"')
    assert "worker" in reg.dispatch(state, "ps")
    reg.dispatch(state, "kill worker")
    assert repo.get_process_by_name("worker").status == ProcessStatus.DISABLED

    # Capabilities
    assert "files" in reg.dispatch(state, "cap ls")

    # Help
    assert "ls" in reg.dispatch(state, "help")
    assert reg.dispatch(state, "exit") is None
