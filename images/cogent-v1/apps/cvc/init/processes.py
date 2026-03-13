# CvC (Cogent vs Cogent) app — two-process coglet for MettaGrid tournaments.
#
# cog-policy (daemon) — game loop: receives observations, executes policy.py, sends actions
# cog (daemon) — strategist: monitors game, rewrites policy.py via LLM

# -- Context engine wiring (includes) --

add_file("apps/cvc/prompts/cog-policy.md", content="", includes=[
    "apps/cvc/shared/game_rules.md",
])

add_file("apps/cvc/prompts/cog.md", content="", includes=[
    "apps/cvc/shared/game_rules.md",
])

# -- Channels --

add_channel("cvc:game_events", channel_type="named")

# -- cog-policy (game loop daemon) --
# Connects to MettaGrid game server, runs policy.py in a tight loop.
# High priority — game loop is time-sensitive.

add_process(
    "cvc/cog-policy",
    mode="daemon",
    code_key="apps/cvc/prompts/cog-policy.md",
    runner="lambda",
    priority=10.0,
    capabilities=["me", "file", "coglet", "channels"],
    handlers=["cvc:game_events"],
)

# -- cog (strategist daemon) --
# Monitors episode.log, analyzes game performance, rewrites policy.py.
# Lower priority — strategy updates are less time-critical.

add_process(
    "cvc/cog",
    mode="daemon",
    code_key="apps/cvc/prompts/cog.md",
    runner="lambda",
    priority=5.0,
    capabilities=["me", "file", "procs", "channels", "web_search"],
    handlers=["system:tick:minute", "cvc:game_events"],
)
