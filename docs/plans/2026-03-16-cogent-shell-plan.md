# Cogent Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive Unix-like shell (`cogent dr.alpha shell`) for managing CogOS processes, files, channels, capabilities, and runs with tab completion.

**Architecture:** A `prompt_toolkit` REPL connected to the CogOS repository. Commands are organized in domain modules (files, procs, channels, caps, runs, llm, builtins). A virtual filesystem with `cwd` overlays the flat key-based file store. A context-aware completer provides tab completion for file paths, process names, channel names, and capability names.

**Tech Stack:** `prompt_toolkit`, existing CogOS `Repository`/`LocalRepository`, `FileStore`, `cogos.runtime.local`

---

### Task 1: Add prompt_toolkit dependency

**Files:**
- Modify: `pyproject.toml:6-28` (add to dependencies)
- Modify: `pyproject.toml:52` (add shell package to hatch build)

**Step 1: Add prompt_toolkit to dependencies**

In `pyproject.toml`, add `"prompt_toolkit>=3.0"` to the `dependencies` list.

In `[tool.hatch.build.targets.wheel]` `packages`, add `"src/cogos/shell"`.

**Step 2: Install**

Run: `cd /Users/daveey/code/cogents/cogents.0 && uv sync`

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(shell): add prompt_toolkit dependency"
```

---

### Task 2: Shell state, command registry, and dispatch

**Files:**
- Create: `src/cogos/shell/__init__.py`
- Create: `src/cogos/shell/commands/__init__.py`
- Test: `tests/cogos/shell/test_dispatch.py`

**Step 1: Write the failing test**

Create `tests/cogos/shell/__init__.py` (empty) and `tests/cogos/shell/test_dispatch.py`:

```python
"""Tests for shell command dispatch."""

from cogos.shell.commands import CommandRegistry, ShellState


def test_registry_dispatches_known_command(tmp_path):
    """Register a command and dispatch it."""
    from cogos.db.local_repository import LocalRepository

    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")

    reg = CommandRegistry()

    @reg.register("echo")
    def echo_cmd(state: ShellState, args: list[str]) -> str:
        return " ".join(args)

    result = reg.dispatch(state, "echo hello world")
    assert result == "hello world"


def test_registry_returns_error_for_unknown_command(tmp_path):
    from cogos.db.local_repository import LocalRepository

    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    result = reg.dispatch(state, "nosuchcmd foo")
    assert "unknown command" in result.lower()


def test_registry_handles_empty_input(tmp_path):
    from cogos.db.local_repository import LocalRepository

    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    result = reg.dispatch(state, "")
    assert result == ""


def test_registry_handles_alias(tmp_path):
    from cogos.db.local_repository import LocalRepository

    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()

    @reg.register("edit", aliases=["vim"])
    def edit_cmd(state, args):
        return f"editing {args[0]}"

    result = reg.dispatch(state, "vim foo.py")
    assert result == "editing foo.py"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_dispatch.py -v`
Expected: FAIL (module not found)

**Step 3: Implement ShellState and CommandRegistry**

Create `src/cogos/shell/__init__.py`:

```python
"""CogentShell — interactive Unix-like shell for CogOS."""

from __future__ import annotations


class CogentShell:
    """Main shell class — instantiated by the CLI entry point."""

    def __init__(self, cogent_name: str) -> None:
        self.cogent_name = cogent_name

    def run(self) -> None:
        """Start the interactive shell loop."""
        from cogos.shell.commands import CommandRegistry, ShellState, build_registry
        from cogos.db.factory import create_repository
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML

        repo = create_repository()
        state = ShellState(cogent_name=self.cogent_name, repo=repo, cwd="")
        registry = build_registry()

        session: PromptSession = PromptSession()

        while True:
            try:
                cwd_display = "/" + state.cwd if state.cwd else "/"
                prompt_text = HTML(
                    f"<b><ansicyan>{self.cogent_name}</ansicyan></b>"
                    f":{cwd_display}$ "
                )
                line = session.prompt(prompt_text)
            except (EOFError, KeyboardInterrupt):
                break

            output = registry.dispatch(state, line)
            if output is None:
                break
            if output:
                print(output)
```

Create `src/cogos/shell/commands/__init__.py`:

```python
"""Command registry and dispatch for the CogOS shell."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ShellState:
    cogent_name: str
    repo: Any
    cwd: str  # current prefix, e.g. "prompts/" or "" for root
    bedrock_client: Any = None


CommandFn = Callable[[ShellState, list[str]], str | None]


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandFn] = {}
        self._aliases: dict[str, str] = {}
        self._help: dict[str, str] = {}

    def register(self, name: str, *, aliases: list[str] | None = None, help: str = ""):
        """Decorator to register a command function."""
        def decorator(fn: CommandFn) -> CommandFn:
            self._commands[name] = fn
            if help:
                self._help[name] = help
            elif fn.__doc__:
                self._help[name] = fn.__doc__.strip().split("\n")[0]
            for alias in (aliases or []):
                self._aliases[alias] = name
            return fn
        return decorator

    def dispatch(self, state: ShellState, line: str) -> str | None:
        """Parse and dispatch a command line. Returns output string, empty for no-op, None for exit."""
        line = line.strip()
        if not line:
            return ""

        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()

        cmd_name = parts[0]
        args = parts[1:]

        # Resolve alias
        cmd_name = self._aliases.get(cmd_name, cmd_name)

        fn = self._commands.get(cmd_name)
        if fn is None:
            return f"Unknown command: {parts[0]}. Type 'help' for available commands."

        return fn(state, args) or ""

    @property
    def command_names(self) -> list[str]:
        return sorted(set(list(self._commands.keys()) + list(self._aliases.keys())))

    def get_help(self, name: str) -> str | None:
        name = self._aliases.get(name, name)
        return self._help.get(name)

    def get_canonical(self, name: str) -> str | None:
        """Resolve alias to canonical name, or return name if it's a command."""
        name = self._aliases.get(name, name)
        return name if name in self._commands else None


