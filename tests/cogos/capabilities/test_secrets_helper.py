"""Tests for _secrets_helper.fetch_secret."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.capabilities._secrets_helper import fetch_secret


class TestFetchSecretSSM:
    def test_returns_value_from_ssm(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.return_value = {
                "Parameter": {"Value": "my-secret-value"}
            }
            mock_client.return_value = mock_ssm
            result = fetch_secret("cogos/api-key")
            assert result == "my-secret-value"
            mock_client.assert_called_with("ssm")

    def test_falls_back_to_secrets_manager(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.side_effect = Exception("not found")
            mock_sm = MagicMock()
            mock_sm.get_secret_value.return_value = {"SecretString": "sm-value"}

            def pick_client(service):
                return mock_ssm if service == "ssm" else mock_sm

            mock_client.side_effect = pick_client
            result = fetch_secret("cogos/api-key")
            assert result == "sm-value"

    def test_raises_on_both_fail(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.side_effect = Exception("ssm fail")
            mock_sm = MagicMock()
            mock_sm.get_secret_value.side_effect = Exception("sm fail")

            def pick_client(service):
                return mock_ssm if service == "ssm" else mock_sm

            mock_client.side_effect = pick_client
            with pytest.raises(RuntimeError, match="Could not fetch secret"):
                fetch_secret("cogos/api-key")
