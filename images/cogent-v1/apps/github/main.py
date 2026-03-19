# GitHub cog orchestrator — Python executor
# Dispatches hourly/daily scans and on-demand discovery to LLM coglets.

channel = event.get("channel_name", "")
payload = event.get("payload", {})
_log_lines = ["github: channel=" + repr(channel) + " payload=" + repr(payload)]
def _log(msg):
    _log_lines.append(msg)
    print(msg)
    file.write("data/github/debug.log", "\n".join(_log_lines))

_log("github: starting, vars=" + str([v for v in dir() if not v.startswith("_")]))

# Source repo identity
SOURCE_REPO = "metta-ai/cogents-v1"

# Read coglet prompts
scanner_content = file.read("apps/github/scanner/main.md")
if hasattr(scanner_content, 'error'):
    _log("github: scanner prompt not found: " + str(scanner_content.error))
    exit()
discovery_content = file.read("apps/github/discovery/main.md")
if hasattr(discovery_content, 'error'):
    _log("github: discovery prompt not found: " + str(discovery_content.error))
    exit()

print("github: coglet prompts loaded")

# Create coglets
scanner = cog.make_coglet("scanner", entrypoint="main.md",
    files={"main.md": scanner_content.content})
discovery = cog.make_coglet("discovery", entrypoint="main.md",
    files={"main.md": discovery_content.content})

worker_caps = {
    "github": None, "data": None, "dir": None,
    "file": None, "channels": None, "stdlib": None,
}

if channel == "github:discover":
    # On-demand discovery
    repo = payload.get("repo", "")
    if not repo:
        _log("github: discover missing repo in payload")
        exit()
    run = coglet_runtime.run(discovery, procs, capability_overrides=worker_caps)
    run.process().send({"repo": repo})

elif channel == "system:tick:hour" or not channel:
    _log("github: running scan")
    # Check if daily scan is due
    last_scan = data.get("last_scan.txt").read()
    today = stdlib.time.strftime("%Y-%m-%d")
    if not hasattr(last_scan, 'error') and last_scan.content.strip() == today:
        _log("github: already scanned today")
        exit()

    # Read repos.md and build scan list
    repos_content = data.get("repos.md").read()
    if hasattr(repos_content, 'error'):
        _log("github: repos.md not found: " + str(repos_content.error))
        exit()
    _log("github: repos.md loaded, parsing")

    scan_repos = []
    for line in repos_content.content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/*"):
            # Org wildcard — list org repos
            org = line[:-2]
            _log("github: listing org " + org)
            org_repos = github.list_org_repos(org, limit=100)
            if hasattr(org_repos, 'error'):
                _log("WARN: list_org_repos " + org + " failed: " + org_repos.error)
                continue
            _log("github: found " + str(len(org_repos)) + " repos in " + org)
            for r in org_repos:
                scan_repos.append(r.full_name)
        else:
            scan_repos.append(line)

    # Deduplicate
    scan_repos = list(dict.fromkeys(scan_repos))
    _log("github: " + str(len(scan_repos)) + " repos to scan")

    # Spawn scanner coglet for each repo
    for repo in scan_repos:
        is_self = repo == SOURCE_REPO
        _log("github: scanning " + repo + (" (self)" if is_self else ""))
        run = coglet_runtime.run(scanner, procs, capability_overrides=worker_caps)
        run.process().send({"repo": repo, "is_self_repo": is_self})

    # Mark today as scanned
    data.get("last_scan.txt").write(today)
    _log("github: dispatched " + str(len(scan_repos)) + " scans")

else:
    _log("github: unknown channel " + repr(channel))
