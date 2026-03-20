# Remove All boto3 from CogOS — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Zero boto3/botocore imports in `src/cogos/`. All AWS access goes through `CogtainerRuntime` methods, which cogos receives — never creates.

**Architecture:** Expand `CogtainerRuntime` with new abstract methods for each service need (messaging, email, blob URLs, LLM). The executor reconstructs a runtime from env vars at startup (same pattern as secrets). Capabilities and IO code receive the runtime or its sub-providers. CLI commands use the runtime from Click context. The discord bridge and shell are borderline — they're services/tools, not cogos core — but we clean them up too.

**Tech Stack:** Python, boto3 (only in `src/cogtainer/`), pytest

---

## Remaining boto3 Calls by Category

### Category A: Blob Storage (S3) — `blob.py`
- `blob.py:51` — `boto3.client("s3")` for upload/download/presigned URLs
- Runtime already has `put_file()`/`get_file()` but blob needs presigned URLs too

### Category B: Message Queue (SQS) — `discord/reply.py`, `discord/capability.py`, `repository.py`
- Discord reply/capability: STS `get_caller_identity()` + SQS `send_message()` to reply queue
- Repository: SQS `send_message()` for ingress nudge

### Category C: LLM (Bedrock) — `llm_client.py`, `shell/`, `cli/__main__.py`
- `llm_client.py:191` — creates Bedrock client directly
- `shell/__init__.py:56`, `shell/commands/llm.py:149` — shell creates its own Bedrock client
- `cli/__main__.py:109` — CLI creates Bedrock client
- Runtime already has `converse()` — these should all use it

### Category D: Email (SES) — `email/sender.py`, `email/provision.py`
- `sender.py:17` — `boto3.client("ses")` for sending email
- `provision.py:104` — `boto3.client("ses")` for verifying domains

### Category E: Database (RDS-Data) — `repository.py`, `migrations/`
- `repository.py:112` — `Repository.create()` classmethod creates RDS-Data client
- `migrations/__init__.py` — 3 places create RDS-Data clients
- Runtime already provides repositories — these are bootstrap/admin paths

### Category F: Discord Bridge Service — `bridge.py`, `registry.py`, `announce.py`
- Bridge: SQS polling, S3 uploads, SecretsManager for bot token
- Registry: DynamoDB scan for cogent configs
- Announce: SecretsManager for bot token
- These run as separate ECS services, not inside cogos

### Category G: CLI Admin — `cli/__main__.py`
- boto3.Session for credentials, DynamoDB for cogent lookup, ECR/S3 for boot verification, ECS client
- CLI has the runtime in Click context

### Category H: Error Handling — `handler.py`
- `botocore.exceptions.ClientError` import for error detection
- This is just a type check, not an API call

---

## Task 1: Add messaging abstraction to CogtainerRuntime

The SQS calls in discord/ and repository are all "send a message to a queue". Abstract this.

**Files:**
- Modify: `src/cogtainer/runtime/base.py`
- Modify: `src/cogtainer/runtime/local.py`
- Modify: `src/cogtainer/runtime/aws.py`

**Step 1: Add methods to base.py**

```python
@abstractmethod
def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
    """Send a message to a named queue."""

@abstractmethod
def get_queue_url(self, queue_name: str) -> str:
    """Return the URL for a named queue."""
```

**Step 2: Implement in AwsRuntime**

```python
def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
    sqs = self._session.client("sqs", region_name=self._region)
    url = self.get_queue_url(queue_name)
    kwargs = {"QueueUrl": url, "MessageBody": body}
    if dedup_id:
        kwargs["MessageDeduplicationId"] = dedup_id
        kwargs["MessageGroupId"] = "default"
    sqs.send_message(**kwargs)

def get_queue_url(self, queue_name: str) -> str:
    sts = self._session.client("sts", region_name=self._region)
    account_id = sts.get_caller_identity()["Account"]
    return f"https://sqs.{self._region}.amazonaws.com/{account_id}/{queue_name}"
```

