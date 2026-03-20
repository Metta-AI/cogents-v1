# Cogent Create — External Service Provisioning Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `polis cogent create` provision Discord role, SES email, Asana guest invite, and GitHub credentials alongside existing AWS infrastructure.

**Architecture:** Add provisioning helper functions to `src/polis/provisioning.py` (new module), call them from the existing `cogents_create` in `cli.py`. Add confirmation step before execution. Augment `cogents_status` with formatted table. Add auto-accept Lambda for Asana invites.

**Tech Stack:** Python, Click, Rich, boto3 (SES), requests (Discord API, Asana API), AWS Lambda

---

### Task 1: Create provisioning module with SES email identity

**Files:**
- Create: `src/polis/provisioning.py`
- Test: `tests/polis/test_provisioning.py`

**Step 1: Write the failing test**

```python
# tests/polis/test_provisioning.py
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from polis.provisioning import provision_ses_email


class FakeSesClient:
    def __init__(self, *, already_exists=False):
        self.created = []
        self._already_exists = already_exists

    def get_email_identity(self, EmailIdentity):
        if self._already_exists:
            return {"VerificationStatus": "SUCCESS"}
        raise self._not_found()

    def create_email_identity(self, EmailIdentity, Tags=None):
        self.created.append(EmailIdentity)
        return {"IdentityType": "EMAIL_ADDRESS"}

    def _not_found(self):
        error = MagicMock()
        error.response = {"Error": {"Code": "NotFoundException"}}
        exc = type("NotFoundException", (Exception,), {"response": error.response})
        return exc("not found")


class FakeStore:
    def __init__(self):
        self.secrets: dict[str, dict] = {}

    def put(self, path, value):
        self.secrets[path] = value

    def get(self, path, **kwargs):
        if path in self.secrets:
            return self.secrets[path]
        raise Exception("not found")


def test_provision_ses_email_creates_identity():
    ses = FakeSesClient()
    store = FakeStore()

    result = provision_ses_email(
        ses_client=ses,
        store=store,
        cogent_name="scout",
        domain="softmax-cogents.com",
    )

    assert result["email"] == "scout@softmax-cogents.com"
    assert ses.created == ["scout@softmax-cogents.com"]
    assert "cogent/scout/ses_identity" in store.secrets


def test_provision_ses_email_idempotent():
    ses = FakeSesClient(already_exists=True)
    store = FakeStore()

    result = provision_ses_email(
        ses_client=ses,
        store=store,
        cogent_name="scout",
        domain="softmax-cogents.com",
    )

    assert result["email"] == "scout@softmax-cogents.com"
    assert ses.created == []  # no duplicate creation
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

```python
# src/polis/provisioning.py
"""External service provisioning for cogent creation."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from polis.secrets.store import SecretStore

logger = logging.getLogger(__name__)


def provision_ses_email(
    *,
    ses_client: Any,
    store: SecretStore,
    cogent_name: str,
    domain: str,
) -> dict[str, str]:
    """Create SES email identity for cogent. Returns {"email": "...", "status": "..."}."""
    email = f"{cogent_name}@{domain}"

    # Check if already exists
    try:
        resp = ses_client.get_email_identity(EmailIdentity=email)
        status = resp.get("VerificationStatus", "unknown")
        return {"email": email, "status": status, "created": False}
    except Exception:
        pass

    ses_client.create_email_identity(
        EmailIdentity=email,
        Tags=[
            {"Key": "cogent", "Value": cogent_name},
            {"Key": "managed-by", "Value": "polis"},
        ],
    )

    store.put(f"cogent/{cogent_name}/ses_identity", {"email": email})

    return {"email": email, "status": "pending", "created": True}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/provisioning.py tests/polis/test_provisioning.py
git commit -m "feat(polis): add SES email provisioning for cogent create"
```

---

### Task 2: Add Discord role provisioning

**Files:**
- Modify: `src/polis/provisioning.py`
- Modify: `tests/polis/test_provisioning.py`

**Step 1: Write the failing test**

Append to `tests/polis/test_provisioning.py`:

```python
from polis.provisioning import provision_discord_role


def test_provision_discord_role_creates_role(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {
        "bot_token": "fake-token",
        "guild_id": "111222333",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "999888777", "name": "cogent-scout"}
    mock_response.raise_for_status = MagicMock()

    def fake_post(url, **kwargs):
        assert "/guilds/111222333/roles" in url
        assert kwargs["json"]["name"] == "cogent-scout"
        return mock_response

    monkeypatch.setattr(requests, "post", fake_post)

    result = provision_discord_role(store=store, cogent_name="scout")

    assert result["role_id"] == "999888777"
    assert result["role_name"] == "cogent-scout"
    assert store.secrets["cogent/scout/discord_role_id"]["role_id"] == "999888777"


def test_provision_discord_role_idempotent(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {
        "bot_token": "fake-token",
        "guild_id": "111222333",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"id": "999888777", "name": "cogent-scout"},
        {"id": "123", "name": "other-role"},
    ]
    mock_response.raise_for_status = MagicMock()

    def fake_get(url, **kwargs):
        return mock_response

    monkeypatch.setattr(requests, "get", fake_get)

    result = provision_discord_role(store=store, cogent_name="scout")

    assert result["role_id"] == "999888777"
    assert result["created"] is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_provisioning.py::test_provision_discord_role_creates_role -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/polis/provisioning.py`:

```python
def provision_discord_role(
    *,
    store: SecretStore,
    cogent_name: str,
) -> dict[str, Any]:
    """Create a Discord role for the cogent. Returns {"role_id": "...", "role_name": "..."}."""
    discord_config = store.get("polis/discord")
    bot_token = discord_config["bot_token"]
    guild_id = discord_config["guild_id"]
    role_name = f"cogent-{cogent_name}"

    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}

    # Check if role already exists
    resp = requests.get(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles",
        headers=headers,
    )
    resp.raise_for_status()
    for role in resp.json():
        if role["name"] == role_name:
            store.put(f"cogent/{cogent_name}/discord_role_id", {
                "role_id": role["id"],
                "role_name": role_name,
                "guild_id": guild_id,
            })
            return {"role_id": role["id"], "role_name": role_name, "created": False}

    # Create role
    resp = requests.post(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles",
        headers=headers,
        json={"name": role_name},
    )
    resp.raise_for_status()
    role_data = resp.json()

    store.put(f"cogent/{cogent_name}/discord_role_id", {
        "role_id": role_data["id"],
        "role_name": role_name,
        "guild_id": guild_id,
    })

    return {"role_id": role_data["id"], "role_name": role_name, "created": True}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/provisioning.py tests/polis/test_provisioning.py
git commit -m "feat(polis): add Discord role provisioning for cogent create"
```

---

### Task 3: Add Asana guest invite provisioning

**Files:**
- Modify: `src/polis/provisioning.py`
- Modify: `tests/polis/test_provisioning.py`

**Step 1: Write the failing test**

Append to `tests/polis/test_provisioning.py`:

```python
from polis.provisioning import provision_asana_guest


def test_provision_asana_guest_invites_user(monkeypatch):
    store = FakeStore()
    store.secrets["polis/asana"] = {
        "access_token": "fake-asana-pat",
        "workspace_gid": "ws-123",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"gid": "asana-user-456", "name": "scout"}}
    mock_response.raise_for_status = MagicMock()

    def fake_post(url, **kwargs):
        assert "/workspaces/ws-123/addUser" in url
        assert kwargs["json"]["data"]["user"] == "scout@softmax-cogents.com"
        return mock_response

    monkeypatch.setattr(requests, "post", fake_post)

    result = provision_asana_guest(
        store=store,
        cogent_name="scout",
        domain="softmax-cogents.com",
    )

    assert result["user_gid"] == "asana-user-456"
    assert result["status"] == "invited"
    assert store.secrets["cogent/scout/asana_user_gid"]["user_gid"] == "asana-user-456"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_provisioning.py::test_provision_asana_guest_invites_user -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/polis/provisioning.py`:

```python
def provision_asana_guest(
    *,
    store: SecretStore,
    cogent_name: str,
    domain: str,
) -> dict[str, Any]:
    """Invite cogent email as guest to Asana workspace. Returns {"user_gid": "...", "status": "invited"}."""
    asana_config = store.get("polis/asana")
    access_token = asana_config["access_token"]
    workspace_gid = asana_config["workspace_gid"]
    email = f"{cogent_name}@{domain}"

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    resp = requests.post(
        f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/addUser",
        headers=headers,
        json={"data": {"user": email}},
    )
    resp.raise_for_status()
    user_data = resp.json()["data"]
    user_gid = user_data["gid"]

    store.put(f"cogent/{cogent_name}/asana_user_gid", {
        "user_gid": user_gid,
        "email": email,
        "workspace_gid": workspace_gid,
        "status": "invited",
    })

    return {"user_gid": user_gid, "email": email, "status": "invited", "created": True}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/provisioning.py tests/polis/test_provisioning.py
git commit -m "feat(polis): add Asana guest invite provisioning for cogent create"
```

---

### Task 4: Add GitHub credentials provisioning

**Files:**
- Modify: `src/polis/provisioning.py`
- Modify: `tests/polis/test_provisioning.py`

**Step 1: Write the failing test**

Append to `tests/polis/test_provisioning.py`:

```python
from polis.provisioning import provision_github_credentials


def test_provision_github_credentials_copies_shared_app():
    store = FakeStore()
    store.secrets["polis/github_app"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }

    result = provision_github_credentials(store=store, cogent_name="scout")

    assert result["type"] == "github_app"
    assert store.secrets["cogent/scout/github"]["app_id"] == "12345"


def test_provision_github_credentials_idempotent():
    store = FakeStore()
    store.secrets["polis/github_app"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }
    store.secrets["cogent/scout/github"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }

    result = provision_github_credentials(store=store, cogent_name="scout")

    assert result["created"] is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_provisioning.py::test_provision_github_credentials_copies_shared_app -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/polis/provisioning.py`:

```python
def provision_github_credentials(
    *,
    store: SecretStore,
    cogent_name: str,
) -> dict[str, Any]:
    """Copy shared GitHub App credentials to cogent secret. Returns {"type": "...", "created": bool}."""
    # Check if already exists
    target_path = f"cogent/{cogent_name}/github"
    try:
        existing = store.get(target_path, use_cache=False)
        if existing:
            return {"type": existing.get("type", "unknown"), "created": False}
    except Exception:
        pass

    shared = store.get("polis/github_app")
    store.put(target_path, shared)

    return {"type": shared.get("type", "unknown"), "created": True}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/provisioning.py tests/polis/test_provisioning.py
git commit -m "feat(polis): add GitHub credentials provisioning for cogent create"
```

---

### Task 5: Add cleanup/destroy functions

**Files:**
- Modify: `src/polis/provisioning.py`
- Modify: `tests/polis/test_provisioning.py`

**Step 1: Write the failing tests**

Append to `tests/polis/test_provisioning.py`:

```python
from polis.provisioning import destroy_discord_role, destroy_ses_email, destroy_asana_guest


def test_destroy_discord_role(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {"bot_token": "fake-token", "guild_id": "111"}
    store.secrets["cogent/scout/discord_role_id"] = {"role_id": "999", "role_name": "cogent-scout", "guild_id": "111"}

    deleted = []
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    def fake_delete(url, **kwargs):
        deleted.append(url)
        return mock_resp

    monkeypatch.setattr(requests, "delete", fake_delete)

    destroy_discord_role(store=store, cogent_name="scout")
    assert any("roles/999" in u for u in deleted)


def test_destroy_ses_email():
    ses = MagicMock()
    destroy_ses_email(ses_client=ses, cogent_name="scout", domain="softmax-cogents.com")
    ses.delete_email_identity.assert_called_once_with(EmailIdentity="scout@softmax-cogents.com")


def test_destroy_asana_guest(monkeypatch):
    store = FakeStore()
    store.secrets["polis/asana"] = {"access_token": "fake-pat", "workspace_gid": "ws-123"}
    store.secrets["cogent/scout/asana_user_gid"] = {"user_gid": "asana-456", "workspace_gid": "ws-123"}

    posted = []
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    def fake_post(url, **kwargs):
        posted.append(url)
        return mock_resp

    monkeypatch.setattr(requests, "post", fake_post)

    destroy_asana_guest(store=store, cogent_name="scout")
    assert any("removeUser" in u for u in posted)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/polis/test_provisioning.py::test_destroy_discord_role -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/polis/provisioning.py`:

```python
def destroy_discord_role(*, store: SecretStore, cogent_name: str) -> None:
    """Delete the cogent's Discord role."""
    discord_config = store.get("polis/discord")
    bot_token = discord_config["bot_token"]
    guild_id = discord_config["guild_id"]

    try:
        role_data = store.get(f"cogent/{cogent_name}/discord_role_id", use_cache=False)
        role_id = role_data["role_id"]
    except Exception:
        logger.warning("No Discord role found for %s", cogent_name)
        return

    headers = {"Authorization": f"Bot {bot_token}"}
    resp = requests.delete(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles/{role_id}",
        headers=headers,
    )
    resp.raise_for_status()


