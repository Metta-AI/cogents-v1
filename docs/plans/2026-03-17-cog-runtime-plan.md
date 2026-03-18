# Cog Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the boot manifest / apply_image cog process creation with a directory-based `Cog` class and `CogRuntime` capability that init uses to load and run cogs from the filesystem.

**Architecture:** A cog is a directory with a `cog.yaml` config and a `main.md`/`main.py` entrypoint. `CogRuntime` is a capability scoped to a cog directory that spawns coglets by name. Init resolves a list of cog paths (with wildcard support), creates `Cog` objects, and runs each cog's main coglet via `CogRuntime`.

**Tech Stack:** Python, Pydantic, PyYAML, existing CogOS capability system, FileStore.

---

### Task 1: Create the `Cog` class

**Files:**
- Create: `src/cogos/cog/cog.py`
- Test: `tests/cogos/test_cog_dir.py`

**Step 1: Write the failing test**

```python
# tests/cogos/test_cog_dir.py
"""Tests for directory-based Cog class."""

import pytest
import yaml
from pathlib import Path
from cogos.cog.cog import Cog


@pytest.fixture
def cog_dir(tmp_path):
    """Create a minimal cog directory."""
    cog_path = tmp_path / "mycog"
    cog_path.mkdir()
    (cog_path / "cog.yaml").write_text(yaml.dump({
        "mode": "daemon",
        "priority": 5.0,
        "executor": "python",
        "capabilities": ["me", "procs", "discord"],
        "handlers": ["mycog:review"],
    }))
    (cog_path / "main.py").write_text("print('hello')")
    # Child coglet directory
    handler = cog_path / "handler"
    handler.mkdir()
    (handler / "main.md").write_text("# Handle messages")
    (handler / "cog.yaml").write_text(yaml.dump({
        "mode": "daemon",
        "capabilities": ["discord"],
        "handlers": ["io:discord:message"],
    }))
    return cog_path


def test_cog_name(cog_dir):
    cog = Cog(cog_dir)
    assert cog.name == "mycog"


def test_cog_config(cog_dir):
    cog = Cog(cog_dir)
    assert cog.config.mode == "daemon"
    assert cog.config.priority == 5.0
    assert cog.config.executor == "python"
    assert "me" in cog.config.capabilities
    assert "mycog:review" in cog.config.handlers


def test_cog_main_content(cog_dir):
    cog = Cog(cog_dir)
    assert cog.main_content == "print('hello')"


def test_cog_main_entrypoint(cog_dir):
    cog = Cog(cog_dir)
    assert cog.main_entrypoint == "main.py"


def test_cog_coglets(cog_dir):
    cog = Cog(cog_dir)
    assert "handler" in cog.coglets


def test_cog_coglet_config(cog_dir):
    cog = Cog(cog_dir)
    handler = cog.get_coglet("handler")
    assert handler.config.mode == "daemon"
    assert "discord" in handler.config.capabilities


def test_cog_coglet_content(cog_dir):
    cog = Cog(cog_dir)
    handler = cog.get_coglet("handler")
    assert handler.main_content == "# Handle messages"


def test_cog_no_main_raises(tmp_path):
    cog_path = tmp_path / "broken"
    cog_path.mkdir()
    (cog_path / "cog.yaml").write_text(yaml.dump({"mode": "one_shot"}))
    with pytest.raises(FileNotFoundError, match="main"):
        Cog(cog_path)


def test_cog_defaults(tmp_path):
    """Cog with no cog.yaml uses defaults."""
    cog_path = tmp_path / "minimal"
    cog_path.mkdir()
    (cog_path / "main.md").write_text("# Hello")
    cog = Cog(cog_path)
    assert cog.config.mode == "one_shot"
    assert cog.config.priority == 0.0
    assert cog.config.capabilities == []


def test_cog_resolve_paths():
    """Test resolve_cog_paths with wildcards."""
    from cogos.cog.cog import resolve_cog_paths
    import tempfile, os
    with tempfile.TemporaryDirectory() as base:
        # Create cog dirs
        for name in ["alpha", "beta", "gamma"]:
            d = Path(base) / "apps" / name
            d.mkdir(parents=True)
            (d / "main.md").write_text("# test")
        # Also a non-cog dir (no main.*)
        (Path(base) / "apps" / "data").mkdir(parents=True)

        paths = resolve_cog_paths([f"{base}/apps/*"], Path(base))
        names = [p.name for p in paths]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
        assert "data" not in names


def test_cog_resolve_explicit_path(tmp_path):
    """Test resolve with explicit path."""
    from cogos.cog.cog import resolve_cog_paths
    cog_path = tmp_path / "supervisor"
    cog_path.mkdir()
    (cog_path / "main.md").write_text("# sup")

    paths = resolve_cog_paths([str(cog_path)], tmp_path)
    assert len(paths) == 1
    assert paths[0] == cog_path
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/cogos/test_cog_dir.py -v`
Expected: ImportError — `cogos.cog.cog` doesn't exist

