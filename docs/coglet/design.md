# Coglet Design

## Overview

A coglet is a long-lived container that wraps code + capabilities + a test command. It provides a uniform interface for Authors to inspect, patch, and evolve the code inside — regardless of whether that code is LLM instructions, Python source, or anything else.

Coglets implement the child side of the authoring protocol. An Author creates a coglet, the Runtime stores and executes it, and the Author interacts with it through a capability API that serves as the protocol's "tendril."

## Core Concepts

### What is a Coglet

A coglet is:
- A **file tree** (code, tests, configs) stored in the CogOS FileStore
- A **test command** that validates the code (exit code 0 = pass)
- A **version counter** on its main state
- An **API** (exposed as a CogOS capability) for inspection and patch management

The coglet does not interpret its own contents. It is a container — the Author decides what goes inside and what the test command checks.

### File Layout

```
/coglets/{coglet_id}/meta.json        -- metadata (name, test_command, version)
/coglets/{coglet_id}/main/...         -- current accepted file tree
/coglets/{coglet_id}/patches/{patch_id}/...  -- per-patch branches
/coglets/{coglet_id}/log              -- append-only patch history
```

- `coglet_id` is a UUID assigned at creation.
- `main/` is the canonical state. It has an integer version counter stored in `meta.json`.
- Each pending patch gets its own branch under `patches/`.

### Patch Workflow (PR Model)

The patch workflow follows a CI/CD mental model:

1. **Propose**: Author calls `propose_patch(diff)`. The container:
   - Records the current main version as `base_version`
   - Creates a patch branch under `patches/{patch_id}/`
   - Copies main files to the branch
   - Applies the diff
   - Runs the test command against the branch
   - Returns `{patch_id, base_version, test_passed, test_output}`

2. **Merge**: Author calls `merge_patch(patch_id)`. The container:
   - Checks that main's current version == patch's `base_version`
   - If match: promotes patch files to main, bumps version, deletes the branch
   - If mismatch: rejects with `{conflict: true, current_version, base_version}`

3. **Discard**: Author calls `discard_patch(patch_id)` to delete a branch.

Multiple patches can be in flight simultaneously. Only one merges at a time. Stale patches (whose `base_version` no longer matches main) get conflict errors on merge — the Author must re-propose against the new main.

### Test Execution

When `propose_patch()` or `run_tests()` is called, the container runs the test command. Two execution modes, selected by the coglet's `executor` field:

- **`sandbox`**: Runs the test code through `SandboxExecutor.execute()` in-process. Fast. Uses the same machinery as the `"python"` executor path in `execute_process()`. Good for lightweight validation (assertions, schema checks).

- **`subprocess`**: Materializes the file tree to a temp directory, runs the test command via `subprocess.run(test_command, shell=True, cwd=tmpdir, timeout=timeout)`, captures stdout/stderr and exit code, cleans up. Required for coglets that need full Python (pytest, imports, etc.).

Default is `subprocess` — it works for everything.

## Capability API

### CogletsCapability (Factory)

Manages the collection of coglets. Bound to an Author process.

```python
class CogletsCapability(Capability):

    def create(
        self,
        name: str,
        test_command: str,
        files: dict[str, str],
        executor: str = "subprocess",
        timeout_seconds: int = 60,
    ) -> CogletInfo:
        """Create a new coglet with initial files.

        Stores files under /coglets/{new_id}/main/.
        Runs test_command to validate initial state.
        Returns {coglet_id, name, version, test_passed, test_output}.
        """

    def list(self) -> list[CogletInfo]:
        """List all coglets the caller can access."""

    def get(self, coglet_id: str) -> CogletInfo:
        """Get metadata for a coglet."""

    def delete(self, coglet_id: str) -> DeleteResult:
        """Delete a coglet and all its files."""
```

Scoping via `_narrow()` restricts which coglet IDs the Author can access.

### CogletCapability (Tendril)

Operates on a single coglet. Scoped to a coglet ID.

