"""Tests for local_dispatcher — tick-based process scheduling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.local_dispatcher import run_tick
from cogtainer.runtime.local import LocalRuntime


@pytest.fixture()
def local_runtime(tmp_path: Path) -> LocalRuntime:
    entry = CogtainerEntry(type="local", data_dir=str(tmp_path), llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""))
    llm = MagicMock()
    return LocalRuntime(entry=entry, llm=llm)


def test_single_tick(local_runtime: LocalRuntime):
    """run_tick should not raise and returns dict with dispatched >= 0."""
    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    result = run_tick(repo, local_runtime, cogent_name)

    assert isinstance(result, dict)
    assert "dispatched" in result
    assert result["dispatched"] >= 0
