from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    priority=100.0,
    handlers=["process:run:failed", "system:alerts"],
    capabilities=[
        "history", "procs", "channels", "alerts", "secrets",
    ],
    idle_timeout_ms=60000,
)