def destroy_ses_email(*, ses_client: Any, cogent_name: str, domain: str) -> None:
    """Delete the cogent's SES email identity."""
    email = f"{cogent_name}@{domain}"
    ses_client.delete_email_identity(EmailIdentity=email)


def destroy_asana_guest(*, store: SecretStore, cogent_name: str) -> None:
    """Remove the cogent's guest from Asana workspace."""
    asana_config = store.get("polis/asana")
    access_token = asana_config["access_token"]

    try:
        user_data = store.get(f"cogent/{cogent_name}/asana_user_gid", use_cache=False)
        user_gid = user_data["user_gid"]
        workspace_gid = user_data["workspace_gid"]
    except Exception:
        logger.warning("No Asana user found for %s", cogent_name)
        return

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resp = requests.post(
        f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/removeUser",
        headers=headers,
        json={"data": {"user": user_gid}},
    )
    resp.raise_for_status()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/polis/test_provisioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/provisioning.py tests/polis/test_provisioning.py
git commit -m "feat(polis): add destroy helpers for external service cleanup"
```

---

### Task 6: Wire provisioning into `cogents create` with confirmation

**Files:**
- Modify: `src/polis/cli.py`
- Modify: `tests/polis/test_cli.py`

**Step 1: Write the failing test**

Append to `tests/polis/test_cli.py`:

```python
def test_cogents_create_shows_confirmation_plan(monkeypatch):
    """The create command should show a plan and ask for confirmation."""
    output = io.StringIO()
    monkeypatch.setattr(
        cli_mod,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=160),
    )

    # Stub all external calls to prevent real work
    monkeypatch.setattr(cli_mod, "get_polis_session", lambda: (FakeSession(), None))

    runner = CliRunner()
    # Answer 'n' to abort after seeing the plan
    result = runner.invoke(polis, ["cogents", "create", "test-bot"], input="n\n")

    rendered = output.getvalue()
    # Should show the plan items
    assert "test-bot" in rendered
    assert "Discord" in rendered or "discord" in rendered.lower()
    assert "Email" in rendered or "SES" in rendered
    assert "Asana" in rendered or "asana" in rendered.lower()
    assert "GitHub" in rendered or "github" in rendered.lower()
    # Should NOT have proceeded to actual creation
    assert "Domain registered" not in rendered
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_cli.py::test_cogents_create_shows_confirmation_plan -v`
Expected: FAIL (current code doesn't show confirmation)

**Step 3: Modify `cogents_create` in `src/polis/cli.py`**

Replace the `cogents_create` function. Key changes:
1. Add confirmation plan display at the top
2. Add new provisioning steps 8-11 after CDK deploy
3. Augment summary table

The function should:
- After computing `subdomain` and `safe_name`, display a Rich table showing all planned resources
- Call `click.confirm("Proceed?", abort=True)`
- After existing step 7 (CDK deploy), add:
  - Step 8: `provision_ses_email()`
  - Step 9: `provision_discord_role()`
  - Step 10: `provision_asana_guest()`
  - Step 11: `provision_github_credentials()`
- Each wrapped in try/except that logs `[yellow]` warning on failure
- Update DynamoDB item with new resource IDs
- Augment summary table

Add these imports at top of cli.py:
```python
from polis.provisioning import (
    provision_ses_email,
    provision_discord_role,
    provision_asana_guest,
    provision_github_credentials,
)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/polis/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/cli.py tests/polis/test_cli.py
git commit -m "feat(polis): wire external provisioning into cogents create with confirmation"
```

---

### Task 7: Wire destroy helpers into `cogents destroy`

**Files:**
- Modify: `src/polis/cli.py`

**Step 1: Modify `cogents_destroy` in `src/polis/cli.py`**

Add cleanup steps before the existing "Delete all secrets" step (step 4). Each wrapped in try/except:

```python
from polis.provisioning import destroy_discord_role, destroy_ses_email, destroy_asana_guest

