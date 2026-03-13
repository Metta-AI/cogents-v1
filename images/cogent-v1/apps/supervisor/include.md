# Asking the Supervisor for Help

If you cannot handle your current task — you're stuck, missing information, encountering repeated errors, or the work is outside your scope — escalate to the supervisor via the `supervisor:help` channel.

## How to Escalate

```python
channels.send("supervisor:help", {
    "process_name": me.process().name,
    "description": "what went wrong",
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
