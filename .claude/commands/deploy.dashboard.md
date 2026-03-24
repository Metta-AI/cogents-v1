Deploy dashboard changes with minimal disruption.

Human-readable reference: [docs/deploy.md](../../docs/deploy.md)

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Identify the cogtainer name from context (default: `agora`).

## Decide what to deploy

Run `git diff HEAD~1 --name-only` (or broader if multiple commits since last deploy) and categorize:

| Changed paths | What's needed |
|---|---|
| `dashboard/frontend/**` only | **S3 bundle** — fast path, ~30s. Run: `cogtainer deploy-dashboard <cogtainer>` |
| `src/dashboard/**` only (backend API) | **Docker image** — needs container rebuild. Run: `cogtainer deploy-dashboard <cogtainer> --docker` |
| Both frontend + backend | **Docker image** — covers both. Run: `cogtainer deploy-dashboard <cogtainer> --docker` |
| `DOCKER_VERSION` changed | **Docker image** — use `--docker` |
| No dashboard changes | Nothing to deploy. Tell the user. |

## Deploy

```bash
# Fast path: build Next.js -> tar.gz -> S3 -> restart ECS (~30s)
uv run cogtainer deploy-dashboard agora

# Full path: rebuild Docker image + push ECR + restart ECS
uv run cogtainer deploy-dashboard agora --docker

# With explicit AWS profile
uv run cogtainer deploy-dashboard agora --profile softmax-org
```

IMPORTANT: Do NOT manually construct S3 bucket names. The `deploy-dashboard` command
reads the correct bucket from the CloudFormation stack outputs automatically.

## Post-deploy

After deploy completes, verify by opening `https://<safe-cogent-name>.softmax-cogents.com` in the browser and confirm the change is visible.
