"""Tests for cogtainer CLI commands."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from cogtainer.cogtainer_cli import cli


def _read_config(path):
    return yaml.safe_load(path.read_text())


def test_cogtainer_create_local(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "create", "dev",
        "--type", "local",
        "--llm-provider", "anthropic",
        "--llm-model", "claude-sonnet-4-20250514",
        "--llm-api-key-env", "ANTHROPIC_API_KEY",
        "--data-dir", str(tmp_path / "data"),
    ])
    assert result.exit_code == 0, result.output

    cfg = _read_config(config_path)
    assert "dev" in cfg["cogtainers"]
    entry = cfg["cogtainers"]["dev"]
    assert entry["type"] == "local"
    assert entry["data_dir"] == str(tmp_path / "data")
    assert entry["llm"]["provider"] == "anthropic"
    # Only cogtainer -> set as default
    assert cfg["defaults"]["cogtainer"] == "dev"
    # Data dir created
    assert (tmp_path / "data").is_dir()


def test_cogtainer_list_empty(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "No cogtainers" in result.output


def test_cogtainer_list_shows_entries(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    cfg = {
        "cogtainers": {
            "dev": {
                "type": "local",
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                },
            },
            "prod": {
                "type": "aws",
                "region": "us-east-1",
                "llm": {
                    "provider": "bedrock",
                    "model": "anthropic.claude-3-sonnet",
                    "api_key_env": "NONE",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }
    config_path.write_text(yaml.dump(cfg))

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "dev" in result.output
    assert "prod" in result.output
    assert "local" in result.output
    assert "aws" in result.output


def test_cogtainer_destroy(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    cfg = {
        "cogtainers": {
            "dev": {
                "type": "local",
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }
    config_path.write_text(yaml.dump(cfg))

    runner = CliRunner()
    result = runner.invoke(cli, ["destroy", "dev"], input="y\n")
    assert result.exit_code == 0

    cfg = _read_config(config_path)
    assert "dev" not in cfg["cogtainers"]