```python
class CogletCapability(Capability):

    # --- Patch workflow ---

    def propose_patch(self, diff: str) -> PatchResult:
        """Snapshot main, create branch, apply diff, run tests.

        Returns {patch_id, base_version, test_passed, test_output}.
        """

    def merge_patch(self, patch_id: str) -> MergeResult:
        """Promote patch to main if base_version matches.

        Returns {merged: bool, new_version} or {conflict: true, current_version, base_version}.
        """

    def discard_patch(self, patch_id: str) -> DiscardResult:
        """Delete a patch branch."""

    # --- Inspection ---

    def read_file(self, path: str, patch_id: str | None = None) -> str:
        """Read a file from main or a specific patch branch."""

    def list_files(self, patch_id: str | None = None) -> list[str]:
        """List files in main or a patch branch."""

    def list_patches(self) -> list[PatchSummary]:
        """All pending patches with status and base_version."""

    def get_status(self) -> CogletStatus:
        """Current state: idle, tests_running, patch count, version."""

    def run_tests(self) -> TestResult:
        """Run test_command against current main state."""

    def get_log(self) -> list[LogEntry]:
        """History of patches proposed/merged/discarded with test results."""
```

## Metadata

Stored at `/coglets/{coglet_id}/meta.json`:

```json
{
    "id": "coglet-uuid",
    "name": "my-discord-bridge",
    "test_command": "pytest tests/",
    "executor": "subprocess",
    "timeout_seconds": 60,
    "version": 3,
    "created_at": "2026-03-15T00:00:00Z",
    "patches": {
        "patch-uuid-1": {
            "base_version": 3,
            "test_passed": true,
            "test_output": "3 passed in 0.5s",
            "created_at": "2026-03-15T01:00:00Z"
        }
    }
}
```

## Authoring Protocol Mapping

| Protocol Role | Coglet Mapping |
|---------------|----------------|
| **Author** | The process that creates and patches the coglet (a Cog, Cogent, or Human) |
| **Requester** | The level above the Author — provides context and interaction capabilities |
| **Runtime** | CogOS infrastructure — file storage, test execution, version tracking |
| **Tendril** | `CogletCapability` — the Author's handle for inspection and patching |
| **`log()`** | `get_log()` — patch history flows up to the Author |
| **`search()`** | `read_file()`, `list_files()`, `get_status()` — inspect the coglet's space |
| **`execute()`** | `propose_patch()`, `merge_patch()` — modify the coglet's space |

## Image Integration

Coglets can be declared in image init scripts:

```python
add_coglet(
    name="my-thing",
    test_command="pytest tests/",
    files={
        "src/main.py": "def hello(): return 'world'",
        "tests/test_main.py": "from src.main import hello\ndef test_hello(): assert hello() == 'world'",
    },
)
```

This creates the coglet at image apply time with version 0.

## Implementation

### New Files

- `src/cogos/coglet/__init__.py` — coglet metadata model, test runner, file tree operations
- `src/cogos/capabilities/coglets.py` — `CogletsCapability` (factory)
- `src/cogos/capabilities/coglet.py` — `CogletCapability` (tendril)
- `tests/cogos/test_coglet.py` — unit tests

### Key Reuse

- **FileStore** for all file operations — coglet files are regular CogOS files with key prefixes
- **FileStore.append()** for accumulating log entries at `/coglets/{id}/log`
- **SandboxExecutor** for `executor: "sandbox"` mode — same machinery as `_execute_python_process()`
- **Capability base class** with `_narrow()` / `_check()` for scoping

### Scope Narrowing

`CogletsCapability._narrow()` restricts the set of coglet IDs the holder can access. `CogletCapability._narrow()` restricts to a single coglet ID. When an Author creates a coglet, it gets back a `CogletCapability` scoped to that ID.

## Key Invariants

1. **Patches are tested before merge** — `merge_patch()` refuses if tests haven't passed.
2. **Optimistic concurrency** — merge fails if main has moved since the patch was proposed.
3. **The container is code-agnostic** — it doesn't interpret files, just stores and tests them.
4. **Test command is the only oracle** — exit 0 = pass, anything else = fail.
5. **Authors can only access coglets they're scoped for** — capability narrowing enforced.
