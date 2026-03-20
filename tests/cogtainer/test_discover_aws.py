"""Tests for cogtainer discover-aws command."""

from __future__ import annotations

from unittest.mock import MagicMock

import yaml
from click.testing import CliRunner

from cogtainer.cogtainer_cli import cli


def _read_config(path):
    return yaml.safe_load(path.read_text())


def test_discover_aws_populates_config(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    # Mock AWS session
    mock_session = MagicMock()
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        "Items": [
            {"cogent_name": "agent1", "db_name": "cogent_agent1"},
            {"cogent_name": "agent2", "db_name": "cogent_agent2"},
        ],
    }
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_session.resource.return_value = mock_ddb

    mock_get_session = MagicMock(return_value=(mock_session, "123456789012"))
    monkeypatch.setattr(
        "cogtainer.cogtainer_cli._get_aws_session", mock_get_session,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["discover-aws", "--region", "us-east-1"])
    assert result.exit_code == 0, result.output

    cfg = _read_config(config_path)
    assert "aws" in cfg["cogtainers"]
    entry = cfg["cogtainers"]["aws"]
    assert entry["type"] == "aws"
    assert entry["region"] == "us-east-1"
    assert entry["account_id"] == "123456789012"

    assert "agent1" in result.output
    assert "agent2" in result.output


def test_discover_aws_does_not_overwrite_existing(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    # Pre-create config with existing aws entry
    existing = {
        "cogtainers": {
            "aws": {
                "type": "aws",
                "region": "eu-west-1",
                "llm": {
                    "provider": "bedrock",
                    "model": "anthropic.claude-3-sonnet",
                    "api_key_env": "",
                },
            },
        },
        "defaults": {"cogtainer": "aws"},
    }
    config_path.write_text(yaml.dump(existing))

    mock_session = MagicMock()
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        "Items": [{"cogent_name": "bot1"}],
    }
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_session.resource.return_value = mock_ddb

    mock_get_session = MagicMock(return_value=(mock_session, "123456789012"))
    monkeypatch.setattr(
        "cogtainer.cogtainer_cli._get_aws_session", mock_get_session,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["discover-aws"])
    assert result.exit_code == 0, result.output

    cfg = _read_config(config_path)
    # Should keep existing region, not overwrite
    assert cfg["cogtainers"]["aws"]["region"] == "eu-west-1"
    assert "bot1" in result.output


def test_discover_aws_no_cogents(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    mock_session = MagicMock()
    mock_table = MagicMock()
    mock_table.scan.return_value = {"Items": []}
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_session.resource.return_value = mock_ddb

    mock_get_session = MagicMock(return_value=(mock_session, "123456789012"))
    monkeypatch.setattr(
        "cogtainer.cogtainer_cli._get_aws_session", mock_get_session,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["discover-aws"])
    assert result.exit_code == 0, result.output
    assert "No cogents" in result.output


def test_discover_aws_with_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    mock_session = MagicMock()
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        "Items": [{"cogent_name": "mybot"}],
    }
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_session.resource.return_value = mock_ddb

    mock_get_session = MagicMock(return_value=(mock_session, "999888777666"))
    monkeypatch.setattr(
        "cogtainer.cogtainer_cli._get_aws_session", mock_get_session,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["discover-aws", "--profile", "myprofile", "--region", "us-west-2"])
    assert result.exit_code == 0, result.output

    # Verify profile was passed
    mock_get_session.assert_called_once_with(region="us-west-2", profile="myprofile")
