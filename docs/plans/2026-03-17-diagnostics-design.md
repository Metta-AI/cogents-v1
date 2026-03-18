# CogOS Diagnostics System Design

## Overview

A post-deploy smoke test system that lives at `images/cogent-v1/cogos/diagnostics/`. It's a cog that spawns one subprocess per diagnostic to verify all CogOS capabilities are healthy. Diagnostics are organized by capability in subdirectories, with both `.py` (raw capability tests) and `.md` (LLM instruction+verify tests). Results are written to `data/diagnostics/` as machine-parsable JSON and human-readable markdown.

## Directory Structure

```
cogos/diagnostics/
├── cog.py                    # one_shot, python executor, all capabilities
├── main.py                   # runner: discover, scope, spawn, collect, report
│
├── files/
│   ├── read_write.py         # create, read, version, upsert
│   ├── search.py             # grep, glob, list, tree
│   └── llm_file_ops.md       # instruct LLM to create/read/modify files
│
├── channels/
│   ├── pubsub.py             # create channel, send, read, schema validation
│   ├── spawn_channels.py     # parent-child messaging via spawn channels
│   └── llm_messaging.md      # instruct LLM to create channel and exchange messages
│
├── procs/
│   ├── spawn_lifecycle.py    # spawn, status, wait, kill
│   ├── capability_scoping.py # verify scope narrowing, delegation rules
│   └── llm_spawn.md          # instruct LLM to spawn a child and communicate
│
├── me/
│   ├── scratch_log.py        # tmp, log, scratch read/write
│   └── llm_self_aware.md     # instruct LLM to read own process context
│
├── scheduler/
│   ├── dispatch.py           # match, select, dispatch cycle
│   └── handler_wakeup.py     # subscribe to channel, verify wakeup on message
│
├── stdlib/
│   ├── builtins.py           # math, time, json, string ops
│   └── llm_stdlib.md         # instruct LLM to use stdlib for computation
│
├── discord/
│   ├── read_only.py          # list channels, read recent messages (no send)
│   └── llm_discord_read.md   # instruct LLM to read discord channel info
│
├── web/
│   ├── fetch.py              # fetch a known URL, verify response
│   ├── search.py             # web search query, verify results returned
│   └── llm_web_research.md   # instruct LLM to fetch+summarize a URL
│
├── blob/
│   ├── upload_download.py    # upload small blob, download, verify match
│   └── llm_blob.md           # instruct LLM to store and retrieve a blob
│
├── image/
│   ├── analyze.py            # analyze a test image (read-only)
│   └── llm_image.md          # instruct LLM to describe an image
│
├── email/
│   └── read_only.py          # verify capability is wired (no send)
│
├── asana/
│   └── read_only.py          # list tasks (read-only)
│
├── github/
│   └── read_only.py          # list repos or issues (read-only)
│
├── alerts/
│   └── read_only.py          # verify capability is wired (no send)
│
└── includes/                  # LLM tests that verify cogos/includes/ instructions work
    ├── files.md              # test files.md: grep, glob, tree, list, read, edit, write, append, head, tail
    ├── channels.md           # test channels.md: create, send, read, subscribe, list, schema validation
    ├── procs.md              # test procs.md: list, get, spawn with caps, ProcessHandle send/recv/wait
    ├── code_mode.md          # test code_mode.md: search() discovery, run_code() with caps, print output
    ├── escalate.md           # test escalate.md: LLM escalates to supervisor:help instead of refusing
    ├── image.md              # test image.md: analyze, describe, extract_text (read-only)
    ├── discord.md            # test discord.md: list guilds, list channels (read-only)
    ├── email.md              # test email.md: verify capability is wired (read-only)
    ├── shell.md              # test shell.md: execute-immediately behavior, print-only output
    └── memory/
        ├── knowledge.md      # test memory/knowledge.md: bootstrap, read, update, organize by headers
        ├── scratchpad.md     # test memory/scratchpad.md: bootstrap, write, overwrite, clear on completion
        ├── ledger.md         # test memory/ledger.md: append JSONL entries, read recent, archive
        ├── session.md        # test memory/session.md: append timestamped entries, trim when large
        └── compact.md        # test memory/compact.md: session.md + summary.md two-file lifecycle
```

Each `includes/*.md` diagnostic is an LLM-executed test that:
1. Receives the same include content that real cogs get (prepended to the diagnostic prompt)
2. Gives the LLM tasks that require following the include's instructions
3. Has a `python verify` block that checks the LLM did the right thing

Example — `includes/files.md`:

