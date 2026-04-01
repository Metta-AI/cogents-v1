# Capability Security as Task Namespaces

Inspired by Linux task_struct namespaces, FreeBSD Capsicum, and seccomp.

## Core idea

Treat the capability set as the process namespace. Today capabilities are a flat bag of named grants. Reframe them as a namespace — a structured, composable view of the world — and support OS-level primitives for manipulating that namespace at runtime.

## 1. clone() — spawn with namespace control

`procs.spawn()` already passes capabilities explicitly. Formalize this as `clone()` semantics: the child gets a copy of (some subset of) the parent's namespace.

```python
# Clone with full namespace copy (like fork)
child = procs.clone("worker", ns="copy")

# Clone with explicit narrowing (like clone with CLONE_NEWNS)
child = procs.clone("worker", ns={
    "workspace": workspace.scope(ops=["read"]),
    "channels": channels.scope(names=["status.*"]),
})
```

The parent's namespace is the ceiling — child can only receive equal or narrower.

## 2. exec() — replace the namespace

A process can shed capabilities irreversibly, like exec dropping privileges after setup.

```python
# Drop everything except what's needed for the task
me.exec(ns={
    "workspace": workspace.scope(prefix="/workspace/output/", ops=["write"]),
    "me": me,
})
# After this call, all other capabilities are gone. No way back.
```

This is monotonic narrowing applied to the whole namespace at once — useful for processes that do setup (read config, fetch secrets) then enter a restricted execution phase.

## 3. Drop-on-exec flags

Mark capabilities as setup-only so they're automatically dropped when entering the execution phase.

```python
config = dir.scope("/config/", ops=["read"], drop_on_exec=True)
secrets = secrets.scope(keys=["db-*"], drop_on_exec=True)

# ... read config, fetch secrets, build connection string ...

me.exec()  # config and secrets are now gone
# process continues with only non-drop_on_exec capabilities
```

Equivalent to `O_CLOEXEC` — the capability exists during init but doesn't survive the transition to steady-state.

## 4. seccomp() — lock the namespace

Irreversibly prevent further namespace changes. After calling `seccomp()`, the process cannot `exec()`, `clone()` with new grants, or modify its namespace in any way.

```python
me.seccomp()
# Namespace is now frozen. Cannot narrow, drop, or delegate.
# Can only use what you have.
```

This is the "I'm done configuring, lock me down" primitive. Useful for long-running processes that should never gain or change capabilities.

## 5. enter(pid, mode) — Capsicum-inspired namespace joining

A process can merge its namespace with another process's namespace. Three modes:

```python
# Replace: discard my namespace, adopt theirs
me.enter(other_pid, mode="replace")

# Intersect: keep only capabilities we both have
me.enter(other_pid, mode="intersect")

# Union: combine both namespaces (requires both to consent)
me.enter(other_pid, mode="union")
```

**Use cases:**
- **replace**: A helper process enters a worker's namespace to operate on its behalf (like `nsenter`)
- **intersect**: Two processes establish a shared least-privilege context for collaboration
- **union**: A coordinator absorbs a specialist's capabilities temporarily (requires mutual consent + still bounded by the DB-level grants)

Union is the dangerous one — it widens the namespace. Guard it: both processes must hold a `procs` capability with `ops=["enter"]`, and the resulting namespace still can't exceed what the DB grants to either process individually.

## How it fits

These five primitives give CogOS a complete lifecycle for capability namespaces:

| Primitive | Linux analog | What it does |
|---|---|---|
| `clone()` | `clone(2)` | Spawn child with namespace subset |
| `exec()` | `execve(2)` | Replace own namespace irreversibly |
| `drop_on_exec` | `O_CLOEXEC` | Auto-drop on exec transition |
| `seccomp()` | `seccomp(2)` | Freeze namespace permanently |
| `enter()` | `nsenter(1)` + Capsicum | Join another process's namespace |

The existing monotonic scoping (`scope()` can only narrow) remains the foundation. These primitives compose on top of it to support phased privilege reduction, collaboration, and hard lockdown.
