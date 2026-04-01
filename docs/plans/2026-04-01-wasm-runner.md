# Wasm Runner — Implementation Plan

**Date:** 2026-04-01
**Status:** Draft
**Idea doc:** `docs/ideas/wasm-runner.md`

## Context

CogOS has two execution paths today:

| Dispatch type | Executor | Shell? | Density | Cold start |
|---------------|----------|--------|---------|------------|
| `lambda` | Lambda function (fire-and-forget) | No | High (~131 MB) | ~500 ms |
| `channel` | Claude Code / ECS (persistent) | Yes | Low (~1 GB) | ~30 s |

The Wasm runner fills the gap: shell affordance at Lambda-class density.

### How execution works today (relevant files)

- **Executor model** — `src/cogos/db/models/executor.py:20-31` — `executor_tags`, `dispatch_type`, `status`
- **Process model** — `src/cogos/db/models/process.py:26-54` — `required_tags`, `executor`, `mode`
- **Tag-based dispatch** — `src/cogos/capabilities/scheduler.py:296-354` — matches `required_tags` to `executor_tags`
- **Dispatch event builder** — `src/cogos/runtime/dispatch.py:47-71`
- **Capability loading** — `src/cogos/executor/capabilities.py:17-89` — `build_process_capabilities()`
- **Capability base class** — `src/cogos/capabilities/base.py:162-242` — scoping, `_check()`, `_narrow()`
- **Sandbox executor** — `src/cogos/sandbox/executor.py:202-265` — restricted Python exec with capability injection
- **CDK stack** — `src/cogtainer/cdk/stacks/cogent_stack.py:286-351` — Lambda definitions
- **Local dispatcher** — `src/cogtainer/local_dispatcher.py:31-75` — `_dispatch_to_matched_executor()`

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  Scheduler tick                               │
│  dispatch_to_executor(process_id)             │
│    → select_executor(required_tags=["wasm"])  │
│    → dispatch_type = "wasm"                   │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Wasm Pool Lambda (or dedicated host)         │
│                                               │
│  ┌────────────────────────────────────────┐  │
│  │  V8 / Wasm Isolate                     │  │
│  │                                        │  │
│  │  POSIX shim layer (JS/TS)              │  │
│  │  ┌──────────┬──────────┬────────────┐  │  │
│  │  │ fs.*     │ fetch    │ process.*  │  │  │
│  │  └────┬─────┴────┬─────┴─────┬──────┘  │  │
│  │       │          │           │          │  │
│  └───────┼──────────┼───────────┼──────────┘  │
│          │          │           │              │
│  ┌───────▼──────────▼───────────▼──────────┐  │
│  │  Capability Bridge (host functions)     │  │
│  │  files.read / files.write / web_fetch   │  │
│  │  procs.spawn / channels.send            │  │
│  └──────────────┬──────────────────────────┘  │
│                 │ HTTP calls to CogOS API     │
└─────────────────┼────────────────────────────┘
                  │
                  ▼
            CogOS API
         (capability router)
```

---

## Methodology: Stubs → Tests → Implementation

We follow a strict **contract-first, test-driven** approach:

1. **Phase 1 — Interfaces & Stubs**: Define every public API surface with typed stubs that raise `NotImplementedError`. This locks the contracts before any logic is written.
2. **Phase 2 — Exhaustive Test Suite**: Write all tests against the stubs. Tests run fast (no real Wasm runtime), use in-memory fakes, and cover happy paths, edge cases, security boundaries, and concurrency. Every test fails (red) at this point.
3. **Phase 3 — Implementation**: Fill in the stubs until all tests pass (green). No test is added during this phase — if a gap is found, it goes back into Phase 2 first.

This means the test harness is **always runnable** and gives immediate signal on every change.

---

## Phase 1 — Interfaces & Stubs

**Goal:** Define every public contract. All stubs raise `NotImplementedError`. Nothing executes real Wasm yet.

### 1a. Directory structure

```
src/wasm_runner/
├── __init__.py
├── types.py              # shared types / dataclasses
├── shim/
│   ├── __init__.py
│   ├── fs.py             # VirtualFS interface
│   ├── net.py            # NetworkGate interface
│   ├── process.py        # ProcessShim interface
│   └── child_process.py  # ChildProcessShim interface
├── bridge/
│   ├── __init__.py
│   ├── capability_bridge.py   # CapabilityBridge ABC
│   └── audit.py               # AuditLogger ABC
├── runtime/
│   ├── __init__.py
│   ├── isolate.py        # WasmIsolate ABC
│   ├── pool.py           # IsolatePool ABC
│   └── handler.py        # handler(event) stub
└── dispatch/
    ├── __init__.py
    └── wasm_dispatch.py  # register_wasm_executor(), dispatch_wasm()
