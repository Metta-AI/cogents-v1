# Coglet Architecture

*Fractal asynchronous control for distributed agent systems.*

## 1. Primitive

**Coglet** = **COG** (control) + **LET** (execution)

- **LET** — fast, reactive, executes tasks
- **COG** — slow, reflective, supervises and adapts LETs

Recursive composition: a COG is itself a LET under a higher COG. The system forms a temporal hierarchy where layers share a uniform interface and differ only in cadence and scope.

## 2. LET Interface

**LET** = Listen, Enact, Transmit

Two I/O channels and one command interface:

**I/O Channels**

| Channel | Signature | Direction | Purpose |
|---|---|---|---|
| **Listen** | `listen() → AsyncStream[Event]` | in | Environment input: tasks, observations, upstream outputs |
| **Transmit** | `transmit(result: Result)` | out | Environment output: actions, decisions, traces |

**Command Interface**

| Method | Signature | Caller | Purpose |
|---|---|---|---|
| **Enact** | `enact(command: Command) → Result` | COG | Apply any directive: patch, query, config change |

Listen/transmit face the environment. Enact faces the COG. A LET with no COG is a standalone reactive process on its I/O channels.

Core loop:

```python
async def run(self):
    async for event in self.listen():
        result = self.process(event)
        await self.transmit(result)
```

## 3. COG Interface

**COG** = Create, Observe, Guide

Three methods:

| Method | Signature | Purpose |
|---|---|---|
| **Create** | `create(config: LETConfig) → Endpoint` | Spawn a new LET, return its channel handles |
| **Observe** | `observe(let_id) → AsyncStream[Result]` | Subscribe to a LET's transmit stream |
| **Guide** | `guide(let_id, command: Command)` | Call `enact()` on a LET |

Core loop:

```python
async def run(self):
    while True:
        results = await self.observe_fleet()
        for let_id, command in self.optimize(results):
            await self.guide(let_id, command)
```

## 4. Capabilities

Capabilities are orthogonal to the COG/LET distinction. They are injected infrastructure, not channel protocol. Any process may be granted any capability at construction time.

### 4.1 Memory

```python
class Memory(Protocol):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any: ...
    async def query(self, predicate: Callable) -> List[Any]: ...
```

Backend is a deployment decision (in-process dict, Redis, vector store, git-backed). A process without memory is a valid, stateless process.

## 5. Communication Model

COG and LET communicate via asynchronous channels and can be instantiated on different runtimes. They have clear boundaries and cannot see inside each other except via agreed protocol.

Properties:
- Location-agnostic (components don't know where peers run)
- Backpressure-tolerant
- Naturally distributable across processes/machines
- No synchronous calls between COG and LET — system remains live under partial failure

## 6. Mixins

Optional mixins for any Coglet.

### 6.1 LifeLet

Lifecycle hooks for the Coglet. All hooks are no-ops by default.

| Hook | When | Use |
|---|---|---|
| `on_start()` | Process initialized, channels open | Connect resources, announce presence |
| `on_message(event)` | Each event arrives on listen channel | Middleware: logging, metrics, filtering |
| `on_stop()` | Shutdown signal received | Flush state, drain output, release resources, deregister |
| `on_child_start(child_id)` | A child Coglet starts | Track fleet, allocate resources, wire observers |
| `on_child_stop(child_id)` | A child Coglet stops | Reassign work, release resources, update fleet state |

Hooks run inside the process's event loop. A hook that raises aborts the transition.

### 6.2 GitLet

Uses a git repo for the Coglet's program. The repo *is* the policy — the Coglet executes from HEAD, and accepts patches as commits.

```
COG analyzes traces → git commit (patch)
Coglet pulls HEAD   → enacts new behavior
```

`enact()` for a GitLet means `git pull` + reload. Rollback is `git revert`. Branching enables parallel policy experiments. The patch protocol is just git — no custom serialization needed.

### 6.3 LogLet

Adds a dedicated log stream alongside the Coglet's transmit stream. The COG subscribes to it separately from the main output.

```
Coglet transmit stream → results, actions, decisions
Coglet log stream      → internal traces, state snapshots, metrics, debug info
```

The COG controls log verbosity by enacting config changes on the Coglet. Without LogLet, the COG only sees the transmit stream.