**Step 3: Implement in LocalRuntime**

```python
def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
    logger.info("local queue message [%s]: %s", queue_name, body[:200])

def get_queue_url(self, queue_name: str) -> str:
    return f"local://{queue_name}"
```

**Step 4: Commit**

---

## Task 2: Add blob URL and email methods to CogtainerRuntime

**Files:**
- Modify: `src/cogtainer/runtime/base.py`
- Modify: `src/cogtainer/runtime/local.py`
- Modify: `src/cogtainer/runtime/aws.py`

**Step 1: Add methods to base.py**

```python
@abstractmethod
def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
    """Return a URL for a stored blob (presigned for AWS, file:// for local)."""

@abstractmethod
def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
    """Send an email. Returns message ID."""

@abstractmethod
def verify_email_domain(self, domain: str) -> bool:
    """Check if a domain is verified for sending."""
```

**Step 2: Implement in AwsRuntime**

```python
def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
    from polis.naming import bucket_name
    s3 = self._session.client("s3", region_name=self._region)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name(cogent_name), "Key": key},
        ExpiresIn=expires_in,
    )

def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
    ses = self._session.client("ses", region_name=self._region)
    kwargs = {
        "Source": source,
        "Destination": {"ToAddresses": [to]},
        "Message": {
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]
    resp = ses.send_email(**kwargs)
    return resp["MessageId"]

def verify_email_domain(self, domain: str) -> bool:
    ses = self._session.client("ses", region_name=self._region)
    resp = ses.get_identity_verification_attributes(Identities=[domain])
    attrs = resp.get("VerificationAttributes", {}).get(domain, {})
    return attrs.get("VerificationStatus") == "Success"
```

**Step 3: Implement in LocalRuntime**

```python
def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
    path = self._data_dir / cogent_name / "files" / key
    return f"file://{path}"

def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
    logger.info("local email [%s -> %s]: %s", source, to, subject)
    import uuid
    return str(uuid.uuid4())

def verify_email_domain(self, domain: str) -> bool:
    return True  # Always verified locally
```

**Step 4: Commit**

---

## Task 3: Make runtime available to the executor as a reconstructed object

The executor runs as a separate process. It needs the full runtime, not just secrets_provider. Add `create_executor_runtime()` that reconstructs a runtime from env vars — this consolidates the existing `get_repo()`, `get_secrets_provider()`, and will handle LLM client creation.

**Files:**
- Modify: `src/cogos/executor/handler.py`
- Modify: `src/cogtainer/runtime/local.py` — pass all needed env vars in `spawn_executor`
- Modify: `src/cogtainer/runtime/factory.py` — add `create_executor_runtime()` that works from env vars

**Step 1: Add `create_executor_runtime` to factory.py**

```python
def create_executor_runtime() -> CogtainerRuntime:
    """Reconstruct a runtime from env vars set by spawn_executor.

    Used by the executor process which can't receive the runtime object directly.
    """
    cogtainer_type = os.environ.get("COGTAINER", "aws")

    if cogtainer_type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime
        from cogtainer.config import CogtainerEntry
        entry = CogtainerEntry(
            type=cogtainer_type,
            data_dir=os.environ.get("COGOS_LOCAL_DATA", ""),
            llm={"provider": os.environ.get("LLM_PROVIDER", "openrouter")},
        )
        llm = create_provider(entry.llm, region=os.environ.get("AWS_REGION", "us-east-1"))
        return LocalRuntime(entry=entry, llm=llm)

    # AWS runtime
    from cogtainer.runtime.aws import AwsRuntime
    from cogtainer.config import CogtainerEntry
    entry = CogtainerEntry(
        type="aws",
        region=os.environ.get("AWS_REGION", "us-east-1"),
        llm={"provider": os.environ.get("LLM_PROVIDER", "bedrock")},
    )
    llm = create_provider(entry.llm, region=entry.region)
    # AWS executor inherits IAM role from Lambda/ECS — no session needed
    return AwsRuntime(entry=entry, llm=llm, session=None)
```