**Step 3: Write the implementation**

```python
# src/cogos/cog/cog.py
"""Directory-based Cog — a cog is just a directory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CogConfig:
    """Parsed cog.yaml."""
    mode: str = "one_shot"
    priority: float = 0.0
    executor: str = "llm"
    model: str | None = None
    runner: str = "lambda"
    capabilities: list = field(default_factory=list)
    handlers: list[str] = field(default_factory=list)
    idle_timeout_ms: int | None = None


def _load_config(path: Path) -> CogConfig:
    yaml_path = path / "cog.yaml"
    if not yaml_path.exists():
        return CogConfig()
    data = yaml.safe_load(yaml_path.read_text()) or {}
    return CogConfig(
        mode=data.get("mode", "one_shot"),
        priority=float(data.get("priority", 0.0)),
        executor=data.get("executor", "llm"),
        model=data.get("model"),
        runner=data.get("runner", "lambda"),
        capabilities=data.get("capabilities", []),
        handlers=data.get("handlers", []),
        idle_timeout_ms=data.get("idle_timeout_ms"),
    )


def _find_entrypoint(path: Path) -> tuple[str, str]:
    """Find main.py or main.md. Returns (filename, content)."""
    for name in ("main.py", "main.md"):
        f = path / name
        if f.exists():
            return name, f.read_text()
    raise FileNotFoundError(
        f"No main.py or main.md in {path}"
    )


class CogletRef:
    """Reference to a child coglet within a cog directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.config = _load_config(path)
        self.main_entrypoint, self.main_content = _find_entrypoint(path)


class Cog:
    """A cog loaded from a directory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.name = self.path.name
        self.config = _load_config(self.path)
        self.main_entrypoint, self.main_content = _find_entrypoint(self.path)

    @property
    def coglets(self) -> list[str]:
        """List child coglet names (subdirs with main.*)."""
        result = []
        for child in sorted(self.path.iterdir()):
            if not child.is_dir():
                continue
            if (child / "main.py").exists() or (child / "main.md").exists():
                result.append(child.name)
        return result

    def get_coglet(self, name: str) -> CogletRef:
        child = self.path / name
        if not child.is_dir():
            raise FileNotFoundError(f"Coglet '{name}' not found in {self.path}")
        return CogletRef(child)


def resolve_cog_paths(
    patterns: list[str], base_dir: Path | None = None
) -> list[Path]:
    """Resolve cog path patterns (with glob support) to concrete directories."""
    import glob as glob_mod

    results: list[Path] = []
    for pattern in patterns:
        expanded = glob_mod.glob(pattern)
        for match in sorted(expanded):
            p = Path(match)
            if not p.is_dir():
                continue
            # Must have a main.* entrypoint to be a cog
            if (p / "main.py").exists() or (p / "main.md").exists():
                results.append(p.resolve())
    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cogos/test_cog_dir.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/cogos/cog/cog.py tests/cogos/test_cog_dir.py
git commit -m "feat: add directory-based Cog class"
```

---

### Task 2: Create `CogRuntime` capability

**Files:**
- Create: `src/cogos/cog/runtime.py`
- Test: `tests/cogos/test_cog_runtime.py`
- Modify: `src/cogos/capabilities/registry.py` — register `cog_runtime` (replaces old entry)

**Step 1: Write the failing test**

