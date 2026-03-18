from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=5.0,
    executor="python",
    capabilities=[
        "me", "procs", "dir", "file", "web", "channels",
        "stdlib",
    ],
    handlers=["io:web:request"],
)
