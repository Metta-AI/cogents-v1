"""OpenRouter LLM provider — translates Bedrock format to/from OpenAI format."""

from __future__ import annotations

import json
import logging

import requests

from cogtainer.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    """Calls OpenRouter using OpenAI-compatible chat completions."""

    def __init__(self, default_model: str = "", api_key: str = "") -> None:
        super().__init__(default_model=default_model)
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Bedrock → OpenAI format converters
    # ------------------------------------------------------------------

    @staticmethod
    def _system_to_openai(system: list[dict]) -> str:
        """Join Bedrock system blocks into a single string."""
        return "\n\n".join(b["text"] for b in system if "text" in b)

    @staticmethod
    def _messages_to_openai(messages: list[dict]) -> list[dict]:
        """Convert Bedrock converse messages to OpenAI chat messages."""
        result: list[dict] = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", [])

            # Check if this message has tool results (user role with toolResult blocks)
            tool_results = [b for b in content if "toolResult" in b]
            if tool_results:
                for b in content:
                    if "toolResult" in b:
                        tr = b["toolResult"]
                        tr_content_parts = []
                        for c in tr.get("content", []):
                            if "text" in c:
                                tr_content_parts.append(c["text"])
                            elif "json" in c:
                                tr_content_parts.append(json.dumps(c["json"]))
                        result.append({
                            "role": "tool",
                            "tool_call_id": tr["toolUseId"],
                            "content": "\n".join(tr_content_parts),
                        })
                continue

            # Check for tool_use blocks (assistant role)
            tool_uses = [b for b in content if "toolUse" in b]
            text_blocks = [b for b in content if "text" in b]

            if tool_uses:
                tool_calls = []
                for b in tool_uses:
                    tu = b["toolUse"]
                    tool_calls.append({
                        "id": tu["toolUseId"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu.get("input", {})),
                        },
                    })
                oai_msg: dict = {"role": "assistant", "tool_calls": tool_calls}
                if text_blocks:
                    oai_msg["content"] = "\n".join(b["text"] for b in text_blocks)
                result.append(oai_msg)
                continue

            # Simple text message
            text = "\n".join(b["text"] for b in text_blocks) if text_blocks else ""
            result.append({"role": role, "content": text})

        return result

    @staticmethod
    def _tools_to_openai(tool_config: dict) -> list[dict]:
        """Convert Bedrock toolConfig to OpenAI tools format."""
        tools = []
        for tool in tool_config.get("tools", []):
            spec = tool.get("toolSpec", {})
            schema = spec.get("inputSchema", {}).get("json", {})
            tools.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": schema,
                },
            })
        return tools

    # ------------------------------------------------------------------
    # OpenAI → Bedrock format converter
    # ------------------------------------------------------------------

    @staticmethod
    def _response_to_bedrock(data: dict) -> dict:
        """Convert OpenAI chat completion response to Bedrock format."""
        choice = data["choices"][0]
        message = choice["message"]

        content: list[dict] = []
        if message.get("content"):
            content.append({"text": message["content"]})

        tool_calls = message.get("tool_calls") or []
        for tc in tool_calls:
            fn = tc["function"]
            content.append({
                "toolUse": {
                    "toolUseId": tc["id"],
                    "name": fn["name"],
                    "input": json.loads(fn["arguments"]),
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

    # ------------------------------------------------------------------
    # converse
    # ------------------------------------------------------------------

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        oai_messages: list[dict] = []

        system_text = self._system_to_openai(system)
        if system_text:
            oai_messages.append({"role": "system", "content": system_text})

        oai_messages.extend(self._messages_to_openai(messages))

        payload: dict = {
            "model": model or self._default_model,
            "messages": oai_messages,
        }

        tools = self._tools_to_openai(tool_config)
        if tools:
            payload["tools"] = tools

        resp = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        return self._response_to_bedrock(resp.json())