```python
# tests/cogos/test_cog_runtime.py
"""Tests for CogRuntime capability."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from cogos.cog.cog import Cog
from cogos.cog.runtime import CogRuntime


@pytest.fixture
def cog_dir(tmp_path):
    cog_path = tmp_path / "testcog"
    cog_path.mkdir()
    (cog_path / "cog.yaml").write_text(yaml.dump({
        "mode": "daemon",
        "priority": 5.0,
        "executor": "python",
        "capabilities": ["me", "discord"],
        "handlers": ["testcog:review"],
    }))
    (cog_path / "main.py").write_text("print('hello')")
    handler = cog_path / "handler"
    handler.mkdir()
    (handler / "main.md").write_text("# Handle")
    (handler / "cog.yaml").write_text(yaml.dump({
        "mode": "daemon",
        "capabilities": ["discord"],
        "handlers": ["io:discord:message"],
    }))
    return cog_path


def test_run_cog_main(cog_dir):
    """CogRuntime.run_cog spawns the main coglet."""
    procs = MagicMock()
    procs.spawn.return_value = MagicMock(id="proc-1")
    cap_objects = {"me": MagicMock(), "discord": MagicMock()}

    runtime = CogRuntime(cog_dir, cap_objects)
    cog = Cog(cog_dir)
    handle = runtime.run_cog(cog, procs)

    procs.spawn.assert_called_once()
    call_kwargs = procs.spawn.call_args
    assert call_kwargs[0][0] == "testcog"  # name
    assert call_kwargs[1]["mode"] == "daemon"
    assert call_kwargs[1]["executor"] == "python"
    assert call_kwargs[1]["priority"] == 5.0
    assert call_kwargs[1]["content"] == "print('hello')"


def test_run_cog_passes_scoped_dir(cog_dir):
    """Main coglet gets dir scoped to cog directory."""
    procs = MagicMock()
    procs.spawn.return_value = MagicMock(id="proc-1")
    cap_objects = {"me": MagicMock(), "discord": MagicMock()}

    runtime = CogRuntime(cog_dir, cap_objects)
    cog = Cog(cog_dir)
    runtime.run_cog(cog, procs)

    caps = procs.spawn.call_args[1]["capabilities"]
    assert "dir" in caps
    assert "data" in caps
    assert "runtime" in caps


def test_run_cog_subscribes_handlers(cog_dir):
    """Main coglet subscribes to handlers from config."""
    procs = MagicMock()
    procs.spawn.return_value = MagicMock(id="proc-1")
    cap_objects = {"me": MagicMock(), "discord": MagicMock()}

    runtime = CogRuntime(cog_dir, cap_objects)
    cog = Cog(cog_dir)
    runtime.run_cog(cog, procs)

    subscribe = procs.spawn.call_args[1]["subscribe"]
    assert "testcog:review" in subscribe


def test_run_coglet_scoped(cog_dir):
    """run_coglet only works within the scoped cog directory."""
    procs = MagicMock()
    procs.spawn.return_value = MagicMock(id="proc-1")
    cap_objects = {"discord": MagicMock()}

    runtime = CogRuntime(cog_dir, cap_objects)
    handle = runtime.run_coglet("handler", procs)

    procs.spawn.assert_called_once()
    call_kwargs = procs.spawn.call_args
    assert call_kwargs[0][0] == "testcog/handler"
    assert call_kwargs[1]["content"] == "# Handle"
    assert call_kwargs[1]["mode"] == "daemon"


def test_run_coglet_outside_scope_raises(cog_dir):
    """Cannot run coglet outside scoped directory."""
    procs = MagicMock()
    cap_objects = {}
    runtime = CogRuntime(cog_dir, cap_objects)

    with pytest.raises(FileNotFoundError):
        runtime.run_coglet("nonexistent", procs)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/cogos/test_cog_runtime.py -v`
Expected: ImportError — `cogos.cog.runtime` doesn't exist

**Step 3: Write the implementation**