```

### 1b. Key interfaces

**`types.py`** — Shared value objects:
```python
@dataclass(frozen=True)
class SyscallEvent:
    op: str               # "fs.readFile", "fetch", "process.spawn", ...
    args: dict[str, Any]
    process_id: str
    timestamp_ms: int
    result: str           # "ok" | "EPERM" | "error"

@dataclass(frozen=True)
class IsolateConfig:
    process_id: str
    run_id: str
    memory_limit_mb: int = 128
    timeout_s: float = 30.0
    max_child_isolates: int = 4
    env: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class IsolateResult:
    exit_code: int
    stdout: str
    stderr: str
    syscall_log: list[SyscallEvent]
    memory_peak_mb: float
    duration_ms: float
```

**`shim/fs.py`** — Virtual filesystem interface:
```python
class VirtualFS(ABC):
    @abstractmethod
    async def read_file(self, path: str) -> bytes: ...
    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> None: ...
    @abstractmethod
    async def readdir(self, path: str) -> list[str]: ...
    @abstractmethod
    async def stat(self, path: str) -> StatResult: ...
    @abstractmethod
    async def unlink(self, path: str) -> None: ...
    @abstractmethod
    async def mkdir(self, path: str) -> None: ...
    @abstractmethod
    def translate_path(self, virtual_path: str) -> str: ...
        """Map /home/agent/workspace/x → cogos file key workspace/x"""
```

**`bridge/capability_bridge.py`** — Maps POSIX ops to CogOS capabilities:
```python
class CapabilityBridge(ABC):
    @abstractmethod
    async def files_read(self, key: str) -> bytes: ...
    @abstractmethod
    async def files_write(self, key: str, data: bytes) -> None: ...
    @abstractmethod
    async def files_search(self, prefix: str) -> list[str]: ...
    @abstractmethod
    async def files_delete(self, key: str) -> None: ...
    @abstractmethod
    async def web_fetch(self, url: str, method: str = "GET", ...) -> FetchResult: ...
    @abstractmethod
    async def process_spawn(self, command: str, args: list[str]) -> SpawnResult: ...
    @abstractmethod
    async def channel_send(self, channel: str, message: str) -> None: ...
```

**`runtime/isolate.py`** — Single isolate lifecycle:
```python
class WasmIsolate(ABC):
    @abstractmethod
    async def boot(self, config: IsolateConfig, bridge: CapabilityBridge) -> None: ...
    @abstractmethod
    async def execute(self, code: str, entrypoint: str = "main") -> IsolateResult: ...
    @abstractmethod
    async def terminate(self) -> None: ...
    @abstractmethod
    def memory_usage_mb(self) -> float: ...
    @abstractmethod
    def is_alive(self) -> bool: ...
```

**`runtime/pool.py`** — Multi-tenant isolate pool:
```python
class IsolatePool(ABC):
    @abstractmethod
    async def acquire(self, config: IsolateConfig, bridge: CapabilityBridge) -> WasmIsolate: ...
    @abstractmethod
    async def release(self, isolate: WasmIsolate) -> None: ...
    @abstractmethod
    def active_count(self) -> int: ...
    @abstractmethod
    def capacity(self) -> int: ...