def build_registry() -> CommandRegistry:
    """Build the full command registry with all command modules."""
    reg = CommandRegistry()

    from cogos.shell.commands.files import register as register_files
    from cogos.shell.commands.procs import register as register_procs
    from cogos.shell.commands.channels import register as register_channels
    from cogos.shell.commands.caps import register as register_caps
    from cogos.shell.commands.runs import register as register_runs
    from cogos.shell.commands.llm import register as register_llm
    from cogos.shell.commands.builtins import register as register_builtins

    register_files(reg)
    register_procs(reg)
    register_channels(reg)
    register_caps(reg)
    register_runs(reg)
    register_llm(reg)
    register_builtins(reg)

    return reg
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_dispatch.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/__init__.py src/cogos/shell/commands/__init__.py tests/cogos/shell/__init__.py tests/cogos/shell/test_dispatch.py
git commit -m "feat(shell): add ShellState, CommandRegistry, and dispatch"
```

---

### Task 3: File commands — ls, cd, pwd, tree, cat, rm

**Files:**
- Create: `src/cogos/shell/commands/files.py`
- Test: `tests/cogos/shell/test_files.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_files.py`:

```python
"""Tests for shell file commands."""

from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "init content")
    fs.create("prompts/scheduler.md", "scheduler content")
    fs.create("config/system.yaml", "key: value")
    fs.create("data/logs/run1.txt", "log output")
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg


def test_pwd_at_root(tmp_path):
    state, reg = _setup(tmp_path)
    assert reg.dispatch(state, "pwd") == "/"


def test_ls_root_shows_directories(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "ls")
    assert "prompts/" in output
    assert "config/" in output
    assert "data/" in output


def test_ls_prefix_shows_children(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "ls prompts")
    assert "init.md" in output
    assert "scheduler.md" in output