```python
# src/cogos/cog/runtime.py
"""CogRuntime — spawns cogs and coglets from directory structure."""

from __future__ import annotations

from pathlib import Path

from cogos.cog.cog import Cog, CogletRef


class CogRuntime:
    """Capability that spawns coglets from a scoped cog directory.

    Usage from init:
        runtime = CogRuntime(cog_dir, cap_objects)
        runtime.run_cog(cog, procs)

    Usage from main coglet:
        runtime.run_coglet("handler", procs)
    """

    def __init__(
        self,
        cog_dir: Path,
        cap_objects: dict,
    ) -> None:
        self._cog_dir = Path(cog_dir)
        self._cog_name = self._cog_dir.name
        self._cap_objects = cap_objects

    def _build_caps(self, cap_list: list, cog_name: str) -> dict:
        """Build capabilities dict from a config list."""
        caps: dict = {}
        for entry in cap_list:
            if isinstance(entry, str):
                obj = self._cap_objects.get(entry)
                caps[entry] = obj if obj is not None else None
            elif isinstance(entry, dict):
                name = entry["name"]
                alias = entry.get("alias", name)
                config = entry.get("config")
                obj = self._cap_objects.get(name)
                if config and obj is not None and hasattr(obj, "scope"):
                    caps[alias] = obj.scope(**config)
                else:
                    caps[alias] = obj if obj is not None else None
        return caps

    def run_cog(self, cog: Cog, procs) -> object:
        """Spawn the main coglet for a cog. Called by init."""
        caps = self._build_caps(cog.config.capabilities, cog.name)

        # Add scoped dir for cog's code directory
        dir_cap = self._cap_objects.get("dir")
        if dir_cap is not None and hasattr(dir_cap, "scope"):
            caps["dir"] = dir_cap.scope(prefix=f"cogs/{cog.name}/")
        else:
            caps["dir"] = None

        # Add scoped data dir
        if dir_cap is not None and hasattr(dir_cap, "scope"):
            caps["data"] = dir_cap.scope(prefix=f"data/{cog.name}/")
        else:
            caps["data"] = None

        # Pass runtime scoped to this cog so main can launch children
        caps["runtime"] = self

        subscribe = cog.config.handlers if cog.config.handlers else None

        return procs.spawn(
            cog.name,
            mode=cog.config.mode,
            content=cog.main_content,
            executor=cog.config.executor,
            model=cog.config.model,
            runner=cog.config.runner,
            priority=cog.config.priority,
            idle_timeout_ms=cog.config.idle_timeout_ms,
            capabilities=caps,
            subscribe=subscribe,
            detached=True,
        )

    def run_coglet(self, name: str, procs, capability_overrides: dict | None = None) -> object:
        """Spawn a child coglet by name within this cog. Called by main coglet."""
        cog = Cog(self._cog_dir)
        ref = cog.get_coglet(name)

        caps = self._build_caps(ref.config.capabilities, cog.name)
        if capability_overrides:
            caps.update(capability_overrides)

        # Scoped dir and data for child too
        dir_cap = self._cap_objects.get("dir")
        if dir_cap is not None and hasattr(dir_cap, "scope"):
            caps.setdefault("dir", dir_cap.scope(prefix=f"cogs/{cog.name}/"))
            caps.setdefault("data", dir_cap.scope(prefix=f"data/{cog.name}/"))

        subscribe = ref.config.handlers if ref.config.handlers else None

        return procs.spawn(
            f"{cog.name}/{name}",
            mode=ref.config.mode,
            content=ref.main_content,
            executor=ref.config.executor,
            model=ref.config.model,
            runner=ref.config.runner,
            priority=ref.config.priority,
            idle_timeout_ms=ref.config.idle_timeout_ms,
            capabilities=caps,
            subscribe=subscribe,
        )

    def __repr__(self) -> str:
        return f"<CogRuntime cog={self._cog_name}>"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cogos/test_cog_runtime.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/cogos/cog/runtime.py tests/cogos/test_cog_runtime.py
git commit -m "feat: add CogRuntime capability for directory-based cog spawning"
```

---

### Task 3: Convert cog definitions from `init/cog.py` to `cog.yaml` + directory structure

This task converts all 4 existing cogs (discord, recruiter, newsfromthefront, website) plus supervisor from Python init scripts to directory-based cog definitions.

