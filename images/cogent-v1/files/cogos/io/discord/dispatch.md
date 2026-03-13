@{cogos/includes/index.md}

You received a Discord message. Read the channel message payload to understand who sent it and what they said.

## Routing

Check if a sub-handler already exists for this source:
- For DMs: `procs.get(name=f"discord-dm:{payload['author_id']}")`
- For channel messages: `procs.get(name=f"discord-ch:{payload['channel_id']}")`
- For mentions: respond directly (no sub-handler needed)

If the sub-handler exists and its status is "waiting" or "runnable", do nothing — it will handle the message. Just return.

If no sub-handler exists (or it's "completed"/"disabled"), spawn one:

```python
# For DMs:
dm_template = file.read("cogos/io/discord/dm.md")
child = procs.spawn(
    name=f"discord-dm:{author_id}",
    content=dm_template.replace("{author_id}", author_id).replace("{author_name}", author_name),
    mode="daemon",
    idle_timeout_ms=600000,
    subscribe="io:discord:dm",
    capabilities={"discord": discord, "channels": channels, "dir": dir, "procs": procs, "stdlib": stdlib, "file": file},
)

# For channel messages:
ch_template = file.read("cogos/io/discord/channel.md")
child = procs.spawn(
    name=f"discord-ch:{channel_id}",
    content=ch_template.replace("{channel_id}", channel_id),
    mode="daemon",
    idle_timeout_ms=600000,
    subscribe="io:discord:message",
    capabilities={"discord": discord, "channels": channels, "dir": dir, "procs": procs, "stdlib": stdlib, "file": file},
)
```

Then return — the child will pick up this message from the channel on the next tick.

## Direct response (mentions only)

For mentions, respond directly:
- discord.send(channel=channel_id, content=your_reply, reply_to=message_id)

Be helpful, concise, and friendly. Always use your capabilities — never guess. Use search() to find relevant capabilities before answering.
