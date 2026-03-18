# Includes Audit Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all include references in cogent-v1/ — correct inaccurate docs, merge duplicates, add missing includes, wire up orphaned includes, and remove inline re-documentation.

**Architecture:** The cogent-v1 include system uses `@{file-key}` syntax resolved by `src/cogos/files/context_engine.py`. There is no auto-injection — only explicit references. Each process prompt should explicitly include the API references it needs. Memory policy includes are a pick-one library. Escalation content should be consolidated.

**Tech Stack:** Markdown prompt files in `images/cogent-v1/`

---

### Task 1: Fix `cogos/docs/fs.md` — remove false auto-injection claim

**Files:**
- Modify: `images/cogent-v1/cogos/docs/fs.md:57-59`

**Step 1: Edit the file**

Replace lines 57-59 (the "Auto-injected includes" section):

```markdown
## Auto-injected includes

All files under `cogos/includes/` are automatically prepended to every process's system prompt. This is how API references and instructions are distributed to all processes.
```

With:

```markdown
## Shared includes

Files under `cogos/includes/` are shared API references and instructions. Each process includes what it needs via `@{cogos/includes/code_mode.md}`, `@{cogos/includes/files.md}`, etc. There is no auto-injection — all includes are explicit.
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/docs/fs.md
git commit -m "fix(docs): correct fs.md — includes are explicit, not auto-injected"
```

---

### Task 2: Merge escalation content into one file

`apps/supervisor/include.md` (practical how-to) and `cogos/includes/escalate.md` (never-refuse policy) cover the same topic. Merge them into `cogos/includes/escalate.md` as the canonical location and update all references.

**Files:**
- Modify: `images/cogent-v1/cogos/includes/escalate.md` — merge content from both files
- Modify: `images/cogent-v1/cogos/includes/index.md` — reference `cogos/includes/escalate.md` instead of `apps/supervisor/include.md`
- Delete: `images/cogent-v1/apps/supervisor/include.md` — replaced by merged file

**Step 1: Rewrite `cogos/includes/escalate.md`**

Replace the entire file with the merged content:

```markdown
# Escalation Policy

**Never refuse a user request.** If you cannot do something yourself — you lack the capability, permission, information, or it's outside your scope — escalate to the supervisor. Do not tell the user you can't help. Acknowledge their request and escalate.

## How to Escalate

```python
channels.send("supervisor:help", {
    "process_name": me.process().name,
    "description": "what went wrong or what the user asked for",
    "context": "what you tried and any relevant state",
    "severity": "info",        # "info" | "warning" | "error"
    "reply_channel": "",       # optional — channel for the supervisor to respond on
})
```

## When to Escalate

- You've tried to resolve the issue yourself and failed
- You need capabilities or information you don't have access to
- A dependency (another process, external service) is not responding
- You're unsure how to proceed and guessing would be risky

## When NOT to Escalate

- Normal operation — don't escalate routine work
- Transient errors — retry once before escalating

## Rules

- **Never say "I can't do that"** — always escalate instead
- **Never suggest the user ask someone else** — you handle it by escalating
- **Acknowledge first** — let the user know you're working on it before escalating
- **Include full context** — the supervisor needs enough detail to act without follow-up questions
- **Pass along reply context** — include any channel IDs, message IDs, or author IDs so the supervisor (or a spawned helper) can respond to the user
```

**Step 2: Update `cogos/includes/index.md`**

Replace entire file:

```markdown
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/channels.md}
@{cogos/includes/escalate.md}
```

Note: this also adds `channels.md` (Task 4) since escalation uses `channels.send()`.

**Step 3: Delete `apps/supervisor/include.md`**

```bash
rm images/cogent-v1/apps/supervisor/include.md
```

**Step 4: Commit**

```bash
git add images/cogent-v1/cogos/includes/escalate.md images/cogent-v1/cogos/includes/index.md
git rm images/cogent-v1/apps/supervisor/include.md
git commit -m "refactor(includes): merge escalation into one file, add channels to index"
```

---

### Task 3: Add missing includes to supervisor prompt

The supervisor uses `channels`, `procs`, `dir`, `file`, `discord`, `email` etc. directly but includes no API reference for any of them. It also double-includes `code_mode.md` (explicit + via `whoami/index.md` which it doesn't actually chain through to index.md, but it's also in the inline sandbox section).