**Files:**
- Create: `images/cogent-v1/apps/discord/cog.yaml`
- Create: `images/cogent-v1/apps/discord/main.py` (symlink or copy of `discord.py`)
- Create: `images/cogent-v1/apps/discord/handler/main.md`
- Create: `images/cogent-v1/apps/discord/handler/cog.yaml`
- Create: `images/cogent-v1/apps/recruiter/cog.yaml`
- Create: `images/cogent-v1/apps/recruiter/main.py` (copy of `recruiter.py`)
- Create: `images/cogent-v1/apps/newsfromthefront/cog.yaml`
- Create: `images/cogent-v1/apps/newsfromthefront/main.py` (copy of `newsfromthefront.py`)
- Create: `images/cogent-v1/apps/website/cog.yaml`
- Create: `images/cogent-v1/apps/website/main.py` (copy of `website.py`)
- Create: `images/cogent-v1/cogos/supervisor/cog.yaml`
- Create: `images/cogent-v1/cogos/supervisor/main.md` (content from `apps/supervisor/supervisor.md`)
- Delete: `images/cogent-v1/apps/*/init/cog.py` (all 4)

**Step 1: Read existing cog definitions to extract exact config values**

Read each `init/cog.py` and the corresponding app files to extract:
- mode, executor, model, priority, capabilities, handlers, idle_timeout_ms
- entrypoint file content
- child coglet definitions

**Step 2: Create cog.yaml files**

For each cog, write `cog.yaml` with the exact same config values as the current `init/cog.py`. Example for discord:

```yaml
# images/cogent-v1/apps/discord/cog.yaml
mode: daemon
priority: 5.0
executor: python
model: us.anthropic.claude-haiku-4-5-20251001-v1:0
capabilities:
  - me
  - procs
  - dir
  - file
  - discord
  - channels
  - stdlib
  - cog
  - coglet_runtime
  - image
  - blob
  - secrets
  - web
  - name: dir
    alias: data
    config:
      prefix: "data/discord/"
handlers:
  - discord-cog:review
  - system:tick:hour
```

**Step 3: Create main.py / main.md entrypoints**

For cogs that already have the file at the right level (e.g., `discord.py` already exists in `apps/discord/`), rename to `main.py`. For cogs where the file is elsewhere, create `main.py` or `main.md` at the cog root.

**Step 4: Create child coglet directories**

For discord handler: create `apps/discord/handler/` with `main.md` and `cog.yaml`.
For recruiter: children are created at runtime, no static directories needed.

**Step 5: Create supervisor cog**

Move `apps/supervisor/supervisor.md` to `cogos/supervisor/main.md` and create `cogos/supervisor/cog.yaml`.

**Step 6: Delete old init/cog.py files**

Remove the Python init scripts that are now replaced by directory structure.

**Step 7: Commit**

```bash
git add images/cogent-v1/
git commit -m "refactor: convert cog definitions from init/cog.py to directory structure"
```

---

### Task 4: Rewrite `init.py` to use `Cog` + `CogRuntime`

**Files:**
- Modify: `images/cogent-v1/cogos/init.py`
- Test: `tests/cogos/test_init_cog_runtime.py`

**Step 1: Write the failing test**

```python
# tests/cogos/test_init_cog_runtime.py
"""Test that init.py loads cogs from directories and spawns via CogRuntime."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, call

from cogos.cog.cog import Cog, resolve_cog_paths
from cogos.cog.runtime import CogRuntime


def test_resolve_and_run_cogs(tmp_path):
    """Simulate init: resolve cog paths, load Cog, run via CogRuntime."""
    # Set up two cog directories
    for name, mode in [("alpha", "daemon"), ("beta", "one_shot")]:
        d = tmp_path / "apps" / name
        d.mkdir(parents=True)
        (d / "cog.yaml").write_text(yaml.dump({
            "mode": mode,
            "capabilities": ["me"],
            "handlers": [f"{name}:tick"],
        }))
        (d / "main.md").write_text(f"# {name}")

    paths = resolve_cog_paths([str(tmp_path / "apps/*")], tmp_path)
    assert len(paths) == 2

    procs = MagicMock()
    procs.spawn.return_value = MagicMock(id="proc-1")
    cap_objects = {"me": MagicMock(), "dir": MagicMock()}

    for p in paths:
        cog = Cog(p)
        runtime = CogRuntime(p, cap_objects)
        runtime.run_cog(cog, procs)

    assert procs.spawn.call_count == 2
    names = [c[0][0] for c in procs.spawn.call_args_list]
    assert "alpha" in names
    assert "beta" in names
```

**Step 2: Run tests to verify they pass** (uses already-built classes)

