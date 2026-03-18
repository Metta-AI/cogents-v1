# Cog Runtime Design

## Summary

Replace the current boot flow where `apply_image` pre-registers cog processes in the DB with a runtime-driven model where `init()` loads cogs from filesystem directories and spawns them via `CogRuntime`.

A cog is just a directory. No DB records, no image spec builders, no factory capabilities.

## Boot Flow

```
init(cog_paths=["cogos/supervisor", "apps/*"])
```

1. Resolve `cog_paths` — expand wildcards/prefixes against the filesystem
2. For each resolved path, create `Cog(path)` — reads directory structure
3. For each cog, call `CogRuntime.run(cog.main, capabilities)` where capabilities are:
   - `dir` scoped to the cog's directory (read-only code/prompts)
   - `data_dir` scoped to a per-cog data directory (read-write persistent state)
   - `runtime` scoped to the cog's directory (can only launch coglets within this cog)
   - plus cog-specific caps declared in `cog.yaml` (discord, channels, etc.)

The main coglet runs as a child of init. When main needs helpers, it calls `runtime.run("handler")` which resolves a coglet within the cog directory and spawns it as a child of main.

## Cog Directory Structure

```
apps/discord/
  cog.yaml            # capabilities, priority, mode, model
  main.md             # main coglet entrypoint (or main.py)
  handler/
    main.py           # child coglet entrypoint
    cog.yaml          # optional per-coglet overrides
```

`cog.yaml`:
```yaml
mode: daemon
priority: 5.0
model: sonnet
capabilities:
  - me
  - procs
  - discord
  - channels
```

Child coglets are subdirectories containing `main.md` or `main.py`. They inherit parent capabilities by default, can override via their own `cog.yaml`.

## Cog Class

Pure data object — reads a directory, no DB:

```python
cog = Cog("apps/discord")
cog.name        # "discord"
cog.main        # main coglet (entrypoint content + config)
cog.config      # parsed cog.yaml
cog.coglets     # ["handler", ...] — subdirs with main.*
```

## CogRuntime Capability

Scoped to a cog directory. Spawns coglets by name:

```python
# In init — spawn main coglet
runtime = CogRuntime(scoped_to=cog.path)
runtime.run(cog.main, capabilities=[
    dir.scope(cog.path),
    data_dir.scope(f"data/{cog.name}"),
    runtime,
    *cog.config.capabilities,
])

# In main coglet — launch child
runtime.run("handler")  # resolves handler/ within cog dir
```

`runtime.run(name)`:
1. Resolves `{name}/` relative to the scoped cog directory
2. Reads `{name}/main.py` or `main.md` as entrypoint
3. Reads `{name}/cog.yaml` if present for overrides
4. Calls `procs.spawn()` — child of caller

## What Changes

### Remove from `apply_image`
- Step 9: cog process creation, child coglets, capability binding, handler registration
- Step 10: stale process cleanup (init owns all processes)
- `_CogBuilder` / `make_default_coglet` / `make_coglet` DSL

### `apply_image` still handles
- Capabilities, resources, cron, files, schemas, channels, standalone processes (steps 1-7)

### New
- `Cog` class — reads directory, exposes config + main + coglet names
- `CogRuntime` capability — scoped to cog dir, spawns coglets by name
- New `init.py` — takes cog path list, resolves wildcards, runs each via CogRuntime

### Rework
- `reboot.py` — simpler, just re-runs init
- Cog definitions (`apps/*/init/cog.py`) become `apps/*/cog.yaml` + `apps/*/main.md`
- Supervisor becomes a cog at `cogos/supervisor/`

### Delete
- `CogCapability` — replaced by directory structure
- `CogletCapability` — subsumed by CogRuntime + dir
- `CogletFactoryCapability` — no factory needed
- Image spec `_CogBuilder` machinery
- Patch/merge/test workflow — dropped (YAGNI, cogs manage own state)
