from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=100.0,
    executor="python",
    capabilities=[
        "me", "procs", "github",
        "channels",
    ],
    handlers=[
        "system:tick:hour",
        "github:discover",
    ],
)
