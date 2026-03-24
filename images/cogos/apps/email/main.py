# Email cog orchestrator — ensures handler exists with correct subscriptions.

handler_content = src.get("handler/main.md").read()
if hasattr(handler_content, 'error'):
    print("WARN: handler content not found: " + str(handler_content.error))
    exit()

r = procs.spawn("email/handler",
    mode="daemon",
    content=handler_content.content,
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    idle_timeout_ms=300000,
    capabilities={
        "email": None, "channels": None,
        "secrets": None,
        "disk": disk,
    },
    subscribe=[
        "io:email:inbound",
    ],
)
if hasattr(r, 'error'):
    print("WARN: handler spawn failed: " + str(r.error))
    exit()

# Health check
h = procs.get(name="email/handler")
if not hasattr(h, 'status') or not callable(h.status):
    print("Handler spawned, waiting for first dispatch")
    exit()

status = h.status()
if status == "waiting" or status == "running" or status == "runnable":
    print("Handler is " + status + ". OK.")
    exit()

channels.send("supervisor:help", {
    "type": "email:handler_unhealthy",
    "handler_status": status,
    "message": "Email handler is " + status + " — needs diagnosis and possible restart",
})
print("Handler is " + status + " — escalated to supervisor")