def test_cd_and_pwd(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    assert state.cwd == "prompts/"
    assert reg.dispatch(state, "pwd") == "/prompts/"


def test_cd_dotdot(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    reg.dispatch(state, "cd ..")
    assert state.cwd == ""


def test_cd_absolute(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    reg.dispatch(state, "cd /config")
    assert state.cwd == "config/"


def test_cat_absolute(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "cat prompts/init.md")
    assert output == "init content"


def test_cat_relative(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    output = reg.dispatch(state, "cat init.md")
    assert output == "init content"


def test_cat_not_found(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "cat nope.txt")
    assert "not found" in output.lower()


def test_rm(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "rm prompts/init.md")
    assert "deleted" in output.lower() or "removed" in output.lower()
    output = reg.dispatch(state, "cat prompts/init.md")
    assert "not found" in output.lower()


def test_tree(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "tree")
    assert "prompts/" in output
    assert "init.md" in output
    assert "config/" in output


def test_mkdir_noop(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "mkdir newdir")
    # Should succeed silently or with acknowledgment
    assert "implicit" in output.lower() or output == ""
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_files.py -v`

**Step 3: Implement file commands**

Create `src/cogos/shell/commands/files.py`:

```python
"""File commands — ls, cd, pwd, tree, cat, less, rm, mkdir, vim/edit."""

from __future__ import annotations

import os
import subprocess
import tempfile

from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState


def _resolve_path(state: ShellState, path: str) -> str:
    """Resolve a path relative to cwd, returning a file store key prefix."""
    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        resolved = state.cwd + path

    # Normalize .. segments
    parts = resolved.split("/")
    normalized: list[str] = []
    for p in parts:
        if p == "..":
            if normalized:
                normalized.pop()
        elif p and p != ".":
            normalized.append(p)
    return "/".join(normalized)


def _ensure_trailing_slash(prefix: str) -> str:
    if prefix and not prefix.endswith("/"):
        return prefix + "/"
    return prefix


def _list_children(repo, prefix: str) -> tuple[list[str], list[str]]:
    """List immediate children (dirs and files) under a prefix.

    Returns (dirs, files) where dirs have trailing slash stripped.
    """
    prefix = _ensure_trailing_slash(prefix) if prefix else ""
    all_files = repo.list_files(prefix=prefix or None, limit=1000)
    dirs: set[str] = set()
    files: list[str] = []
    prefix_len = len(prefix)

    for f in all_files:
        remainder = f.key[prefix_len:]
        if "/" in remainder:
            # It's in a subdirectory
            dir_name = remainder.split("/")[0]
            dirs.add(dir_name)
        else:
            files.append(remainder)

    return sorted(dirs), sorted(files)


def register(reg: CommandRegistry) -> None:

    @reg.register("pwd", help="Print working directory")
    def pwd(state: ShellState, args: list[str]) -> str:
        return "/" + state.cwd if state.cwd else "/"

    @reg.register("ls", help="List files and directories")
    def ls(state: ShellState, args: list[str]) -> str:
        target = _resolve_path(state, args[0]) if args else state.cwd.rstrip("/")
        prefix = target
        dirs, files = _list_children(state.repo, prefix)
        lines: list[str] = []
        for d in dirs:
            lines.append(f"\033[1;34m{d}/\033[0m")
        for f in files:
            lines.append(f)
        if not lines:
            return "(empty)"
        return "\n".join(lines)

    @reg.register("cd", help="Change directory")
    def cd(state: ShellState, args: list[str]) -> str:
        if not args or args[0] == "/":
            state.cwd = ""
            return ""
        resolved = _resolve_path(state, args[0])
        if not resolved:
            state.cwd = ""
            return ""
        # Verify the prefix exists by checking for any files under it
        new_prefix = _ensure_trailing_slash(resolved)
        files = state.repo.list_files(prefix=new_prefix, limit=1)
        if not files:
            return f"cd: no such directory: {args[0]}"
        state.cwd = new_prefix
        return ""

    @reg.register("cat", help="Print file content")
    def cat(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: cat <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"cat: not found: {args[0]}"
        return content

    @reg.register("less", help="Page file content through system pager")
    def less(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: less <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"less: not found: {args[0]}"
        pager = os.environ.get("PAGER", "less")
        try:
            proc = subprocess.Popen([pager], stdin=subprocess.PIPE)
            proc.communicate(input=content.encode())
        except FileNotFoundError:
            return content
        return ""

    @reg.register("rm", help="Delete a file")
    def rm(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: rm <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        try:
            fs.delete(key)
        except ValueError:
            return f"rm: not found: {args[0]}"
        return f"Removed: {key}"

    @reg.register("mkdir", help="Create a directory (no-op — directories are implicit)")
    def mkdir(state: ShellState, args: list[str]) -> str:
        return "Directories are implicit from file key prefixes."

    @reg.register("tree", help="Recursive file listing")
    def tree(state: ShellState, args: list[str]) -> str:
        target = _resolve_path(state, args[0]) if args else state.cwd.rstrip("/")
        prefix = _ensure_trailing_slash(target) if target else ""
        all_files = state.repo.list_files(prefix=prefix or None, limit=1000)
        if not all_files:
            return "(empty)"
        prefix_len = len(prefix)
        lines: list[str] = []
        # Group by directory
        tree: dict[str, list[str]] = {}
        for f in all_files:
            remainder = f.key[prefix_len:]
            parts = remainder.rsplit("/", 1)
            if len(parts) == 2:
                dir_path, filename = parts
                tree.setdefault(dir_path, []).append(filename)
            else:
                tree.setdefault(".", []).append(remainder)

        for dir_path in sorted(tree.keys()):
            if dir_path != ".":
                lines.append(f"\033[1;34m{dir_path}/\033[0m")
            for filename in sorted(tree[dir_path]):
                indent = "  " if dir_path != "." else ""
                lines.append(f"{indent}{filename}")
        return "\n".join(lines)

    @reg.register("edit", aliases=["vim"], help="Edit a file with $EDITOR")
    def edit(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: edit <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key) or ""
        is_new = fs.get(key) is None

        editor = os.environ.get("EDITOR", "vim")
        suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ".txt"

        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            subprocess.call([editor, tmp_path])
            with open(tmp_path) as f:
                new_content = f.read()
        finally:
            os.unlink(tmp_path)

        if new_content == content:
            return "(no changes)"

        fs.upsert(key, new_content, source="shell")
        verb = "Created" if is_new else "Updated"
        return f"{verb}: {key}"
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_files.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/files.py tests/cogos/shell/test_files.py
git commit -m "feat(shell): add file commands (ls, cd, pwd, tree, cat, rm, edit)"
```

---

### Task 4: Process commands — ps, kill, spawn, top

**Files:**
- Create: `src/cogos/shell/commands/procs.py`
- Test: `tests/cogos/shell/test_procs.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_procs.py`:

```python
"""Tests for shell process commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.procs import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_process(Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, runner="lambda"))
    repo.upsert_process(Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda"))
    repo.upsert_process(Process(name="done-job", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED, runner="lambda"))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_ps_excludes_completed(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ps")
    assert "init" in output
    assert "scheduler" in output
    assert "done-job" not in output


def test_ps_all_includes_completed(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ps --all")
    assert "done-job" in output


def test_kill_disables(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill scheduler")
    p = repo.get_process_by_name("scheduler")
    assert p.status == ProcessStatus.DISABLED


def test_kill_9_disables_and_clears(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill -9 scheduler")
    p = repo.get_process_by_name("scheduler")
    assert p.status == ProcessStatus.DISABLED


def test_kill_hup_restarts(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill -HUP init")
    p = repo.get_process_by_name("init")
    assert p.status == ProcessStatus.RUNNABLE


def test_kill_not_found(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "kill nonexistent")
    assert "not found" in output.lower()


def test_spawn(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, 'spawn worker --content "do stuff"')
    p = repo.get_process_by_name("worker")
    assert p is not None
    assert p.status == ProcessStatus.RUNNABLE
    assert p.content == "do stuff"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_procs.py -v`

**Step 3: Implement process commands**

Create `src/cogos/shell/commands/procs.py`:

```python
"""Process commands — ps, kill, spawn, top."""

from __future__ import annotations

import time

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState

_STATUS_COLORS = {
    "running": "\033[32m",    # green
    "runnable": "\033[33m",   # yellow
    "waiting": "\033[33m",    # yellow
    "blocked": "\033[31m",    # red
    "suspended": "\033[31m",  # red
    "disabled": "\033[31m",   # red
    "completed": "\033[90m",  # dim
}
_RESET = "\033[0m"


def _format_process_table(procs: list[Process]) -> str:
    if not procs:
        return "(no processes)"
    lines = [f"{'NAME':<24} {'STATUS':<12} {'MODE':<10} {'RUNNER':<8} {'PRI':>5}"]
    lines.append("-" * 63)
    for p in procs:
        color = _STATUS_COLORS.get(p.status.value, "")
        lines.append(
            f"{p.name:<24} {color}{p.status.value:<12}{_RESET} "
            f"{p.mode.value:<10} {p.runner:<8} {p.priority:>5.1f}"
        )
    return "\n".join(lines)


def register(reg: CommandRegistry) -> None:

    @reg.register("ps", help="List processes (--all to include completed)")
    def ps(state: ShellState, args: list[str]) -> str:
        show_all = "--all" in args or "-a" in args
        procs = state.repo.list_processes()
        if not show_all:
            procs = [p for p in procs if p.status != ProcessStatus.COMPLETED]
        procs.sort(key=lambda p: (p.status != ProcessStatus.RUNNING, p.name))
        return _format_process_table(procs)

    @reg.register("kill", help="Kill a process (-9=force, -HUP=restart)")
    def kill(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: kill [-9|-HUP] <name>"

        signal = None
        name = args[0]
        if name.startswith("-"):
            signal = name
            if len(args) < 2:
                return "Usage: kill [-9|-HUP] <name>"
            name = args[1]

        p = state.repo.get_process_by_name(name)
        if not p:
            return f"kill: not found: {name}"

        if signal == "-HUP":
            state.repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
            return f"Restarted: {name} (RUNNABLE)"
        elif signal == "-9":
            state.repo.update_process_status(p.id, ProcessStatus.DISABLED)
            if hasattr(state.repo, "execute"):
                state.repo.execute(
                    "UPDATE cogos_process SET clear_context = TRUE WHERE id = :id",
                    {"id": p.id},
                )
            return f"Force killed: {name} (DISABLED, context cleared)"
        else:
            state.repo.update_process_status(p.id, ProcessStatus.DISABLED)
            return f"Killed: {name} (DISABLED)"

    @reg.register("spawn", help="Create a new process")
    def spawn(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: spawn <name> [--content '...'] [--runner lambda|ecs] [--model ...]"

        name = args[0]
        content = ""
        runner = "lambda"
        model = None
        mode = "one_shot"
        priority = 0.0

        i = 1
        while i < len(args):
            if args[i] == "--content" and i + 1 < len(args):
                content = args[i + 1]
                i += 2
            elif args[i] == "--runner" and i + 1 < len(args):
                runner = args[i + 1]
                i += 2
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            elif args[i] == "--mode" and i + 1 < len(args):
                mode = args[i + 1]
                i += 2
            elif args[i] == "--priority" and i + 1 < len(args):
                priority = float(args[i + 1])
                i += 2
            else:
                i += 1

        p = Process(
            name=name,
            mode=ProcessMode(mode),
            content=content,
            runner=runner,
            model=model,
            priority=priority,
            status=ProcessStatus.RUNNABLE,
        )
        pid = state.repo.upsert_process(p)
        return f"Spawned: {name} ({pid})"

    @reg.register("top", help="Live-refreshing process view (ctrl+c to exit)")
    def top(state: ShellState, args: list[str]) -> str:
        try:
            while True:
                procs = state.repo.list_processes()
                procs = [p for p in procs if p.status != ProcessStatus.COMPLETED]
                procs.sort(key=lambda p: (p.status != ProcessStatus.RUNNING, p.name))
                print("\033[2J\033[H", end="")  # clear screen
                print(f"cogent: {state.cogent_name}  (ctrl+c to exit)\n")
                print(_format_process_table(procs))
                time.sleep(2)
        except KeyboardInterrupt:
            return ""
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_procs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/procs.py tests/cogos/shell/test_procs.py
git commit -m "feat(shell): add process commands (ps, kill, spawn, top)"
```

---

### Task 5: Channel commands — ch ls, ch send, ch log

**Files:**
- Create: `src/cogos/shell/commands/channels.py`
- Test: `tests/cogos/shell/test_channels.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_channels.py`:

```python
"""Tests for shell channel commands."""

import json

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.channels import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=None, payload={"type": "test", "data": "hello"},
    ))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_ch_ls(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ch ls")
    assert "events" in output


def test_ch_send(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, 'ch send events {"type":"ping"}')
    ch = repo.get_channel_by_name("events")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 2
    assert msgs[-1].payload["type"] == "ping"


def test_ch_log(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ch log events")
    assert "test" in output
    assert "hello" in output
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_channels.py -v`

**Step 3: Implement channel commands**

Create `src/cogos/shell/commands/channels.py`:

```python
"""Channel commands — ch ls, ch send, ch log."""

from __future__ import annotations

import json

from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("ch", help="Channel commands: ch ls | ch send <name> <json> | ch log <name>")
    def ch(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: ch ls | ch send <name> <json> | ch log <name> [--limit N]"

        subcmd = args[0]

        if subcmd == "ls":
            channels = state.repo.list_channels()
            if not channels:
                return "(no channels)"
            lines = [f"{'NAME':<40} {'TYPE':<12}"]
            lines.append("-" * 54)
            for c in channels:
                lines.append(f"{c.name:<40} {c.channel_type.value:<12}")
            return "\n".join(lines)

        elif subcmd == "send":
            if len(args) < 3:
                return "Usage: ch send <channel> <json-payload>"
            ch_name = args[1]
            payload_str = " ".join(args[2:])
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError as e:
                return f"Invalid JSON: {e}"
            ch_obj = state.repo.get_channel_by_name(ch_name)
            if not ch_obj:
                ch_obj = Channel(name=ch_name, channel_type=ChannelType.NAMED)
                state.repo.upsert_channel(ch_obj)
            msg = ChannelMessage(channel=ch_obj.id, sender_process=None, payload=payload)
            mid = state.repo.append_channel_message(msg)
            return f"Sent to {ch_name} ({mid})"

        elif subcmd == "log":
            if len(args) < 2:
                return "Usage: ch log <channel> [--limit N]"
            ch_name = args[1]
            limit = 20
            if "--limit" in args:
                idx = args.index("--limit")
                if idx + 1 < len(args):
                    limit = int(args[idx + 1])
            ch_obj = state.repo.get_channel_by_name(ch_name)
            if not ch_obj:
                return f"Channel not found: {ch_name}"
            msgs = state.repo.list_channel_messages(ch_obj.id, limit=limit)
            if not msgs:
                return "(no messages)"
            lines = []
            for m in msgs:
                ts = str(m.created_at)[:19] if m.created_at else "?"
                lines.append(f"[{ts}] {json.dumps(m.payload, default=str)}")
            return "\n".join(lines)

        else:
            return f"Unknown subcommand: ch {subcmd}"
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_channels.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/channels.py tests/cogos/shell/test_channels.py
git commit -m "feat(shell): add channel commands (ch ls, ch send, ch log)"
```

---

### Task 6: Capability commands — cap ls, cap enable, cap disable

**Files:**
- Create: `src/cogos/shell/commands/caps.py`
- Test: `tests/cogos/shell/test_caps.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_caps.py`:

```python
"""Tests for shell capability commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.caps import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    repo.upsert_capability(Capability(name="procs", description="Process mgmt", enabled=True))
    repo.upsert_capability(Capability(name="secrets", description="Secret store", enabled=False))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_cap_ls(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "cap ls")
    assert "files" in output
    assert "procs" in output
    assert "secrets" in output


def test_cap_disable(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "cap disable files")
    cap = repo.get_capability_by_name("files")
    assert not cap.enabled


def test_cap_enable(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "cap enable secrets")
    cap = repo.get_capability_by_name("secrets")
    assert cap.enabled
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_caps.py -v`

**Step 3: Implement capability commands**

Create `src/cogos/shell/commands/caps.py`:

```python
"""Capability commands — cap ls, cap enable, cap disable."""

from __future__ import annotations

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("cap", help="Capability commands: cap ls | cap enable <name> | cap disable <name>")
    def cap(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: cap ls | cap enable <name> | cap disable <name>"

        subcmd = args[0]

        if subcmd == "ls":
            caps = state.repo.list_capabilities()
            if not caps:
                return "(no capabilities)"
            lines = [f"{'NAME':<20} {'ENABLED':<10} {'DESCRIPTION'}"]
            lines.append("-" * 60)
            for c in caps:
                enabled = "\033[32myes\033[0m" if c.enabled else "\033[31mno\033[0m"
                lines.append(f"{c.name:<20} {enabled:<19} {c.description or ''}")
            return "\n".join(lines)

        elif subcmd == "enable":
            if len(args) < 2:
                return "Usage: cap enable <name>"
            name = args[1]
            cap_obj = state.repo.get_capability_by_name(name)
            if not cap_obj:
                return f"Capability not found: {name}"
            cap_obj.enabled = True
            state.repo.upsert_capability(cap_obj)
            return f"Enabled: {name}"

        elif subcmd == "disable":
            if len(args) < 2:
                return "Usage: cap disable <name>"
            name = args[1]
            cap_obj = state.repo.get_capability_by_name(name)
            if not cap_obj:
                return f"Capability not found: {name}"
            cap_obj.enabled = False
            state.repo.upsert_capability(cap_obj)
            return f"Disabled: {name}"

        else:
            return f"Unknown subcommand: cap {subcmd}"
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_caps.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/caps.py tests/cogos/shell/test_caps.py
git commit -m "feat(shell): add capability commands (cap ls, cap enable, cap disable)"
```

---

### Task 7: Run commands — runs, run show

**Files:**
- Create: `src/cogos/shell/commands/runs.py`
- Test: `tests/cogos/shell/test_runs.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_runs.py`:

```python
"""Tests for shell run commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.runs import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    p = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda")
    repo.upsert_process(p)
    r = Run(process=p.id, status=RunStatus.COMPLETED, tokens_in=100, tokens_out=50, duration_ms=1200)
    repo.create_run(r)
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo, r


def test_runs_list(tmp_path):
    state, reg, _, r = _setup(tmp_path)
    output = reg.dispatch(state, "runs")
    assert "scheduler" in output or str(r.id)[:8] in output


def test_run_show(tmp_path):
    state, reg, _, r = _setup(tmp_path)
    output = reg.dispatch(state, f"run show {r.id}")
    assert "100" in output  # tokens_in
    assert "1200" in output or "1.2" in output  # duration
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_runs.py -v`

**Step 3: Implement run commands**

Create `src/cogos/shell/commands/runs.py`:

```python
"""Run commands — runs, run show."""

from __future__ import annotations

import json
from uuid import UUID

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("runs", help="List recent runs [--process <name>] [--limit N]")
    def runs(state: ShellState, args: list[str]) -> str:
        process_name = None
        limit = 20
        i = 0
        while i < len(args):
            if args[i] == "--process" and i + 1 < len(args):
                process_name = args[i + 1]
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            else:
                i += 1

        pid = None
        if process_name:
            p = state.repo.get_process_by_name(process_name)
            if p:
                pid = p.id

        run_list = state.repo.list_runs(process_id=pid, limit=limit)
        if not run_list:
            return "(no runs)"

        # Build process name cache
        proc_cache: dict[str, str] = {}
        lines = [f"{'ID':<12} {'PROCESS':<20} {'STATUS':<12} {'TOKENS':>12} {'DURATION':>10}"]
        lines.append("-" * 70)
        for r in run_list:
            pkey = str(r.process)
            if pkey not in proc_cache:
                proc = state.repo.get_process(r.process)
                proc_cache[pkey] = proc.name if proc else pkey[:8]
            tokens = f"{r.tokens_in or 0}/{r.tokens_out or 0}"
            dur = f"{r.duration_ms or 0}ms"
            lines.append(
                f"{str(r.id)[:12]} {proc_cache[pkey]:<20} {r.status.value:<12} {tokens:>12} {dur:>10}"
            )
        return "\n".join(lines)

    @reg.register("run", help="Run subcommands: run show <id>")
    def run_cmd(state: ShellState, args: list[str]) -> str:
        if not args or args[0] != "show" or len(args) < 2:
            return "Usage: run show <run-id>"

        try:
            run_id = UUID(args[1])
        except ValueError:
            return f"Invalid run ID: {args[1]}"

        r = state.repo.get_run(run_id)
        if not r:
            return f"Run not found: {args[1]}"

        data = r.model_dump(mode="json")
        lines = []
        for k, v in data.items():
            if v is not None:
                lines.append(f"  {k}: {json.dumps(v, default=str) if isinstance(v, (dict, list)) else v}")
        return "\n".join(lines)
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_runs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/runs.py tests/cogos/shell/test_runs.py
git commit -m "feat(shell): add run commands (runs, run show)"
```

---

### Task 8: Builtins — help, clear, exit

**Files:**
- Create: `src/cogos/shell/commands/builtins.py`
- Test: `tests/cogos/shell/test_builtins.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_builtins.py`:

```python
"""Tests for shell builtins."""

from cogos.db.local_repository import LocalRepository
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.builtins import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    # Add a dummy command so help has something to show
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_builtins.py -v`

**Step 3: Implement builtins**

Create `src/cogos/shell/commands/builtins.py`:

```python
"""Shell builtins — help, clear, exit."""

from __future__ import annotations

import os

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("help", help="Show available commands")
    def help_cmd(state: ShellState, args: list[str]) -> str:
        if args:
            name = args[0]
            h = reg.get_help(name)
            if h:
                return f"{name}: {h}"
            return f"No help for: {name}"
        lines = ["Available commands:", ""]
        for name in reg.command_names:
            canonical = reg.get_canonical(name)
            if canonical and canonical != name:
                continue  # skip aliases in listing
            h = reg.get_help(name) or ""
            lines.append(f"  {name:<16} {h}")
        return "\n".join(lines)

    @reg.register("clear", help="Clear screen")
    def clear(state: ShellState, args: list[str]) -> str:
        os.system("clear" if os.name != "nt" else "cls")
        return ""

    @reg.register("exit", aliases=["quit"], help="Exit the shell")
    def exit_cmd(state: ShellState, args: list[str]) -> str | None:
        return None
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_builtins.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/builtins.py tests/cogos/shell/test_builtins.py
git commit -m "feat(shell): add builtins (help, clear, exit)"
```

---

### Task 9: LLM execution — llm, source

**Files:**
- Create: `src/cogos/shell/commands/llm.py`
- Test: `tests/cogos/shell/test_llm.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_llm.py`:

```python
"""Tests for shell llm command — uses a mock executor."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessStatus, Run, RunStatus
from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.llm import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    fs = FileStore(repo)
    fs.create("prompts/hello.md", "Say hello world")
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_llm_creates_and_cleans_temp_process(tmp_path, monkeypatch):
    """llm command should create a temp process, run it, and mark completed."""
    state, reg, repo = _setup(tmp_path)

    executed = []

    def fake_run_and_complete(process, event_data, run, config, repo, **kwargs):
        executed.append(process.name)
        run.tokens_in = 10
        run.tokens_out = 5
        run.result = "Hello world!"
        return run

    monkeypatch.setattr("cogos.shell.commands.llm.run_and_complete", fake_run_and_complete)
    monkeypatch.setattr("cogos.shell.commands.llm.get_config", lambda: None)

    output = reg.dispatch(state, "llm say hi")
    assert len(executed) == 1
    assert executed[0].startswith("shell-")


def test_source_reads_file(tmp_path, monkeypatch):
    state, reg, repo = _setup(tmp_path)

    prompts_seen = []

    def fake_run_and_complete(process, event_data, run, config, repo, **kwargs):
        prompts_seen.append(process.content)
        run.tokens_in = 5
        run.tokens_out = 3
        return run

    monkeypatch.setattr("cogos.shell.commands.llm.run_and_complete", fake_run_and_complete)
    monkeypatch.setattr("cogos.shell.commands.llm.get_config", lambda: None)

    reg.dispatch(state, "source prompts/hello.md")
    assert "Say hello world" in prompts_seen[0]
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_llm.py -v`

**Step 3: Implement llm command**

Create `src/cogos/shell/commands/llm.py`:

```python
"""LLM execution — llm, source, . commands."""

from __future__ import annotations

import time

from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor.handler import get_config
from cogos.files.store import FileStore
from cogos.runtime.local import run_and_complete
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import _resolve_path


def _execute_prompt(state: ShellState, content: str) -> str:
    """Create a temp process, execute the prompt, return output."""
    ts = int(time.time())
    proc_name = f"shell-{ts}"

    process = Process(
        name=proc_name,
        mode=ProcessMode.ONE_SHOT,
        content=content,
        runner="local",
        status=ProcessStatus.RUNNING,
    )
    state.repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.RUNNING)
    state.repo.create_run(run)

    config = get_config()
    run = run_and_complete(
        process, {}, run, config, state.repo,
        bedrock_client=state.bedrock_client,
    )

    # Clean up temp process
    state.repo.update_process_status(process.id, ProcessStatus.COMPLETED)

    lines = []
    if run.result:
        lines.append(run.result)
    lines.append(
        f"\n\033[90mtokens: {run.tokens_in or 0} in, {run.tokens_out or 0} out"
        f" ({run.duration_ms or 0}ms)\033[0m"
    )
    if run.status == RunStatus.FAILED:
        lines.append(f"\033[31mError: {run.error}\033[0m")
    return "\n".join(lines)


def _execute_interactive(state: ShellState, initial_content: str = "") -> str:
    """Interactive multi-turn LLM session."""
    from prompt_toolkit import PromptSession

    session: PromptSession = PromptSession()
    lines = []

    if initial_content:
        lines.append(f"\033[90m(loaded context: {len(initial_content)} chars)\033[0m")
        output = _execute_prompt(state, initial_content)
        lines.append(output)

    try:
        while True:
            try:
                user_input = session.prompt("llm> ")
            except EOFError:
                break
            if user_input.strip() in ("/exit", "exit", "quit"):
                break
            if not user_input.strip():
                continue
            output = _execute_prompt(state, user_input)
            lines.append(output)
    except KeyboardInterrupt:
        pass

    return "\n".join(lines) if lines else "(session ended)"


def register(reg: CommandRegistry) -> None:

    @reg.register("llm", help="Run an LLM prompt: llm <text> | llm -f <file> | llm -i")
    def llm(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: llm <prompt> | llm -f <file> | llm -i [-f <file>]"

        interactive = "-i" in args
        file_path = None
        prompt_parts = []

        i = 0
        while i < len(args):
            if args[i] == "-i":
                i += 1
            elif args[i] == "-f" and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            else:
                prompt_parts.append(args[i])
                i += 1

        content = ""
        if file_path:
            key = _resolve_path(state, file_path)
            fs = FileStore(state.repo)
            file_content = fs.get_content(key)
            if file_content is None:
                return f"File not found: {file_path}"
            content = file_content

        if prompt_parts:
            inline = " ".join(prompt_parts)
            content = f"{content}\n\n{inline}" if content else inline

        if interactive:
            return _execute_interactive(state, content)

        if not content:
            return "Usage: llm <prompt> | llm -f <file>"

        return _execute_prompt(state, content)

    @reg.register("source", aliases=["."], help="Execute a file as an LLM prompt")
    def source(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: source <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"File not found: {args[0]}"
        return _execute_prompt(state, content)
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_llm.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/llm.py tests/cogos/shell/test_llm.py
git commit -m "feat(shell): add llm command (llm, source, .)"
```

---

### Task 10: Tab completer

**Files:**
- Create: `src/cogos/shell/completer.py`
- Test: `tests/cogos/shell/test_completer.py`

**Step 1: Write the failing tests**

Create `tests/cogos/shell/test_completer.py`:

```python
"""Tests for shell tab completer."""

from prompt_toolkit.document import Document

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState, build_registry
from cogos.shell.completer import ShellCompleter


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "x")
    fs.create("prompts/scheduler.md", "x")
    fs.create("config/system.yaml", "x")
    repo.upsert_process(Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, runner="lambda"))
    repo.upsert_process(Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda"))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    registry = build_registry()
    return state, registry


def _completions(completer, text: str) -> list[str]:
    doc = Document(text, len(text))
    from prompt_toolkit.completion import CompleteEvent
    event = CompleteEvent()
    return [c.text for c in completer.get_completions(doc, event)]


def test_completes_command_names(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "p")
    assert "ps" in results
    assert "pwd" in results


def test_completes_file_paths_for_cat(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "cat ")
    # Should include directory prefixes
    assert "prompts/" in results or any("prompts" in r for r in results)


def test_completes_process_names_for_kill(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "kill ")
    assert "init" in results
    assert "scheduler" in results


def test_completes_subdir_files(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "cat prompts/")
    assert "prompts/init.md" in results or "init.md" in results
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_completer.py -v`

**Step 3: Implement the completer**

Create `src/cogos/shell/completer.py`:

```python
"""Context-aware tab completer for the CogOS shell."""

from __future__ import annotations

import time
from typing import Iterable

from prompt_toolkit.completion import CompleteEvent, Completion, Completer
from prompt_toolkit.document import Document

from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import _ensure_trailing_slash

# Commands that take file path arguments
_FILE_COMMANDS = {"cat", "less", "rm", "vim", "edit", "source", "."}
_DIR_COMMANDS = {"cd", "ls", "tree"}
_PROC_COMMANDS = {"kill"}
_CHANNEL_SUBCMDS = {"send", "log"}
_CAP_SUBCMDS = {"enable", "disable"}

_CACHE_TTL = 2.0  # seconds


class ShellCompleter(Completer):
    def __init__(self, state: ShellState, registry: CommandRegistry) -> None:
        self._state = state
        self._registry = registry
        self._cache: dict[str, tuple[float, list]] = {}

    def _cached(self, key: str, fetch):
        now = time.time()
        if key in self._cache:
            ts, data = self._cache[key]
            if now - ts < _CACHE_TTL:
                return data
        data = fetch()
        self._cache[key] = (now, data)
        return data

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        parts = text.split()

        # Completing the command name
        if not parts or (len(parts) == 1 and not text.endswith(" ")):
            prefix = parts[0] if parts else ""
            for name in self._registry.command_names:
                if name.startswith(prefix):
                    yield Completion(name, start_position=-len(prefix))
            return

        cmd = parts[0]
        # What we're currently typing
        current = parts[-1] if not text.endswith(" ") else ""
        start_pos = -len(current)

        # File path completion
        if cmd in _FILE_COMMANDS or cmd in _DIR_COMMANDS:
            yield from self._complete_paths(current, start_pos, dirs_only=(cmd in _DIR_COMMANDS))
            return

        # llm -f <file>
        if cmd == "llm" and "-f" in parts:
            f_idx = parts.index("-f")
            # Complete the arg right after -f
            if len(parts) == f_idx + 2 and not text.endswith(" "):
                yield from self._complete_paths(current, start_pos)
                return
            if len(parts) == f_idx + 1 and text.endswith(" "):
                yield from self._complete_paths("", 0)
                return

        # Process name completion
        if cmd in _PROC_COMMANDS:
            # Handle kill -9 <name>, kill -HUP <name>
            yield from self._complete_processes(current, start_pos)
            return

        # Channel subcommand completion
        if cmd == "ch" and len(parts) >= 2:
            subcmd = parts[1]
            if subcmd in _CHANNEL_SUBCMDS:
                yield from self._complete_channels(current, start_pos)
                return

        # Capability subcommand completion
        if cmd == "cap" and len(parts) >= 2:
            subcmd = parts[1]
            if subcmd in _CAP_SUBCMDS:
                yield from self._complete_capabilities(current, start_pos)
                return

        # spawn --runner completion
        if cmd == "spawn" and len(parts) >= 2 and parts[-2] == "--runner":
            for r in ("lambda", "ecs"):
                if r.startswith(current):
                    yield Completion(r, start_position=start_pos)
            return

        # runs --process completion
        if cmd == "runs" and len(parts) >= 2 and parts[-2] == "--process":
            yield from self._complete_processes(current, start_pos)
            return

    def _complete_paths(self, current: str, start_pos: int, dirs_only: bool = False) -> Iterable[Completion]:
        state = self._state
        # Resolve the prefix to search
        if "/" in current:
            dir_part = current.rsplit("/", 1)[0]
            resolved = current if current.startswith("/") else state.cwd + current
            # Get the directory portion
            if "/" in resolved:
                search_prefix = resolved.rsplit("/", 1)[0] + "/"
            else:
                search_prefix = ""
        else:
            search_prefix = state.cwd
            resolved = state.cwd + current

        all_files = self._cached(
            f"files:{search_prefix}",
            lambda: state.repo.list_files(prefix=search_prefix or None, limit=500),
        )

        seen_dirs: set[str] = set()
        prefix_len = len(search_prefix)

        for f in all_files:
            remainder = f.key[prefix_len:]
            if "/" in remainder:
                dir_name = remainder.split("/")[0] + "/"
                full_completion = search_prefix[len(state.cwd):] + dir_name if search_prefix.startswith(state.cwd) else dir_name
                if full_completion.startswith(current) and dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    yield Completion(full_completion, start_position=start_pos)
            elif not dirs_only:
                full_completion = search_prefix[len(state.cwd):] + remainder if search_prefix.startswith(state.cwd) else remainder
                if full_completion.startswith(current):
                    yield Completion(full_completion, start_position=start_pos)

    def _complete_processes(self, current: str, start_pos: int) -> Iterable[Completion]:
        procs = self._cached(
            "procs",
            lambda: self._state.repo.list_processes(),
        )
        for p in procs:
            if p.name.startswith(current):
                yield Completion(p.name, start_position=start_pos)

    def _complete_channels(self, current: str, start_pos: int) -> Iterable[Completion]:
        channels = self._cached(
            "channels",
            lambda: self._state.repo.list_channels(),
        )
        for ch in channels:
            if ch.name.startswith(current):
                yield Completion(ch.name, start_position=start_pos)

    def _complete_capabilities(self, current: str, start_pos: int) -> Iterable[Completion]:
        caps = self._cached(
            "caps",
            lambda: self._state.repo.list_capabilities(),
        )
        for c in caps:
            if c.name.startswith(current):
                yield Completion(c.name, start_position=start_pos)
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_completer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/completer.py tests/cogos/shell/test_completer.py
git commit -m "feat(shell): add context-aware tab completer"
```

---

### Task 11: Wire up shell entry point and bottom toolbar

**Files:**
- Modify: `src/cli/__main__.py:10` (add "shell" to _COMMANDS)
- Modify: `src/cli/__main__.py:41-62` (register shell command)
- Modify: `src/cogos/shell/__init__.py` (add completer and toolbar)
- Test: `tests/cli/test_shell_entry.py`

**Step 1: Write the failing test**

Create `tests/cli/test_shell_entry.py`:

```python
"""Tests for shell CLI entry point registration."""

from click.testing import CliRunner

from cli.__main__ import main, _COMMANDS


def test_shell_in_commands():
    assert "shell" in _COMMANDS


def test_shell_help():
    runner = CliRunner()
    result = runner.invoke(main, ["shell", "--help"])
    assert result.exit_code == 0
    assert "Interactive CogOS shell" in result.output
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cli/test_shell_entry.py -v`

**Step 3: Wire everything up**

In `src/cli/__main__.py`, add `"shell"` to `_COMMANDS`:

```python
_COMMANDS = {"dashboard", "cogtainer", "memory", "run", "cogos", "status", "shell", "--help", "-h"}
```

After the existing command registrations (after line 61), add:

```python
@main.command("shell")
@click.pass_context
def shell_cmd(ctx: click.Context):
    """Interactive CogOS shell."""
    from cogos.shell import CogentShell

    cogent_name = ctx.obj.get("cogent_id", "dr.alpha")
    CogentShell(cogent_name).run()
```

Update `src/cogos/shell/__init__.py` to integrate the completer and bottom toolbar:

```python
"""CogentShell — interactive Unix-like shell for CogOS."""

from __future__ import annotations


class CogentShell:
    """Main shell class — instantiated by the CLI entry point."""

    def __init__(self, cogent_name: str) -> None:
        self.cogent_name = cogent_name

    def run(self) -> None:
        """Start the interactive shell loop."""
        from cogos.db.factory import create_repository
        from cogos.shell.commands import CommandRegistry, ShellState, build_registry
        from cogos.shell.completer import ShellCompleter
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML

        repo = create_repository()
        state = ShellState(cogent_name=self.cogent_name, repo=repo, cwd="")

        # Try to set up Bedrock client for llm command
        try:
            import boto3
            state.bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")
        except Exception:
            pass

        registry = build_registry()
        completer = ShellCompleter(state, registry)

        def _bottom_toolbar():
            try:
                procs = repo.list_processes()
                running = sum(1 for p in procs if p.status.value == "running")
                waiting = sum(1 for p in procs if p.status.value in ("waiting", "runnable"))
                files = repo.list_files(limit=1000)
                caps = repo.list_capabilities(enabled_only=True)
                return HTML(
                    f" procs: <b>{running}</b> running, <b>{waiting}</b> waiting"
                    f" | files: <b>{len(files)}</b>"
                    f" | caps: <b>{len(caps)}</b> enabled"
                )
            except Exception:
                return ""

        session: PromptSession = PromptSession(
            completer=completer,
            bottom_toolbar=_bottom_toolbar,
            complete_while_typing=False,
        )

        print(f"CogOS shell for \033[1;36m{self.cogent_name}\033[0m (type 'help' for commands, 'exit' to quit)")

        while True:
            try:
                cwd_display = "/" + state.cwd.rstrip("/") if state.cwd else "/"
                prompt_text = HTML(
                    f"<b><ansicyan>{self.cogent_name}</ansicyan></b>"
                    f":{cwd_display}$ "
                )
                line = session.prompt(prompt_text)
            except (EOFError, KeyboardInterrupt):
                print()
                break

            output = registry.dispatch(state, line)
            if output is None:
                break
            if output:
                print(output)
```

**Step 4: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cli/test_shell_entry.py tests/cogos/shell/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/cli/__main__.py src/cogos/shell/__init__.py tests/cli/test_shell_entry.py
git commit -m "feat(shell): wire up entry point with completer and toolbar"
```

---

### Task 12: Integration smoke test

**Files:**
- Test: `tests/cogos/shell/test_integration.py`

**Step 1: Write integration test**

Create `tests/cogos/shell/test_integration.py`:

```python
"""Integration test — full registry with all commands, exercise a realistic workflow."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessMode, ProcessStatus
from cogos.files.store import FileStore
from cogos.shell.commands import ShellState, build_registry


def test_full_workflow(tmp_path):
    """Navigate files, manage processes, and check channels in one session."""
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
    output = reg.dispatch(state, "ps")
    assert "init" in output
    reg.dispatch(state, 'spawn worker --content "do stuff"')
    output = reg.dispatch(state, "ps")
    assert "worker" in output
    reg.dispatch(state, "kill worker")
    p = repo.get_process_by_name("worker")
    assert p.status == ProcessStatus.DISABLED

    # Capabilities
    assert "files" in reg.dispatch(state, "cap ls")

    # Help
    assert "ls" in reg.dispatch(state, "help")
    assert reg.dispatch(state, "exit") is None
```

**Step 2: Run the integration test**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/test_integration.py -v`
Expected: PASS

**Step 3: Run ALL shell tests**

Run: `cd /Users/daveey/code/cogents/cogents.0 && python -m pytest tests/cogos/shell/ tests/cli/test_shell_entry.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/cogos/shell/test_integration.py
git commit -m "test(shell): add integration smoke test"
```
