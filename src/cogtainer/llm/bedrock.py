"""Bedrock LLM provider — thin wrapper around boto3 bedrock-runtime."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from cogtainer.llm.provider import LLMProvider


class BedrockProvider(LLMProvider):
    """Delegates to the Bedrock converse API directly."""

    def __init__(
        self,
        default_model: str = "",
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        super().__init__(default_model=default_model)
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "modelId": model or self._default_model,
            "messages": messages,
            "system": system,
        }
        if tool_config:
            kwargs["toolConfig"] = tool_config
        return self._client.converse(**kwargs)
