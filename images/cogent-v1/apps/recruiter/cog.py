from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels", "secrets",
        "stdlib",
    ],
    handlers=["recruiter:feedback"],
)