```

**`dispatch/wasm_dispatch.py`** — Executor registration and dispatch:
```python
def register_wasm_executor(repo) -> Executor: ...
    """Register the wasm-pool executor. Returns the Executor record."""

async def dispatch_wasm(repo, process_id: str, run_id: str) -> dict: ...
    """Build and fire a wasm dispatch event. Returns the event payload."""
```

### 1c. Existing files to modify (stubs only)

| File | Change |
|------|--------|
| `src/cogos/db/models/executor.py` | Add `"wasm"` to `dispatch_type` docstring/validation |
| `src/cogos/capabilities/scheduler.py` | Add `elif result.dispatch_type == "wasm":` branch (stub) |
| `src/cogtainer/local_dispatcher.py` | Add `"wasm"` to dispatch type handling (stub) |

---

## Phase 2 — Exhaustive Test Suite

**Goal:** Complete test coverage written against Phase 1 stubs. All tests **fail** (red) until Phase 3. Tests must be fast — no real Wasm runtime, no network, no database.

### Test runner setup

```
tests/wasm_runner/
├── conftest.py              # shared fixtures: FakeBridge, FakeRepo, FakeAuditLogger
├── test_path_translation.py # virtual path → CogOS key mapping
├── test_virtual_fs.py       # VirtualFS operations via FakeBridge
├── test_network_gate.py     # fetch proxy, URL allowlist, deny-by-default
├── test_child_process.py    # exec → sub-isolate, cap on children, deny
├── test_process_shim.py     # env, argv, exit behavior
├── test_capability_bridge.py# bridge ↔ capability API contract
├── test_security.py         # EPERM paths, scope enforcement, no escape
├── test_audit_logging.py    # every syscall produces SyscallEvent
├── test_isolate_lifecycle.py# boot → execute → terminate, timeout, OOM
├── test_pool.py             # acquire/release, capacity, concurrent isolates
├── test_dispatch.py         # executor registration, tag matching, event shape
├── test_resource_limits.py  # memory cap, CPU fuel, child isolate cap
└── test_concurrency.py      # N parallel isolates, no cross-contamination
```

### Test categories and coverage targets

#### 2a. Path translation (`test_path_translation.py`)
```python
# Happy paths
("/home/agent/workspace/foo.txt", "workspace/foo.txt")
("/home/agent/workspace/sub/dir/bar.py", "workspace/sub/dir/bar.py")

# /tmp is ephemeral
("/tmp/scratch.txt", None)  # returns EPHEMERAL sentinel

# Traversal attacks
("/../../../etc/passwd", PermissionError)
("/home/agent/../../etc/shadow", PermissionError)
("workspace/../../../secret", PermissionError)

# Edge cases
("/home/agent/workspace/", "workspace/")          # trailing slash
("/home/agent/workspace", "workspace")             # no trailing slash
("/home/agent/workspace/a/b/../c", "workspace/a/c")  # normalized
("", PermissionError)                              # empty
("/", PermissionError)                             # root
```

#### 2b. Virtual filesystem (`test_virtual_fs.py`)
```python
# CRUD cycle
async def test_write_then_read(): ...
async def test_readdir_lists_written_files(): ...
async def test_stat_existing_file(): ...
async def test_stat_nonexistent_raises_ENOENT(): ...
async def test_unlink_removes_file(): ...
async def test_mkdir_creates_prefix(): ...

# /tmp ephemeral layer
async def test_tmp_write_read_is_memory_only(): ...
async def test_tmp_not_persisted_to_bridge(): ...

# Scoping enforcement
async def test_read_outside_prefix_raises_EPERM(): ...
async def test_write_outside_prefix_raises_EPERM(): ...

