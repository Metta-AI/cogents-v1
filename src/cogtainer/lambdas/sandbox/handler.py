"""Sandbox Lambda handler — executes code snippets in a sandboxed namespace."""

from __future__ import annotations

from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.db import get_repo
from cogtainer.lambdas.shared.logging import setup_logging
from cogtainer.tools.sandbox import execute_in_sandbox, load_and_wrap_tools

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point — run user code in a sandboxed namespace."""
    try:
        config = get_config()
        repo = get_repo()

        code = event["code"]
        tool_names = event.get("tool_names", [])

        namespace = load_and_wrap_tools(tool_names, config, repo)
        result = execute_in_sandbox(code, namespace)

        return {"statusCode": 200, "result": result}

    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}", exc_info=True)
        return {"statusCode": 500, "error": str(e)}
