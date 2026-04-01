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

## Implementation Phases

### Phase 1 — POSIX Shim Layer (TypeScript)

**Goal:** A JS/TS module that implements a fake POSIX surface, delegating every call to typed host functions.

**Files to create:**

```
src/wasm_runner/
├── shim/
│   ├── fs.ts          # readFile, writeFile, readdir, stat, unlink, mkdir
│   ├── net.ts         # fetch wrapper, TCP stub
│   ├── process.ts     # env, argv, exit, spawn (sub-isolate)
│   ├── child_process.ts  # exec, execSync → sub-isolate or deny
│   └── index.ts       # assembles shim into globalThis / WASI imports
├── bridge/
│   ├── host.ts        # host function definitions (called by shim)
│   └── client.py      # Python HTTP client for CogOS capability API
├── runtime/
│   ├── isolate.py     # manages a single Wasm isolate lifecycle
│   ├── pool.py        # pool of isolates on a single host
│   └── handler.py     # Lambda/local handler entry point
└── tests/
    ├── test_shim.ts
    ├── test_bridge.py
    └── test_isolate.py
```

**Key design decisions:**

| POSIX call | Shim behavior | CogOS capability |
|------------|--------------|-----------------|
| `fs.readFile(path)` | Translate path to key, call host `files_read` | `files.read` |
| `fs.writeFile(path, data)` | Translate path to key, call host `files_write` | `files.write` |
| `fs.readdir(path)` | Call host `files_search` with prefix | `files.search` |
| `fs.stat(path)` | Check existence via `files_read`, synthesize stat | `files.read` |
| `fs.unlink(path)` | Call host `files_delete` | `files.write` (delete op) |
| `fetch(url)` | Call host `web_fetch` | `web_fetch` capability |
| `child_process.exec(cmd)` | Parse cmd, spawn sub-isolate or deny | `procs.spawn` |
| `process.env` | Read-only env from capability config | Injected at init |
| `process.exit(code)` | Signal host to terminate isolate | Lifecycle |
| Anything unmapped | `throw new Error("EPERM")` | — |

**Path translation:** The isolate sees a virtual filesystem rooted at `/`. Paths are translated to CogOS file keys:
- `/home/agent/workspace/foo.txt` → `workspace/foo.txt` (prefix = process file namespace)
- `/tmp/*` → ephemeral in-memory Map (no persistence)

### Phase 2 — Isolate Runtime (Python)

**Goal:** Python code that boots a Wasm isolate, injects the shim, and bridges host function calls to the CogOS capability API.

**Files to modify:**

| File | Change |
|------|--------|
| `src/cogos/db/models/executor.py` | Add `"wasm"` as valid `dispatch_type` |
| `src/cogos/capabilities/scheduler.py` | Handle `dispatch_type == "wasm"` in dispatch logic |
| `src/cogtainer/local_dispatcher.py` | Add wasm dispatch path in `_dispatch_to_matched_executor()` |
| `src/cogos/runtime/dispatch.py` | Build dispatch event for wasm (same shape, new type) |

**Files to create:**

| File | Purpose |
|------|---------|
| `src/wasm_runner/runtime/isolate.py` | `WasmIsolate` class — boots V8/wasm runtime, loads shim, exposes host functions |
| `src/wasm_runner/runtime/pool.py` | `IsolatePool` — manages N isolates per host, lifecycle, memory limits |
| `src/wasm_runner/runtime/handler.py` | Lambda handler entry point: receive dispatch event → boot isolate → run → return |
| `src/wasm_runner/bridge/client.py` | HTTP client that calls CogOS capability API with `X-Process-Id` header |

**Isolate lifecycle:**
1. Receive dispatch event (process_id, run_id, capabilities)
2. Boot isolate with memory limit (default 128 MB)
3. Inject POSIX shim with host function bindings
4. Load and execute agent code (from `files.read` of process cog)
5. On completion or timeout → destroy isolate, report result