# In cogents_destroy, before step 4 (delete secrets):

# Clean up Discord role
try:
    destroy_discord_role(store=store, cogent_name=name)
    console.print("  [green]Deleted Discord role[/green]")
except Exception as e:
    console.print(f"  [yellow]Discord role cleanup: {e}[/yellow]")

# Clean up SES email identity
try:
    ses = session.client("sesv2")
    destroy_ses_email(ses_client=ses, cogent_name=name, domain=config.domain)
    console.print("  [green]Deleted SES email identity[/green]")
except Exception as e:
    console.print(f"  [yellow]SES cleanup: {e}[/yellow]")

# Clean up Asana guest
try:
    destroy_asana_guest(store=store, cogent_name=name)
    console.print("  [green]Removed Asana guest[/green]")
except Exception as e:
    console.print(f"  [yellow]Asana cleanup: {e}[/yellow]")
```

**Step 2: Run tests**

Run: `python -m pytest tests/polis/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/polis/cli.py
git commit -m "feat(polis): add external service cleanup to cogents destroy"
```

---

### Task 8: Augment `cogents status` with formatted table

**Files:**
- Modify: `src/polis/cli.py`
- Modify: `tests/polis/test_cli.py`

**Step 1: Write the failing test**

Append to `tests/polis/test_cli.py`:

```python
class FakeStoreForStatus:
    def __init__(self, secrets=None):
        self._secrets = secrets or {}

    def get(self, path, **kwargs):
        if path in self._secrets:
            return self._secrets[path]
        raise Exception("not found")