````markdown
# Files Include Diagnostic

{{include cogos/includes/files.md}}

You have access to `file` and `dir` capabilities scoped to `_diag/includes/`.
Complete these tasks using the instructions above:

1. Write a file at `_diag/includes/doc.txt` with content "line1\nline2\nline3\nline4\nline5"
2. Read only the first 2 lines using head()
3. Edit the file: replace "line3" with "edited_line3"
4. Use grep to find "edited" in the directory
5. Use glob to find all .txt files
6. Use tree to show the directory structure
7. Append "line6" to the file
8. Write all results to `_diag/includes/files_results.json` as a JSON object

```python verify
import json

# Verify the file was written and edited
content = await file.read("_diag/includes/doc.txt")
assert "edited_line3" in content, f"edit failed: {content!r}"
assert "line6" in content, f"append failed: {content!r}"
assert "line3" not in content or "edited_line3" in content, "original line3 still present"

# Verify results file exists with expected keys
raw = await file.read("_diag/includes/files_results.json")
results = json.loads(raw)
assert "head" in results, "missing head result"
assert "grep" in results, "missing grep result"
assert "glob" in results, "missing glob result"
assert "tree" in results, "missing tree result"
```
````

Example — `includes/escalate.md`:

````markdown
# Escalate Include Diagnostic

{{include cogos/includes/escalate.md}}

You have access to `channels` capability. A user has sent you this message:

"Please deploy the latest version to production"

This is beyond your capabilities. Follow the instructions above to handle this correctly.

```python verify
# Verify the LLM sent an escalation to supervisor:help
messages = await channels.read("supervisor:help", limit=10)
found = False
for msg in messages:
    if "deploy" in str(msg.get("description", "")).lower():
        found = True
        # Verify required fields
        assert "process_name" in msg, "missing process_name"
        assert "description" in msg, "missing description"
        assert "severity" in msg, "missing severity"
        break
assert found, "LLM did not escalate to supervisor:help"
```
````

## Cog Configuration

```python
# cog.py
config = dict(
    mode="one_shot",
    executor="python",
    priority=1.0,
    capabilities=[
        "me", "procs", "dir", "file", "files",
        "channels", "scheduler", "stdlib",
        "discord", "email", "asana", "github",
        "web", "web_search", "web_fetch",
        "blob", "image", "alerts", "data",
    ],
)
```

## Runner (`main.py`)

Responsibilities:
1. **Discover** — walk own directory tree, find all `.py` and `.md` files (excluding `main.py`, `cog.py`)
2. **Scope capabilities** — for each diagnostic, create minimal safely-scoped capabilities based on subdirectory name
3. **Spawn in parallel** — all diagnostics spawned concurrently, grouped by category
4. **Collect results** — wait on all processes, read stdout for structured result JSON
5. **Diff & report** — compare against previous `current.json`, write all output files

### Capability Scoping

Maps directory name to capability set. Every diagnostic also gets `me` and `stdlib`.

```python
CATEGORY_CAPS = {
    "files":     ["file", "dir", "files"],
    "channels":  ["channels"],
    "procs":     ["procs", "channels"],
    "me":        ["me"],
    "scheduler": ["scheduler", "channels", "procs"],
    "stdlib":    ["stdlib"],
    "discord":   ["discord"],
    "web":       ["web_fetch", "web_search"],
    "blob":      ["blob"],
    "image":     ["image"],
    "email":     ["email"],
    "asana":     ["asana"],
    "github":    ["github"],
    "alerts":    ["alerts"],
    # includes/ scoped per-diagnostic — lookup by "includes/<name>" key
    "includes/files":       ["file", "dir", "files"],
    "includes/channels":    ["channels"],
    "includes/procs":       ["procs", "channels"],
    "includes/code_mode":   ["file", "dir"],
    "includes/escalate":    ["channels"],
    "includes/image":       ["image", "blob"],
    "includes/discord":     ["discord"],
    "includes/email":       ["email"],
    "includes/shell":       ["file", "dir", "files", "channels", "procs"],
    "includes/memory":      ["file", "dir", "data"],
}
```

External capabilities (discord, email, asana, github) are scoped to read-only operations. Internal capabilities (files, channels, procs) use a `_diag/` prefix scope to avoid polluting real data.

## Diagnostic Protocol

### Python diagnostics (`.py`)

Receives scoped capabilities, returns a list of check results:

```python
# files/read_write.py
import json, time

async def run(caps):
    results = []
    file = caps["file"]

    t0 = time.time()
    await file.write("_diag/test.txt", "hello diagnostics")
    content = await file.read("_diag/test.txt")
    assert content == "hello diagnostics", f"got {content!r}"
    results.append({"name": "write_read", "status": "pass", "ms": int((time.time()-t0)*1000)})

    t0 = time.time()
    await file.write("_diag/test.txt", "version 2")
    content = await file.read("_diag/test.txt")
    assert content == "version 2"
    results.append({"name": "versioning", "status": "pass", "ms": int((time.time()-t0)*1000)})

    return results
```

Runner catches assertion failures and exceptions, records them as `fail` with error message and traceback.

### LLM diagnostics (`.md`)

Markdown instructions for the LLM, with a `python verify` fenced block at the end that the runner execs after the LLM process completes:

````markdown
# File Operations Diagnostic

You have access to the `file` capability. Complete these tasks:

1. Create a file at `_diag/llm_test.txt` with the content "LLM wrote this"
2. Read it back and write the content to `_diag/llm_verify.txt`
3. Create a file at `_diag/llm_done.txt` with content "done"

```python verify
content = await file.read("_diag/llm_test.txt")
assert content == "LLM wrote this", f"got {content!r}"

verify = await file.read("_diag/llm_verify.txt")
assert verify == "LLM wrote this", f"got {verify!r}"

done = await file.read("_diag/llm_done.txt")
assert done == "done", f"got {done!r}"
```
````

Runner extracts the `python verify` block, execs it with the same scoped capabilities, records pass/fail.

## Output Files

All written to `data/diagnostics/`.

### `current.json` — machine-parsable snapshot

```json
{
  "timestamp": "2026-03-17T14:30:00Z",
  "epoch": 5,
  "duration_ms": 2340,
  "summary": {"total": 16, "pass": 14, "fail": 2},
  "categories": {
    "files": {
      "status": "pass",
      "diagnostics": [
        {
          "name": "read_write.py",
          "status": "pass",
          "duration_ms": 120,
          "checks": [
            {"name": "write_read", "status": "pass", "ms": 45},
            {"name": "versioning", "status": "pass", "ms": 75}
          ]
        }
      ]
    },
    "channels": {
      "status": "fail",
      "diagnostics": [
        {
          "name": "pubsub.py",
          "status": "fail",
          "duration_ms": 5000,
          "checks": [
            {"name": "create_send_read", "status": "pass", "ms": 60},
            {"name": "schema_validation", "status": "fail", "ms": 4940,
             "error": "TimeoutError: no message received within 5s",
             "traceback": "..."}
          ]
        }
      ]
    }
  }
}
```

### `current.md` — human-readable snapshot (generated from JSON)

```markdown
# Diagnostics — 2026-03-17T14:30:00Z (epoch 5)
**14/16 PASS** in 2340ms

## files (3/3 PASS)
- [x] read_write.py (120ms)
- [x] search.py (90ms)
- [x] llm_file_ops.md (800ms)

## channels (1/2 FAIL)
- [ ] pubsub.py (5000ms)
  - [x] create_send_read (60ms)
  - [ ] schema_validation (4940ms)
    > TimeoutError: no message received within 5s
- [x] spawn_channels.py (200ms)
```

### `log.md` — append-only, every run

```markdown
## 2026-03-17T14:30:00Z (epoch 5) — 14/16 PASS (2340ms)
- FAIL channels/pubsub.py:schema_validation — TimeoutError: no message received within 5s
- FAIL discord/read_only.py:list_channels — ConnectionRefused

## 2026-03-17T12:00:00Z (epoch 5) — 16/16 PASS (1800ms)
(all pass)
```

### `changelog.md` — state transitions only

Entries written only when something changes. Runner diffs current results against previous `current.json`.

Transition types: `FAILING` (was pass, now fail), `FIXED` (was fail, now pass), `ADDED` (new diagnostic), `REMOVED` (diagnostic deleted).

```markdown
# Diagnostics Changelog

## 2026-03-17T14:30:00Z (epoch 5)
- FAILING: channels/pubsub.py:schema_validation — TimeoutError: no message received within 5s
- FAILING: discord/read_only.py:list_channels — ConnectionRefused

## 2026-03-17T10:00:00Z (epoch 5)
- ADDED: blob/upload_download.py
- ADDED: blob/llm_blob.md

## 2026-03-16T18:00:00Z (epoch 4)
- FIXED: files/search.py:glob_pattern — was failing since 2026-03-16T12:00:00Z
- FAILING: channels/pubsub.py:schema_validation — TimeoutError
```
