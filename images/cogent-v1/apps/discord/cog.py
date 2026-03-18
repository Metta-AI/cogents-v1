from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=5.0,
    executor="python",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "stdlib", "image", "blob", "secrets", "web",
    ],
    handlers=[
        "discord-cog:review",
        "system:tick:hour",
    ],
)