class FakeStatusTableForSingle:
    def __init__(self, item):
        self._item = item

    def get_item(self, Key):
        return {"Item": self._item}


class FakeDynamoForSingle:
    def __init__(self, item):
        self._table = FakeStatusTableForSingle(item)

    def Table(self, name):
        return self._table


class FakeSessionForStatus:
    def __init__(self, dynamo, secrets=None):
        self._dynamo = dynamo
        self._secrets = secrets or {}

    def client(self, name, **kwargs):
        if name == "secretsmanager":
            return FakeSecretsManagerClient()
        raise AssertionError(f"Unexpected client: {name}")

    def resource(self, name):
        assert name == "dynamodb"
        return self._dynamo


def test_cogents_status_shows_formatted_table(monkeypatch):
    output = io.StringIO()
    item = {
        "cogent_name": "scout",
        "stack_status": "UPDATE_COMPLETE",
        "domain": f"scout.{_DEFAULT_DOMAIN}",
        "dashboard_url": f"https://scout.{_DEFAULT_DOMAIN}",
        "email": "scout@softmax-cogents.com",
        "discord_role_id": "999",
        "asana_user_gid": "456",
        "asana_status": "active",
        "github_type": "github_app",
    }
    dynamo = FakeDynamoForSingle(item)
    session = FakeSessionForStatus(dynamo)

    monkeypatch.setattr(
        cli_mod,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=160),
    )
    monkeypatch.setattr(cli_mod, "get_polis_session", lambda: (session, None))

    runner = CliRunner()
    result = runner.invoke(polis, ["cogents", "status", "scout"])

    rendered = output.getvalue()
    assert "scout" in rendered
    assert "Discord" in rendered
    assert "Email" in rendered
    assert "Asana" in rendered
    assert "GitHub" in rendered
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_cli.py::test_cogents_status_shows_formatted_table -v`
Expected: FAIL (current code dumps raw JSON)

**Step 3: Rewrite `cogents_status` in `src/polis/cli.py`**

Replace the `cogents_status` function:

```python
@cogents.command("status")
@click.argument("name")
def cogents_status(name: str):
    """Show detailed status for a cogent."""
    session, _ = get_polis_session()
    ddb = session.resource("dynamodb")
    table_resource = ddb.Table("cogent-status")

    item = table_resource.get_item(Key={"cogent_name": name}).get("Item")
    if not item:
        console.print(f"[red]No status found for cogent: {name}[/red]")
        return

    ct = Table(title=f"[bold]{name}[/bold]", show_header=False, padding=(0, 1))
    ct.add_column("Component", style="bold")
    ct.add_column("Status")

    # Infrastructure
    ct.add_row("Stack", _cell(item.get("stack_status")))
    ct.add_row("Domain", item.get("domain", "-"))
    ct.add_row("Dashboard URL", item.get("dashboard_url", "-"))

    # Dashboard/Discord/Executor components
    dashboard = _component_state(item.get("dashboard"))
    discord_comp = _component_state(item.get("discord"))
    executor = _component_state(item.get("executor"))
    ct.add_row("Dashboard", _cell(_component_status(dashboard)))
    ct.add_row("Executor Image", _cell(_component_image(executor)))

    # External services
    email = item.get("email")
    ct.add_row("Email", f"[green]{email}[/green]" if email else "[dim]-[/dim]")

    discord_role = item.get("discord_role_id")
    ct.add_row("Discord Role", f"[green]cogent-{name} ({discord_role})[/green]" if discord_role else "[dim]-[/dim]")

    asana_gid = item.get("asana_user_gid")
    asana_status = item.get("asana_status", "unknown")
    if asana_gid:
        style = "green" if asana_status == "active" else "yellow"
        ct.add_row("Asana", f"[{style}]{asana_gid} ({asana_status})[/{style}]")
    else:
        ct.add_row("Asana", "[dim]-[/dim]")

    github_type = item.get("github_type")
    ct.add_row("GitHub", f"[green]{github_type}[/green]" if github_type else "[dim]-[/dim]")

    console.print(ct)
