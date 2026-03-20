# Cogtainer Multi-Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace polis with cogtainer as the top-level concept, supporting AWS, local, and Docker runtime environments with a unified CogtainerRuntime API.

**Architecture:** Three-layer split: `cogtainer` CLI manages infrastructure lifecycle, `cogent` CLI manages cogent lifecycle within a cogtainer, `cogos` CLI operates a specific cogent. CogOS code depends only on a `CogtainerRuntime` interface — never imports boto3 or knows about AWS/local/docker. The runtime is injected at startup based on cogtainer type from `~/.cogos/cogtainers.yml`.

**Tech Stack:** Python 3.12, Click (CLI), Pydantic (config), boto3 (AWS runtime), AWS CDK (infrastructure), existing LocalRepository (local runtime)

---

### Task 1: Config — cogtainers.yml loader

**Files:**
- Create: `src/cogtainer/config.py`
- Test: `tests/cogtainer/test_config.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_config.py
"""Tests for cogtainer config loading."""
import os
import pytest
from pathlib import Path


def test_load_cogtainers_from_yaml(tmp_path):
    """Load cogtainers.yml and parse into typed config."""
    config_file = tmp_path / "cogtainers.yml"
    config_file.write_text("""
cogtainers:
  prod:
    type: aws
    region: us-east-1
    account_id: "901289084804"
    domain: softmax-cogents.com
    llm:
      provider: bedrock
      model: anthropic.claude-sonnet-4-20250514

  dev:
    type: local
    data_dir: /tmp/cogos-test/dev
    llm:
      provider: openrouter
      api_key_env: OPENROUTER_API_KEY
      model: anthropic/claude-sonnet-4

defaults:
  cogtainer: dev
""")
    from cogtainer.config import load_config

    cfg = load_config(config_file)
    assert len(cfg.cogtainers) == 2
    assert cfg.cogtainers["prod"].type == "aws"
    assert cfg.cogtainers["prod"].region == "us-east-1"
    assert cfg.cogtainers["prod"].llm.provider == "bedrock"
    assert cfg.cogtainers["dev"].type == "local"
    assert cfg.cogtainers["dev"].llm.provider == "openrouter"
    assert cfg.defaults.cogtainer == "dev"


def test_resolve_cogtainer_from_env(tmp_path, monkeypatch):
    """COGTAINER env var overrides defaults."""
    config_file = tmp_path / "cogtainers.yml"
    config_file.write_text("""
cogtainers:
  prod:
    type: aws
    region: us-east-1
    llm:
      provider: bedrock
      model: x
  dev:
    type: local
    data_dir: /tmp/test
    llm:
      provider: openrouter
      api_key_env: X
      model: y
defaults:
  cogtainer: dev
""")
    from cogtainer.config import load_config, resolve_cogtainer_name

    cfg = load_config(config_file)

    # Default
    assert resolve_cogtainer_name(cfg) == "dev"

    # Env override
    monkeypatch.setenv("COGTAINER", "prod")
    assert resolve_cogtainer_name(cfg) == "prod"


def test_resolve_auto_selects_single(tmp_path):
    """Auto-select when only one cogtainer exists."""
    config_file = tmp_path / "cogtainers.yml"
    config_file.write_text("""
cogtainers:
  only-one:
    type: local
    data_dir: /tmp/test
    llm:
      provider: openrouter
      api_key_env: X
      model: y
""")
    from cogtainer.config import load_config, resolve_cogtainer_name

    cfg = load_config(config_file)
    assert resolve_cogtainer_name(cfg) == "only-one"


def test_resolve_errors_on_ambiguous(tmp_path):
    """Error when multiple cogtainers and no default or env."""
    config_file = tmp_path / "cogtainers.yml"
    config_file.write_text("""
cogtainers:
  a:
    type: local
    data_dir: /tmp/a
    llm: {provider: openrouter, api_key_env: X, model: y}
  b:
    type: local
    data_dir: /tmp/b
    llm: {provider: openrouter, api_key_env: X, model: y}
""")
    from cogtainer.config import load_config, resolve_cogtainer_name

    cfg = load_config(config_file)
    with pytest.raises(ValueError, match="multiple"):
        resolve_cogtainer_name(cfg)


def test_resolve_cogent_name(tmp_path, monkeypatch):
    """Resolve cogent name from env or auto-select."""
    from cogtainer.config import resolve_cogent_name

    # From env
    monkeypatch.setenv("COGENT", "alpha")
    assert resolve_cogent_name(["alpha", "beta"]) == "alpha"

    # Auto-select single
    monkeypatch.delenv("COGENT")
    assert resolve_cogent_name(["only"]) == "only"

    # Error on ambiguous
    with pytest.raises(ValueError, match="multiple"):
        resolve_cogent_name(["a", "b"])


def test_empty_config_file(tmp_path):
    """Handle missing or empty config gracefully."""
    config_file = tmp_path / "cogtainers.yml"
    config_file.write_text("")
    from cogtainer.config import load_config

    cfg = load_config(config_file)
    assert len(cfg.cogtainers) == 0


def test_missing_config_file(tmp_path):
    """Return empty config when file doesn't exist."""
    from cogtainer.config import load_config

    cfg = load_config(tmp_path / "nonexistent.yml")
    assert len(cfg.cogtainers) == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogtainer.config'` (the new config module doesn't exist yet)

**Step 3: Write minimal implementation**

```python
# src/cogtainer/config.py
"""Cogtainer configuration: load and resolve cogtainer/cogent names."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG_PATH = Path.home() / ".cogos" / "cogtainers.yml"


class LLMConfig(BaseModel):
    provider: str = "bedrock"
    model: str = ""
    api_key_env: str = ""


class CogtainerEntry(BaseModel):
    type: str  # "aws", "local", "docker"
    region: str = "us-east-1"
    account_id: str = ""
    domain: str = ""
    data_dir: str = ""
    image: str = ""
    llm: LLMConfig = Field(default_factory=LLMConfig)


class DefaultsConfig(BaseModel):
    cogtainer: str = ""


class CogtainersConfig(BaseModel):
    cogtainers: dict[str, CogtainerEntry] = Field(default_factory=dict)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


def load_config(path: Path | None = None) -> CogtainersConfig:
    """Load cogtainers config from YAML file."""
    path = path or _DEFAULT_CONFIG_PATH
    if not path.is_file():
        return CogtainersConfig()
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw or not isinstance(raw, dict):
        return CogtainersConfig()
    return CogtainersConfig(**raw)


def resolve_cogtainer_name(
    cfg: CogtainersConfig,
    env_var: str = "COGTAINER",
) -> str:
    """Resolve active cogtainer name.

    Resolution order:
    1. Environment variable
    2. If only one cogtainer exists, use it
    3. Default from config
    4. Error
    """
    # 1. Env var
    env_name = os.environ.get(env_var)
    if env_name:
        if env_name not in cfg.cogtainers:
            raise ValueError(f"Cogtainer '{env_name}' not found in config")
        return env_name

    # 2. Auto-select single
    if len(cfg.cogtainers) == 1:
        return next(iter(cfg.cogtainers))

    # 3. Default from config
    if cfg.defaults.cogtainer:
        if cfg.defaults.cogtainer not in cfg.cogtainers:
            raise ValueError(
                f"Default cogtainer '{cfg.defaults.cogtainer}' not found in config"
            )
        return cfg.defaults.cogtainer

    # 4. Error
    names = ", ".join(sorted(cfg.cogtainers.keys()))
    raise ValueError(
        f"multiple cogtainers found ({names}), set COGTAINER env var or defaults.cogtainer in config"
    )


def resolve_cogent_name(
    available: list[str],
    env_var: str = "COGENT",
) -> str:
    """Resolve active cogent name.

    Resolution order:
    1. Environment variable
    2. If only one cogent exists, use it
    3. Error
    """
    env_name = os.environ.get(env_var)
    if env_name:
        return env_name

    if len(available) == 1:
        return available[0]

    if not available:
        raise ValueError("No cogents found in this cogtainer")

    names = ", ".join(sorted(available))
    raise ValueError(
        f"multiple cogents found ({names}), set COGENT env var"
    )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_config.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/cogtainer/config.py tests/cogtainer/test_config.py
git commit -m "feat(cogtainer): add cogtainers.yml config loader with name resolution"
```

---

### Task 2: LLM Provider Abstraction

**Files:**
- Create: `src/cogtainer/llm/__init__.py`
- Create: `src/cogtainer/llm/provider.py`
- Create: `src/cogtainer/llm/bedrock.py`
- Create: `src/cogtainer/llm/openrouter.py`
- Create: `src/cogtainer/llm/anthropic_provider.py`
- Test: `tests/cogtainer/test_llm_provider.py`

This task extracts the LLM abstraction from `src/cogos/executor/llm_client.py`. The existing `LLMClient` already handles Bedrock and Anthropic — we factor out a clean `LLMProvider` interface and add OpenRouter.

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_llm_provider.py
"""Tests for LLM provider abstraction."""
from unittest.mock import MagicMock, patch
import pytest


def test_provider_factory_bedrock():
    """Factory creates BedrockProvider for 'bedrock' type."""
    from cogtainer.llm.provider import create_provider
    from cogtainer.config import LLMConfig

    config = LLMConfig(provider="bedrock", model="us.anthropic.claude-sonnet-4-20250514-v1:0")
    provider = create_provider(config, region="us-east-1")
    assert provider is not None
    assert provider.default_model == config.model


def test_provider_factory_openrouter():
    """Factory creates OpenRouterProvider."""
    from cogtainer.llm.provider import create_provider
    from cogtainer.config import LLMConfig

    config = LLMConfig(provider="openrouter", model="anthropic/claude-sonnet-4", api_key_env="TEST_KEY")
    with patch.dict("os.environ", {"TEST_KEY": "sk-test-key"}):
        provider = create_provider(config)
    assert provider is not None
    assert provider.default_model == config.model


def test_provider_factory_anthropic():
    """Factory creates AnthropicProvider."""
    from cogtainer.llm.provider import create_provider
    from cogtainer.config import LLMConfig

    config = LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514", api_key_env="TEST_KEY")
    with patch.dict("os.environ", {"TEST_KEY": "sk-test-key"}):
        provider = create_provider(config)
    assert provider is not None


def test_provider_factory_unknown_raises():
    """Unknown provider type raises ValueError."""
    from cogtainer.llm.provider import create_provider
    from cogtainer.config import LLMConfig

    config = LLMConfig(provider="unknown", model="x")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_provider(config)


def test_bedrock_converse_delegates():
    """BedrockProvider.converse delegates to boto3 client."""
    from cogtainer.llm.bedrock import BedrockProvider

    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }
    provider = BedrockProvider(client=mock_client, default_model="test-model")
    result = provider.converse(
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        system=[{"text": "system prompt"}],
        tool_config={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hi"
    mock_client.converse.assert_called_once()


def test_openrouter_converse_format():
    """OpenRouterProvider formats request correctly."""
    from cogtainer.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-test", default_model="anthropic/claude-sonnet-4")

    # Mock the HTTP call
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "hello",
                "tool_calls": None,
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = provider.converse(
            messages=[{"role": "user", "content": [{"text": "hello"}]}],
            system=[{"text": "you are helpful"}],
            tool_config={"tools": []},
        )
    assert result["output"]["message"]["content"][0]["text"] == "hello"
    assert result["usage"]["inputTokens"] == 10
    # Verify OpenRouter-specific headers
    call_kwargs = mock_post.call_args
    assert "Authorization" in call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_llm_provider.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

```python
# src/cogtainer/llm/__init__.py
"""LLM provider abstraction for cogtainer."""

# src/cogtainer/llm/provider.py
"""LLM provider interface and factory."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from cogtainer.config import LLMConfig


class LLMProvider(ABC):
    """Abstract LLM provider — all cogos LLM calls go through this."""

    def __init__(self, default_model: str = "") -> None:
        self.default_model = default_model

    @abstractmethod
    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        """Call the LLM. Returns Bedrock-format response dict.

        All providers normalize their response to Bedrock converse format:
        {
            "output": {"message": {"role": "assistant", "content": [...]}},
            "stopReason": "end_turn" | "tool_use" | "max_tokens",
            "usage": {"inputTokens": int, "outputTokens": int},
        }
        """
        ...


def create_provider(config: LLMConfig, region: str = "us-east-1") -> LLMProvider:
    """Create an LLM provider from config."""
    if config.provider == "bedrock":
        from cogtainer.llm.bedrock import BedrockProvider
        return BedrockProvider.from_config(config, region=region)

    if config.provider == "openrouter":
        from cogtainer.llm.openrouter import OpenRouterProvider
        api_key = os.environ.get(config.api_key_env, "")
        return OpenRouterProvider(api_key=api_key, default_model=config.model)

    if config.provider == "anthropic":
        from cogtainer.llm.anthropic_provider import AnthropicProvider
        api_key = os.environ.get(config.api_key_env, "")
        return AnthropicProvider(api_key=api_key, default_model=config.model)

    raise ValueError(f"Unknown LLM provider: {config.provider}")


# src/cogtainer/llm/bedrock.py
"""Bedrock LLM provider."""
from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from cogtainer.config import LLMConfig
from cogtainer.llm.provider import LLMProvider


class BedrockProvider(LLMProvider):
    """AWS Bedrock converse API provider."""

    def __init__(self, *, client: Any, default_model: str = "") -> None:
        super().__init__(default_model=default_model)
        self._client = client

    @classmethod
    def from_config(cls, config: LLMConfig, region: str = "us-east-1") -> BedrockProvider:
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )
        return cls(client=client, default_model=config.model)

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "modelId": model or self.default_model,
            "messages": messages,
            "system": system,
            "toolConfig": tool_config,
        }
        return self._client.converse(**kwargs)


# src/cogtainer/llm/openrouter.py
"""OpenRouter LLM provider."""
from __future__ import annotations

import json
from typing import Any

import requests

from cogtainer.llm.provider import LLMProvider

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider — translates Bedrock format to/from OpenAI format."""

    def __init__(self, *, api_key: str, default_model: str = "") -> None:
        super().__init__(default_model=default_model)
        self._api_key = api_key

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        # Convert Bedrock messages to OpenAI format
        oai_messages = _bedrock_to_openai_messages(system, messages)
        tools = _bedrock_to_openai_tools(tool_config)

        body: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": oai_messages,
            "max_tokens": 16384,
        }
        if tools:
            body["tools"] = tools

        resp = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()

        return _openai_response_to_bedrock(data)


def _bedrock_to_openai_messages(
    system: list[dict], messages: list[dict]
) -> list[dict]:
    """Convert Bedrock converse messages to OpenAI chat format."""
    result: list[dict] = []

    # System message
    system_text = "\n\n".join(b.get("text", "") for b in system if "text" in b)
    if system_text:
        result.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", [])

        if role == "user":
            # Check for tool results
            tool_results = [b for b in content if "toolResult" in b]
            if tool_results:
                for tr_block in tool_results:
                    tr = tr_block["toolResult"]
                    tr_content = ""
                    for c in tr.get("content", []):
                        if "text" in c:
                            tr_content += c["text"]
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr["toolUseId"],
                        "content": tr_content,
                    })
            else:
                text = "\n".join(b.get("text", "") for b in content if "text" in b)
                result.append({"role": "user", "content": text})

        elif role == "assistant":
            text_parts = [b.get("text", "") for b in content if "text" in b]
            tool_uses = [b["toolUse"] for b in content if "toolUse" in b]

            msg_dict: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                msg_dict["content"] = "\n".join(text_parts)
            if tool_uses:
                msg_dict["tool_calls"] = [
                    {
                        "id": tu["toolUseId"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu.get("input", {})),
                        },
                    }
                    for tu in tool_uses
                ]
                if not text_parts:
                    msg_dict["content"] = ""
            result.append(msg_dict)

    return result


def _bedrock_to_openai_tools(tool_config: dict) -> list[dict]:
    """Convert Bedrock toolConfig to OpenAI tools format."""
    tools = []
    for tool in tool_config.get("tools", []):
        spec = tool.get("toolSpec", {})
        tools.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec.get("inputSchema", {}).get("json", {}),
            },
        })
    return tools


def _openai_response_to_bedrock(data: dict) -> dict:
    """Convert OpenAI chat completion response to Bedrock converse format."""
    choice = data["choices"][0]
    message = choice["message"]
    content: list[dict] = []

    if message.get("content"):
        content.append({"text": message["content"]})

    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc["function"]
        try:
            tool_input = json.loads(fn["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_input = {"raw": fn.get("arguments", "")}
        content.append({
            "toolUse": {
                "toolUseId": tc["id"],
                "name": fn["name"],
                "input": tool_input,
            },
        })

    finish_reason = choice.get("finish_reason", "stop")
    stop_reason_map = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
    }

    usage = data.get("usage", {})

    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": content,
            },
        },
        "stopReason": stop_reason_map.get(finish_reason, "end_turn"),
        "usage": {
            "inputTokens": usage.get("prompt_tokens", 0),
            "outputTokens": usage.get("completion_tokens", 0),
        },
    }


# src/cogtainer/llm/anthropic_provider.py
"""Anthropic direct API provider."""
from __future__ import annotations

from typing import Any

from cogtainer.llm.provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """Direct Anthropic Messages API provider.

    Reuses conversion helpers from cogos.executor.llm_client.
    """

    def __init__(self, *, api_key: str, default_model: str = "") -> None:
        super().__init__(default_model=default_model)
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        from cogos.executor.llm_client import (
            _anthropic_response_to_bedrock,
            _bedrock_messages_to_anthropic,
            _bedrock_model_to_anthropic,
            _bedrock_tools_to_anthropic,
        )

        model_name = model or self.default_model
        # Try to convert Bedrock model ID to Anthropic name
        try:
            model_name = _bedrock_model_to_anthropic(model_name)
        except Exception:
            pass

        api_messages = _bedrock_messages_to_anthropic(messages)
        system_text = "\n\n".join(b["text"] for b in system if "text" in b)
        tools = _bedrock_tools_to_anthropic(tool_config)

        api_kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": 16384,
            "messages": api_messages,
        }
        if system_text:
            api_kwargs["system"] = system_text
        if tools:
            api_kwargs["tools"] = tools

        response = self._client.messages.create(**api_kwargs)
        return _anthropic_response_to_bedrock(response)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_llm_provider.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/cogtainer/llm/ tests/cogtainer/test_llm_provider.py
git commit -m "feat(cogtainer): add LLM provider abstraction (Bedrock, OpenRouter, Anthropic)"
```

---

### Task 3: CogtainerRuntime Interface + LocalRuntime

**Files:**
- Create: `src/cogtainer/runtime/__init__.py`
- Create: `src/cogtainer/runtime/base.py`
- Create: `src/cogtainer/runtime/local.py`
- Test: `tests/cogtainer/test_runtime_local.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_runtime_local.py
"""Tests for local cogtainer runtime."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_local_runtime_get_repository(tmp_path):
    """LocalRuntime returns a LocalRepository for a cogent."""
    from cogtainer.runtime.local import LocalRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(
        type="local",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="X", model="y"),
    )
    runtime = LocalRuntime(entry, llm_provider=MagicMock())
    repo = runtime.get_repository("alpha")
    # Should be a LocalRepository instance
    from cogos.db.local_repository import LocalRepository
    assert isinstance(repo, LocalRepository)


def test_local_runtime_file_storage(tmp_path):
    """LocalRuntime stores/retrieves files on local disk."""
    from cogtainer.runtime.local import LocalRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(
        type="local",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="X", model="y"),
    )
    runtime = LocalRuntime(entry, llm_provider=MagicMock())

    # Put and get
    runtime.put_file("alpha", "test/key.txt", b"hello world")
    data = runtime.get_file("alpha", "test/key.txt")
    assert data == b"hello world"


def test_local_runtime_converse_delegates():
    """LocalRuntime.converse delegates to LLM provider."""
    from cogtainer.runtime.local import LocalRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    mock_llm = MagicMock()
    mock_llm.converse.return_value = {"output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}}}

    entry = CogtainerEntry(
        type="local",
        data_dir="/tmp/test",
        llm=LLMConfig(provider="openrouter", api_key_env="X", model="y"),
    )
    runtime = LocalRuntime(entry, llm_provider=mock_llm)
    result = runtime.converse(
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        system=[{"text": "sys"}],
        tool_config={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hi"
    mock_llm.converse.assert_called_once()


def test_local_runtime_list_cogents(tmp_path):
    """LocalRuntime lists cogents by scanning data directories."""
    from cogtainer.runtime.local import LocalRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(
        type="local",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="X", model="y"),
    )
    runtime = LocalRuntime(entry, llm_provider=MagicMock())

    # No cogents yet
    assert runtime.list_cogents() == []

    # Create a cogent
    runtime.create_cogent("alpha")
    assert "alpha" in runtime.list_cogents()

    # Create another
    runtime.create_cogent("beta")
    assert sorted(runtime.list_cogents()) == ["alpha", "beta"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_runtime_local.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

```python
# src/cogtainer/runtime/__init__.py
"""Cogtainer runtime implementations."""

# src/cogtainer/runtime/base.py
"""CogtainerRuntime — abstract interface between cogos and infrastructure."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CogtainerRuntime(ABC):
    """Abstract runtime that cogos depends on. Hides AWS/local/docker details."""

    @abstractmethod
    def get_repository(self, cogent_name: str) -> Any:
        """Get the database repository for a cogent."""
        ...

    @abstractmethod
    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        """Call the LLM. Returns Bedrock-format response."""
        ...

    @abstractmethod
    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        """Store a file. Returns the storage key."""
        ...

    @abstractmethod
    def get_file(self, cogent_name: str, key: str) -> bytes:
        """Retrieve a file by key."""
        ...

    @abstractmethod
    def emit_event(self, cogent_name: str, event: dict) -> None:
        """Emit an event for routing."""
        ...

    @abstractmethod
    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        """Spawn an executor for a process."""
        ...

    @abstractmethod
    def list_cogents(self) -> list[str]:
        """List cogent names in this cogtainer."""
        ...

    @abstractmethod
    def create_cogent(self, name: str) -> None:
        """Create a new cogent in this cogtainer."""
        ...

    @abstractmethod
    def destroy_cogent(self, name: str) -> None:
        """Destroy a cogent and its data."""
        ...


# src/cogtainer/runtime/local.py
"""Local cogtainer runtime — file-backed, subprocess execution."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)


class LocalRuntime(CogtainerRuntime):
    """Runtime backed by local filesystem and subprocesses."""

    def __init__(self, entry: CogtainerEntry, llm_provider: LLMProvider) -> None:
        self._entry = entry
        self._llm = llm_provider
        self._data_dir = Path(entry.data_dir).expanduser()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._repos: dict[str, Any] = {}

    def _cogent_dir(self, cogent_name: str) -> Path:
        d = self._data_dir / cogent_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_repository(self, cogent_name: str) -> Any:
        if cogent_name not in self._repos:
            from cogos.db.local_repository import LocalRepository
            cogent_dir = self._cogent_dir(cogent_name)
            os.environ["LOCAL_DB_DIR"] = str(cogent_dir)
            self._repos[cogent_name] = LocalRepository()
        return self._repos[cogent_name]

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        return self._llm.converse(
            messages=messages,
            system=system,
            tool_config=tool_config,
            model=model,
        )

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        file_path = self._cogent_dir(cogent_name) / "files" / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        file_path = self._cogent_dir(cogent_name) / "files" / key
        return file_path.read_bytes()

    def emit_event(self, cogent_name: str, event: dict) -> None:
        # Local: directly invoke the event router
        logger.info("Local event: %s -> %s", cogent_name, event.get("event_type", "?"))

    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        """Spawn executor as a subprocess."""
        env = {
            **os.environ,
            "COGTAINER": self._entry.type,
            "COGENT": cogent_name,
            "USE_LOCAL_DB": "1",
            "LOCAL_DB_DIR": str(self._cogent_dir(cogent_name)),
        }
        subprocess.Popen(
            [sys.executable, "-m", "cogos.executor.handler"],
            env=env,
        )

    def list_cogents(self) -> list[str]:
        if not self._data_dir.exists():
            return []
        return sorted(
            d.name for d in self._data_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def create_cogent(self, name: str) -> None:
        cogent_dir = self._cogent_dir(name)
        cogent_dir.mkdir(parents=True, exist_ok=True)
        (cogent_dir / "files").mkdir(exist_ok=True)

    def destroy_cogent(self, name: str) -> None:
        cogent_dir = self._data_dir / name
        if cogent_dir.exists():
            shutil.rmtree(cogent_dir)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_runtime_local.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/cogtainer/runtime/ tests/cogtainer/test_runtime_local.py
git commit -m "feat(cogtainer): add CogtainerRuntime interface and LocalRuntime implementation"
```

---

### Task 4: AwsRuntime

**Files:**
- Create: `src/cogtainer/runtime/aws.py`
- Test: `tests/cogtainer/test_runtime_aws.py`

This wraps the existing AWS infrastructure access (RDS Data API, S3, EventBridge, Lambda) behind the CogtainerRuntime interface. Most of the logic already exists in `polis/aws.py`, `cogos/db/repository.py`, etc. — this just wraps it.

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_runtime_aws.py
"""Tests for AWS cogtainer runtime (mocked)."""
from unittest.mock import MagicMock, patch
import pytest


def test_aws_runtime_converse_delegates():
    """AwsRuntime.converse delegates to LLM provider."""
    from cogtainer.runtime.aws import AwsRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    mock_llm = MagicMock()
    mock_llm.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }

    entry = CogtainerEntry(
        type="aws",
        region="us-east-1",
        account_id="123456789",
        domain="test.com",
        llm=LLMConfig(provider="bedrock", model="test-model"),
    )
    runtime = AwsRuntime(entry, llm_provider=mock_llm, session=MagicMock())
    result = runtime.converse(
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        system=[{"text": "sys"}],
        tool_config={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hi"


def test_aws_runtime_list_cogents():
    """AwsRuntime.list_cogents queries DynamoDB."""
    from cogtainer.runtime.aws import AwsRuntime
    from cogtainer.config import CogtainerEntry, LLMConfig

    mock_session = MagicMock()
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        "Items": [
            {"cogent_name": "alpha"},
            {"cogent_name": "beta"},
        ],
    }
    mock_session.resource.return_value.Table.return_value = mock_table

    entry = CogtainerEntry(
        type="aws",
        region="us-east-1",
        llm=LLMConfig(provider="bedrock", model="x"),
    )
    runtime = AwsRuntime(entry, llm_provider=MagicMock(), session=mock_session)
    assert sorted(runtime.list_cogents()) == ["alpha", "beta"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_runtime_aws.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/runtime/aws.py
"""AWS cogtainer runtime — RDS, S3, EventBridge, Lambda."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)


class AwsRuntime(CogtainerRuntime):
    """Runtime backed by AWS services (RDS Data API, S3, EventBridge, Lambda)."""

    def __init__(
        self,
        entry: CogtainerEntry,
        llm_provider: LLMProvider,
        session: Any,
    ) -> None:
        self._entry = entry
        self._llm = llm_provider
        self._session = session
        self._repos: dict[str, Any] = {}

    def _safe_name(self, cogent_name: str) -> str:
        return cogent_name.replace(".", "-")

    def _db_name(self, cogent_name: str) -> str:
        return f"cogent_{self._safe_name(cogent_name).replace('-', '_')}"

    def get_repository(self, cogent_name: str) -> Any:
        if cogent_name not in self._repos:
            from cogos.db.repository import Repository

            # Look up DB ARNs from DynamoDB
            ddb = self._session.resource("dynamodb", region_name=self._entry.region)
            item = ddb.Table("cogent-status").get_item(
                Key={"cogent_name": cogent_name}
            ).get("Item", {})
            db_info = item.get("database", {})

            self._repos[cogent_name] = Repository.create(
                resource_arn=db_info.get("cluster_arn", ""),
                secret_arn=db_info.get("secret_arn", ""),
                database=db_info.get("db_name", self._db_name(cogent_name)),
                region=self._entry.region,
            )
        return self._repos[cogent_name]

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        return self._llm.converse(
            messages=messages,
            system=system,
            tool_config=tool_config,
            model=model,
        )

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        from polis import naming
        bucket = naming.bucket_name(cogent_name)
        s3 = self._session.client("s3", region_name=self._entry.region)
        s3.put_object(Bucket=bucket, Key=key, Body=data)
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        from polis import naming
        bucket = naming.bucket_name(cogent_name)
        s3 = self._session.client("s3", region_name=self._entry.region)
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def emit_event(self, cogent_name: str, event: dict) -> None:
        eb = self._session.client("events", region_name=self._entry.region)
        safe = self._safe_name(cogent_name)
        eb.put_events(
            Entries=[{
                "EventBusName": f"cogent-{safe}",
                "Source": event.get("source", "cogos"),
                "DetailType": event.get("event_type", "custom"),
                "Detail": json.dumps(event),
            }]
        )

    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        safe = self._safe_name(cogent_name)
        fn_name = f"cogent-{safe}-executor"
        lam = self._session.client("lambda", region_name=self._entry.region)
        lam.invoke(
            FunctionName=fn_name,
            InvocationType="Event",
            Payload=json.dumps({"process_id": process_id}).encode(),
        )

    def list_cogents(self) -> list[str]:
        ddb = self._session.resource("dynamodb", region_name=self._entry.region)
        table = ddb.Table("cogent-status")
        items = table.scan().get("Items", [])
        return sorted(item["cogent_name"] for item in items if "cogent_name" in item)

    def create_cogent(self, name: str) -> None:
        # AWS cogent creation is handled by CDK — this is a placeholder
        # The real implementation will call _deploy_cogent_stack
        raise NotImplementedError("AWS cogent creation requires CDK deploy — use 'cogent create' CLI")

    def destroy_cogent(self, name: str) -> None:
        raise NotImplementedError("AWS cogent destruction requires CDK destroy — use 'cogent destroy' CLI")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_runtime_aws.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/cogtainer/runtime/aws.py tests/cogtainer/test_runtime_aws.py
git commit -m "feat(cogtainer): add AwsRuntime wrapping existing AWS services"
```

---

### Task 5: Runtime Factory

**Files:**
- Create: `src/cogtainer/runtime/factory.py`
- Test: `tests/cogtainer/test_runtime_factory.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_runtime_factory.py
"""Tests for runtime factory."""
from unittest.mock import patch, MagicMock
import pytest


def test_create_local_runtime(tmp_path):
    """Factory creates LocalRuntime for 'local' type."""
    from cogtainer.runtime.factory import create_runtime
    from cogtainer.config import CogtainerEntry, LLMConfig
    from cogtainer.runtime.local import LocalRuntime

    entry = CogtainerEntry(
        type="local",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="TEST_KEY", model="test"),
    )
    with patch.dict("os.environ", {"TEST_KEY": "sk-test"}):
        runtime = create_runtime(entry)
    assert isinstance(runtime, LocalRuntime)


def test_create_docker_runtime(tmp_path):
    """Factory creates LocalRuntime for 'docker' type (same impl)."""
    from cogtainer.runtime.factory import create_runtime
    from cogtainer.config import CogtainerEntry, LLMConfig
    from cogtainer.runtime.local import LocalRuntime

    entry = CogtainerEntry(
        type="docker",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="TEST_KEY", model="test"),
    )
    with patch.dict("os.environ", {"TEST_KEY": "sk-test"}):
        runtime = create_runtime(entry)
    assert isinstance(runtime, LocalRuntime)


def test_create_unknown_type_raises():
    """Unknown type raises ValueError."""
    from cogtainer.runtime.factory import create_runtime
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(type="unknown", llm=LLMConfig(provider="bedrock", model="x"))
    with pytest.raises(ValueError, match="Unknown cogtainer type"):
        create_runtime(entry)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_runtime_factory.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/runtime/factory.py
"""Runtime factory — creates the right runtime from config."""
from __future__ import annotations

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import create_provider
from cogtainer.runtime.base import CogtainerRuntime


def create_runtime(entry: CogtainerEntry) -> CogtainerRuntime:
    """Create a runtime from a cogtainer config entry."""
    llm = create_provider(entry.llm, region=entry.region)

    if entry.type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime
        return LocalRuntime(entry, llm_provider=llm)

    if entry.type == "aws":
        from cogtainer.runtime.aws import AwsRuntime
        from polis.aws import get_polis_session
        session, _ = get_polis_session()
        return AwsRuntime(entry, llm_provider=llm, session=session)

    raise ValueError(f"Unknown cogtainer type: {entry.type}")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_runtime_factory.py -v`

**Step 5: Commit**

```bash
git add src/cogtainer/runtime/factory.py tests/cogtainer/test_runtime_factory.py
git commit -m "feat(cogtainer): add runtime factory for creating runtimes from config"
```

---

### Task 6: `cogtainer` CLI

**Files:**
- Create: `src/cogtainer/cogtainer_cli.py`
- Test: `tests/cogtainer/test_cogtainer_cli.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_cogtainer_cli.py
"""Tests for cogtainer CLI."""
import pytest
from click.testing import CliRunner


def test_cogtainer_create_local(tmp_path, monkeypatch):
    """cogtainer create creates a local cogtainer entry."""
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    from cogtainer.cogtainer_cli import cogtainer

    runner = CliRunner()
    result = runner.invoke(cogtainer, [
        "create", "dev", "--type", "local",
        "--llm-provider", "openrouter",
        "--llm-model", "anthropic/claude-sonnet-4",
        "--data-dir", str(tmp_path / "data"),
    ])
    assert result.exit_code == 0, result.output

    # Verify config was written
    from cogtainer.config import load_config
    cfg = load_config(config_path)
    assert "dev" in cfg.cogtainers
    assert cfg.cogtainers["dev"].type == "local"
    assert cfg.cogtainers["dev"].llm.provider == "openrouter"


def test_cogtainer_list_empty(tmp_path, monkeypatch):
    """cogtainer list with no config shows empty."""
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    from cogtainer.cogtainer_cli import cogtainer

    runner = CliRunner()
    result = runner.invoke(cogtainer, ["list"])
    assert result.exit_code == 0
    assert "No cogtainers" in result.output


def test_cogtainer_list_shows_entries(tmp_path, monkeypatch):
    """cogtainer list shows configured cogtainers."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text("""
cogtainers:
  dev:
    type: local
    data_dir: /tmp/dev
    llm: {provider: openrouter, api_key_env: X, model: y}
  prod:
    type: aws
    region: us-east-1
    llm: {provider: bedrock, model: z}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    from cogtainer.cogtainer_cli import cogtainer

    runner = CliRunner()
    result = runner.invoke(cogtainer, ["list"])
    assert result.exit_code == 0
    assert "dev" in result.output
    assert "prod" in result.output


def test_cogtainer_destroy(tmp_path, monkeypatch):
    """cogtainer destroy removes entry from config."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text("""
cogtainers:
  dev:
    type: local
    data_dir: /tmp/dev
    llm: {provider: openrouter, api_key_env: X, model: y}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    from cogtainer.cogtainer_cli import cogtainer

    runner = CliRunner()
    result = runner.invoke(cogtainer, ["destroy", "dev"], input="y\n")
    assert result.exit_code == 0

    from cogtainer.config import load_config
    cfg = load_config(config_path)
    assert "dev" not in cfg.cogtainers
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_cogtainer_cli.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/cogtainer_cli.py
"""cogtainer CLI — manage cogtainer lifecycle."""
from __future__ import annotations

import os
from pathlib import Path

import click
import yaml

from cogtainer.config import (
    CogtainerEntry,
    CogtainersConfig,
    DefaultsConfig,
    LLMConfig,
    load_config,
)


def _config_path() -> Path:
    env = os.environ.get("COGOS_CONFIG_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cogos" / "cogtainers.yml"


def _save_config(cfg: CogtainersConfig, path: Path | None = None) -> None:
    path = path or _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"cogtainers": {}}
    for name, entry in cfg.cogtainers.items():
        data["cogtainers"][name] = entry.model_dump(exclude_defaults=False)
    if cfg.defaults.cogtainer:
        data["defaults"] = {"cogtainer": cfg.defaults.cogtainer}
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load() -> CogtainersConfig:
    return load_config(_config_path())


@click.group()
def cogtainer():
    """Manage cogtainer lifecycle."""
    pass


@cogtainer.command("create")
@click.argument("name")
@click.option("--type", "ctype", required=True, type=click.Choice(["aws", "local", "docker"]))
@click.option("--llm-provider", default="bedrock", help="LLM provider (bedrock, openrouter, anthropic)")
@click.option("--llm-model", default="", help="LLM model identifier")
@click.option("--llm-api-key-env", default="", help="Env var containing API key")
@click.option("--region", default="us-east-1", help="AWS region (for aws type)")
@click.option("--data-dir", default="", help="Data directory (for local/docker)")
@click.option("--domain", default="", help="Domain (for aws type)")
def create_cmd(
    name: str,
    ctype: str,
    llm_provider: str,
    llm_model: str,
    llm_api_key_env: str,
    region: str,
    data_dir: str,
    domain: str,
):
    """Create a new cogtainer."""
    cfg = _load()

    if name in cfg.cogtainers:
        raise click.ClickException(f"Cogtainer '{name}' already exists")

    if ctype in ("local", "docker") and not data_dir:
        data_dir = str(Path.home() / ".cogos" / "cogtainers" / name)

    entry = CogtainerEntry(
        type=ctype,
        region=region,
        domain=domain,
        data_dir=data_dir,
        llm=LLMConfig(
            provider=llm_provider,
            model=llm_model,
            api_key_env=llm_api_key_env,
        ),
    )
    cfg.cogtainers[name] = entry

    # Set as default if it's the only one
    if len(cfg.cogtainers) == 1:
        cfg.defaults = DefaultsConfig(cogtainer=name)

    _save_config(cfg)

    # For local/docker, create the data directory
    if ctype in ("local", "docker"):
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    click.echo(f"Cogtainer '{name}' created ({ctype})")


@cogtainer.command("destroy")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure?")
def destroy_cmd(name: str):
    """Destroy a cogtainer."""
    cfg = _load()

    if name not in cfg.cogtainers:
        raise click.ClickException(f"Cogtainer '{name}' not found")

    del cfg.cogtainers[name]

    if cfg.defaults.cogtainer == name:
        cfg.defaults = DefaultsConfig()

    _save_config(cfg)
    click.echo(f"Cogtainer '{name}' destroyed")


@cogtainer.command("list")
def list_cmd():
    """List all cogtainers."""
    cfg = _load()

    if not cfg.cogtainers:
        click.echo("No cogtainers configured.")
        return

    for name, entry in sorted(cfg.cogtainers.items()):
        default = " (default)" if name == cfg.defaults.cogtainer else ""
        click.echo(f"  {name}: {entry.type} [{entry.llm.provider}]{default}")


@cogtainer.command("status")
@click.argument("name", required=False)
def status_cmd(name: str | None):
    """Show cogtainer status."""
    cfg = _load()

    if name is None:
        from cogtainer.config import resolve_cogtainer_name
        name = resolve_cogtainer_name(cfg)

    if name not in cfg.cogtainers:
        raise click.ClickException(f"Cogtainer '{name}' not found")

    entry = cfg.cogtainers[name]
    click.echo(f"Cogtainer: {name}")
    click.echo(f"  Type: {entry.type}")
    click.echo(f"  LLM: {entry.llm.provider} ({entry.llm.model})")
    if entry.data_dir:
        click.echo(f"  Data: {entry.data_dir}")
    if entry.region:
        click.echo(f"  Region: {entry.region}")
    if entry.domain:
        click.echo(f"  Domain: {entry.domain}")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_cogtainer_cli.py -v`

**Step 5: Register CLI entry point**

In `pyproject.toml`, add under `[project.scripts]`:
```
cogtainer = "cogtainer.cogtainer_cli:cogtainer"
```

**Step 6: Commit**

```bash
git add src/cogtainer/cogtainer_cli.py tests/cogtainer/test_cogtainer_cli.py pyproject.toml
git commit -m "feat(cogtainer): add cogtainer CLI (create, destroy, list, status)"
```

---

### Task 7: `cogent` CLI

**Files:**
- Create: `src/cogtainer/cogent_cli.py`
- Test: `tests/cogtainer/test_cogent_cli.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_cogent_cli.py
"""Tests for cogent CLI."""
import pytest
from click.testing import CliRunner


def test_cogent_create_local(tmp_path, monkeypatch):
    """cogent create creates a cogent in a local cogtainer."""
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    config_path.write_text(f"""
cogtainers:
  dev:
    type: local
    data_dir: {data_dir}
    llm: {{provider: openrouter, api_key_env: TEST_KEY, model: test}}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TEST_KEY", "sk-test")

    from cogtainer.cogent_cli import cogent

    runner = CliRunner()
    result = runner.invoke(cogent, ["create", "alpha"])
    assert result.exit_code == 0, result.output
    assert (data_dir / "alpha").is_dir()


def test_cogent_list_local(tmp_path, monkeypatch):
    """cogent list shows cogents in a local cogtainer."""
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "alpha").mkdir()
    (data_dir / "beta").mkdir()
    config_path.write_text(f"""
cogtainers:
  dev:
    type: local
    data_dir: {data_dir}
    llm: {{provider: openrouter, api_key_env: TEST_KEY, model: test}}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TEST_KEY", "sk-test")

    from cogtainer.cogent_cli import cogent

    runner = CliRunner()
    result = runner.invoke(cogent, ["list"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output


def test_cogent_destroy_local(tmp_path, monkeypatch):
    """cogent destroy removes a cogent directory."""
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "alpha").mkdir()
    config_path.write_text(f"""
cogtainers:
  dev:
    type: local
    data_dir: {data_dir}
    llm: {{provider: openrouter, api_key_env: TEST_KEY, model: test}}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TEST_KEY", "sk-test")

    from cogtainer.cogent_cli import cogent

    runner = CliRunner()
    result = runner.invoke(cogent, ["destroy", "alpha"], input="y\n")
    assert result.exit_code == 0
    assert not (data_dir / "alpha").exists()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_cogent_cli.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/cogent_cli.py
"""cogent CLI — manage cogent lifecycle within a cogtainer."""
from __future__ import annotations

import click

from cogtainer.config import load_config, resolve_cogtainer_name
from cogtainer.cogtainer_cli import _config_path
from cogtainer.runtime.factory import create_runtime


def _get_runtime():
    """Load config, resolve cogtainer, create runtime."""
    cfg = load_config(_config_path())
    name = resolve_cogtainer_name(cfg)
    entry = cfg.cogtainers[name]
    return create_runtime(entry), name


@click.group()
def cogent():
    """Manage cogents within a cogtainer."""
    pass


@cogent.command("create")
@click.argument("name")
def create_cmd(name: str):
    """Create a new cogent."""
    runtime, cogtainer_name = _get_runtime()
    runtime.create_cogent(name)
    click.echo(f"Cogent '{name}' created in cogtainer '{cogtainer_name}'")


@cogent.command("destroy")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure?")
def destroy_cmd(name: str):
    """Destroy a cogent and its data."""
    runtime, cogtainer_name = _get_runtime()
    runtime.destroy_cogent(name)
    click.echo(f"Cogent '{name}' destroyed from cogtainer '{cogtainer_name}'")


@cogent.command("list")
def list_cmd():
    """List cogents in the active cogtainer."""
    runtime, cogtainer_name = _get_runtime()
    cogents = runtime.list_cogents()
    if not cogents:
        click.echo(f"No cogents in cogtainer '{cogtainer_name}'")
        return
    click.echo(f"Cogents in '{cogtainer_name}':")
    for name in cogents:
        click.echo(f"  {name}")


@cogent.command("status")
@click.argument("name", required=False)
def status_cmd(name: str | None):
    """Show cogent status."""
    runtime, cogtainer_name = _get_runtime()
    cogents = runtime.list_cogents()

    if name is None:
        from cogtainer.config import resolve_cogent_name
        name = resolve_cogent_name(cogents)

    if name not in cogents:
        raise click.ClickException(f"Cogent '{name}' not found in cogtainer '{cogtainer_name}'")

    click.echo(f"Cogent: {name} (in {cogtainer_name})")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_cogent_cli.py -v`

**Step 5: Register CLI entry point**

In `pyproject.toml`, add under `[project.scripts]`:
```
cogent = "cogtainer.cogent_cli:cogent"
```

**Step 6: Commit**

```bash
git add src/cogtainer/cogent_cli.py tests/cogtainer/test_cogent_cli.py pyproject.toml
git commit -m "feat(cogtainer): add cogent CLI (create, destroy, list, status)"
```

---

### Task 8: EventRouter (rename of orchestrator)

**Files:**
- Create: `src/cogtainer/event_router.py`
- Test: `tests/cogtainer/test_event_router.py`

This extracts the core event-matching logic from `src/cogtainer/lambdas/orchestrator/handler.py` into a runtime-agnostic module. The Lambda handler becomes a thin wrapper.

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_event_router.py
"""Tests for EventRouter — runtime-agnostic event matching and dispatch."""
from unittest.mock import MagicMock
import pytest


def test_match_exact_pattern():
    """Exact pattern matches exact event type."""
    from cogtainer.event_router import match_pattern
    assert match_pattern("discord:message", "discord:message") is True
    assert match_pattern("discord:message", "discord:reaction") is False


def test_match_glob_pattern():
    """Glob pattern matches event types with prefix."""
    from cogtainer.event_router import match_pattern
    assert match_pattern("discord:*", "discord:message") is True
    assert match_pattern("discord:*", "discord:reaction") is True
    assert match_pattern("discord:*", "email:received") is False


def test_route_event_matches_triggers():
    """route_event matches triggers and returns dispatch list."""
    from cogtainer.event_router import EventRouter

    mock_repo = MagicMock()
    mock_trigger = MagicMock()
    mock_trigger.event_pattern = "discord:*"
    mock_trigger.program_name = "handler"
    mock_trigger.id = "trigger-1"
    mock_trigger.config.max_events = 0
    mock_repo.list_triggers.return_value = [mock_trigger]
    mock_repo.get_program.return_value = MagicMock(runner="lambda")

    mock_runtime = MagicMock()

    router = EventRouter(repo=mock_repo, runtime=mock_runtime)
    result = router.route_event(
        event_type="discord:message",
        source="discord-bridge",
        payload={"content": "hello"},
    )
    assert len(result) == 1
    assert result[0]["program_name"] == "handler"


def test_route_event_cascade_guard():
    """Don't let a program's output re-trigger itself."""
    from cogtainer.event_router import EventRouter

    mock_repo = MagicMock()
    mock_trigger = MagicMock()
    mock_trigger.event_pattern = "discord:*"
    mock_trigger.program_name = "handler"
    mock_trigger.id = "trigger-1"
    mock_trigger.config.max_events = 0
    mock_repo.list_triggers.return_value = [mock_trigger]

    router = EventRouter(repo=mock_repo, runtime=MagicMock())
    result = router.route_event(
        event_type="discord:message",
        source="handler",  # same as program_name
        payload={},
    )
    assert len(result) == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_event_router.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/event_router.py
"""EventRouter — matches events to triggers and dispatches executors.

Runtime-agnostic: works with any CogtainerRuntime implementation.
Extracted from the orchestrator Lambda handler.
"""
from __future__ import annotations

import logging
from typing import Any

from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)


def match_pattern(pattern: str, event_type: str) -> bool:
    """Match event type against trigger pattern. Supports * glob at end."""
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


class EventRouter:
    """Matches events against triggers and dispatches executors."""

    def __init__(self, repo: Any, runtime: CogtainerRuntime) -> None:
        self._repo = repo
        self._runtime = runtime

    def route_event(
        self,
        event_type: str,
        source: str,
        payload: dict,
    ) -> list[dict]:
        """Match event against triggers and return list of programs to dispatch.

        Returns list of dicts with keys: program_name, trigger_id, payload.
        Does NOT dispatch — caller is responsible for spawning executors.
        """
        triggers = self._repo.list_triggers(enabled_only=True)
        matched = [t for t in triggers if match_pattern(t.event_pattern, event_type)]

        if not matched:
            return []

        dispatches: list[dict] = []
        for trigger in matched:
            # Cascade guard
            if source and source == trigger.program_name:
                logger.info("Skipping cascade: %s triggered by itself", trigger.program_name)
                continue

            # Throttle check
            if trigger.config.max_events > 0:
                result = self._repo.throttle_check(
                    trigger.id, trigger.config.max_events, trigger.config.throttle_window_seconds
                )
                if not result.allowed:
                    logger.info("Throttled trigger %s for %s", trigger.id, trigger.program_name)
                    continue

            # Verify program exists
            program = self._repo.get_program(trigger.program_name)
            if not program:
                logger.warning("Program not found: %s", trigger.program_name)
                continue

            dispatches.append({
                "program_name": trigger.program_name,
                "trigger_id": str(trigger.id),
                "payload": payload,
                "runner": program.runner or "lambda",
            })

        return dispatches
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_event_router.py -v`

**Step 5: Commit**

```bash
git add src/cogtainer/event_router.py tests/cogtainer/test_event_router.py
git commit -m "feat(cogtainer): add EventRouter — runtime-agnostic event matching"
```

---

### Task 9: Local Dispatcher (cogos start)

**Files:**
- Create: `src/cogtainer/local_dispatcher.py`
- Test: `tests/cogtainer/test_local_dispatcher.py`

The local dispatcher runs as a long-lived process, ticking every 60 seconds like the Lambda dispatcher. It reuses the existing scheduler logic from `cogos.runtime.schedule` and `cogos.capabilities.scheduler`.

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_local_dispatcher.py
"""Tests for local dispatcher."""
from unittest.mock import MagicMock, patch
import pytest


def test_single_tick(tmp_path):
    """A single dispatcher tick runs scheduler logic."""
    from cogtainer.local_dispatcher import run_tick
    from cogtainer.config import CogtainerEntry, LLMConfig
    from cogtainer.runtime.local import LocalRuntime

    entry = CogtainerEntry(
        type="local",
        data_dir=str(tmp_path),
        llm=LLMConfig(provider="openrouter", api_key_env="X", model="y"),
    )
    runtime = LocalRuntime(entry, llm_provider=MagicMock())
    runtime.create_cogent("test")
    repo = runtime.get_repository("test")

    # Should not raise
    result = run_tick(repo, runtime, cogent_name="test")
    assert result["dispatched"] >= 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_local_dispatcher.py -v`

**Step 3: Write minimal implementation**

```python
# src/cogtainer/local_dispatcher.py
"""Local dispatcher — long-lived process that ticks every 60s.

Equivalent of the dispatcher Lambda but runs as a local process.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)

_TICK_INTERVAL = 60  # seconds
_THROTTLE_COOLDOWN_MS = 300_000


def run_tick(repo: Any, runtime: CogtainerRuntime, cogent_name: str) -> dict:
    """Run a single dispatcher tick. Returns dict with dispatch count."""
    from cogos.capabilities.scheduler import SchedulerCapability
    from cogos.runtime.schedule import apply_scheduled_messages

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))

    # Heartbeat
    try:
        repo.set_meta("scheduler:last_tick")
        repo.set_meta("state:modified_at")
    except Exception:
        pass

    # Reap stale runs
    try:
        reaped = repo.timeout_stale_runs(max_age_ms=900_000)
        if reaped:
            logger.warning("Reaped %s stale runs", reaped)
    except Exception:
        pass

    # Throttle check
    try:
        from cogos.db.models import RunStatus
        recent = repo.list_recent_failed_runs(max_age_ms=_THROTTLE_COOLDOWN_MS)
        if any(r.status == RunStatus.THROTTLED for r in recent):
            logger.info("Throttle cooldown active — skipping dispatch")
            return {"dispatched": 0, "throttle_cooldown": True}
    except Exception:
        pass

    # System ticks
    try:
        apply_scheduled_messages(repo, now=datetime.now(timezone.utc))
    except Exception:
        logger.debug("Could not apply scheduled messages", exc_info=True)

    # Match messages
    dispatched = 0
    try:
        match_result = scheduler.match_messages()
        if match_result.deliveries_created > 0:
            dispatched += _dispatch_ready(repo, scheduler, runtime, cogent_name)
    except Exception:
        logger.debug("Message matching failed", exc_info=True)

    # Select and dispatch runnable processes
    try:
        select_result = scheduler.select_processes(slots=50)
        for proc in select_result.selected:
            try:
                dispatched += _dispatch_ready(
                    repo, scheduler, runtime, cogent_name,
                    process_ids={UUID(proc.id)},
                )
            except Exception:
                logger.exception("Failed to dispatch %s", proc.name)
    except Exception:
        logger.debug("Process selection failed", exc_info=True)

    return {"dispatched": dispatched}


def _dispatch_ready(
    repo: Any,
    scheduler: Any,
    runtime: CogtainerRuntime,
    cogent_name: str,
    process_ids: set[UUID] | None = None,
) -> int:
    """Dispatch runnable processes via the runtime."""
    from cogos.db.models import ProcessStatus
    from cogos.runtime.dispatch import build_dispatch_event

    if process_ids is None:
        process_ids = set()

    dispatched = 0
    for pid in sorted(process_ids, key=str):
        proc = repo.get_process(pid)
        if proc is None or proc.status != ProcessStatus.RUNNABLE:
            continue

        dispatch_result = scheduler.dispatch_process(process_id=str(pid))
        if hasattr(dispatch_result, "error"):
            continue

        try:
            runtime.spawn_executor(cogent_name, str(pid))
            dispatched += 1
        except Exception:
            repo.rollback_dispatch(
                pid,
                UUID(dispatch_result.run_id),
                UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
                error="local dispatch failed",
            )
            logger.exception("Failed to spawn executor for %s", pid)

    return dispatched


def run_loop(repo: Any, runtime: CogtainerRuntime, cogent_name: str) -> None:
    """Run the dispatcher loop until interrupted."""
    running = True

    def _stop(sig, frame):
        nonlocal running
        running = False
        logger.info("Stopping dispatcher...")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("Local dispatcher started for cogent '%s' (tick every %ss)", cogent_name, _TICK_INTERVAL)

    while running:
        try:
            result = run_tick(repo, runtime, cogent_name)
            if result.get("dispatched"):
                logger.info("Tick: dispatched %s", result["dispatched"])
        except Exception:
            logger.exception("Dispatcher tick failed")

        # Sleep in small increments for responsive shutdown
        for _ in range(_TICK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    logger.info("Dispatcher stopped.")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogtainer/test_local_dispatcher.py -v`

**Step 5: Commit**

```bash
git add src/cogtainer/local_dispatcher.py tests/cogtainer/test_local_dispatcher.py
git commit -m "feat(cogtainer): add local dispatcher for tick-based process scheduling"
```

---

### Task 10: Wire everything together — pyproject.toml entry points

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add all three CLI entry points**

Add/update in `[project.scripts]`:

```toml
cogos = "cogos.cli.__main__:entry"
cogtainer = "cogtainer.cogtainer_cli:cogtainer"
cogent = "cogtainer.cogent_cli:cogent"
polis = "polis.cli:polis"
discord-bridge = "cogos.io.discord.bridge:main"
```

Add `src/cogtainer` to hatch packages if not already present (it is):
```toml
packages = ["src/cli", "src/cogents", "src/cogos", "src/cogtainer", "src/dashboard", "src/memory", "src/polis"]
```

**Step 2: Verify CLIs work**

Run:
```bash
python -m cogtainer.cogtainer_cli --help
python -m cogtainer.cogent_cli --help
```

**Step 3: Run all new tests**

Run: `python -m pytest tests/cogtainer/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(cogtainer): register cogtainer and cogent CLI entry points"
```

---

### Task 11: Integration test — full local flow

**Files:**
- Create: `tests/cogtainer/test_integration_local.py`

**Step 1: Write integration test**

```python
# tests/cogtainer/test_integration_local.py
"""Integration test: create local cogtainer, create cogent, verify runtime."""
import pytest
from click.testing import CliRunner
from pathlib import Path


def test_full_local_flow(tmp_path, monkeypatch):
    """End-to-end: create cogtainer -> create cogent -> get repo -> list cogents."""
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TEST_OR_KEY", "sk-test")

    # 1. Create cogtainer via CLI
    from cogtainer.cogtainer_cli import cogtainer as cogtainer_cli

    runner = CliRunner()
    result = runner.invoke(cogtainer_cli, [
        "create", "dev",
        "--type", "local",
        "--llm-provider", "openrouter",
        "--llm-model", "anthropic/claude-sonnet-4",
        "--llm-api-key-env", "TEST_OR_KEY",
        "--data-dir", str(data_dir),
    ])
    assert result.exit_code == 0, result.output

    # 2. Create cogent via CLI
    from cogtainer.cogent_cli import cogent as cogent_cli

    result = runner.invoke(cogent_cli, ["create", "alpha"])
    assert result.exit_code == 0, result.output

    # 3. Verify cogent directory exists
    assert (data_dir / "alpha").is_dir()
    assert (data_dir / "alpha" / "files").is_dir()

    # 4. Verify we can get a runtime and repository
    from cogtainer.config import load_config, resolve_cogtainer_name
    from cogtainer.runtime.factory import create_runtime

    cfg = load_config(config_path)
    name = resolve_cogtainer_name(cfg)
    assert name == "dev"

    runtime = create_runtime(cfg.cogtainers[name])

    # 5. List cogents
    assert "alpha" in runtime.list_cogents()

    # 6. Get repository
    repo = runtime.get_repository("alpha")
    from cogos.db.local_repository import LocalRepository
    assert isinstance(repo, LocalRepository)

    # 7. File storage
    runtime.put_file("alpha", "test.txt", b"hello")
    assert runtime.get_file("alpha", "test.txt") == b"hello"

    # 8. Create another cogent
    result = runner.invoke(cogent_cli, ["create", "beta"])
    assert result.exit_code == 0
    assert sorted(runtime.list_cogents()) == ["alpha", "beta"]

    # 9. List via CLI
    result = runner.invoke(cogent_cli, ["list"])
    assert "alpha" in result.output
    assert "beta" in result.output
```

**Step 2: Run integration test**

Run: `python -m pytest tests/cogtainer/test_integration_local.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/cogtainer/test_integration_local.py
git commit -m "test(cogtainer): add integration test for full local cogtainer flow"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Config loader | `src/cogtainer/config.py` |
| 2 | LLM providers | `src/cogtainer/llm/` (provider, bedrock, openrouter, anthropic) |
| 3 | Runtime interface + LocalRuntime | `src/cogtainer/runtime/base.py`, `local.py` |
| 4 | AwsRuntime | `src/cogtainer/runtime/aws.py` |
| 5 | Runtime factory | `src/cogtainer/runtime/factory.py` |
| 6 | `cogtainer` CLI | `src/cogtainer/cogtainer_cli.py` |
| 7 | `cogent` CLI | `src/cogtainer/cogent_cli.py` |
| 8 | EventRouter | `src/cogtainer/event_router.py` |
| 9 | Local dispatcher | `src/cogtainer/local_dispatcher.py` |
| 10 | Wire entry points | `pyproject.toml` |
| 11 | Integration test | `tests/cogtainer/test_integration_local.py` |

---

### Task 12: CDK Stacks — CogtainerStack + CogentStack

**Files:**
- Create: `src/cogtainer/cdk/app.py`
- Create: `src/cogtainer/cdk/stacks/cogtainer_stack.py`
- Create: `src/cogtainer/cdk/stacks/cogent_stack.py`

This is a copy+rename of the existing polis CDK code. Each AWS cogtainer gets its own fully isolated stack (no shared infra).

**Step 1: Create CDK app entry point**

Copy `src/polis/cdk/app.py` → `src/cogtainer/cdk/app.py`. Change imports from `polis.*` to `cogtainer.*`. The app deploys a `CogtainerStack` (shared resources for this cogtainer) when no `cogent_name` context is set, or a `CogentStack` when one is.

```python
# src/cogtainer/cdk/app.py
"""CDK app entry point for cogtainer stacks.

Usage (cogtainer infra):
    npx cdk deploy --app "python -m cogtainer.cdk.app" -c cogtainer_name=<name>

Usage (per-cogent):
    npx cdk deploy --app "python -m cogtainer.cdk.app" \
        -c cogtainer_name=<name> -c cogent_name=<cogent>
"""
from __future__ import annotations

import aws_cdk as cdk

from cogtainer.config import load_config


def _ctx(app: cdk.App, key: str, default: str = "") -> str:
    return app.node.try_get_context(key) or default


def build_app() -> cdk.App:
    app = cdk.App()
    cogtainer_name = _ctx(app, "cogtainer_name")
    if not cogtainer_name:
        raise RuntimeError("cogtainer_name context variable required")

    cfg = load_config()
    entry = cfg.cogtainers.get(cogtainer_name)
    if not entry or entry.type != "aws":
        raise RuntimeError(f"Cogtainer '{cogtainer_name}' not found or not type 'aws'")

    env = cdk.Environment(account=entry.account_id, region=entry.region)
    cogent_name = _ctx(app, "cogent_name")

    if cogent_name:
        from cogtainer.cdk.stacks.cogent_stack import CogentStack
        CogentStack(
            app,
            f"cogtainer-{cogtainer_name}-cogent-{cogent_name}",
            cogtainer_name=cogtainer_name,
            cogent_name=cogent_name,
            domain=entry.domain,
            env=env,
        )
    else:
        from cogtainer.cdk.stacks.cogtainer_stack import CogtainerStack
        CogtainerStack(
            app,
            f"cogtainer-{cogtainer_name}",
            cogtainer_name=cogtainer_name,
            domain=entry.domain,
            env=env,
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.synth()
```

**Step 2: Create CogtainerStack**

Copy core resources from `src/polis/cdk/stacks/core.py` — but scoped to a single cogtainer (not shared across all):

```python
# src/cogtainer/cdk/stacks/cogtainer_stack.py
"""CogtainerStack — per-cogtainer infrastructure (Aurora, ECS, ALB, ECR, EventBridge)."""
from __future__ import annotations
# ... (adapt from polis/cdk/stacks/core.py)
# Key change: all resource names are prefixed with cogtainer name, not "cogent-polis"
# e.g., cluster name = f"cogtainer-{cogtainer_name}"
# ECR repo = f"cogtainer-{cogtainer_name}"
# EventBridge bus = f"cogtainer-{cogtainer_name}"
```

**Step 3: Create CogentStack**

Copy from `src/polis/cdk/stacks/cogent.py` — references cogtainer stack outputs instead of shared polis:

```python
# src/cogtainer/cdk/stacks/cogent_stack.py
"""Per-cogent CDK stack within a cogtainer."""
from __future__ import annotations
# ... (adapt from polis/cdk/stacks/cogent.py)
# Key change: Lambda names use f"cogtainer-{cogtainer_name}-{cogent_name}-event-router"
# instead of f"cogent-{safe_name}-orchestrator"
```

**Step 4: Wire into cogtainer CLI**

Update `cogtainer create` for `--type aws` to run CDK deploy.
Update `cogent create` for AWS cogtainer to deploy CogentStack.

**Step 5: Commit**

```bash
git add src/cogtainer/cdk/
git commit -m "feat(cogtainer): add CDK stacks (CogtainerStack, CogentStack) for AWS cogtainers"
```

---

### Task 13: Refactor cogos CLI to use COGTAINER/COGENT env vars

**Files:**
- Modify: `src/cogos/cli/__main__.py`
- Modify: `src/cli/__main__.py`

Currently the cogos CLI uses `COGENT_ID` env var and `default_cogent` from `~/.cogos/config.yml`. Refactor to use `COGTAINER` + `COGENT` env vars, resolving the runtime via `cogtainer.config`.

**Step 1: Update cogos group command**

Replace the `_ensure_db_env` / `_default_cogent` / `COGENT_ID` logic in `src/cogos/cli/__main__.py`:

```python
@click.group()
@click.pass_context
def cogos(ctx: click.Context):
    """CogOS — management CLI."""
    ctx.ensure_object(dict)

    # Resolve cogtainer + cogent from env/config
    from cogtainer.config import load_config, resolve_cogtainer_name, resolve_cogent_name
    from cogtainer.cogtainer_cli import _config_path
    from cogtainer.runtime.factory import create_runtime

    cfg = load_config(_config_path())
    if not cfg.cogtainers:
        # Fall back to legacy behavior (direct COGENT_ID / polis)
        cogent = os.environ.get("COGENT_ID") or _default_cogent()
        if cogent:
            ctx.obj["cogent_name"] = cogent
            if cogent == "local":
                apply_local_checkout_env()
            else:
                _ensure_db_env(cogent)
        return

    cogtainer_name = resolve_cogtainer_name(cfg)
    entry = cfg.cogtainers[cogtainer_name]
    runtime = create_runtime(entry)
    ctx.obj["runtime"] = runtime
    ctx.obj["cogtainer_name"] = cogtainer_name

    cogents = runtime.list_cogents()
    cogent_name = resolve_cogent_name(cogents)
    ctx.obj["cogent_name"] = cogent_name

    # For local/docker, set USE_LOCAL_DB
    if entry.type in ("local", "docker"):
        os.environ["USE_LOCAL_DB"] = "1"
    else:
        _ensure_db_env(cogent_name)
```

**Step 2: Update `_repo()` helper**

```python
def _repo():
    """Get repository — from runtime if available, else legacy."""
    ctx = click.get_current_context()
    runtime = ctx.obj.get("runtime")
    if runtime:
        return runtime.get_repository(ctx.obj["cogent_name"])
    from cogos.db.factory import create_repository
    return create_repository()
```

**Step 3: Add `cogos start` command for local dispatcher**

```python
@cogos.command("start")
@click.option("--daemon", is_flag=True, help="Run in background")
@click.pass_context
def start_cmd(ctx, daemon):
    """Start the local dispatcher (local/docker cogtainers only)."""
    from cogtainer.local_dispatcher import run_loop
    runtime = ctx.obj.get("runtime")
    if runtime is None:
        raise click.ClickException("No cogtainer runtime configured")
    repo = runtime.get_repository(ctx.obj["cogent_name"])
    if daemon:
        import subprocess, sys
        subprocess.Popen([sys.executable, "-m", "cogtainer.local_dispatcher",
                         ctx.obj["cogtainer_name"], ctx.obj["cogent_name"]])
        click.echo("Dispatcher started in background")
    else:
        run_loop(repo, runtime, ctx.obj["cogent_name"])
```

**Step 4: Verify existing tests still pass**

Run: `python -m pytest tests/ -v --timeout=60`

**Step 5: Commit**

```bash
git add src/cogos/cli/__main__.py src/cli/__main__.py
git commit -m "refactor(cogos): use COGTAINER/COGENT env vars, inject runtime from config"
```

---

### Task 14: Docker runtime — docker-compose generation

**Files:**
- Create: `src/cogtainer/docker_compose.py`
- Test: `tests/cogtainer/test_docker_compose.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_docker_compose.py
"""Tests for docker-compose generation."""
import yaml
import pytest


def test_generate_docker_compose(tmp_path):
    """Generate a valid docker-compose.yml for a docker cogtainer."""
    from cogtainer.docker_compose import generate_compose
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(
        type="docker",
        data_dir=str(tmp_path / "data"),
        image="cogos:latest",
        llm=LLMConfig(provider="openrouter", api_key_env="OPENROUTER_API_KEY", model="anthropic/claude-sonnet-4"),
    )
    compose = generate_compose(entry, cogtainer_name="staging", cogent_names=["alpha"])

    # Should be valid YAML
    parsed = yaml.safe_load(compose)
    assert "services" in parsed
    assert "dispatcher-alpha" in parsed["services"]
    assert "dashboard-alpha" in parsed["services"]

    # Verify LLM env var is passed through
    env = parsed["services"]["dispatcher-alpha"]["environment"]
    assert "OPENROUTER_API_KEY" in str(env) or any("OPENROUTER_API_KEY" in str(e) for e in env)
```

**Step 2: Write implementation**

```python
# src/cogtainer/docker_compose.py
"""Generate docker-compose.yml for docker cogtainers."""
from __future__ import annotations

import yaml

from cogtainer.config import CogtainerEntry


def generate_compose(
    entry: CogtainerEntry,
    cogtainer_name: str,
    cogent_names: list[str],
) -> str:
    """Generate a docker-compose.yml string for the given cogtainer config."""
    services: dict = {}

    for cogent in cogent_names:
        # Dispatcher service (long-running, ticks every 60s)
        services[f"dispatcher-{cogent}"] = {
            "image": entry.image or "cogos:latest",
            "command": ["python", "-m", "cogtainer.local_dispatcher", cogtainer_name, cogent],
            "environment": _build_env(entry, cogent),
            "volumes": [f"{entry.data_dir}/{cogent}:/data/{cogent}"],
            "restart": "unless-stopped",
        }

        # Dashboard service
        services[f"dashboard-{cogent}"] = {
            "image": entry.image or "cogos:latest",
            "command": ["python", "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8080"],
            "environment": _build_env(entry, cogent),
            "volumes": [f"{entry.data_dir}/{cogent}:/data/{cogent}"],
            "ports": [f"8080"],
            "restart": "unless-stopped",
        }

    compose = {
        "version": "3.8",
        "services": services,
    }
    return yaml.dump(compose, default_flow_style=False, sort_keys=False)


def _build_env(entry: CogtainerEntry, cogent_name: str) -> list[str]:
    """Build environment variable list for a docker service."""
    env = [
        f"COGENT={cogent_name}",
        "USE_LOCAL_DB=1",
        f"LOCAL_DB_DIR=/data/{cogent_name}",
        f"LLM_PROVIDER={entry.llm.provider}",
        f"DEFAULT_MODEL={entry.llm.model}",
    ]
    if entry.llm.api_key_env:
        # Pass through the env var from host
        env.append(f"{entry.llm.api_key_env}")
    return env
```

**Step 3: Wire into cogtainer CLI**

Add `cogtainer compose <name>` command that generates and writes `docker-compose.yml` to the data_dir.

**Step 4: Commit**

```bash
git add src/cogtainer/docker_compose.py tests/cogtainer/test_docker_compose.py
git commit -m "feat(cogtainer): add docker-compose.yml generation for docker cogtainers"
```

---

### Task 15: `cogtainer discover-aws` command

**Files:**
- Modify: `src/cogtainer/cogtainer_cli.py`
- Test: `tests/cogtainer/test_discover_aws.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_discover_aws.py
"""Tests for discover-aws command."""
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner


def test_discover_aws_populates_config(tmp_path, monkeypatch):
    """discover-aws finds existing AWS infrastructure and creates config entries."""
    config_path = tmp_path / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    # Mock AWS calls
    mock_session = MagicMock()
    mock_cf = MagicMock()
    mock_cf.describe_stacks.return_value = {
        "Stacks": [{
            "StackName": "cogent-polis",
            "StackStatus": "UPDATE_COMPLETE",
            "Outputs": [
                {"OutputKey": "SharedDbClusterArn", "OutputValue": "arn:aws:rds:us-east-1:123:cluster:test"},
            ],
        }]
    }
    mock_session.client.return_value = mock_cf
    mock_ddb_table = MagicMock()
    mock_ddb_table.scan.return_value = {
        "Items": [
            {"cogent_name": "alpha", "domain": "alpha.test.com"},
            {"cogent_name": "beta", "domain": "beta.test.com"},
        ]
    }
    mock_session.resource.return_value.Table.return_value = mock_ddb_table

    from cogtainer.cogtainer_cli import cogtainer

    with patch("cogtainer.cogtainer_cli._get_aws_session", return_value=mock_session):
        runner = CliRunner()
        result = runner.invoke(cogtainer, ["discover-aws", "--region", "us-east-1"])

    assert result.exit_code == 0, result.output

    from cogtainer.config import load_config
    cfg = load_config(config_path)
    # Should have created an entry
    assert len(cfg.cogtainers) >= 1
```

**Step 2: Write implementation**

Add `discover-aws` command to `cogtainer_cli.py`:

```python
@cogtainer.command("discover-aws")
@click.option("--region", default="us-east-1")
@click.option("--profile", default=None, help="AWS profile to use")
def discover_aws(region: str, profile: str | None):
    """Discover existing AWS cogtainer infrastructure and populate config."""
    session = _get_aws_session(profile, region)

    # Scan DynamoDB cogent-status table for existing cogents
    ddb = session.resource("dynamodb", region_name=region)
    table = ddb.Table("cogent-status")
    items = table.scan().get("Items", [])

    if not items:
        click.echo("No cogents found in AWS.")
        return

    cfg = _load()
    cogtainer_name = f"aws-{region}"

    if cogtainer_name not in cfg.cogtainers:
        entry = CogtainerEntry(
            type="aws",
            region=region,
            llm=LLMConfig(provider="bedrock", model="us.anthropic.claude-sonnet-4-20250514-v1:0"),
        )
        cfg.cogtainers[cogtainer_name] = entry
        _save_config(cfg)

    cogent_names = [item["cogent_name"] for item in items if "cogent_name" in item]
    click.echo(f"Discovered cogtainer '{cogtainer_name}' with {len(cogent_names)} cogents:")
    for name in sorted(cogent_names):
        click.echo(f"  {name}")


def _get_aws_session(profile: str | None = None, region: str = "us-east-1"):
    """Get AWS session, optionally with profile."""
    from polis.aws import get_polis_session, set_org_profile
    if profile:
        set_org_profile(profile)
    session, _ = get_polis_session()
    return session
```

**Step 3: Commit**

```bash
git add src/cogtainer/cogtainer_cli.py tests/cogtainer/test_discover_aws.py
git commit -m "feat(cogtainer): add discover-aws command to populate config from existing AWS infra"
```

---

### Task 16: Remove polis code

**Files:**
- Delete: `src/polis/` (entire directory)
- Modify: `pyproject.toml` — remove polis from packages and scripts
- Modify: any remaining imports of `polis.*` — update to `cogtainer.*`

**Prerequisite:** Tasks 1–15 are complete and all tests pass.

**Step 1: Find all remaining polis imports**

Run: `grep -r "from polis" src/ --include="*.py" -l`
Run: `grep -r "import polis" src/ --include="*.py" -l`

**Step 2: Update imports in cogtainer code**

Any `from polis import naming` → create `src/cogtainer/naming.py` with the same functions.
Any `from polis.aws import ...` → move to `src/cogtainer/aws.py`.
Any `from polis.config import ...` → already replaced by `cogtainer.config`.
Any `from polis.secrets.store import ...` → move to `src/cogtainer/secrets/`.

**Step 3: Update pyproject.toml**

Remove `polis = "polis.cli:polis"` from scripts.
Remove `"src/polis"` from packages list.

**Step 4: Delete `src/polis/`**

```bash
rm -rf src/polis/
```

**Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove polis code — fully replaced by cogtainer"
```

---

### Task 17: `cogtainers.ci.yml` config + `cogtainer update` command

**Files:**
- Create: `src/cogtainer/ci_config.py`
- Modify: `src/cogtainer/cogtainer_cli.py` — add `update` command
- Create: `cogtainers.ci.yml` (repo root)
- Test: `tests/cogtainer/test_ci_config.py`
- Test: `tests/cogtainer/test_cogtainer_update.py`

**Context:** Currently CI builds images, pushes to a single ECR repo (`cogent`), uploads Lambda zips to S3 (`cogent-polis-ci-artifacts`), then the user runs `cogos <name> cogtainer update ecs --tag ...` to roll out. With multiple isolated cogtainers, each has its own ECR repo and Lambda functions. CI needs to know which cogtainers to target, and `cogtainer update` replaces the old `cogtainer update ecs/lambda` commands.

**Step 1: Write CI config test**

```python
# tests/cogtainer/test_ci_config.py
"""Tests for cogtainers.ci.yml loader."""
import pytest


def test_load_ci_config(tmp_path):
    """Load CI config with cogtainer deploy targets."""
    from cogtainer.ci_config import load_ci_config

    config_file = tmp_path / "cogtainers.ci.yml"
    config_file.write_text("""
cogtainers:
  prod:
    account_id: "901289084804"
    region: us-east-1
    ecr_repo: cogtainer-prod
    components: all
    cogents: [alpha, beta]
  staging:
    account_id: "123456789012"
    region: us-west-2
    ecr_repo: cogtainer-staging
    components: [lambdas, dashboard]
    cogents: [test]
""")
    cfg = load_ci_config(config_file)
    assert len(cfg.cogtainers) == 2
    assert cfg.cogtainers["prod"].account_id == "901289084804"
    assert cfg.cogtainers["prod"].ecr_repo == "cogtainer-prod"
    assert cfg.cogtainers["prod"].components == "all"
    assert cfg.cogtainers["prod"].cogents == ["alpha", "beta"]
    assert cfg.cogtainers["staging"].components == ["lambdas", "dashboard"]


def test_ci_config_list_targets():
    """List deploy targets for CI matrix."""
    from cogtainer.ci_config import CIConfig, CICogtainerEntry

    cfg = CIConfig(cogtainers={
        "prod": CICogtainerEntry(
            account_id="111", region="us-east-1",
            ecr_repo="r1", components="all", cogents=["a"],
        ),
        "staging": CICogtainerEntry(
            account_id="222", region="us-west-2",
            ecr_repo="r2", components=["lambdas"], cogents=["b"],
        ),
    })
    targets = cfg.deploy_targets()
    assert len(targets) == 2
    assert targets[0]["name"] == "prod"
    assert targets[0]["account_id"] == "111"
```

**Step 2: Write CI config loader**

```python
# src/cogtainer/ci_config.py
"""CI deploy configuration — cogtainers.ci.yml loader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class CICogtainerEntry(BaseModel):
    account_id: str
    region: str = "us-east-1"
    ecr_repo: str
    components: str | list[str] = "all"  # "all" or list of ["lambdas", "dashboard", "discord"]
    cogents: list[str] = Field(default_factory=list)
    aws_role: str = ""  # OIDC role ARN for CI
    s3_artifacts_bucket: str = ""  # for Lambda zips


class CIConfig(BaseModel):
    cogtainers: dict[str, CICogtainerEntry] = Field(default_factory=dict)

    def deploy_targets(self) -> list[dict[str, Any]]:
        """Return list of deploy target dicts for CI matrix."""
        return [
            {
                "name": name,
                "account_id": entry.account_id,
                "region": entry.region,
                "ecr_repo": entry.ecr_repo,
                "components": entry.components,
                "cogents": entry.cogents,
                "aws_role": entry.aws_role,
                "s3_artifacts_bucket": entry.s3_artifacts_bucket,
            }
            for name, entry in sorted(self.cogtainers.items())
        ]


def load_ci_config(path: Path | None = None) -> CIConfig:
    """Load CI config from cogtainers.ci.yml."""
    path = path or Path("cogtainers.ci.yml")
    if not path.is_file():
        return CIConfig()
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw or not isinstance(raw, dict):
        return CIConfig()
    return CIConfig(**raw)
```

**Step 3: Write `cogtainer update` test**

```python
# tests/cogtainer/test_cogtainer_update.py
"""Tests for cogtainer update command."""
from unittest.mock import MagicMock, patch, call
from click.testing import CliRunner
import pytest


def test_update_lambdas_only(tmp_path, monkeypatch):
    """cogtainer update --lambdas updates Lambda function code."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text("""
cogtainers:
  prod:
    type: aws
    region: us-east-1
    account_id: "123456789"
    llm: {provider: bedrock, model: x}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    mock_session = MagicMock()
    mock_lambda = MagicMock()
    mock_session.client.return_value = mock_lambda

    # Mock DynamoDB to return cogent list
    mock_table = MagicMock()
    mock_table.scan.return_value = {"Items": [{"cogent_name": "alpha"}]}
    mock_session.resource.return_value.Table.return_value = mock_table

    from cogtainer.cogtainer_cli import cogtainer

    with patch("cogtainer.cogtainer_cli._get_aws_session", return_value=mock_session):
        runner = CliRunner()
        result = runner.invoke(cogtainer, [
            "update", "prod", "--lambdas",
            "--lambda-s3-bucket", "my-bucket",
            "--lambda-s3-key", "lambda/abc123/lambda.zip",
        ])

    assert result.exit_code == 0, result.output
    # Should have called update_function_code for each Lambda
    assert mock_lambda.update_function_code.called


def test_update_services_only(tmp_path, monkeypatch):
    """cogtainer update --services restarts ECS services."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text("""
cogtainers:
  prod:
    type: aws
    region: us-east-1
    account_id: "123456789"
    llm: {provider: bedrock, model: x}
""")
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    mock_session = MagicMock()
    mock_ecs = MagicMock()
    mock_session.client.return_value = mock_ecs

    mock_table = MagicMock()
    mock_table.scan.return_value = {"Items": [{"cogent_name": "alpha"}]}
    mock_session.resource.return_value.Table.return_value = mock_table

    from cogtainer.cogtainer_cli import cogtainer

    with patch("cogtainer.cogtainer_cli._get_aws_session", return_value=mock_session):
        runner = CliRunner()
        result = runner.invoke(cogtainer, [
            "update", "prod", "--services",
            "--image-tag", "executor-abc1234",
        ])

    assert result.exit_code == 0, result.output
```

**Step 4: Write `cogtainer update` command**

Add to `cogtainer_cli.py`:

```python
@cogtainer.command("update")
@click.argument("name")
@click.option("--lambdas", is_flag=True, help="Update Lambda function code")
@click.option("--services", is_flag=True, help="Restart ECS services with new image")
@click.option("--all", "update_all", is_flag=True, default=True, help="Update everything (default)")
@click.option("--lambda-s3-bucket", default="", help="S3 bucket containing Lambda zip")
@click.option("--lambda-s3-key", default="", help="S3 key for Lambda zip")
@click.option("--image-tag", default="", help="ECR image tag for ECS services")
def update_cmd(name, lambdas, services, update_all, lambda_s3_bucket, lambda_s3_key, image_tag):
    """Update a cogtainer's running services.

    By default updates everything. Use --lambdas or --services to update selectively.
    """
    cfg = _load()
    if name not in cfg.cogtainers:
        raise click.ClickException(f"Cogtainer '{name}' not found")

    entry = cfg.cogtainers[name]
    if entry.type != "aws":
        raise click.ClickException("update is only for AWS cogtainers")

    session = _get_aws_session()

    # If neither flag is set, update everything
    if not lambdas and not services:
        lambdas = True
        services = True

    # Get cogent list
    ddb = session.resource("dynamodb", region_name=entry.region)
    table = ddb.Table("cogent-status")
    items = table.scan().get("Items", [])
    cogent_names = sorted(item["cogent_name"] for item in items if "cogent_name" in item)

    if lambdas and lambda_s3_bucket and lambda_s3_key:
        _update_lambdas(session, entry, cogent_names, lambda_s3_bucket, lambda_s3_key)

    if services and image_tag:
        _update_services(session, entry, cogent_names, image_tag)

    click.echo(f"Cogtainer '{name}' updated.")


def _update_lambdas(session, entry, cogent_names, s3_bucket, s3_key):
    """Update Lambda function code from S3."""
    lam = session.client("lambda", region_name=entry.region)
    lambda_suffixes = ["event-router", "executor", "dispatcher", "ingress"]

    for cogent in cogent_names:
        safe = cogent.replace(".", "-")
        for suffix in lambda_suffixes:
            fn_name = f"cogtainer-{safe}-{suffix}"
            try:
                lam.update_function_code(
                    FunctionName=fn_name,
                    S3Bucket=s3_bucket,
                    S3Key=s3_key,
                )
                click.echo(f"  Updated Lambda: {fn_name}")
            except Exception as e:
                click.echo(f"  Warning: {fn_name}: {e}")


def _update_services(session, entry, cogent_names, image_tag):
    """Force new deployment of ECS services with updated image."""
    ecs = session.client("ecs", region_name=entry.region)

    for cogent in cogent_names:
        safe = cogent.replace(".", "-")
        cluster = f"cogtainer-{safe}"
        for svc_suffix in ["dashboard", "discord"]:
            svc_name = f"cogtainer-{safe}-{svc_suffix}"
            try:
                ecs.update_service(
                    cluster=cluster,
                    service=svc_name,
                    forceNewDeployment=True,
                )
                click.echo(f"  Restarted ECS: {svc_name}")
            except Exception as e:
                click.echo(f"  Warning: {svc_name}: {e}")
```

**Step 5: Create `cogtainers.ci.yml` in repo root**

```yaml
# cogtainers.ci.yml — CI deploy targets
# CI reads this to know which cogtainers to build/deploy to.
# Each entry is self-contained: account, region, ECR repo, cogents.
cogtainers:
  prod:
    account_id: "901289084804"
    region: us-east-1
    ecr_repo: cogtainer-prod
    aws_role: arn:aws:iam::901289084804:role/github-actions
    s3_artifacts_bucket: cogtainer-prod-ci-artifacts
    components: all
    cogents: []  # populated by discover-aws or manually
```

**Step 6: Commit**

```bash
git add src/cogtainer/ci_config.py src/cogtainer/cogtainer_cli.py cogtainers.ci.yml \
  tests/cogtainer/test_ci_config.py tests/cogtainer/test_cogtainer_update.py
git commit -m "feat(cogtainer): add cogtainers.ci.yml config and cogtainer update command"
```

---

### Task 18: Update CI workflows for multi-cogtainer deploy

**Files:**
- Modify: `.github/workflows/docker-build-executor.yml`
- Modify: `.github/workflows/docker-build-dashboard.yml`
- Modify: `.github/actions/ecr-build/action.yml`

Currently CI pushes to a single ECR repo (`cogent`) in a single account. Update to read `cogtainers.ci.yml` and deploy to each cogtainer's ECR repo.

**Step 1: Add CI matrix from cogtainers.ci.yml**

Update `.github/workflows/docker-build-executor.yml`:

```yaml
jobs:
  # Read deploy targets from cogtainers.ci.yml
  load-targets:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.targets.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
      - name: Parse deploy targets
        id: targets
        run: |
          python -c "
          import yaml, json
          with open('cogtainers.ci.yml') as f:
              cfg = yaml.safe_load(f)
          targets = []
          for name, entry in (cfg.get('cogtainers') or {}).items():
              components = entry.get('components', 'all')
              if components == 'all' or 'lambdas' in components:
                  targets.append({
                      'name': name,
                      'account_id': entry['account_id'],
                      'region': entry.get('region', 'us-east-1'),
                      'ecr_repo': entry['ecr_repo'],
                      'aws_role': entry.get('aws_role', ''),
                      's3_bucket': entry.get('s3_artifacts_bucket', ''),
                  })
          print(f'matrix={json.dumps({\"include\": targets})}')
          " >> "$GITHUB_OUTPUT"

  build-and-deploy:
    needs: load-targets
    runs-on: ubuntu-latest
    strategy:
      matrix: ${{ fromJson(needs.load-targets.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4

      - name: Build and push executor image
        uses: ./.github/actions/ecr-build
        with:
          image_name: ${{ matrix.ecr_repo }}
          dockerfile: src/cogtainer/docker/Dockerfile
          context: .
          aws_role: ${{ matrix.aws_role }}
          aws_region: ${{ matrix.region }}
          tag_prefix: executor

      - name: Package and upload Lambda zip
        # ... (same as current, but targets matrix.s3_bucket)

      - name: Update cogtainer
        run: |
          cogtainer update ${{ matrix.name }} \
            --lambdas \
            --lambda-s3-bucket ${{ matrix.s3_bucket }} \
            --lambda-s3-key lambda/${{ github.sha }}/lambda.zip
```

**Step 2: Update ecr-build action**

The action already takes `image_name` and `aws_role` as inputs — these just get different values per matrix entry. No changes needed to the action itself.

**Step 3: Update dashboard workflow similarly**

Same pattern: read `cogtainers.ci.yml`, filter for entries with `components: all` or `components` containing `"dashboard"`, deploy to each.

**Step 4: Commit**

```bash
git add .github/workflows/ .github/actions/
git commit -m "ci: update workflows for multi-cogtainer deploy via cogtainers.ci.yml matrix"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Config loader | `src/cogtainer/config.py` |
| 2 | LLM providers | `src/cogtainer/llm/` (provider, bedrock, openrouter, anthropic) |
| 3 | Runtime interface + LocalRuntime | `src/cogtainer/runtime/base.py`, `local.py` |
| 4 | AwsRuntime | `src/cogtainer/runtime/aws.py` |
| 5 | Runtime factory | `src/cogtainer/runtime/factory.py` |
| 6 | `cogtainer` CLI | `src/cogtainer/cogtainer_cli.py` |
| 7 | `cogent` CLI | `src/cogtainer/cogent_cli.py` |
| 8 | EventRouter | `src/cogtainer/event_router.py` |
| 9 | Local dispatcher | `src/cogtainer/local_dispatcher.py` |
| 10 | Wire entry points | `pyproject.toml` |
| 11 | Integration test | `tests/cogtainer/test_integration_local.py` |
| 12 | CDK stacks (AWS) | `src/cogtainer/cdk/` (app, cogtainer_stack, cogent_stack) |
| 13 | Refactor cogos CLI | `src/cogos/cli/__main__.py` — use COGTAINER/COGENT env vars |
| 14 | Docker compose | `src/cogtainer/docker_compose.py` |
| 15 | `discover-aws` command | `src/cogtainer/cogtainer_cli.py` |
| 16 | Remove polis | Delete `src/polis/`, update imports |
| 17 | `cogtainers.ci.yml` + `cogtainer update` | CI config, update CLI with `--lambdas`/`--services`/`--all` |
| 18 | Update CI workflows | `.github/workflows/` — matrix deploy from `cogtainers.ci.yml` |
