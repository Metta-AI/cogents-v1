from cogos.cog.cog import CogConfig, model

config = CogConfig(
    mode="daemon",
    priority=100.0,
    executor="python",
    model=model("haiku"),
    capabilities=[
        "me", "procs", "email", "channels",
        "secrets",
    ],
    handlers=[
        "email-cog:review",
        "system:tick:hour",
    ],
)
