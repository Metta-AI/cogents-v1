Deploy dashboard changes with minimal disruption.

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Identify the cogent name from context (default: `dr.alpha`).

## Decide what to deploy

Run `git diff HEAD~1 --name-only` (or broader if multiple commits since last deploy) and categorize:

| Changed paths | What's needed |
|---|---|
| `dashboard/frontend/**` only | **S3 bundle** — fast path, ~30s. Run: `cogent <name> dashboard deploy` |
| `src/dashboard/**` only (backend API) | **Docker image** — needs container rebuild. Run: `cogent <name> dashboard deploy --docker` |
| Both frontend + backend | **Docker image** — covers both. Run: `cogent <name> dashboard deploy --docker` |
| `DOCKER_VERSION` changed | **Docker image** — auto-detected, but use `--docker` to be explicit |
| No dashboard changes | Nothing to deploy. Tell the user. |

## Commands reference

```bash
# Fast path: build Next.js -> tar.gz -> S3 -> restart ECS (~30s)
cogent <name> dashboard deploy

# Full path: rebuild Docker image + push ECR + update task def + restart
cogent <name> dashboard deploy --docker

# Skip health check wait (if you want to move on)
cogent <name> dashboard deploy --skip-health
```

## Post-deploy

After deploy completes, verify by opening `https://<safe-name>.softmax-cogents.com` in the browser and confirm the change is visible.
