"""Coglet executor — fast-path game loop for MettaGrid.

Implements the hybrid execution model (Option C from coglet-protocol.md):
- Fast path: runs policy.py directly in a Python sandbox (no LLM round-trip)
- Fallback: on error or reload, drops into the standard LLM handler briefly

The game loop:
1. Receive PreparePolicyRequest → set up episode
2. Load policy.py from the file store
3. Loop: receive BatchStepRequest → parse obs → call policy.step() → encode actions → send
4. Episode ends when the game server closes the WebSocket

This executor is designed to achieve sub-millisecond action latency by
bypassing the LLM for the hot path.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import time
import types
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PolicySandbox:
    """Sandboxed execution environment for policy.py.

    Loads a policy module from source code and calls its step() function
    in a restricted environment. The module is reloadable without restarting
    the process.
    """

    def __init__(self) -> None:
        self._module: Optional[types.ModuleType] = None
        self._source: Optional[str] = None

    def load(self, source: str, module_name: str = "policy") -> None:
        """Load or reload a policy module from source code.

        Args:
            source: Python source code of the policy module.
            module_name: Name to register in sys.modules.
        """
        spec = importlib.util.spec_from_loader(
            module_name, loader=None, origin="<policy>"
        )
        module = importlib.util.module_from_spec(spec)

        # Provide a restricted builtins set
        module.__builtins__ = _safe_builtins()

        try:
            exec(compile(source, "<policy.py>", "exec"), module.__dict__)  # noqa: S102
        except Exception:
            logger.exception("Failed to compile/exec policy.py")
            raise

        if not hasattr(module, "step"):
            raise ValueError("policy.py must define a step(obs, game_rules, state) function")

        self._module = module
        self._source = source
        logger.info("Policy module loaded successfully")

    def step(
        self,
        obs: dict,
        game_rules: dict,
        state: dict,
    ) -> tuple[dict, dict]:
        """Execute one step of the policy.

        Args:
            obs: {agent_id: [(row, col, feature_name, value), ...]}
            game_rules: Game rules dict from prepare phase
            state: Persistent state dict (mutable, carried across steps)

        Returns:
            (actions, state) where actions = {agent_id: action_name}
        """
        if self._module is None:
            raise RuntimeError("Policy module not loaded")

        return self._module.step(obs, game_rules, state)

    @property
    def is_loaded(self) -> bool:
        return self._module is not None


class CogletExecutor:
    """Orchestrates the fast-path game loop.

    Coordinates between the MettaGridAdapter (WebSocket transport),
    the PolicySandbox (policy execution), and the CogletCapability
    (game state management).

    This class is instantiated by the CogOS process executor when a
    process with runner="coglet" (or the coglet capability) starts.
    """

    def __init__(self) -> None:
        self._sandbox = PolicySandbox()
        self._state: dict = {}
        self._step_count: int = 0
        self._episode_id: Optional[str] = None
        self._game_rules: Optional[dict] = None
        self._agent_ids: list[int] = []
        self._step_times: list[float] = []

    def prepare(
        self,
        episode_id: str,
        game_rules: dict,
        agent_ids: list[int],
        policy_source: str,
    ) -> None:
        """Prepare for a new episode.

        Args:
            episode_id: Unique episode identifier.
            game_rules: Game rules dict (features, actions, tags, dimensions).
            agent_ids: List of agent IDs we control.
            policy_source: Python source code of the policy module.
        """
        self._episode_id = episode_id
        self._game_rules = game_rules
        self._agent_ids = agent_ids
        self._state = {}
        self._step_count = 0
        self._step_times = []

        self._sandbox.load(policy_source)
        logger.info(
            "CogletExecutor prepared: episode=%s agents=%s",
            episode_id, agent_ids,
        )

    def step(self, observations: dict) -> dict:
        """Execute one game step.

        Args:
            observations: {agent_id: [(row, col, feature_name, value), ...]}

        Returns:
            {agent_id: action_name} — actions for each agent.
        """
        self._step_count += 1
        start = time.monotonic()

        try:
            actions, self._state = self._sandbox.step(
                observations, self._game_rules, self._state
            )
        except Exception:
            logger.exception(
                "Policy error at step %d, falling back to noop",
                self._step_count,
            )
            # Fall back to noop for all agents
            actions = {aid: "noop" for aid in self._agent_ids}

        elapsed_ms = (time.monotonic() - start) * 1000
        self._step_times.append(elapsed_ms)

        if self._step_count % 100 == 0:
            avg_ms = sum(self._step_times[-100:]) / min(100, len(self._step_times))
            logger.info(
                "Step %d: avg policy time %.2fms (last 100 steps)",
                self._step_count, avg_ms,
            )

        return actions

    def reload_policy(self, policy_source: str) -> bool:
        """Hot-reload the policy module.

        Args:
            policy_source: New Python source code.

        Returns:
            True if reload succeeded, False if it failed (old policy stays).
        """
        old_source = self._sandbox._source
        try:
            self._sandbox.load(policy_source)
            logger.info("Policy hot-reloaded at step %d", self._step_count)
            return True
        except Exception:
            logger.exception("Failed to reload policy, keeping old version")
            # Restore old policy if possible
            if old_source:
                try:
                    self._sandbox.load(old_source)
                except Exception:
                    logger.exception("Failed to restore old policy!")
            return False

    def get_summary(self) -> dict:
        """Get a summary of the current episode state for the strategist."""
        return {
            "episode_id": self._episode_id,
            "step_count": self._step_count,
            "agent_ids": self._agent_ids,
            "avg_step_ms": (
                sum(self._step_times[-100:]) / max(1, min(100, len(self._step_times)))
                if self._step_times else 0.0
            ),
            "state_keys": list(self._state.keys()),
        }


def _safe_builtins() -> dict:
    """Return a restricted builtins dict for the policy sandbox.

    Allows standard Python operations but blocks dangerous functions
    like exec, eval, open, __import__, etc.
    """
    import builtins

    allowed = {
        # Types and constructors
        "True", "False", "None",
        "int", "float", "str", "bool", "bytes", "bytearray",
        "list", "dict", "set", "tuple", "frozenset",
        "complex", "memoryview", "slice", "type", "object",
        # Functions
        "abs", "all", "any", "bin", "chr", "divmod",
        "enumerate", "filter", "format", "hash", "hex",
        "id", "isinstance", "issubclass", "iter", "len",
        "map", "max", "min", "next", "oct", "ord",
        "pow", "print", "range", "repr", "reversed",
        "round", "sorted", "sum", "zip",
        # Math helpers
        "ValueError", "TypeError", "KeyError", "IndexError",
        "StopIteration", "RuntimeError", "AttributeError",
        "Exception", "ZeroDivisionError", "OverflowError",
        "NotImplementedError",
        # Useful for policy logic
        "staticmethod", "classmethod", "property",
        "super", "callable", "getattr", "setattr", "hasattr",
        "delattr",
    }

    safe = {}
    for name in allowed:
        val = getattr(builtins, name, None)
        if val is not None:
            safe[name] = val

    # Allow importing only safe modules
    safe["__import__"] = _restricted_import

    return safe


_ALLOWED_MODULES = frozenset({
    "math", "random", "collections", "itertools", "functools",
    "operator", "heapq", "bisect", "copy", "json",
    "dataclasses", "typing", "enum", "abc",
    "statistics", "time",
})


def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Import function that only allows safe modules."""
    if name not in _ALLOWED_MODULES:
        raise ImportError(
            f"Module '{name}' is not available in the policy sandbox. "
            f"Allowed modules: {', '.join(sorted(_ALLOWED_MODULES))}"
        )
    return __builtins__["__import__"](name, *args, **kwargs)  # type: ignore[index]
