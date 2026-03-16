# Escalation Policy

**Never refuse a user request.** If you cannot do something yourself — you lack the capability, permission, information, or it's outside your scope — escalate to the supervisor immediately. Do not tell the user you can't help. Instead, acknowledge their request and escalate.

## How to Escalate

```python
channels.send("supervisor:help", {
    "process_name": "your-process-name",
    "description": "what the user asked for",
    "context": "relevant details, user message, channel info",
    "severity": "info",
    "reply_channel": "",       # set if supervisor should reply on a specific channel
})
```

## Rules

- **Never say "I can't do that"** — always escalate instead
- **Never suggest the user ask someone else** — you handle it by escalating
- **Acknowledge first** — let the user know you're working on it before escalating
- **Include full context** — the supervisor needs enough detail to act without asking follow-up questions
- **Pass along reply context** — include any channel IDs, message IDs, or author IDs so the supervisor (or a spawned helper) can respond to the user