**Files:**
- Modify: `images/cogent-v1/cogos/supervisor/main.md`

**Step 1: Edit supervisor/main.md**

The current header is:

```markdown
# Supervisor

@{whoami/index.md}
@{cogos/includes/code_mode.md}

You handle escalated help requests from the `supervisor:help` channel.

## Sandbox environment

- `json` is pre-loaded. **Do NOT use `import`** — it does not exist.
- Variables **persist** between `run_code` calls.
- Available objects: `me`, `procs`, `dir`, `file`, `discord`, `channels`, `secrets`, `stdlib`, `alerts`, `asana`, `email`, `github`, `web_search`, `web_fetch`, `web`, `blob`, `image`, `cog_registry`, `coglet_runtime`.
```

Replace with:

```markdown
# Supervisor

@{whoami/index.md}
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/channels.md}
@{cogos/includes/procs.md}
@{cogos/includes/discord.md}
@{cogos/includes/email.md}
@{cogos/includes/image.md}
@{cogos/includes/memory/knowledge.md}

You handle escalated help requests from the `supervisor:help` channel.

## Sandbox environment

- `json` is pre-loaded. **Do NOT use `import`** — it does not exist.
- Variables **persist** between `run_code` calls.
- Available objects: `me`, `procs`, `dir`, `file`, `discord`, `channels`, `secrets`, `stdlib`, `alerts`, `asana`, `email`, `github`, `web_search`, `web_fetch`, `web`, `blob`, `image`, `cog_registry`, `coglet_runtime`.
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/supervisor/main.md
git commit -m "fix(supervisor): add missing API includes — files, channels, procs, discord, email, image, memory"
```

---

### Task 4: Add missing includes to worker prompt

The worker mentions `search` and `run_code` inline but doesn't include `code_mode.md`. It should use the canonical include. Also add `coglet/channels.md` since workers may run as coglets, and `scratchpad.md` for ephemeral working memory.

**Files:**
- Modify: `images/cogent-v1/cogos/worker/main.md`

**Step 1: Edit worker/main.md**

Current:

```markdown
# Worker

@{whoami/index.md}

You are a worker process spawned to complete a specific task.

## Tools

You have two tools: `search` and `run_code`.

- `search(query)` — discover available capabilities by keyword. Use `search("")` to list all.
- `run_code(code)` — execute Python in the sandbox. Capabilities are pre-injected as variables. `json` is pre-loaded. Use `print()` to see results. Do NOT use `import`.

## Instructions
```

Replace with:

```markdown
# Worker

@{whoami/index.md}
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/memory/scratchpad.md}

You are a worker process spawned to complete a specific task.

## Instructions
```

This removes the inline re-documentation of search/run_code (now covered by code_mode.md) and adds files.md for file operations + scratchpad.md for working memory.

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/worker/main.md
git commit -m "fix(worker): use canonical code_mode include, add files and scratchpad"
```

---

### Task 5: Add missing includes to discord handler prompt

The discord handler has extensive inline re-documentation of discord.send, data.get, web.publish. Replace with canonical includes where possible, keeping only handler-specific details inline.

**Files:**
- Modify: `images/cogent-v1/apps/discord/handler/main.md`

**Step 1: Edit the includes header**

Current:

```markdown
@{whoami/index.md}
@{cogos/includes/code_mode.md}

You are the Discord message handler. Process the message in the payload below.

## Sandbox environment

- `json` is pre-loaded. **Do NOT use `import`** — it does not exist.
- Variables **persist** between `run_code` calls.
- Available objects: `discord`, `channels`, `data` (dir), `file`, `stdlib`, `procs`, `image`, `blob`, `secrets`, `web`.
- `data` is a directory scoped to `data/discord/`. Use `data.get("key")` to get a file handle, then `.read()`, `.write(content)`, `.append(text)`.
- `web` lets you publish websites: `web.publish(path, content)` publishes HTML/CSS/JS at `web/{path}`. `web.url(path)` returns the exact public URL for that page under `/web/static/`. `web.list()` shows published files. `web.unpublish(path)` removes a file.
- Use `stdlib.time.time()` for timestamps. Use `stdlib.time.strftime(...)` for formatting.
- Pydantic models: access fields with `.field_name`, not `.get("field_name")`.

