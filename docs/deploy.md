# Deploy Guide

Single reference for deploying CogOS components. For operational runbooks used by Claude, see `.claude/commands/deploy.*.md`.

## Architecture

Four deployable components:

| Component | Infrastructure | Deploy tool |
|-----------|---------------|-------------|
| **Lambda functions** | event-router, executor, dispatcher, ingress | `cogtainer update <name> --lambdas` |
| **Dashboard / ECS** | ECS Fargate on cogtainer cluster | `cogtainer update <name> --services --image-tag dashboard-<sha>` |
| **Discord bridge** | ECS Fargate on cogtainer cluster | `cogtainer update <name> --services --image-tag discord-<sha>` |
| **CDK stack** | All infrastructure definitions (IAM, VPC, ALB, ECS task defs) | `cogtainer update <name>` |

## Decision Tree

What changed? Run `git diff HEAD~1 --name-only` and match:

| Changed paths | Command |
|---|---|
| `images/**` | `cogos restart` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**` | `cogtainer update <name> --lambdas` |
| `src/cogos/capabilities/**` | `cogtainer update <name> --lambdas` + `cogos restart` |
| `dashboard/frontend/**` | CI builds automatically; then `cogtainer update <name> --services --image-tag dashboard-<sha>` |
| `src/dashboard/**` | CI builds automatically; then `cogtainer update <name> --services --image-tag dashboard-<sha>` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogtainer update <name>` |

## Command Reference

### Update all components

```bash
cogtainer update <name>                                    # Update all (Lambdas + ECS services)
cogtainer update <name> --lambdas                          # Lambda code only
cogtainer update <name> --services                         # ECS services only
cogtainer update <name> --services --image-tag <tag>       # Specific ECS image
```

DB migrations run automatically during `cogos start` (image boot).

### Start / Stop / Restart

```bash
cogos start                     # Boot image + start dispatcher
cogos start --clean             # Wipe all tables first, then boot + start
cogos start --skip-boot         # Start dispatcher without re-booting image
cogos stop                      # Stop dispatcher
cogos restart                   # Stop + boot + start
cogos snapshot my-snapshot      # Snapshot running state into an image
```

### Dashboard (local)

```bash
cogos dashboard start             # Start backend + frontend in background (local dev)
cogos dashboard stop              # Stop both servers
cogos dashboard reload            # Restart (stop + start)
```

### Discord Bridge

```bash
cogos io discord start        # Scale ECS service to 1 task
cogos io discord stop         # Scale to 0
cogos io discord restart      # Force new deployment
cogos io discord status       # Check running/desired counts
```

## Typical Sequences

**Image-only change** (edited files in `images/`):
```bash
cogos restart
```

**Executor code change** (`src/cogos/executor/`, `src/cogos/sandbox/`):
```bash
cogtainer update <name> --lambdas
cogos restart    # if image also changed
```

**Full infrastructure change** (CDK constructs, IAM, ALB):
```bash
cogtainer update <name>
cogos restart
```

## Adding a New Cogent

When deploying a new cogent to AWS:

1. Create the cogent: `COGTAINER=<name> uv run cogent create <cogent-name>`
2. Deploy its CDK stack: `PYTHONPATH=src npx cdk deploy --app "python -m cogtainer.cdk.app" -c cogtainer_name=<name> -c cogent_name=<cogent-name>`
3. **Add the cogent to `cogtainers.ci.yml`** in the `cogents` array for its cogtainer — CI uses this list to push Lambda code updates to each cogent's functions. Without this, the cogent's Lambdas will stop receiving updates and drift out of sync.
4. Boot CogOS: `COGTAINER=<name> COGENT=<cogent-name> uv run cogos start`

## Post-Deploy Verification

```bash
cogtainer status                              # Infrastructure health
cogos status                                  # CogOS status
cogos process list                            # Processes running
```

For dashboard, open `https://<safe-name>.<your-domain>` and confirm the change is visible.
