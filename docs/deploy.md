# Deploy Guide

Single reference for deploying CogOS components. For operational runbooks used by Claude, see `.claude/commands/deploy.*.md`.

## Architecture

Four deployable components:

| Component | Infrastructure | Deploy tool |
|-----------|---------------|-------------|
| **Lambda functions** | orchestrator, executor, dispatcher, ingress | `cogtainer update lambda` |
| **Database schema** | Aurora PostgreSQL via RDS Data API | `cogtainer update rds` |
| **Dashboard** | ECS Fargate on cogent-polis cluster | `dashboard deploy` |
| **CDK stack** | All infrastructure definitions (IAM, VPC, ALB, ECS task defs) | `cogtainer create` |

## Decision Tree

What changed? Run `git diff HEAD~1 --name-only` and match:

| Changed paths | Command |
|---|---|
| `images/**` | `cogos <name> cogos image boot cogos` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**` | `cogos <name> cogtainer update lambda` |
| `src/cogos/capabilities/**` | `cogos <name> cogtainer update lambda` + `cogos image boot cogos` |
| `src/cogos/db/migrations/**` | `cogos <name> cogtainer update rds` |
| `dashboard/frontend/**` | `cogos <name> dashboard deploy` |
| `src/dashboard/**` | `cogos <name> dashboard deploy --docker` |
| Both frontend + backend | `cogos <name> dashboard deploy --docker` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogos <name> cogtainer create` |
| `DOCKER_VERSION` changed | `cogos <name> cogtainer create` |

## Command Reference

### Lambda + DB

```bash
cogos <name> cogtainer update lambda       # Update Lambda code only (~15s)
cogos <name> cogtainer update rds          # Run DB schema migrations
cogos <name> cogtainer update ecs          # Force new ECS deployment (restart containers)
cogos <name> cogtainer update all          # Lambda + RDS migrations + sync
```

### CDK Stack

```bash
cogos <name> cogtainer create              # Full CDK deploy (~3-5 min)
cogos <name> cogtainer build               # Build + push executor Docker image to ECR
cogos <name> cogtainer status              # Check infrastructure status
```

### Image

```bash
cogos <name> cogos image boot cogos          # Upsert capabilities, files, processes into DB
cogos <name> cogos image boot cogos --clean  # Wipe all tables first, then boot
cogos <name> cogos reload -i cogos -y        # Reload config from image, preserving runtime data
cogos <name> cogos reload -i cogos -y --full # Wipe ALL data (including runtime) and reload
```

### Dashboard

```bash
cogos <name> dashboard deploy              # Fast path: Next.js build -> S3 -> restart ECS (~30s)
cogos <name> dashboard deploy --docker     # Full path: rebuild Docker image + push ECR + restart
cogos <name> dashboard deploy --skip-health  # Skip health check wait
cogos <name> cogos dashboard reload          # Restart local dashboard (stop + start)
```

### Discord Bridge

```bash
cogos <name> cogos io discord start        # Scale ECS service to 1 task
cogos <name> cogos io discord stop         # Scale to 0
cogos <name> cogos io discord restart      # Force new deployment
cogos <name> cogos io discord status       # Check running/desired counts
```

## Typical Sequences

**Image-only change** (edited files in `images/`):
```bash
cogos <name> cogos image boot cogos
```

**Executor code change** (`src/cogos/executor/`, `src/cogos/sandbox/`):
```bash
cogos <name> cogtainer update lambda
cogos <name> cogos image boot cogos    # if image also changed
```

**Schema migration + executor change**:
```bash
cogos <name> cogtainer update rds
cogos <name> cogtainer update lambda
cogos <name> cogos image boot cogos
```

**Dashboard frontend-only**:
```bash
cogos <name> dashboard deploy
```

**Dashboard with backend changes**:
```bash
cogos <name> dashboard deploy --docker
```

**Full infrastructure change** (CDK constructs, IAM, ALB):
```bash
cogos <name> cogtainer create
cogos <name> cogos image boot cogos
```

**Docker image change** (Dockerfile, new deps):
```bash
cogos <name> cogtainer build
cogos <name> cogtainer update ecs
```

## Post-Deploy Verification

```bash
cogos <name> cogtainer status              # Infrastructure health
cogos <name> cogos status                  # CogOS status
cogos <name> cogos process list            # Processes running
```

For dashboard, open `https://<safe-name>.<your-domain>` and confirm the change is visible.
