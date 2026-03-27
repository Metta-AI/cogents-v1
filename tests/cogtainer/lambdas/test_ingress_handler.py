"""Tests for the ingress Lambda handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.local import LocalRuntime


@pytest.fixture()
def local_runtime(tmp_path: Path, monkeypatch) -> LocalRuntime:
    monkeypatch.setenv("COGTAINER", "test-local")
    monkeypatch.setenv("COGENT", "test-cogent")
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:fake")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:fake")
    monkeypatch.setenv("DB_NAME", "cogent_test")
    monkeypatch.chdir(tmp_path)
    entry = CogtainerEntry(
        type="local",
        llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""),
    )
    llm = MagicMock()
    rt = LocalRuntime(entry=entry, llm=llm)
    rt.create_cogent("test-cogent")
    import cogtainer.lambdas.shared.config as cfg_mod
    cfg_mod._config = None
    return rt


def test_ingress_handler_gets_repo_via_runtime(local_runtime, monkeypatch):
    """Ingress handler should obtain the repo through create_executor_runtime."""
    from cogtainer.lambdas.ingress import handler as ingress_module

    monkeypatch.setattr(
        ingress_module, "create_executor_runtime", lambda: local_runtime,
    )
    monkeypatch.setattr(ingress_module.boto3, "client", MagicMock())

    result = ingress_module.handler({}, None)

    assert result["statusCode"] == 200
    assert "dispatched" in result
