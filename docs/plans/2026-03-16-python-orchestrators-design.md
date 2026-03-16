# Python Orchestrator Refactor Design

Replace LLM orchestrators (recruiter.md, newsfromthefront.md) with Python dispatchers. LLM worker coglets stay as .md prompts.

## Problem

The current orchestrator `.md` files contain inlined Python code blocks that the LLM reads and executes via `run_code`. This wastes tokens, adds latency, and risks the LLM misinterpreting or modifying deterministic dispatch logic.

## Solution

Each cog's orchestrator becomes a `.py` file running with `executor="python"`. It reads events, creates coglets from separate `.md` files, and dispatches to them. LLM workers keep their `.md` prompts unchanged.

## Infrastructure Change

Add `channel_name` to the dispatch event in `build_dispatch_event()`:

```python
{"process_id": ..., "payload": ..., "channel_name": "newsfromthefront:tick", ...}
```

Looked up from the message's channel. `None` if no message.

## File Layout

```
images/cogent-v1/apps/newsfromthefront/
  init/cog.py              # boot: register cog, entrypoint=newsfromthefront.py
  newsfromthefront.py       # runtime: python dispatcher (replaces .md)
  researcher.md             # LLM worker (unchanged)
  analyst.md                # LLM worker (unchanged)
  test.md                   # LLM worker (unchanged)
  backfill.md               # LLM worker (unchanged)

images/cogent-v1/apps/recruiter/
  init/cog.py              # boot: register cog, entrypoint=recruiter.py
  recruiter.py             # runtime: python dispatcher (replaces .md)
  discover.md              # LLM worker (unchanged)
  present.md               # LLM worker (unchanged)
  profile.md               # LLM worker (unchanged)
  evolve.md                # LLM worker (unchanged)
  criteria.md              # config (unchanged)
  strategy.md              # config (unchanged)
  ...other config files    # unchanged
```

## Orchestrator Pattern

```python
# newsfromthefront.py
channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Create/get coglets (idempotent)
researcher = cog.make_coglet("researcher", entrypoint="main.md",
    files={"main.md": file.read("apps/newsfromthefront/researcher.md").content})

# Dispatch based on channel
if channel == "newsfromthefront:tick":
    coglet_runtime.run(researcher, procs, capability_overrides={...})
elif channel == "newsfromthefront:findings-ready":
    run = coglet_runtime.run(analyst, procs, capability_overrides={...})
    run.process().send(payload)
```

## init/cog.py Changes

Only the entrypoint and files change:

```python
cog.make_default_coglet(
    entrypoint="newsfromthefront.py",  # was "main.md"
    mode="daemon",
    files={"newsfromthefront.py": _read("newsfromthefront.py")},  # was .md
    capabilities=[...same...],
    handlers=[...same...],
)
```

## What Changes

- `newsfromthefront.md` → `newsfromthefront.py` (python dispatcher)
- `recruiter.md` → `recruiter.py` (python dispatcher)
- `init/cog.py` for each: entrypoint changes to `.py`
- `build_dispatch_event()`: adds `channel_name` field
- Worker `.md` prompts: unchanged

## What Doesn't Change

- LLM worker coglets (researcher.md, analyst.md, etc.)
- Config files (criteria.md, rubric.json, etc.)
- Cog/coglet infrastructure
- Capability system
- Channel/handler subscriptions