**Step 2: Update handler.py to use a single runtime**

Replace the separate `get_repo()`, `get_secrets_provider()`, and bedrock client creation with one runtime:

```python
_RUNTIME = None

def _get_runtime():
    global _RUNTIME
    if _RUNTIME is None:
        from cogtainer.runtime.factory import create_executor_runtime
        _RUNTIME = create_executor_runtime()
    return _RUNTIME
```

Then use `_get_runtime().get_repository(cogent_name)`, `_get_runtime().get_secrets_provider()`, `_get_runtime().converse(...)` etc.

**Step 3: Update `_setup_capability_proxies` to pass runtime**

Instead of just `secrets_provider`, pass the whole runtime so capabilities can access any service.

**Step 4: Commit**

---

## Task 4: Add runtime to Capability base, remove boto3 from capabilities

**Files:**
- Modify: `src/cogos/capabilities/base.py` — replace `secrets_provider` with `runtime`
- Modify: `src/cogos/capabilities/blob.py` — use `self._runtime.put_file()`, `get_file()`, `get_file_url()`
- Modify: `src/cogos/io/email/sender.py` — use runtime.send_email()
- Modify: `src/cogos/io/email/provision.py` — use runtime.verify_email_domain()
- Modify: `src/cogos/executor/handler.py` — pass runtime to capabilities

**Step 1: Change Capability base to accept `runtime` instead of `secrets_provider`**

```python
def __init__(
    self, repo, process_id, run_id=None, trace_id=None, runtime=None,
) -> None:
    ...
    self._runtime = runtime
    self._secrets_provider = runtime.get_secrets_provider() if runtime else None
```

This preserves backward compat — `_secrets_provider` still works for all the code we already updated.

**Step 2: Rewrite blob.py to use runtime**

Replace `boto3.client("s3")` with `self._runtime.put_file()`, `self._runtime.get_file()`, `self._runtime.get_file_url()`.

**Step 3: Rewrite email/sender.py**

Replace `boto3.client("ses")` with a `runtime` parameter. `SesSender` accepts runtime, calls `runtime.send_email()`.

**Step 4: Rewrite email/provision.py**

Replace `boto3.client("ses")` with `runtime.verify_email_domain()`.

**Step 5: Commit**

---

## Task 5: Remove boto3 from Discord IO (reply, capability, announce)

**Files:**
- Modify: `src/cogos/io/discord/reply.py` — use runtime.send_queue_message()
- Modify: `src/cogos/io/discord/capability.py` — use runtime.send_queue_message()
- Modify: `src/cogos/io/discord/announce.py` — use runtime.get_secrets_provider()

**Step 1: Rewrite discord/reply.py**

Replace STS `get_caller_identity` + SQS `send_message` with `runtime.send_queue_message(queue_name, body)`. The `reply`, `react`, `create_thread`, `dm` functions need to accept a runtime parameter.

**Step 2: Rewrite discord/capability.py**

Same pattern — replace `_get_queue_url()` and `_send_sqs()` with `runtime.send_queue_message()`. The `DiscordCapability` already has `self._runtime` via the Capability base.

**Step 3: Rewrite discord/announce.py**

Replace `get_polis_session()` + `boto3.client("secretsmanager")` with `runtime.get_secrets_provider().get_secret()`.

**Step 4: Commit**

---

## Task 6: Remove boto3 from Repository and migrations

**Files:**
- Modify: `src/cogos/db/repository.py` — remove `Repository.create()` classmethod that calls `boto3.client("rds-data")`, remove SQS nudge
- Modify: `src/cogos/db/migrations/__init__.py` — accept client as parameter instead of creating

**Step 1: Remove `Repository.create()` classmethod**

The runtime already creates Repository instances via `get_repository()`. The `create()` classmethod is only used by `create_repository()` in `db/factory.py`. Remove `create()` and have `factory.py` construct the Repository directly with an already-created client.