You do NOT have: email, web_search, github, asana, or any other capability not listed above.
If a user asks you to do something that requires a capability you don't have (e.g. send an email, search the web), you MUST escalate to the supervisor. Do NOT attempt it yourself.

@{cogos/includes/image.md}
```

Replace with:

```markdown
@{whoami/index.md}
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/discord.md}
@{cogos/includes/channels.md}
@{cogos/includes/image.md}
@{cogos/includes/escalate.md}
@{cogos/includes/memory/session.md}

You are the Discord message handler. Process the message in the payload below.

## Sandbox environment

- `json` is pre-loaded. **Do NOT use `import`** — it does not exist.
- Variables **persist** between `run_code` calls.
- Available objects: `discord`, `channels`, `data` (dir), `file`, `stdlib`, `procs`, `image`, `blob`, `secrets`, `web`.
- `data` is a directory scoped to `data/discord/`. Use `data.get("key")` to get a file handle, then `.read()`, `.write(content)`, `.append(text)`.
- `web` lets you publish websites: `web.publish(path, content)` publishes HTML/CSS/JS at `web/{path}`. `web.url(path)` returns the exact public URL for that page under `/web/static/`. `web.list()` shows published files. `web.unpublish(path)` removes a file.
- Use `stdlib.time.time()` for timestamps. Use `stdlib.time.strftime(...)` for formatting.
- Pydantic models: access fields with `.field_name`, not `.get("field_name")`.

You do NOT have: email, web_search, github, asana, or any other capability not listed above.
If a user asks you to do something that requires a capability you don't have (e.g. send an email, search the web), you MUST escalate to the supervisor. Do NOT attempt it yourself.
```

This adds files.md, discord.md, channels.md, escalate.md, session.md as canonical includes. Keeps handler-specific inline docs (data scoping, web, available objects, what it does NOT have) since those are specific to this process.

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/discord/handler/main.md
git commit -m "fix(discord-handler): add canonical includes for discord, files, channels, escalation, session"
```

---

### Task 6: Wire up `cogos/io/discord/` files

These templates (handler.md, dm.md, channel.md) are for spawning per-DM and per-channel sub-handlers. They reference `cogos/includes/index.md` which is correct. They should also include `discord.md` since they use the discord API.

**Files:**
- Modify: `images/cogent-v1/cogos/io/discord/handler.md`
- Modify: `images/cogent-v1/cogos/io/discord/dm.md`
- Modify: `images/cogent-v1/cogos/io/discord/channel.md`

**Step 1: Update `handler.md`**

Current:

```markdown
@{cogos/includes/index.md}

You are a Discord handler. Always use your capabilities — never guess or make up information. Use search() to find relevant tools before answering.

When you receive a message, read the channel message payload to understand who sent it and what they said. Then use your capabilities to help them.
```

Replace with:

```markdown
@{cogos/includes/index.md}
@{cogos/includes/discord.md}
@{cogos/includes/memory/session.md}

You are a Discord handler. Always use your capabilities — never guess or make up information. Use search() to find relevant tools before answering.

When you receive a message, read the channel message payload to understand who sent it and what they said. Then use your capabilities to help them.
```

**Step 2: Update `dm.md`**

Current line 29:
```markdown
2. Use discord.receive(message_type="discord:dm") to read recent DM history for context
```

Replace `message_type` with `channel_name` to match the actual discord.md API:

```markdown
2. Use discord.receive(channel_name="io:discord:dm") to read recent DM history for context
```

**Step 3: Commit**

```bash
git add images/cogent-v1/cogos/io/discord/handler.md images/cogent-v1/cogos/io/discord/dm.md
git commit -m "fix(io/discord): add discord and session includes, fix receive API call"
```

---

### Task 7: Wire up `coglet/channels.md` in worker prompt

The coglet channels doc explains io:stdin, io:stdout, io:stderr, cog:from, cog:to — the standard channels every coglet gets. Workers spawned as coglets should know about these.

**Files:**
- Modify: `images/cogent-v1/cogos/worker/main.md` (already modified in Task 4)