# Edge cases
async def test_read_empty_file(): ...
async def test_write_overwrite_existing(): ...
async def test_readdir_empty_directory(): ...
async def test_binary_data_roundtrip(): ...
async def test_large_file_write(size=10_MB): ...
```

#### 2c. Network gate (`test_network_gate.py`)
```python
# Allowed fetch
async def test_fetch_allowed_url(): ...
async def test_fetch_returns_status_and_body(): ...

# Blocked fetch
async def test_fetch_denied_url_raises_EPERM(): ...
async def test_fetch_private_ip_raises_EPERM(): ...     # SSRF protection
async def test_fetch_localhost_raises_EPERM(): ...

# No direct socket access
async def test_raw_tcp_raises_EPERM(): ...
async def test_raw_udp_raises_EPERM(): ...
```

#### 2d. Security boundary tests (`test_security.py`)
```python
# Unmapped syscalls
async def test_unmapped_posix_call_returns_EPERM(): ...

# Capability scope cannot widen
async def test_bridge_enforces_file_prefix_scope(): ...
async def test_bridge_enforces_read_only_ops(): ...

# No ambient capabilities
async def test_isolate_cannot_access_other_process_files(): ...
async def test_isolate_cannot_forge_process_id(): ...

# Resource exhaustion attacks
async def test_infinite_loop_hits_fuel_limit(): ...
async def test_memory_bomb_hits_limit(): ...
async def test_fork_bomb_hits_child_cap(): ...

# Path traversal (redundant with 2a but tested at VirtualFS level)
async def test_dotdot_traversal_blocked(): ...
async def test_symlink_escape_blocked(): ...
async def test_null_byte_in_path_blocked(): ...
```

#### 2e. Audit logging (`test_audit_logging.py`)
```python
async def test_every_fs_call_emits_syscall_event(): ...
async def test_every_fetch_emits_syscall_event(): ...
async def test_denied_calls_logged_with_EPERM_result(): ...
async def test_syscall_event_has_required_fields(): ...
async def test_syscall_log_ordering_matches_execution(): ...
```

#### 2f. Isolate lifecycle (`test_isolate_lifecycle.py`)
```python
async def test_boot_execute_terminate_happy_path(): ...
async def test_execute_returns_stdout_stderr(): ...
async def test_execute_captures_exit_code(): ...
async def test_execute_timeout_kills_isolate(): ...
async def test_execute_oom_kills_isolate(): ...
async def test_terminated_isolate_not_alive(): ...
async def test_double_terminate_is_noop(): ...
async def test_execute_after_terminate_raises(): ...
```

#### 2g. Pool management (`test_pool.py`)
```python
async def test_acquire_returns_isolate(): ...
async def test_release_decrements_active_count(): ...
async def test_acquire_at_capacity_blocks_or_raises(): ...
async def test_concurrent_acquire_release(n=16): ...
async def test_isolate_crash_does_not_leak_slot(): ...
async def test_pool_tracks_active_count_accurately(): ...
```

#### 2h. Dispatch integration (`test_dispatch.py`)
```python
def test_register_wasm_executor_creates_record(): ...
def test_wasm_executor_has_correct_tags(): ...
def test_wasm_dispatch_type_recognized_by_scheduler(): ...
def test_wasm_pool_stays_idle_after_dispatch(): ...
def test_dispatch_event_shape_matches_schema(): ...
def test_process_with_wasm_tag_routes_to_wasm_pool(): ...
def test_process_without_wasm_tag_does_not_route_to_wasm(): ...
```

#### 2i. Concurrency (`test_concurrency.py`)
```python
async def test_16_parallel_isolates_no_cross_contamination(): ...
    """Each isolate writes a unique file, reads it back, verifies isolation."""

