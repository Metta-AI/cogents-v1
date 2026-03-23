"""Tests for dashboard setup router — gemini secret status and fallback."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_secrets_provider(secrets: dict[str, str] | None = None):
    """Create a mock SecretsProvider."""
    provider = MagicMock()

    def _get(secret_id):
        if secrets and secret_id in secrets:
            return secrets[secret_id]
        raise KeyError(secret_id)

    provider.get_secret.side_effect = _get
    return provider


def _patch_sp(provider):
    """Patch _get_secrets_provider to return the given provider."""
    return patch("dashboard.routers.setup._get_secrets_provider", return_value=provider)


@pytest.fixture(autouse=True)
def _patch_runtime():
    """Patch create_executor_runtime so importing setup doesn't need COGTAINER."""
    mock_rt = MagicMock()
    mock_sp = MagicMock()
    mock_sp.get_secret.side_effect = KeyError("not mocked")
    mock_rt.get_secrets_provider.return_value = mock_sp
    mock_rt.get_ecs_client.return_value = None
    with patch("dashboard.routers.setup._get_runtime", return_value=mock_rt), \
         patch("dashboard.routers.setup._get_secrets_provider", return_value=mock_sp):
        yield


class TestGeminiSecretStatus:
    """Tests for _gemini_secret_status with cogent/all fallback."""

    def test_cogent_specific_secret_found(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "key-alpha"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_falls_back_to_all_secret(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/all/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/all/gemini"

    def test_cogent_specific_takes_precedence_over_all(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "alpha-key"}),
            "cogent/all/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_returns_false_when_both_missing(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({})

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is False
        assert error is None
        assert source is None

    def test_returns_false_when_api_key_empty(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": ""}),
            "cogent/all/gemini": json.dumps({"api_key": ""}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is False
        assert error is None
        assert source is None

    def test_returns_error_on_exception(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = MagicMock()
        provider.get_secret.side_effect = RuntimeError("connection failed")

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is None
        assert error == "RuntimeError"
        assert source is None


class TestBuildGeminiSetup:
    """Tests for _build_gemini_setup showing shared vs cogent-specific summary."""

    def test_shared_secret_summary(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({
            "cogent/all/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert "shared" in setup.summary
        assert setup.status.value == "ready"

    def test_cogent_specific_secret_summary(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "alpha-key"}),
        })

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert "cogent-specific" in setup.summary
        assert setup.status.value == "ready"

    def test_missing_secret_needs_action(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({})

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert setup.status.value == "needs_action"
        assert not setup.ready_for_test