Run: `python -m pytest tests/cogos/test_init_cog_runtime.py -v`
Expected: PASS

**Step 3: Rewrite init.py**

```python
# images/cogent-v1/cogos/init.py
# CogOS Init — boot script
# Loads cogs from directories and runs them via CogRuntime.

from pathlib import Path
from cogos.cog.cog import Cog, resolve_cog_paths
from cogos.cog.runtime import CogRuntime

# ── Capability lookup for dynamic spawning ────────────────────
_cap_objects = {
    "me": me, "procs": procs, "dir": dir, "file": file,
    "discord": discord, "channels": channels, "secrets": secrets,
    "stdlib": stdlib, "alerts": alerts, "blob": blob, "image": image,
    "asana": asana, "email": email, "github": github,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
    "cog": cog, "coglet_runtime": coglet_runtime,
}

# ── Cog paths to load ────────────────────────────────────────
# Resolve from the image directory (available as IMAGE_DIR or derive from file store)
COG_PATHS = [
    "cogos/supervisor",
    "apps/*",
]

# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
]:
    channels.create(ch_name)

# ── Load and run cogs ────────────────────────────────────────
image_dir = Path(IMAGE_DIR) if "IMAGE_DIR" in dir() else Path("/opt/image")

cog_paths = resolve_cog_paths(
    [str(image_dir / p) for p in COG_PATHS],
    image_dir,
)

for cog_path in cog_paths:
    cog_obj = Cog(cog_path)

    # Create channels declared by this cog and its coglets
    for ch_name in cog_obj.config.handlers:
        channels.create(ch_name)
    for coglet_name in cog_obj.coglets:
        ref = cog_obj.get_coglet(coglet_name)
        for ch_name in ref.config.handlers:
            channels.create(ch_name)

    runtime = CogRuntime(cog_path, _cap_objects)
    r = runtime.run_cog(cog_obj, procs)
    if hasattr(r, 'error'):
        print(f"WARN: failed to run cog {cog_obj.name}: {r.error}")
    else:
        print(f"Started cog: {cog_obj.name}")

# Kick cog orchestrators so they can set up child processes.
channels.send("discord-cog:review", {"reason": "boot"})

print("Init complete")
```

**Step 4: Run the full test suite to verify nothing is broken**

Run: `python -m pytest tests/cogos/ -v`
Expected: Some existing tests may fail — they depend on the old manifest approach. We fix those in Task 6.

**Step 5: Commit**

```bash
git add images/cogent-v1/cogos/init.py tests/cogos/test_init_cog_runtime.py
git commit -m "feat: rewrite init.py to load cogs from directories via CogRuntime"
```

---

### Task 5: Remove cog process creation from `apply_image`

**Files:**
- Modify: `src/cogos/image/apply.py` — remove steps 8 (cogs) and 10 (stale cleanup)
- Modify: `src/cogos/image/spec.py` — remove `_CogBuilder`, `add_cog()`, `cogs` from ImageSpec

**Step 1: Remove cog-related code from apply_image**

In `src/cogos/image/apply.py`:
- Remove the entire section 8 (cogs — save metadata, write boot manifest) — lines 171-272
- Remove section 10 (stale process cleanup) — lines 336-350
- Remove the `_boot/cog_processes.json` manifest write

**Step 2: Remove `_CogBuilder` and cog support from spec.py**

In `src/cogos/image/spec.py`:
- Remove `_CogBuilder` class
- Remove `add_cog()` function from the execution environment
- Remove `cogs` field from `ImageSpec`
- Keep `add_coglet()` for now (legacy coglets still in the spec)

**Step 3: Remove old init/cog.py from image loading**

