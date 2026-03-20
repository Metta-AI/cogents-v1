# Cogtainer Design

A cogtainer is the self-contained infrastructure environment that hosts cogents. It can be an AWS account, a local Docker setup, or a local development environment.
It provisions shared resources, manages credentials, and monitors cogent health.

## Architecture

Three layers:

1. **Infrastructure** (CDK) — Shared AWS resources: ECS cluster, ECR repo,
   Route53 hosted zone, DynamoDB status table, watcher Lambda.
2. **Secrets** — AWS Secrets Manager as centralized credential store. Agents
   fetch keys directly via IAM task roles. Rotation handled by Lambda.
3. **Monitoring** — EventBridge-triggered Lambda polls CF/ECS/CloudWatch every
   60s, writes aggregated status to DynamoDB. CLI reads from DynamoDB.

### What changed from the original design

- No Envoy sidecar or auth injector proxy
- No WebSocket proxy or boundary stack
- No Python-generated CloudFormation — replaced by CDK
- Agents access secrets directly instead of going through a proxy

## Module Structure

```
src/cogtainer/
  __init__.py
  cli.py              # Click CLI
  config.py            # CogtainerConfig model
  aws.py               # AWS session/account helpers
  cdk/
    app.py             # CDK app entry point
    stacks/
      core.py          # ECS, ECR, Route53, DynamoDB, watcher Lambda
      secrets.py       # Secrets Manager resources, rotation Lambda
  secrets/
    store.py           # SecretStore client
    rotation/
      handler.py       # Rotation Lambda handler
  watcher/
    handler.py         # Agent watcher Lambda handler
```

## Infrastructure Layer (CDK)

A single `CogtainerStack` with these resources:

### ECS Cluster

- Capacity providers: FARGATE + FARGATE_SPOT
- Shared cluster where all cogent tasks run

### ECR Repository (`cogent`)

- Single repo, cogent name as tag prefix (e.g., `cogent:alpha-latest`,
  `cogent:beta-v1.2`)
- Cross-account pull policy scoped to the AWS Organization via
  `aws:PrincipalOrgID`
- Lifecycle policy to expire untagged images after 30 days

### Route53 Hosted Zone

- Domain for cogent DNS (from `~/.cogos/cogtainers.yml`)
- Cogent accounts create subdomains via cross-account delegation

### DynamoDB Table (`cogent-status`)

- Partition key: `cogent_name`
- Stores cached status: stack state, task counts, CPU/memory, channels,
  timestamp
- TTL on items to auto-expire stale entries

### Agent Watcher Lambda (`cogent-watcher`)

- Triggered by EventBridge rule every 60 seconds
- Queries all `cogent-*` CF stacks across the org
- Polls ECS for task counts, CloudWatch for CPU/memory metrics
- Writes aggregated status to DynamoDB

### IAM Roles

- Watcher Lambda execution role: CF describe, ECS list, CloudWatch get-metrics,
  DynamoDB write
- Cross-account role for cogent accounts to read from ECR and Secrets Manager

## Secrets Layer

AWS Secrets Manager as the centralized credential store. No proxies — agents
fetch keys directly using their IAM task role.

### Secret path convention

```
cogent/{cogent_name}/{channel}       # e.g., cogent/alpha/discord
cogent/{cogent_name}/{channel}/meta  # optional metadata
cogtainer/shared/{key_name}          # org-wide shared keys
```

### SecretStore client (`secrets/store.py`)

Thin wrapper around boto3 Secrets Manager:

- `get(path) -> dict` — fetch and parse secret value
- `put(path, value)` — create or update a secret
- `list(prefix) -> list[str]` — list secret names under a prefix
- `delete(path)` — delete a secret
- In-memory TTL cache (5 min default) to avoid repeated API calls

### Access control

- Each cogent's ECS task role gets read access scoped to `cogent/{name}/*`
- Cogtainer admin role gets full read/write
- Cross-account access via `aws:PrincipalOrgID` condition

### Rotation Lambda (`secrets/rotation/handler.py`)

Implements the Secrets Manager 4-step rotation protocol:

1. `createSecret` — generate new token
2. `setSecret` — store pending token
3. `testSecret` — verify pending token works
4. `finishSecret` — promote pending to current

Supported token types:
- **GitHub App** — generates RS256 JWT, creates installation access token
- **OAuth** — standard refresh_token flow

### CLI commands

```
cogtainer secrets list [--cogent NAME]
cogtainer secrets get <path>
cogtainer secrets set <path> [--value | --file]
cogtainer secrets delete <path>
cogtainer secrets rotate <path>
```

## Monitoring Layer

### Agent Watcher Lambda

EventBridge triggers every 60s. The watcher:

1. Lists all `cogent-*` CloudFormation stacks in the org
2. Queries ECS for running/desired task counts per cogent
3. Queries CloudWatch for CPU (1m, 10m averages) and memory utilization
4. Checks Secrets Manager for channel token freshness
5. Writes a status record per cogent to DynamoDB

### DynamoDB status record

```
cogent_name: str       # partition key
stack_status: str      # e.g., CREATE_COMPLETE
running_count: int
desired_count: int
image_tag: str         # e.g., alpha-v1.3
channels: dict         # e.g., {"discord": "ok", "github": "stale"}
cpu_1m: int
cpu_10m: int
mem_pct: int
updated_at: int        # unix timestamp
```

## CLI

Entry point: `cogtainer` (defined in pyproject.toml).

### Commands

```
cogtainer create <name> --type aws   # Create cogtainer + deploy CDK stack
cogtainer update <name>              # Update CDK stack
cogtainer destroy <name>             # Tear down CDK stack
cogtainer status [<name>]            # Show cogtainer resource status

cogtainer secrets list [--cogent]    # List secrets
cogtainer secrets get <path>         # Get a secret value
cogtainer secrets set <path>         # Set a secret
cogtainer secrets delete <path>      # Delete a secret
cogtainer secrets rotate <path>      # Trigger rotation

cogent list                          # List all cogents with DynamoDB status
cogent create <name>                 # Create a cogent in the current cogtainer
cogent destroy <name>                # Destroy a cogent
```

## Configuration

Stored as YAML in `~/.cogos/cogtainers.yml`.
