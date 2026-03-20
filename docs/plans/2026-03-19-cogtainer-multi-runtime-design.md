# Cogtainer: Multi-Runtime Cogent Environments

## Overview

Replace "polis" with "cogtainer" as the top-level concept. A cogtainer is a self-contained environment that hosts one or more cogents. Cogtainers can run on AWS, locally, or in Docker.

## Core Concepts

- **Cogtainer** — a self-contained runtime environment (replaces polis)
- **Cogent** — an identity running cogos within a cogtainer (unchanged)
- **CogOS** — the execution engine (unchanged)
- **EventRouter** — matches events to triggers, dispatches executors (replaces orchestrator)

## Cogtainer Types

| Type | Database | Compute | LLM | File Storage |
|------|----------|---------|-----|-------------|
| `aws` | Aurora Serverless v2 (RDS Data API) | Lambda + ECS Fargate | Pluggable (Bedrock, OpenRouter, etc.) | S3 |
| `local` | LocalRepository (JSON) | Subprocesses | Pluggable (OpenRouter, Anthropic, etc.) | Local filesystem |
| `docker` | LocalRepository (JSON) | Subprocesses (containerized) | Pluggable | Container filesystem / volume |

Each AWS cogtainer is fully isolated — own Aurora cluster, ECS cluster, ALB, ECR. No shared infrastructure across cogtainers.

Within a cogtainer, cogents share compute but get separate databases.

## Configuration

### `~/.cogos/cogtainers.yml`

```yaml
cogtainers:
  prod:
    type: aws
    region: us-east-1
    account_id: "901289084804"
    domain: softmax-cogents.com
    llm:
      provider: bedrock
      model: anthropic.claude-sonnet-4-20250514

  dev:
    type: local
    data_dir: ~/.cogos/cogtainers/dev
    llm:
      provider: openrouter
      api_key_env: OPENROUTER_API_KEY
      model: anthropic/claude-sonnet-4

  staging:
    type: docker
    data_dir: ~/.cogos/cogtainers/staging
    image: cogos:latest
    llm:
      provider: anthropic
      api_key_env: ANTHROPIC_API_KEY
      model: claude-sonnet-4-20250514

defaults:
  cogtainer: dev
```

### Local/Docker data layout

```
~/.cogos/cogtainers/dev/
  cogent_alpha/
    db.json
    sessions/
  cogent_beta/
    db.json
    sessions/
```

## CLI Design

Three separate CLIs with clear responsibilities:

### `cogtainer` — cogtainer lifecycle

```bash
cogtainer create <name> --type aws|local|docker [--llm-provider openrouter]
cogtainer destroy <name>
cogtainer list
cogtainer status [<name>]
cogtainer update <name>          # AWS only, redeploy CDK
cogtainer discover-aws           # populate config from AWS
```

### `cogent` — cogent lifecycle

```bash
export COGTAINER=dev             # optional if only one exists

cogent create <name>
cogent destroy <name>
cogent list
cogent status [<name>]
```

### `cogos` — operating a cogent

```bash
export COGTAINER=dev             # optional if only one
export COGENT=alpha              # optional if only one

cogos image boot cogos
cogos io discord start
cogos run <process>
cogos db migrate
cogos start                      # local/docker: starts dispatcher
cogos start --daemon
cogos stop
cogos dashboard start
cogos status
```

### Resolution order (for both COGTAINER and COGENT)

1. Environment variable
2. If only one exists, use it automatically
3. Error: "multiple found, specify one"

## CogtainerRuntime API

CogOS depends only on this interface. No AWS/Docker/local knowledge in cogos.

```python
class CogtainerRuntime:
    # Database
    def get_repository(self, cogent_name: str) -> Repository

    # LLM
    def converse(self, messages, tools, model) -> Response

    # File storage
    def put_file(self, key, data) -> str
    def get_file(self, key) -> bytes

    # Event routing
    def emit_event(self, event) -> None

    # Process execution
    def spawn_executor(self, cogent_name, process_id) -> None
```

### Implementations

- **`AwsRuntime`** — RDS Data API, S3, EventBridge, Lambda invoke, pluggable LLM
- **`LocalRuntime`** — LocalRepository, local filesystem, in-process routing, subprocess spawn, pluggable LLM
- **`DockerRuntime`** — same as LocalRuntime, containerized

### LLM Provider abstraction

```python
class LLMProvider:
    def converse(self, messages, tools, model) -> Response
```

Implementations: `BedrockProvider`, `OpenRouterProvider`, `AnthropicProvider`.

## Local/Docker Execution Model

Local cogtainer runs cogos components as separate Python processes:

- **Dispatcher** — long-lived process running 60-second tick loop. Spawns executor subprocesses for runnable processes. Handles message matching and queue dispatch.
- **EventRouter** — spawned as subprocess when events arrive. Matches event against triggers, spawns executor subprocesses.
- **Executor** — spawned as subprocess per invocation. Runs a single process, calls LLM provider, writes to LocalRepository.
- **Dashboard** — separate process, FastAPI + React on localhost.

Docker cogtainer packages the same thing in a container. `cogtainer create staging --type docker` generates a `docker-compose.yml`.

## AWS Cogtainer Infrastructure

Each AWS cogtainer deploys a single CDK app with two stack types:

### CogtainerStack (one per cogtainer)
- Aurora Serverless v2 cluster
- ECS Fargate cluster
- ALB with wildcard cert
- ECR repository
- Route53 hosted zone / subdomain
- EventBridge bus

### CogentStack (one per cogent within the cogtainer)
- IAM role
- S3 sessions bucket
- SQS FIFO ingress queue
- Lambdas: event-router, executor, dispatcher, ingress
- ECS service: dashboard
- External services: SES, Discord, Asana, GitHub

CDK structure:
```
src/cogtainer/
  cdk/
    app.py
    stacks/
      cogtainer_stack.py
      cogent_stack.py
```

## Migration Path

### Code changes
1. `src/polis/` → `src/cogtainer/` (merge with existing)
2. Rename orchestrator → event-router everywhere
3. Extract `CogtainerRuntime` interface from existing code
4. Create `AwsRuntime` wrapping current boto3 calls
5. Create `LocalRuntime` wrapping existing LocalRepository + subprocess spawning
6. Remove all boto3/AWS imports from cogos — route through runtime
7. Add LLM provider abstraction
8. New `cogtainer` and `cogent` CLIs
9. Refactor `cogos` CLI to use COGTAINER/COGENT env vars

### CDK changes
- Rename polis stack → cogtainer-scoped stack
- Lambda names: `cogtainer-{name}-event-router` (was `cogtainer-{name}-orchestrator`)

### Config migration
- `~/.cogos/config.yml` → `~/.cogos/cogtainers.yml`
- One-time conversion script

### Data
- No data migration needed — databases, S3, secrets keep working
- CDK stack rename requires import/export or parallel deploy + cutover
