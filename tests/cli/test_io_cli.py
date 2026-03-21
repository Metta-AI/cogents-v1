"""Tests for cogent io CLI commands (email provisioning and send)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cogos.io.cli import io


def test_create_no_args_lists_integrations():
    """io create with no args should list available integrations including email."""
    runner = CliRunner()
    result = runner.invoke(io, ["create"])
    assert result.exit_code == 0
    assert "email" in result.output
    assert "cloudflare_ses" in result.output


def test_create_email_no_cogent_name_shows_usage():
    """io create email with no cogent name should show usage error."""
    runner = CliRunner()
    result = runner.invoke(io, ["create", "email"])
    assert result.exit_code != 0
    assert "Usage" in result.output


@patch("cogtainer.runtime.factory.create_runtime", return_value=MagicMock())
@patch("cogtainer.config.load_config")
@patch("cogos.io.email.provision.provision_email")
def test_create_email_calls_provision(mock_provision, mock_load_config, mock_create_runtime):
    """io create email my-cogent should call provision_email and print results."""
    mock_load_config.return_value.cogtainers = {"": MagicMock()}
    mock_provision.return_value = {
        "address": "my-cogent@softmax-cogents.com",
        "ingest_url": "https://my-cogent.softmax-cogents.com/api/ingest/email",
        "cf_rule_id": "rule-123",
        "ses_verified": True,
    }

    runner = CliRunner()
    result = runner.invoke(io, ["create", "email", "my-cogent"])

    assert result.exit_code == 0
    mock_provision.assert_called_once()
    assert "my-cogent@softmax-cogents.com" in result.output
    assert "rule-123" in result.output
    assert "True" in result.output


@patch("cogtainer.runtime.factory.create_runtime", return_value=MagicMock())
@patch("cogtainer.config.load_config")
@patch("cogos.io.email.provision.provision_email")
def test_create_email_provision_failure(mock_provision, mock_load_config, mock_create_runtime):
    """io create email should report failure when provision_email raises."""
    mock_load_config.return_value.cogtainers = {"": MagicMock()}
    mock_provision.side_effect = RuntimeError("CLOUDFLARE_API_TOKEN not set")

    runner = CliRunner()
    result = runner.invoke(io, ["create", "email", "my-cogent"])

    assert result.exit_code != 0
    assert "Email provisioning failed" in result.output


@patch("cogtainer.runtime.factory.create_executor_runtime")
def test_send_email_calls_sender(mock_create_runtime):
    """io send email my-cogent should call runtime.send_email and print message ID."""
    mock_runtime = MagicMock()
    mock_runtime.send_email.return_value = "msg-abc-123"
    mock_create_runtime.return_value = mock_runtime

    runner = CliRunner()
    result = runner.invoke(io, ["send", "email", "my-cogent", "-m", "Hello test"])

    assert result.exit_code == 0
    mock_runtime.send_email.assert_called_once()
    assert "msg-abc-123" in result.output


@patch("cogtainer.runtime.factory.create_executor_runtime")
def test_send_email_failure(mock_create_runtime):
    """io send email should report failure when send raises."""
    mock_runtime = MagicMock()
    mock_runtime.send_email.side_effect = Exception("SES error")
    mock_create_runtime.return_value = mock_runtime

    runner = CliRunner()
    result = runner.invoke(io, ["send", "email", "my-cogent"])

    assert result.exit_code != 0
    assert "Send failed" in result.output
