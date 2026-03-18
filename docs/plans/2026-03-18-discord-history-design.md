# Discord Channel History Design

## Overview

Add `discord.history(channel_id, limit=50)` to the Discord capability so the handler (and any cog) can fetch channel history from the Discord API. The handler uses this to backfill `recent.log` after reboots or when entering a new channel, then continues appending locally.

## API

```python
discord.history(channel_id, limit=50, before=None, after=None)
```

Returns a list of dicts matching the existing inbound message format:

```python
[
    {
        "content": "hello",
        "author": "alice",
        "author_id": "123456",
        "channel_id": "789",
        "message_id": "111",
        "timestamp": "2026-03-18T12:30:00Z",
        "is_dm": False,
        "is_mention": False,
        "attachments": [],
        "thread_id": None,
        "reference_message_id": None,
    },
]
```

- `before` / `after` are message IDs for pagination
- Results ordered oldest-first (chronological)
- Timeout: 15 seconds

## Bridge Request/Response

Two new CogOS channels created by init:

- `io:discord:api:request` — capability writes requests here
- `io:discord:api:response` — bridge writes responses here

**Request format:**
```python
{
    "request_id": "uuid",
    "method": "history",
    "channel_id": "789",
    "limit": 50,
    "before": None,
    "after": None,
}
```

**Response format:**
```python
{
    "request_id": "uuid",
    "status": "ok",
    "messages": [...],
    "error": None,
}
```

The bridge polls `io:discord:api:request` every 2 seconds. On request, it calls `channel.history()` via discord.py, converts messages to the standard payload format, and writes the response.

The capability writes a request, then polls `io:discord:api:response` filtering by `request_id` until it gets a match or times out.

## Handler Changes

One change to `handler/main.md` Step 1 — when `recent.log` is empty or missing, backfill from Discord API:

```python
log_handle = data.get(f"{conv_key}/recent.log")
log_data = log_handle.read()

if hasattr(log_data, 'error') or not log_data.content:
    history_msgs = discord.history(channel_id=channel_id, limit=50)
    lines = []
    for msg in history_msgs:
        lines.append(msg["author"] + ": " + msg["content"])
    log_handle.write("\n".join(lines))
    history = "\n".join(lines)
else:
    history = log_data.content
```

Everything else stays the same — local log appending, waterline dedup, escalation.

## Files to Change

| File | Change |
|------|--------|
| `src/cogos/io/discord/capability.py` | Add `history()` method with request/response polling |
| `src/cogos/io/discord/bridge.py` | Add API request polling task, `channel.history()` fetch |
| `images/cogent-v1/apps/discord/handler/main.md` | Add backfill block in Step 1 |
| `images/cogent-v1/cogos/init.py` | Create `io:discord:api:request` and `io:discord:api:response` channels |
| `images/cogent-v1/cogos/includes/discord.md` | Document `discord.history()` |