Since `apps/*/init/cog.py` files are deleted (Task 3), `load_image()` won't find them anymore. No code change needed — just verify it doesn't break.

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_image_e2e.py tests/cogos/test_discord_cog_image.py -v`
Expected: Failures — tests reference old manifest. Fix in Task 6.

**Step 5: Commit**

```bash
git add src/cogos/image/apply.py src/cogos/image/spec.py
git commit -m "refactor: remove cog process creation from apply_image"
```

---

### Task 6: Update tests

**Files:**
- Modify: `tests/cogos/test_image_e2e.py` — remove manifest assertions, add cog directory tests
- Modify: `tests/cogos/test_discord_cog_image.py` — test discord cog directory structure
- Modify: `tests/cogos/test_cog.py` — remove `TestAddCog` tests that use `_CogBuilder`
- Modify: `tests/cogos/test_reboot.py` — verify reboot still works with new init

**Step 1: Update test_image_e2e.py**

Remove assertions about `_boot/cog_processes.json`. Add assertions that cog directories exist and contain correct `cog.yaml` + `main.*`.

**Step 2: Update test_discord_cog_image.py**

Test that `images/cogent-v1/apps/discord/` has the expected directory structure:
- `cog.yaml` with correct config
- `main.py` with discord orchestrator
- `handler/main.md` with handler content
- `handler/cog.yaml` with handler config

**Step 3: Update test_cog.py**

Remove tests for `_CogBuilder` / `add_cog()` / `make_default_coglet()`. Replace with tests for `Cog` class if not already covered by `test_cog_dir.py`.

**Step 4: Update test_reboot.py**

Verify reboot increments epoch and creates fresh init process. The init process will now load cogs from directories instead of reading a manifest — but reboot itself doesn't need to change.

**Step 5: Run full test suite**

Run: `python -m pytest tests/cogos/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add tests/cogos/
git commit -m "test: update tests for directory-based cog boot flow"
```

---

### Task 7: Delete dead code

**Files:**
- Delete: `src/cogos/capabilities/cog.py` (CogCapability — replaced by directory structure)
- Delete: `src/cogos/capabilities/coglet.py` (CogletCapability — subsumed by CogRuntime)
- Delete: `src/cogos/capabilities/coglet_factory.py` (CogletFactoryCapability — no factory needed)
- Delete: `src/cogos/capabilities/coglet_runtime.py` (old CogletRuntimeCapability — replaced)
- Modify: `src/cogos/capabilities/registry.py` — remove entries for deleted capabilities
- Modify: `images/cogent-v1/init/processes.py` — remove `coglet_factory`, `coglet` from init capabilities; keep `cog` and `coglet_runtime` if they're re-pointed to new classes, or remove if init no longer needs them
- Delete: `src/cogos/capabilities/coglet_caps.py` — helper for old coglet spawn

**Step 1: Remove capability registry entries**

In `registry.py`, remove entries for: `cog`, `coglet`, `coglet_factory`, `coglet_runtime` (old versions). If `CogRuntime` needs a registry entry, add one pointing to `cogos.cog.runtime.CogRuntime`.

**Step 2: Delete the capability files**

Remove the 5 files listed above.

**Step 3: Update init process capabilities**

In `images/cogent-v1/init/processes.py`, remove capabilities that no longer exist.

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS (tests for deleted code were updated in Task 6)

**Step 5: Commit**

```bash
git rm src/cogos/capabilities/cog.py src/cogos/capabilities/coglet.py \
    src/cogos/capabilities/coglet_factory.py src/cogos/capabilities/coglet_runtime.py \
    src/cogos/capabilities/coglet_caps.py
git add src/cogos/capabilities/registry.py images/cogent-v1/init/processes.py
git commit -m "chore: delete old CogCapability, CogletCapability, CogletFactory code"
```

---

### Task 8: Clean up cog model

**Files:**
- Modify: `src/cogos/cog/__init__.py` — remove patch workflow, factory helpers, old Coglet class
- Keep: Storage helpers if still needed by anything; otherwise delete

**Step 1: Audit what's still used**

Grep for imports of `cogos.cog` across the codebase. Anything still importing the old `Coglet`, `CogMeta`, patch helpers, etc. needs to be updated or the import removed.

**Step 2: Slim down `src/cogos/cog/__init__.py`**

Remove:
- `Coglet` class (old patch-workflow coglet)
- Patch-related models (`PatchResult`, `MergeResult`, `DiscardResult`, `PatchSummary`, `PatchInfo`)
- `apply_diff`, `run_tests` helpers
- Old `CogMeta` if not used

Re-export from the new `cog.py`:
```python
from cogos.cog.cog import Cog, CogConfig, CogletRef, resolve_cog_paths
from cogos.cog.runtime import CogRuntime
```

**Step 3: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/cogos/cog/
git commit -m "chore: clean up cog module — remove patch workflow, export new Cog classes"
```