**Step 1: Add coglet channels include**

After the Task 4 edits, the header should be:

```markdown
# Worker

@{whoami/index.md}
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/memory/scratchpad.md}
```

Add `coglet/channels.md`:

```markdown
# Worker

@{whoami/index.md}
@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/coglet/channels.md}
@{cogos/includes/memory/scratchpad.md}
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/worker/main.md
git commit -m "fix(worker): add coglet channels include"
```

---

### Task 8: Wire up remaining memory includes

Assign memory strategies to processes that don't yet have one:
- `memory/compact.md` → discord cog orchestrator (`apps/discord/discord.md`) — long-running daemon that needs durable + session memory
- `memory/ledger.md` → supervisor — audit trail of escalations (alternative: already has knowledge.md from Task 3, add ledger too for the audit trail)
- `memory/knowledge.md` → already assigned to supervisor in Task 3

The remaining unassigned memory file is `memory/compact.md` and `memory/ledger.md`.

**Files:**
- Modify: `images/cogent-v1/apps/discord/discord.md` — add compact memory
- Modify: `images/cogent-v1/cogos/supervisor/main.md` — add ledger memory (already has knowledge from Task 3)

**Step 1: Update `apps/discord/discord.md`**

Current line 1:
```markdown
@{cogos/includes/index.md}
```

Replace with:
```markdown
@{cogos/includes/index.md}
@{cogos/includes/discord.md}
@{cogos/includes/procs.md}
@{cogos/includes/memory/compact.md}
```

This adds discord API ref (it uses discord.send), procs (it uses procs.get/spawn), and compact memory for long-running session + summary.

**Step 2: Update supervisor main.md — add ledger**

After Task 3 edits, the supervisor header has `memory/knowledge.md`. Add `memory/ledger.md` for audit trail:

```markdown
@{cogos/includes/memory/knowledge.md}
@{cogos/includes/memory/ledger.md}
```

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/discord/discord.md images/cogent-v1/cogos/supervisor/main.md
git commit -m "fix(includes): wire up compact memory to discord cog, ledger to supervisor"
```

---

### Task 9: Update `shell.md` to use escalate include

The shell include (`cogos/includes/shell.md`) already includes code_mode, files, channels, procs. It should also include escalate for consistency.

**Files:**
- Modify: `images/cogent-v1/cogos/includes/shell.md`

**Step 1: Edit shell.md**

Current:

```markdown
You are an interactive shell process in CogOS. The user types commands and expects immediate results.

@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/channels.md}
@{cogos/includes/procs.md}
```

Replace with:

```markdown
You are an interactive shell process in CogOS. The user types commands and expects immediate results.

@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/channels.md}
@{cogos/includes/procs.md}
@{cogos/includes/discord.md}
@{cogos/includes/escalate.md}
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/includes/shell.md
git commit -m "fix(shell): add discord and escalate includes"
```

---

### Task 10: Verify all includes are wired up

After all tasks, every include file should be referenced by at least one prompt:

| Include file | Referenced by |
|---|---|
| `code_mode.md` | index.md, supervisor, worker, discord handler, shell, io/discord/handler (via index) |
| `files.md` | index.md, supervisor, worker, discord handler, shell |
| `channels.md` | index.md, supervisor, discord handler, shell |
| `procs.md` | supervisor, discord cog, shell |
| `discord.md` | supervisor, discord handler, discord cog, io/discord/handler, shell |
| `email.md` | supervisor |
| `image.md` | supervisor, discord handler |
| `escalate.md` | index.md, discord handler, shell |
| `shell.md` | standalone (shell process prompt) |
| `coglet/channels.md` | worker |
| `memory/knowledge.md` | supervisor |
| `memory/scratchpad.md` | worker |
| `memory/session.md` | discord handler, io/discord/handler |
| `memory/compact.md` | discord cog |
| `memory/ledger.md` | supervisor |

**Step 1: Run grep to verify**

```bash
cd images/cogent-v1 && grep -r "@{cogos/includes/" --include="*.md" | sort
```

Verify every file in `cogos/includes/` appears at least once.

**Step 2: Final commit (if any missed adjustments)**

```bash
git add -A images/cogent-v1/
git commit -m "fix(includes): final verification — all includes wired up"
```