async def test_concurrent_fs_writes_to_different_keys(): ...
async def test_concurrent_fetches(): ...
async def test_pool_under_load_respects_capacity(): ...
```

### Test fixtures (`conftest.py`)

```python
class FakeBridge(CapabilityBridge):
    """In-memory fake that records all calls and returns canned data."""
    def __init__(self):
        self.call_log: list[SyscallEvent] = []
        self.files: dict[str, bytes] = {}
        self.fetch_responses: dict[str, FetchResult] = {}
        self.allowed_urls: set[str] = {"*"}
        self.scope_prefix: str | None = None
        self.allowed_ops: set[str] | None = None

class FakeAuditLogger(AuditLogger):
    """Collects SyscallEvents in a list for assertion."""
    def __init__(self):
        self.events: list[SyscallEvent] = []

class FakeIsolate(WasmIsolate):
    """Scriptable fake — takes a callable to simulate code execution."""
    ...

@pytest.fixture
def bridge() -> FakeBridge: ...

@pytest.fixture
def audit() -> FakeAuditLogger: ...

@pytest.fixture
def isolate_config() -> IsolateConfig: ...

@pytest.fixture
def pool(bridge) -> IsolatePool: ...
```

### Running the tests

```bash
# All wasm runner tests — should complete in < 5 seconds
pytest tests/wasm_runner/ -x -q

# Just security tests
pytest tests/wasm_runner/test_security.py -v

