add_process(
    "scheduler",
    mode="daemon",
    content="CogOS scheduler daemon",
    code_key="cogos/lib/scheduler.md",
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_channel_messages",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
    ],
    handlers=[],
)

add_process(
    "discord-handle-message",
    mode="daemon",
    code_key="cogos/lib/discord-handle-message",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=["discord", "channels", "dir"],
    handlers=["io:discord:dm", "io:discord:mention"],
)
