# Wasm Runner

Source: [Rivet AI / agentOS](https://rivet.gg)

A third runner type (`runner: wasm`) using WebAssembly + V8 isolates to give agents a POSIX-like shell environment at Lambda-class density (~131 MB per instance vs. ~1 GB for Fargate).

## Motivation

Today CogOS has two runner types:

| Runner | Shell affordance | Density | Cost |
|--------|-----------------|---------|------|
| **Lambda** | None — function-only | High (~131 MB) | Low |
| **ECS** | Full Linux shell | Low (~1 GB) | High |

Many workloads — especially **Cogames** where dozens of game-playing agents write and execute strategy code — need shell affordance (write a file, run a script, pipe output) but don't need a full container. Wasm fills the gap.

## Design Sketch

### Fake POSIX via Capability Proxies

The Wasm isolate presents a standard POSIX surface (filesystem, network, process table), but every syscall is backed by a CogOS capability proxy:

| POSIX call | CogOS capability | Notes |
|------------|-----------------|-------|
| `fs.readFile` / `fs.writeFile` | `files.read` / `files.write` | Scoped to process file namespace |
| `fetch` / `net.connect` | Network capability gate | URL allowlist per process |
| `child_process.exec` | Process capability | Can spawn sub-isolates |
| Anything unmapped | Returns `EPERM` | Deny by default |

Agents think they're in Linux, but every syscall is **typed, logged, and revocable**.

### Runtime

- V8 isolates (via wasi-compatible runtime, e.g. wasm-micro-runtime or wazero)
- Cold start < 50 ms (vs. ~500 ms Lambda, ~30 s ECS)
- Memory ceiling per isolate: configurable, default ~128 MB
- Multiple isolates share a single host process for high tenant density

### Integration Points

- **Executor dispatch**: `runner: wasm` in cogent config, executor routes to Wasm pool
- **Capability injection**: isolate receives only the capabilities granted to the process
- **Observability**: every proxied syscall emits a CogOS event (already fits the event model)
- **Lifecycle**: isolate created on process start, destroyed on process end or timeout

## Use Cases

1. **Cogames**: many concurrent agents writing/executing strategy code without a container per player
2. **Code-gen agents**: agents that need to write, lint, and test code in a sandboxed shell
3. **Batch scripting**: lightweight cron-like processes that run shell scripts on a schedule

## Open Questions

- Which Wasm runtime? (V8/wasi, wazero, wasmtime, wasm-micro-runtime)
- How to handle long-running isolates vs. request-scoped ones?
- Should the fake filesystem support a persistent layer (backed by CogOS files) or be ephemeral only?
- Networking: full proxy vs. direct egress with audit logging?