# With coverage
pytest tests/wasm_runner/ --cov=src/wasm_runner --cov-report=term-missing
```

---

## Phase 3 — Implementation

**Goal:** Fill in every stub until all Phase 2 tests pass. No new tests added here — gaps go back to Phase 2.

### 3a. POSIX Shim Layer (Python, not TS)

> **Design change:** We implement the shim in Python rather than TypeScript. The shim runs as host-side code that translates POSIX-shaped calls into capability bridge calls. The Wasm isolate calls host functions (via WASI imports) which land in Python. This avoids a two-language build and keeps everything testable in pytest.

| POSIX call | Shim behavior | CogOS capability |
|------------|--------------|-----------------|
| `fs.readFile(path)` | `translate_path` → `bridge.files_read` | `files.read` |
| `fs.writeFile(path, data)` | `translate_path` → `bridge.files_write` | `files.write` |
| `fs.readdir(path)` | `translate_path` → `bridge.files_search` | `files.search` |
| `fs.stat(path)` | `translate_path` → `bridge.files_read` (existence check) | `files.read` |
| `fs.unlink(path)` | `translate_path` → `bridge.files_delete` | `files.write` (delete) |
| `fetch(url)` | `bridge.web_fetch` (URL allowlist) | `web_fetch` |
| `child_process.exec(cmd)` | `bridge.process_spawn` (capped) | `procs.spawn` |
| `process.env` | Read-only dict from `IsolateConfig.env` | Injected at init |
| `process.exit(code)` | Signal host to terminate isolate | Lifecycle |
| Anything unmapped | `raise PermissionError("EPERM")` | — |

**Path translation rules:**
- `/home/agent/workspace/*` → CogOS file key `workspace/*` (prefix = process namespace)
- `/tmp/*` → ephemeral in-memory dict (no persistence, no bridge calls)
- Everything else → `PermissionError("EPERM")`
- `..` components resolved then checked (no traversal escape)
- Null bytes, empty paths → `PermissionError`

### 3b. Capability Bridge (Python)

Concrete `CapabilityBridge` implementation using CogOS capability API:
```python
class HttpCapabilityBridge(CapabilityBridge):
    def __init__(self, api_base: str, process_id: str, audit: AuditLogger): ...
```

- All calls include `X-Process-Id` header → server-side scope enforcement
- All calls emit `SyscallEvent` via `AuditLogger`
- Network errors → clean error propagation (not raw tracebacks)

### 3c. Isolate Runtime (Python + wasmtime-py)

```python
class WasmtimeIsolate(WasmIsolate):
    """Real implementation using wasmtime-py."""
```

- Boot: create wasmtime `Store` with `StoreLimits(memory_size=config.memory_limit_mb * 1024 * 1024)`
- Fuel: `store.set_fuel(config.timeout_s * 1_000_000)` for CPU limiting
- Host functions registered via `Linker.define_func` for each POSIX shim method
- Execute: call Wasm module's entrypoint, collect stdout/stderr from captured buffers
- Terminate: `store.close()` + release memory

### 3d. Dispatch Integration

| File | Change |
|------|--------|
| `src/cogos/db/models/executor.py` | Add `"wasm"` to dispatch_type |
| `src/cogos/capabilities/scheduler.py` | `elif result.dispatch_type == "wasm":` → fire-and-forget, pool stays IDLE |
| `src/cogtainer/local_dispatcher.py` | `elif result.dispatch_type == "wasm":` → spawn isolate locally |
| `src/cogtainer/lambdas/dispatcher/handler.py` | Register `wasm-pool` executor on startup |
| `src/cogtainer/cdk/stacks/cogent_stack.py` | Add Wasm Pool Lambda (Python 3.12, 512 MB, wasmtime layer) |

### 3e. Cog config

Authors opt in:
```python
config = CogConfig(
    executor="wasm",
    required_tags=["wasm"],
    capabilities=["files", "web_fetch"],
)
```

---

## Phase 4 — Integration & Cogames Validation

**Goal:** End-to-end validation with real Wasm runtime and a Cogames scenario.

1. **Integration tests** (these DO use real wasmtime):
   - `tests/integration/test_wasm_e2e.py` — boot → execute → capability calls → result
   - `tests/integration/test_wasm_dispatch_e2e.py` — scheduler → wasm pool → isolate → done
   - `tests/integration/test_wasm_concurrency_e2e.py` — 16 parallel isolates on one host

2. **Cogames test cogent:**
   - Writes strategy code to `/home/agent/workspace/`
   - Executes it via `child_process.exec`
   - Reads results, communicates via channels
   - 16+ concurrent game-playing agents

---

## Execution Order

| # | Phase | Dependencies | Notes |
|---|-------|-------------|-------|
| 1 | Interfaces & Stubs | None | All `NotImplementedError`. Fast. |
| 2 | Test Suite | Phase 1 stubs | All tests red. No real Wasm. < 5s to run. |
| 3 | Implementation | Phase 2 tests | Fill stubs → tests go green. |
| 4 | Integration | Phase 3 | Real wasmtime, real dispatch, Cogames. |

**Phase 1 → 2 is the critical path.** Once the test harness is solid, Phase 3 implementation can proceed with high confidence and fast feedback.

---

## Open Decisions

| Decision | Options | Recommendation |
|----------|---------|---------------|
| Wasm runtime | wasmtime-py, pywasm, V8 via wasm-bindgen | **wasmtime-py** — mature, WASI support, Python-native |
| Hosting model | Lambda (fire-and-forget) vs dedicated pool | **Lambda** initially (matches existing pattern), pool later |
| Filesystem persistence | Ephemeral only vs backed by CogOS files | **Both** — `/tmp` ephemeral, `/home/agent/*` persisted via files capability |
| Networking | Full proxy vs direct egress + audit | **Full proxy** — all traffic through host functions, no direct egress |
| Shim language | TypeScript (compiled to Wasm) vs Rust | **TypeScript** — faster iteration, agents likely write JS/TS |
| Sub-isolate spawning | Allow `child_process.exec` → sub-isolate | **Yes but capped** — max 4 child isolates per parent |

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Wasm runtime bugs / escapes | wasmtime has formal verification; add seccomp on Lambda host |
| Memory exhaustion from many isolates | Hard per-isolate limit + pool-level cap; Lambda concurrency limit |
| Slow cold start if shim is large | Pre-compile shim to .wasm, bundle as Lambda layer |
| Capability API latency from isolate | Batch reads, local cache for repeated `fs.stat` |
| Agent code infinite loops | Isolate fuel/instruction counter (wasmtime supports this natively) |