```

**Step 4: Run tests**

Run: `python -m pytest tests/polis/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/cli.py tests/polis/test_cli.py
git commit -m "feat(polis): formatted cogents status with external service info"
```

---

### Task 9: Add external services to top-level `polis status` per-cogent tables

**Files:**
- Modify: `src/polis/cli.py`

**Step 1: Add rows to the per-cogent loop in `status()`**

In the `status` function, inside the `for item in items:` loop (around line 366), after the existing `ct.add_row("Secrets", ...)` line, add:

```python
# External services
email = item.get("email")
ct.add_row("Email", f"[green]{email}[/green]" if email else "[dim]-[/dim]")

discord_role = item.get("discord_role_id")
ct.add_row("Discord Role", f"[green]cogent-{name} ({discord_role})[/green]" if discord_role else "[dim]-[/dim]")

asana_gid = item.get("asana_user_gid")
asana_status = item.get("asana_status", "unknown")
if asana_gid:
    style = "green" if asana_status == "active" else "yellow"
    ct.add_row("Asana", f"[{style}]{asana_gid} ({asana_status})[/{style}]")
else:
    ct.add_row("Asana", "[dim]-[/dim]")

github_type = item.get("github_type")
ct.add_row("GitHub", f"[green]{github_type}[/green]" if github_type else "[dim]-[/dim]")
```

**Step 2: Run existing status test to ensure no regression**

Run: `python -m pytest tests/polis/test_cli.py::test_status_renders_stored_snapshot_without_listing_dashboard_services -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/polis/cli.py
git commit -m "feat(polis): show external services in top-level polis status"
```

---

### Task 10: Add Asana auto-accept Lambda

**Files:**
- Create: `src/polis/io/asana/__init__.py`
- Create: `src/polis/io/asana/handler.py`
- Create: `tests/polis/test_asana_auto_accept.py`

**Step 1: Write the failing test**

```python
# tests/polis/test_asana_auto_accept.py
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_asana_auto_accept_extracts_and_hits_link():
    """The handler should extract the accept link from Asana invite email and GET it."""
    from polis.io.asana.handler import _extract_accept_link, _auto_accept

    html_body = '''
    <html><body>
    <a href="https://app.asana.com/0/accept/invitation/12345?token=abc123">Accept Invite</a>
    </body></html>
    '''

    link = _extract_accept_link(html_body)
    assert link is not None
    assert "accept" in link
    assert "asana.com" in link


