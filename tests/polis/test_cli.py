from __future__ import annotations

from click.testing import CliRunner

from polis.cli import polis


def test_update_ensures_polis_quotas(monkeypatch):
    calls: list[tuple] = []

    monkeypatch.setattr("polis.cli.get_org_id", lambda: "o-test")
    monkeypatch.setattr("polis.cli._cdk_deploy", lambda org_id, profile=None: calls.append(("deploy", org_id, profile)))
    monkeypatch.setattr("polis.cli.get_polis_session", lambda: ("session", "901289084804"))
    monkeypatch.setattr(
        "polis.cli._ensure_polis_quotas",
        lambda session, config, **kwargs: calls.append(("quotas", session, config.domain)),
    )
    monkeypatch.setattr(
        "polis.cli._ensure_cloudflare_access",
        lambda session, domain: calls.append(("cloudflare", session, domain)),
    )

    runner = CliRunner()
    result = runner.invoke(polis, ["update"])

    assert result.exit_code == 0
    assert calls == [
        ("deploy", "o-test", "softmax-org"),
        ("quotas", "session", "softmax-cogents.com"),
        ("cloudflare", "session", "softmax-cogents.com"),
    ]


def test_quotas_ensure_runs_quota_helper(monkeypatch):
    calls: list[tuple] = []

    monkeypatch.setattr("polis.cli.get_polis_session", lambda: ("session", "901289084804"))
    monkeypatch.setattr(
        "polis.cli._ensure_polis_quotas",
        lambda session, config, **kwargs: calls.append(("quotas", session, config.domain, kwargs.get("fail_on_error"))),
    )

    runner = CliRunner()
    result = runner.invoke(polis, ["quotas", "ensure"])

    assert result.exit_code == 0
    assert calls == [("quotas", "session", "softmax-cogents.com", True)]
