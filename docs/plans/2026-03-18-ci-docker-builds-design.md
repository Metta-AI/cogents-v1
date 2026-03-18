# CI Docker Builds — Design

Move Docker image builds from local machines to GitHub Actions with smart triggers, OIDC auth, and SHA-based tagging.

## Problem

Building and pushing Docker images locally to ECR is slow, error-prone, and blocks the developer. Two images are affected:
- **Executor** (`src/cogtainer/docker/Dockerfile`) — heavy image with Claude Code, Node.js, AWS CLI, etc.
- **Dashboard** (`dashboard/Dockerfile`) — Next.js frontend + FastAPI backend

## Design

### 1. IAM: GitHub OIDC in Polis Account

Add to `src/polis/cdk/stacks/core.py`:

- **OIDC Provider** for `token.actions.githubusercontent.com` (AWS allows only one per issuer per account)
- **IAM Role** `github-actions-cogents` with:
  - Trust: OIDC federation scoped to `repo:Metta-AI/cogents-v1:*`
  - Policy: `AmazonEC2ContainerRegistryPowerUser`

This lives in the polis account (`901289084804`) where ECR is. Separate from metta's OIDC setup (in account `751442549699`).

### 2. Shared Composite Action

`.github/actions/ecr-build/action.yml` — reusable action handling:
- OIDC credential exchange via `aws-actions/configure-aws-credentials@v4`
- ECR login via `aws-actions/amazon-ecr-login@v2`
- Tag generation via `docker/metadata-action@v5`
- Build + push via `docker/build-push-action@v5` with GitHub Actions layer cache

Inputs: `image_name`, `dockerfile`, `context`, `aws_role`.

### 3. Executor Build Workflow

`.github/workflows/docker-build-executor.yml`

**Triggers:**
- Push to main when these paths change: `src/cogtainer/docker/**`, `src/cogos/**`, `src/cogents/**`, `pyproject.toml`
- Manual dispatch (`workflow_dispatch`)

**Tags produced:**
- `executor-{sha-short}`
- `executor-{sha-full}`
- `executor-latest` (main branch only)

### 4. Dashboard Build Workflow

`.github/workflows/docker-build-dashboard.yml`

**Triggers:**
- Push to main when these paths change: `dashboard/**`, `src/dashboard/**`
- Manual dispatch (`workflow_dispatch`)

**Tags produced:**
- `dashboard-{sha-short}`
- `dashboard-{sha-full}`
- `dashboard-latest` (main branch only)

### 5. CLI: `--tag` Flag on `cogtainer update ecs`

Add optional `--tag` to `cogtainer update ecs` so you can deploy a specific CI-built image:

```bash
cogent dr.alpha cogtainer update ecs --tag executor-abc1234
cogent dr.alpha cogtainer update ecs --tag executor-latest
```

Without `--tag`, current behavior (cogent-specific local tag) is preserved.

## Tagging Strategy

CI builds one image per commit. Each cogent pins to a specific tag. Deploying to a cogent is a separate manual step — no auto-deploy.

| Tag | When | Purpose |
|-----|------|---------|
| `executor-{sha}` | Every CI build | Immutable, pinnable |
| `executor-latest` | Main branch builds | Convenience for new cogents |
| `executor-{safe_name}` | Local `cogtainer build` | Unchanged, still works |

## Files Changed

| File | Change |
|------|--------|
| `src/polis/cdk/stacks/core.py` | Add OIDC provider + IAM role (~20 lines) |
| `.github/actions/ecr-build/action.yml` | New composite action |
| `.github/workflows/docker-build-executor.yml` | New workflow |
| `.github/workflows/docker-build-dashboard.yml` | New workflow |
| `src/cogtainer/update_cli.py` | Add `--tag` option to `update ecs` |

## Post-Deploy Steps

1. Run `polis update` to deploy the OIDC provider + IAM role to the polis account
2. Copy the `GitHubActionsRoleArn` from stack outputs: `polis status` or check CloudFormation console
3. Set GitHub Actions variable: `gh variable set AWS_ROLE --body "<role-arn>" --repo Metta-AI/cogents-v1`
4. Push a change to main to verify the workflow triggers