def test_asana_auto_accept_updates_dynamo():
    """After accepting, the handler should update DynamoDB status to active."""
    from polis.io.asana.handler import handler

    event = {
        "Records": [
            {
                "body": json.dumps({
                    "cogent_name": "scout",
                    "from": "no-reply@asana.com",
                    "subject": "You've been invited to join Softmax",
                    "html_body": '<a href="https://app.asana.com/0/accept/invitation/123?token=abc">Accept</a>',
                }),
            }
        ]
    }

    with patch("polis.io.asana.handler.requests") as mock_requests, \
         patch("polis.io.asana.handler._get_dynamo_table") as mock_dynamo:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests.get.return_value = mock_resp

        mock_table = MagicMock()
        mock_dynamo.return_value = mock_table

        handler(event, None)

        mock_requests.get.assert_called_once()
        mock_table.update_item.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/polis/test_asana_auto_accept.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/polis/io/asana/__init__.py
```

```python
# src/polis/io/asana/handler.py
"""Asana auto-accept Lambda — processes Asana invite emails and accepts them.

Triggered by SQS when an email from Asana is received by the cogent's SES address.
Extracts the accept link from the HTML body and hits it to complete onboarding.
"""

import json
import logging
import os
import re
from typing import Any

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")

_dynamo_table: Any = None