**Runtime choice (Phase 2 scope):** Start with [pywasm](https://github.com/aspect-build/aspect-cli) or [wasmtime-py](https://github.com/bytecodealliance/wasmtime-py) for the Python host. V8 isolates (via workers or wasm-bindgen) is a Phase 3 optimization for production density.

### Phase 3 — Executor Registration & Dispatch Integration

**Goal:** Wire the Wasm runner into the existing dispatch system so `required_tags: ["wasm"]` routes to it.

**Changes:**

1. **Register wasm executor** — In dispatcher startup (`src/cogtainer/lambdas/dispatcher/handler.py`), seed a wasm-pool executor:
   ```python
   wasm_executor = Executor(
       executor_id="wasm-pool",
       channel_type="wasm",
       executor_tags=["wasm", "python", "javascript"],
       dispatch_type="wasm",
       metadata={"pool": True, "max_isolates": 64},
   )
   repo.register_executor(wasm_executor)
   ```

2. **Dispatch path** — In scheduler, handle `dispatch_type == "wasm"` similar to lambda (fire-and-forget, stays IDLE):
   ```python
   # scheduler.py dispatch_to_executor()
   if result.dispatch_type == "wasm":
       # Invoke wasm pool Lambda (or local subprocess)
       # Pool stays IDLE (multi-tenant)
   ```

3. **CDK stack** — Add Wasm Pool Lambda to `cogent_stack.py`:
   - Runtime: Python 3.12 (hosts wasmtime-py)
   - Memory: 512 MB (fits ~4 isolates at 128 MB each)
   - Timeout: 5 min (matches executor Lambda)
   - Layers: wasmtime-py, prebuilt POSIX shim .wasm

4. **Cog config** — Authors opt in:
   ```python
   config = CogConfig(
       executor="wasm",
       required_tags=["wasm"],
       capabilities=["files", "web_fetch"],
   )
   ```

### Phase 4 — Capability Bridge Hardening

**Goal:** Ensure the POSIX shim correctly enforces CogOS capability scoping.

**Key concerns:**

1. **Scope propagation** — The bridge must pass the process's capability scope to every API call. The shim cannot bypass scoping by crafting raw HTTP.
   - Host functions receive `process_id` at init time; API enforces scope server-side
   - Shim has no direct network access (all `fetch` goes through host)

2. **Deny by default** — Any POSIX call not in the mapping table returns EPERM:
   ```typescript
   // shim/index.ts
   const handler = {
     get(target, prop) {
       if (prop in target) return target[prop];
       return () => { throw new Error(`EPERM: ${prop} not available`); };
     }
   };
   ```

3. **Audit logging** — Every host function call emits a CogOS event:
   ```python
   # bridge/client.py
   async def files_read(self, key: str) -> bytes:
       self._emit_event("wasm.syscall", {"op": "fs.readFile", "key": key})
       return await self._capability_api("files", "read", key=key)
   ```

4. **Resource limits:**
   - Memory: configurable per isolate (default 128 MB)
   - CPU: isolate timeout (default 30s per execution, configurable)
   - File writes: rate limit via capability config
   - Network: URL allowlist in `web_fetch` capability scope

### Phase 5 — Cogames Integration & Testing

**Goal:** Validate with a real use case — concurrent game-playing agents.

1. **Test cogent** — Create a test cog that uses `runner: wasm`:
   - Writes strategy code to filesystem
   - Executes it via `child_process.exec`
   - Reads results back
   - Communicates with other agents via channels

2. **Concurrency test** — Spin up 16+ simultaneous wasm processes on a single Lambda invocation to validate density claims.

3. **Integration tests:**
   - `tests/integration/test_wasm_dispatch.py` — end-to-end dispatch
   - `tests/integration/test_wasm_capabilities.py` — capability scoping in isolate
   - `tests/integration/test_wasm_posix_shim.py` — POSIX surface correctness

---

## Execution Order

| # | Phase | Dependencies | Est. complexity |
|---|-------|-------------|-----------------|
| 1 | POSIX shim (TS) | None | Medium — straightforward mapping |
| 2 | Isolate runtime (Python) | Phase 1 shim artifact | Medium — wasmtime-py integration |
| 3 | Dispatch integration | Phase 2 runtime | Low — follows existing patterns |
| 4 | Capability hardening | Phases 1-3 | Medium — security review needed |
| 5 | Cogames integration | Phases 1-4 | Low-Medium — validation |

**Phase 1-2** can be developed in parallel (shim TS + runtime Python) since the bridge interface is defined upfront.

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
