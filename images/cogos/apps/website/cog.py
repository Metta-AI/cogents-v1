from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=100.0,
    executor="python",
    capabilities=[
        "me", "procs", "web", "channels",
    ],
    handlers=["io:web:request"],
)
