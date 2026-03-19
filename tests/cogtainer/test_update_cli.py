from __future__ import annotations

import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner

from cogtainer.update_cli import (
    _ensure_discord_bridge_state,
    _find_dashboard_service,
    _get_discord_desired_count,
    _is_dashboard_service_name,
    update,
)


class _FakeEcsClient:
    def __init__(self, service_arns: list[str]):
        self.service_arns = service_arns
        self.describe_services_response: dict[str, list[dict]] = {"services": []}
        self.update_calls: list[dict] = []

    def list_services(self, cluster: str) -> dict[str, list[str]]:
        assert cluster == "cogent-polis"
        return {"serviceArns": self.service_arns}

    def describe_services(self, cluster: str, services: list[str]) -> dict[str, list[dict]]:
        assert cluster == "cogent-polis"
        assert services
        return self.describe_services_response

    def update_service(self, **kwargs) -> None:
        self.update_calls.append(kwargs)


class _FakeSession:
    def __init__(self, *, ecs_client, acm_client, ecr_client, secrets_client):
        self._clients = {
            "ecs": ecs_client,
            "acm": acm_client,
            "ecr": ecr_client,
            "secretsmanager": secrets_client,
        }

    def client(self, name: str, region_name: str | None = None):
        return self._clients[name]


class _FakeSecretsClient:
    def __init__(self, *, exists: bool):
        self.exists = exists
        self.calls: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict:
        self.calls.append(SecretId)
        if not self.exists:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
                "GetSecretValue",
            )
        return {"SecretString": '{"access_token":"discord-token"}'}


def test_is_dashboard_service_name_rejects_non_dashboard_services():
    assert _is_dashboard_service_name("cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ", "dr-gamma")
    assert _is_dashboard_service_name("cogent-dr-gamma-dashboard", "dr-gamma")
    assert not _is_dashboard_service_name("cogent-dr-gamma-discord", "dr-gamma")


def test_find_dashboard_service_prefers_dashboard_service_over_discord():
    ecs_client = _FakeEcsClient(
        [
            "arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-discord",
            "arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ",
        ]
    )

    service_arn = _find_dashboard_service(ecs_client, "dr-gamma")

    assert service_arn.endswith("cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ")


def test_find_dashboard_service_raises_when_dashboard_service_missing():
    ecs_client = _FakeEcsClient(["arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-discord"])

    with pytest.raises(Exception, match="No dashboard service found"):
        _find_dashboard_service(ecs_client, "dr-gamma")


def test_get_discord_desired_count_returns_none():
    """Discord bridge is now polis-level, per-cogent returns None."""
    session = _FakeSession(
        ecs_client=_FakeEcsClient([]),
        acm_client=object(),
        ecr_client=object(),
        secrets_client=_FakeSecretsClient(exists=True),
    )
    assert _get_discord_desired_count(session, "dr.gamma") is None  # type: ignore[arg-type]


def test_discord_bridge_state_is_noop():
    """Discord bridge is now polis-level, per-cogent management is no-op."""
    session = _FakeSession(
        ecs_client=_FakeEcsClient([]),
        acm_client=object(),
        ecr_client=object(),
        secrets_client=_FakeSecretsClient(exists=True),
    )
    action = _ensure_discord_bridge_state(
        session,  # type: ignore[arg-type]
        "dr.gamma",
        "dr-gamma",
        previous_desired_count=None,
    )
    assert action is None


def test_update_stack_no_per_cogent_discord_management(monkeypatch):
    """Discord bridge is polis-level; update stack should not manage per-cogent bridge."""
    ecs_client = _FakeEcsClient([])
    acm_client = type(
        "FakeAcm",
        (),
        {"list_certificates": lambda self: {"CertificateSummaryList": []}},
    )()
    ecr_client = type(
        "FakeEcr",
        (),
        {
            "describe_repositories": (
                lambda self, repositoryNames: {
                    "repositories": [{"repositoryUri": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent"}]
                }
            )
        },
    )()
    session = _FakeSession(
        ecs_client=ecs_client,
        acm_client=acm_client,
        ecr_client=ecr_client,
        secrets_client=_FakeSecretsClient(exists=True),
    )

    monkeypatch.setattr("polis.aws.resolve_org_profile", lambda profile=None: "softmax-org")
    monkeypatch.setattr("polis.aws.set_profile", lambda profile: None)
    monkeypatch.setattr("polis.aws.get_polis_session", lambda: (session, "901289084804"))

    class _Result:
        returncode = 0

    run_calls: list[dict] = []

    def _fake_run(cmd, capture_output, env):
        run_calls.append({"cmd": cmd, "capture_output": capture_output, "env": env})
        return _Result()

    monkeypatch.setattr("subprocess.run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(update, ["stack"], obj={"cogent_id": "dr.gamma"})

    assert result.exit_code == 0
    assert run_calls
    # No per-cogent discord bridge management
    assert ecs_client.update_calls == []


def test_update_rds_runs_brain_and_cogos_migrations(monkeypatch):
    calls: dict[str, object] = {}
    fake_repo = object()

    monkeypatch.setattr(
        "cogtainer.update_cli._ensure_db_env", lambda name, profile=None: calls.setdefault("ensure", (name, profile))
    )
    monkeypatch.setattr("cogos.db.migrations.apply_schema", lambda: 10)
    monkeypatch.setattr(
        "cogos.db.migrations.apply_cogos_sql_migrations",
        lambda repo: calls.__setitem__("repo", repo) or 42,
    )
    monkeypatch.setenv("DB_CLUSTER_ARN", "cluster-arn")
    monkeypatch.setenv("DB_SECRET_ARN", "secret-arn")
    monkeypatch.setenv("DB_NAME", "cogent")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(
        "cogos.db.repository.Repository.create",
        lambda **kwargs: calls.__setitem__("repo_create", kwargs) or fake_repo,
    )

    runner = CliRunner()
    result = runner.invoke(update, ["rds"], obj={"cogent_id": "dr.gamma"})

    assert result.exit_code == 0
    assert calls["ensure"] == ("dr.gamma", None)
    assert calls["repo"] is fake_repo
    assert calls["repo_create"] == {
        "resource_arn": "cluster-arn",
        "secret_arn": "secret-arn",
        "database": "cogent",
        "region": "us-east-1",
    }
    assert "Schema at version 10." in result.output
    assert "CogOS SQL migrations applied" in result.output