def _get_dynamo_table():
    global _dynamo_table
    if _dynamo_table is None:
        _dynamo_table = boto3.resource("dynamodb").Table(DYNAMO_TABLE)
    return _dynamo_table


def _extract_accept_link(html_body: str) -> str | None:
    """Extract Asana invitation accept link from email HTML body."""
    pattern = r'https://app\.asana\.com/\S*accept\S*?["\s<]'
    match = re.search(pattern, html_body)
    if match:
        link = match.group(0).rstrip('"< \t\n')
        return link
    # Fallback: look for any asana.com link with "invitation" or "accept"
    pattern2 = r'href="(https://app\.asana\.com/[^"]*)"'
    for m in re.finditer(pattern2, html_body):
        url = m.group(1)
        if "accept" in url or "invitation" in url:
            return url
    return None


def _auto_accept(link: str) -> bool:
    """Hit the accept link to complete the Asana invitation."""
    resp = requests.get(link, allow_redirects=True)
    return resp.status_code < 400


def handler(event, context):
    """SQS Lambda handler — processes Asana invite emails."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            cogent_name = body.get("cogent_name")
            sender = body.get("from", "")
            subject = body.get("subject", "")
            html_body = body.get("html_body", "")

            if "asana.com" not in sender.lower():
                logger.info("Skipping non-Asana email from=%s cogent=%s", sender, cogent_name)
                continue

            link = _extract_accept_link(html_body)
            if not link:
                logger.warning("No accept link found in Asana email cogent=%s subject=%s", cogent_name, subject)
                continue

            logger.info("Auto-accepting Asana invite cogent=%s link=%s", cogent_name, link)
            if _auto_accept(link):
                logger.info("Asana invite accepted cogent=%s", cogent_name)
                # Update DynamoDB status
                _get_dynamo_table().update_item(
                    Key={"cogent_name": cogent_name},
                    UpdateExpression="SET asana_status = :s",
                    ExpressionAttributeValues={":s": "active"},
                )
            else:
                logger.error("Failed to accept Asana invite cogent=%s", cogent_name)

        except Exception:
            logger.exception("Error processing Asana invite record")
```

**Step 4: Run tests**

Run: `python -m pytest tests/polis/test_asana_auto_accept.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/polis/io/asana/__init__.py src/polis/io/asana/handler.py tests/polis/test_asana_auto_accept.py
git commit -m "feat(polis): add Asana auto-accept Lambda for invite emails"
```

---

### Task 11: Run full test suite and final commit

**Step 1: Run all polis tests**

Run: `python -m pytest tests/polis/ -v`
Expected: All PASS

**Step 2: Run linting**

Run: `ruff check src/polis/provisioning.py src/polis/io/asana/handler.py`
Expected: Clean

**Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: fix lint issues in provisioning code"
```
