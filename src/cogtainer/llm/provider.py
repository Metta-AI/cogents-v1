"""LLM provider abstraction — uniform interface over Bedrock, OpenRouter, Anthropic."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from cogtainer.config import LLMConfig


class LLMProvider(ABC):
    """Abstract base for LLM providers.

    All providers accept Bedrock converse-format inputs and return
    Bedrock converse-format responses.
    """

    def __init__(self, default_model: str = "") -> None:
        self._default_model = default_model

    @abstractmethod
    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        """Call the LLM.

        Returns Bedrock-format response::

            {
                "output": {"message": {"role": "assistant", "content": [...]}},
                "stopReason": "end_turn" | "tool_use" | "max_tokens",
                "usage": {"inputTokens": int, "outputTokens": int},
            }
        """


def create_provider(config: LLMConfig, region: str = "us-east-1") -> LLMProvider:
    """Factory: instantiate the right provider from an LLMConfig."""
    provider = config.provider.lower()

    if provider == "bedrock":
        from cogtainer.llm.bedrock import BedrockProvider
        return BedrockProvider(default_model=config.model, region=region)

    if provider == "openrouter":
        from cogtainer.llm.openrouter import OpenRouterProvider
        api_key = os.environ.get(config.api_key_env, "")
        return OpenRouterProvider(default_model=config.model, api_key=api_key)

    if provider == "anthropic":
        from cogtainer.llm.anthropic_provider import AnthropicProvider
        api_key = os.environ.get(config.api_key_env, "")
        return AnthropicProvider(default_model=config.model, api_key=api_key)

    raise ValueError(f"Unknown LLM provider: {config.provider!r}")
