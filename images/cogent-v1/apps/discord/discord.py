# Discord cog orchestrator — Python executor (no LLM needed for health checks).
#
# This runs every activation. The common path (handler healthy) completes
# instantly with zero LLM tokens. Only escalates if something is wrong.

h = procs.get(name="discord/handler")
has_handler = hasattr(h, 'status') and callable(h.status)

if not has_handler:
    # Bootstrap: create the handler coglet
    handler_prompt = file.read("apps/discord/handler/main.md").content
    test_content_result = file.read("apps/discord/handler/test_main.py")
    test_content = test_content_result.content if hasattr(test_content_result, 'content') else ""
    cog.make_coglet(
        name="handler",
        test_command="pytest test_main.py -v",
        files={"main.md": handler_prompt, "test_main.py": test_content},
        entrypoint="main.md",
        mode="daemon",
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        capabilities=[
            "discord", "channels", "stdlib", "procs", "file",
            "image", "blob", "secrets",
            {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
        ],
        idle_timeout_ms=300000,
    )
    h2 = cog.make_coglet("handler")
    coglet_runtime.run(h2, procs, subscribe=[
        "io:discord:dm", "io:discord:mention", "io:discord:message",
    ])
    print("Handler created and started")
    exit()

# Health check
status = h.status()
if status == "waiting" or status == "running":
    print(f"Handler is {status}. No action needed.")
    exit()

# Handler is unhealthy — escalate to supervisor for LLM-powered diagnosis
channels.send("supervisor:help", {
    "type": "discord:handler_unhealthy",
    "handler_status": status,
    "message": f"Discord handler is {status} — needs diagnosis and possible restart",
})
print(f"Handler is {status} — escalated to supervisor")
