"""Coglet capability — game interaction for MettaGrid coglets.

Provides cog-policy processes with the ability to interact with a MettaGrid
game server: receive observations, send actions, access game rules, and
log step data.  This capability is injected into the cog-policy sandbox
so that LLM-generated or user-written policy code can call these methods
directly.

In the fast-path game loop (executor/coglet.py), this capability is used
programmatically; in LLM fallback mode, the process calls these methods
via run_code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional
from uuid import UUID

from cogos.capabilities.base import Capability
from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


class CogletCapability(Capability):
    """Capability for MettaGrid game interaction.

    Injected into cog-policy processes to provide game loop primitives.
    Methods are callable from sandbox code (policy.py or LLM-generated code).
    """

    def __init__(self, repo: Repository, process_id: UUID, run_id: UUID | None = None) -> None:
        super().__init__(repo, process_id, run_id)
        self._observation: Optional[dict] = None
        self._game_rules: Optional[dict] = None
        self._episode_info: Optional[dict] = None
        self._policy_state: dict = {}
        self._step_log: list[dict] = []
        self._action_callback: Optional[Any] = None
        self._policy_module: Optional[Any] = None
        self._reload_requested = asyncio.Event()

    def _narrow(self, existing: dict, requested: dict) -> dict:
        """Coglet capability has no scope narrowing — it's all-or-nothing."""
        return {**existing, **requested}

    # ── Game state accessors ──────────────────────────────────────────

    def get_observation(self) -> dict:
        """Get the current game observation as parsed tokens.

        Returns a dict of {agent_id: [(row, col, feature_name, value), ...]}.
        Empty dict if no observation is available yet.
        """
        return self._observation or {}

    def get_game_rules(self) -> dict:
        """Get the game rules (features, actions, tags, obs dimensions).

        Returns the GameRules dict sent during the prepare phase.
        """
        return self._game_rules or {}

    def get_episode_info(self) -> dict:
        """Get current episode metadata.

        Returns dict with episode_id, agent_ids, step_count, and timing info.
        """
        return self._episode_info or {}

    def get_policy_state(self) -> dict:
        """Get the persistent policy state dict.

        This dict persists across steps within an episode. Policy code can
        store arbitrary state here (e.g., role assignments, target tracking).
        """
        return self._policy_state

    # ── Action submission ─────────────────────────────────────────────

    def send_actions(self, actions: dict) -> None:
        """Send action names for each agent back to the game server.

        Args:
            actions: {agent_id: action_name} mapping.
        """
        if self._action_callback:
            self._action_callback(actions)
        else:
            logger.warning("send_actions called but no action callback is set")

    # ── Logging ───────────────────────────────────────────────────────

    def log_step(self, step_data: dict) -> None:
        """Append step data to the episode log.

        The step data is accumulated in memory and can be flushed to the
        file store by the executor.

        Args:
            step_data: Arbitrary dict with step-level information
                (observations summary, actions taken, reward, etc.)
        """
        step_data.setdefault("timestamp", time.time())
        self._step_log.append(step_data)

    def get_step_log(self) -> list[dict]:
        """Get all logged step data for the current episode."""
        return list(self._step_log)

    # ── Policy management ─────────────────────────────────────────────

    def request_policy_reload(self) -> None:
        """Signal that policy.py should be reloaded.

        Called by the strategist (cog) via channel message to trigger
        a hot-reload of the policy module.
        """
        self._reload_requested.set()

    def is_reload_requested(self) -> bool:
        """Check if a policy reload has been requested."""
        return self._reload_requested.is_set()

    def clear_reload_request(self) -> None:
        """Clear the reload request flag after reloading."""
        self._reload_requested.clear()

    # ── Internal setters (used by the executor, not by sandbox code) ──

    def _set_observation(self, obs: dict) -> None:
        """Set the current observation (called by executor)."""
        self._observation = obs

    def _set_game_rules(self, rules: dict) -> None:
        """Set game rules from the prepare phase (called by executor)."""
        self._game_rules = rules

    def _set_episode_info(self, info: dict) -> None:
        """Set episode metadata (called by executor)."""
        self._episode_info = info

    def _set_action_callback(self, callback: Any) -> None:
        """Set the callback for action submission (called by executor)."""
        self._action_callback = callback

    def _reset_episode(self) -> None:
        """Reset state for a new episode."""
        self._observation = None
        self._policy_state = {}
        self._step_log = []
        self._policy_module = None
        self._reload_requested.clear()
