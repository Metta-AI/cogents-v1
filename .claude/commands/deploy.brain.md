Deploy brain infrastructure changes (CDK stack, Lambda, ECS, RDS).

This is the heaviest deploy — only use when actual infrastructure changes are needed.

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Identify the cogent name from context (default: `dr.alpha`).

## Check: do you actually need a brain deploy?

Run `git diff HEAD~1 --name-only` and check:

| Changed paths | Use instead |
|---|---|
| `dashboard/frontend/**` or `src/dashboard/**` only | `/deploy.dashboard` — no brain deploy needed |
| `images/**` only | `/deploy.cogos` — just reboot the image |
| `src/cogos/executor/**`, `src/cogos/sandbox/**`, `src/cogos/capabilities/**` | `/deploy.cogos` — Lambda update + image reboot |
| `src/cogos/db/migrations/**` only | `/deploy.cogos` — RDS migration only |
| `src/brain/cdk/**` or CDK construct changes | **Yes, brain deploy needed** — read on |
| `DOCKER_VERSION` changed | **Yes, brain deploy needed** — CDK stack references image tag |
| IAM, VPC, ALB, or other infra changes | **Yes, brain deploy needed** |

If the change doesn't require a brain deploy, tell the user and suggest the right skill.

## Commands reference

```bash
# Full CDK stack deploy (creates/updates all infra: Lambda, ECS, RDS, ALB, etc.)
# This is slow (~3-5 min). Only use when infra definition changed.
cogent <name> brain create --watch

# Build and push executor Docker image to ECR (without CDK deploy)
cogent <name> brain build

# Update Lambda code only (fast, ~15s)
cogent <name> brain update lambda

# Run RDS schema migrations only
cogent <name> brain update rds

# Force new ECS deployment (restart containers with current image)
cogent <name> brain update ecs

# Update Lambda + RDS migrations + mind sync
cogent <name> brain update all

# Check current infrastructure status
cogent <name> brain status
```

## When to use `brain create` vs `brain update`

- **`brain create --watch`**: CDK stack changes — new resources, IAM policy changes, ALB rules, ECS task def changes, env var changes in CDK. This runs `cdk deploy`.
- **`brain update lambda`**: Only Python code in `src/cogos/` changed. Zips and uploads to existing Lambda.
- **`brain update ecs`**: Need to restart ECS tasks (e.g. after ECR image push). Does NOT rebuild image.
- **`brain build` + `brain update ecs`**: Executor Docker image changed (new dependencies, Dockerfile changes).

## Post-deploy

```bash
cogent <name> brain status
cogent <name> cogos status
```