**Step 2: Remove SQS nudge from Repository**

Move the ingress nudge to the runtime. Repository shouldn't know about SQS. Add `nudge_ingress(cogent_name, process_id)` to runtime if needed, or remove the nudge entirely if it's unused in local mode.

**Step 3: Fix migrations to accept client parameter**

`_get_data_client()` and `apply_schema()` / `reset_schema()` should accept a client parameter. The caller (usually the runtime or CLI) provides the RDS-Data client.

**Step 4: Commit**

---

## Task 7: Remove boto3 from LLM client and shell

**Files:**
- Modify: `src/cogos/executor/llm_client.py` — accept bedrock client or runtime, never create boto3 client
- Modify: `src/cogos/shell/__init__.py` — get bedrock client from runtime
- Modify: `src/cogos/shell/commands/llm.py` — get bedrock client from runtime

**Step 1: Fix llm_client.py**

`LLMClient.__init__` currently falls back to `boto3.client("bedrock-runtime")` when no client is given. Change to require `bedrock_client` (no fallback). The caller (handler.py, shell) is responsible for providing it via the runtime.

**Step 2: Fix shell**

Shell commands get the runtime from Click context. Use `runtime.converse()` directly or get a bedrock client from the runtime.

**Step 3: Commit**

---

## Task 8: Remove boto3 from Discord bridge and registry (service code)

**Files:**
- Modify: `src/cogos/io/discord/bridge.py` — accept runtime or explicit clients
- Modify: `src/cogos/io/discord/registry.py` — accept runtime for DynamoDB access
- Modify: `src/cogos/io/discord/setup.py` — remove remaining boto3 (ECS call)

**Step 1: Fix bridge.py**

The bridge is a standalone ECS service. It should accept a runtime at construction time. Replace `boto3.client("sqs")`, `boto3.client("s3")`, and `boto3.client("secretsmanager")` with runtime methods.

**Step 2: Fix registry.py**

Replace `boto3.resource("dynamodb")` with a client provided by the runtime. Add `list_cogent_configs()` to runtime or pass a DynamoDB table reference.

**Step 3: Fix setup.py**

Replace the ECS `describe_services` call with a runtime method or accept a client parameter.

**Step 4: Commit**

---

## Task 9: Remove boto3 from CLI

**Files:**
- Modify: `src/cogos/cli/__main__.py`

**Step 1: Replace all direct boto3 calls**

The CLI already has the runtime in Click context. Replace:
- `boto3.Session()` credential snapshotting → use runtime
- `boto3.client("bedrock-runtime")` → use runtime.converse()
- `session.resource("dynamodb")` → use runtime.get_repository()
- `session.client("ecr")` / `session.client("s3")` → move to runtime
- `boto3.client("ecs")` → move to runtime

**Step 2: Commit**

---

## Task 10: Remove botocore exception handling from handler.py

**Files:**
- Modify: `src/cogos/executor/handler.py`

**Step 1: Replace botocore.exceptions.ClientError check**

The handler catches `ClientError` to detect Bedrock context-overflow errors. Instead, catch generic exceptions and check the error message pattern (the handler already checks for keywords like "token", "context", "input" in the message).

**Step 2: Commit**

---

## Task 11: Final verification

**Step 1: Grep for any remaining boto3/botocore in src/cogos/**

```bash
grep -rn "boto3\|botocore" src/cogos/ --include="*.py"
```
Expected: Zero matches.

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: All tests pass (except pre-existing missing-dep failures).

**Step 3: Commit any final cleanup**

---

## Out of Scope

- `src/cogtainer/` — this is WHERE boto3 calls live (AwsRuntime, AwsSecretsProvider). That's correct by design.
- `src/dashboard/` — the dashboard is a separate service, not cogos. It can use AwsSecretsProvider directly.
- `src/polis/` — infrastructure/provisioning code.
