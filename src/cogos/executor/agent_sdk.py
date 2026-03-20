"""Agent SDK executor — converts CogOS capabilities to @tool functions."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, get_type_hints

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def get_public_methods(cap: Any) -> list[tuple[str, Any]]:
    skip = {"help", "scope"}
    results = []
    for name in dir(cap):
        if name.startswith("_") or name in skip:
            continue
        attr = getattr(cap, name, None)
        if callable(attr) and not isinstance(attr, type):
            results.append((name, attr))
    return results


def schema_from_method(method: Any) -> dict:
    try:
        hints = get_type_hints(method)
    except Exception:
        hints = {}

    sig = inspect.signature(method)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ptype = hints.get(pname, str)
        origin = getattr(ptype, "__origin__", None)
        if origin is type(None):
            continue
        args = getattr(ptype, "__args__", None)
        if args and type(None) in args:
            ptype = next(a for a in args if a is not type(None))
        else:
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        json_type = _TYPE_MAP.get(ptype, "string")
        properties[pname] = {"type": json_type}

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class _CallableTool:
    """Wraps SdkMcpTool to be directly callable and carry __tool_name__."""

    def __init__(self, sdk_tool: Any, tool_name: str) -> None:
        self._sdk_tool = sdk_tool
        self.__tool_name__ = tool_name

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._sdk_tool.handler(args)

    def unwrap(self) -> Any:
        return self._sdk_tool


def build_tool_functions(capabilities: dict[str, Any]) -> list[_CallableTool]:
    tools = []

    for cap_name, cap in capabilities.items():
        for method_name, method in get_public_methods(cap):
            tool_name = f"{cap_name}_{method_name}"
            description = (method.__doc__ or f"{cap_name}.{method_name}").strip().split("\n")[0]
            schema = schema_from_method(method)

            @tool(tool_name, description, schema)
            async def handler(
                args: dict[str, Any],
                _cap: Any = cap,
                _method: Any = method,
                _name: str = method_name,
            ) -> dict[str, Any]:
                try:
                    _cap._check(_name, **args)
                except PermissionError as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}
                try:
                    result = _method(**args)
                    if hasattr(result, "model_dump"):
                        text = json.dumps(result.model_dump(), default=str)
                    elif isinstance(result, (dict, list)):
                        text = json.dumps(result, default=str)
                    else:
                        text = str(result)
                    return {"content": [{"type": "text", "text": text}]}
                except Exception as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}

            tools.append(_CallableTool(handler, tool_name))

    return tools


def build_mcp_server(capabilities: dict[str, Any]) -> Any:
    callable_tools = build_tool_functions(capabilities)
    sdk_tools = [ct.unwrap() for ct in callable_tools]
    return create_sdk_mcp_server(name="cogent", version="1.0.0", tools=sdk_tools)
