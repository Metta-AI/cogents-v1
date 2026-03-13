"""Tests for the secret-audit example app image."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_secret_audit_loads():
    spec = load_image(Path("images/cogent-v1"))

    proc_names = {p["name"] for p in spec.processes}
    assert "secret-audit" in proc_names

    audit = next(p for p in spec.processes if p["name"] == "secret-audit")
    assert audit["mode"] == "daemon"
    assert audit["content"] == "@{apps/secret-audit/orchestrator.md}"
    assert "procs" in audit["capabilities"]
    assert "secrets" in audit["capabilities"]
    assert "channels" in audit["capabilities"]
    assert "system:tick:hour" in audit["handlers"]
    assert "secret-audit:requests" in audit["handlers"]
    assert "secret-audit:events" in audit["handlers"]


def test_cogent_v1_secret_audit_files():
    spec = load_image(Path("images/cogent-v1"))
    audit_files = {k for k in spec.files if k.startswith("apps/secret-audit/")}

    assert "apps/secret-audit/config.json" in audit_files
    assert "apps/secret-audit/heuristics.md" in audit_files
    assert "apps/secret-audit/report-format.md" in audit_files
    assert "apps/secret-audit/orchestrator.md" in audit_files
    assert "apps/secret-audit/scout.md" in audit_files
    assert "apps/secret-audit/verifier.md" in audit_files


def test_cogent_v1_secret_audit_prompt_refs_are_explicit():
    spec = load_image(Path("images/cogent-v1"))

    assert "@{apps/secret-audit/config.json}" in spec.files["apps/secret-audit/orchestrator.md"]
    assert "@{apps/secret-audit/heuristics.md}" in spec.files["apps/secret-audit/orchestrator.md"]
    assert "@{apps/secret-audit/report-format.md}" in spec.files["apps/secret-audit/orchestrator.md"]
    assert "@{apps/secret-audit/heuristics.md}" in spec.files["apps/secret-audit/scout.md"]
    assert "@{apps/secret-audit/config.json}" in spec.files["apps/secret-audit/verifier.md"]


def test_cogent_v1_secret_audit_channels_and_schemas():
    spec = load_image(Path("images/cogent-v1"))

    channel_names = {c["name"] for c in spec.channels}
    assert "secret-audit:requests" in channel_names
    assert "secret-audit:events" in channel_names
    assert "secret-audit:findings" in channel_names

    schema_names = {s["name"] for s in spec.schemas}
    assert "secret-audit-request" in schema_names
    assert "secret-audit-event" in schema_names
    assert "secret-audit-finding" in schema_names
