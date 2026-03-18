# Recruiter — Python Orchestrator
# Dispatches events to LLM worker coglets (discover, present, profile, evolve).
# Config coglet holds static data (criteria, rubric, strategy, sourcer prompts).

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Config coglet — data only, no entrypoint
config = cog.make_coglet("config", files={
    "criteria.md": file.read("apps/recruiter/criteria.md").content,
    "rubric.json": file.read("apps/recruiter/rubric.json").content,
    "strategy.md": file.read("apps/recruiter/strategy.md").content,
    "diagnosis.md": file.read("apps/recruiter/diagnosis.md").content,
    "evolution.md": file.read("apps/recruiter/evolution.md").content,
    "sourcer/github.md": file.read("apps/recruiter/sourcer/github.md").content,
    "sourcer/twitter.md": file.read("apps/recruiter/sourcer/twitter.md").content,
    "sourcer/web.md": file.read("apps/recruiter/sourcer/web.md").content,
    "sourcer/substack.md": file.read("apps/recruiter/sourcer/substack.md").content,
})

# Executable coglets
discover = cog.make_coglet("discover", entrypoint="main.md",
    files={"main.md": file.read("apps/recruiter/discover.md").content})
present = cog.make_coglet("present", entrypoint="main.md", mode="daemon",
    files={"main.md": file.read("apps/recruiter/present.md").content})
profile = cog.make_coglet("profile", entrypoint="main.md",
    files={"main.md": file.read("apps/recruiter/profile.md").content})
evolve = cog.make_coglet("evolve", entrypoint="main.md",
    files={"main.md": file.read("apps/recruiter/evolve.md").content})

# Shared capability set for worker coglets
worker_caps = {
    "me": None, "data": None, "config_coglet": config,
    "secrets": None, "discord": None, "channels": None,
    "supervisor": channels.scope(names=["supervisor:help"], ops=["send"]),
}

# Ensure present daemon is running
p = procs.get(name="recruiter/present")
if hasattr(p, "error") or p.status() in ("disabled", "completed"):
    coglet_runtime.run(present, procs,
        capability_overrides=worker_caps,
        subscribe="system:tick:hour")

# Dispatch based on triggering channel
if channel == "recruiter:feedback":
    # Route feedback to the present daemon or evolve
    run = coglet_runtime.run(evolve, procs,
        capability_overrides={
            **worker_caps,
            "discover_coglet": discover,
            "present_coglet": present,
        })
    run.process().send(payload)

elif channel == "system:tick:hour":
    # Periodic tick — check if discovery is needed
    run = coglet_runtime.run(discover, procs,
        capability_overrides=worker_caps)

else:
    print(f"recruiter: unknown channel {channel!r}")
