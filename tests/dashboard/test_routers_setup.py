"""Tests for dashboard setup router — gemini secret status and fallback."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_secrets_provider(secrets: dict[str, str] | None = None):
    """Create a mock AwsSecretsProvider."""
    provider = MagicMock()

    def _get(secret_id):
        if secrets and secret_id in secrets:
            return secrets[secret_id]
        raise KeyError(secret_id)

    provider.get_secret.side_effect = _get
    return provider


@pytest.fixture(autouse=True)
def _patch_aws_secrets():
    """Patch AwsSecretsProvider so importing dashboard.routers.setup doesn't need AWS."""
    # If the module is already imported, just patch the provider
    if "dashboard.routers.setup" in sys.modules:
        mock_provider = MagicMock()
        mock_provider.get_secret.side_effect = KeyError("not mocked")
        with patch("dashboard.routers.setup._secrets_provider", mock_provider):
            yield
    else:
        with patch("cogtainer.secrets.AwsSecretsProvider", return_value=MagicMock()):
            yield


class TestGeminiSecretStatus:
    """Tests for _gemini_secret_status with cogent/all fallback."""

    def test_cogent_specific_secret_found(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "key-alpha"}),
        })

        with patch("dashboard.routers.setup._secrets_provider", provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_falls_back_to_all_secret(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/all/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with patch("dashboard.routers.setup._secrets_provider", provider):
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

        with patch("dashboard.routers.setup._secrets_provider", provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_returns_false_when_both_missing(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({})

        with patch("dashboard.routers.setup._secrets_provider", provider):
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

        with patch("dashboard.routers.setup._secrets_provider", provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is False
        assert error is None
        assert source is None

    def test_returns_error_on_exception(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = MagicMock()
        provider.get_secret.side_effect = RuntimeError("connection failed")

        with patch("dashboard.routers.setup._secrets_provider", provider):
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

        with patch("dashboard.routers.setup._secrets_provider", provider):
            setup = _build_gemini_setup("alpha")

        assert "shared" in setup.summary
        assert setup.status.value == "ready"

    def test_cogent_specific_secret_summary(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "alpha-key"}),
        })

        with patch("dashboard.routers.setup._secrets_provider", provider):
            setup = _build_gemini_setup("alpha")

        assert "cogent-specific" in setup.summary
        assert setup.status.value == "ready"

    def test_missing_secret_needs_action(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({})

        with patch("dashboard.routers.setup._secrets_provider", provider):
            setup = _build_gemini_setup("alpha")

        assert setup.status.value == "needs_action"
        assert not setup.ready_for_test
