"""MettaGrid policy protocol helpers.

Handles parsing and encoding of the protobuf-over-WebSocket policy protocol
defined in mettagrid.protobuf.sim.policy_v1.policy_pb2.

The protocol flow:
1. PreparePolicyRequest (JSON) -> PreparePolicyResponse (JSON)
2. BatchStepRequest (binary protobuf) -> BatchStepResponse (binary protobuf)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ObservationToken:
    row: int
    col: int
    feature_id: int
    feature_name: str
    value: int


@dataclass
class AgentObs:
    agent_id: int
    tokens: list[ObservationToken] = field(default_factory=list)


@dataclass
class GameAction:
    id: int
    name: str


@dataclass
class GameFeature:
    id: int
    name: str
    normalization: float


@dataclass
class GameRules:
    features: list[GameFeature] = field(default_factory=list)
    actions: list[GameAction] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    action_names: list[str] = field(default_factory=list)
    obs_height: int = 13
    obs_width: int = 13

    @property
    def feature_by_id(self) -> dict[int, GameFeature]:
        return {f.id: f for f in self.features}

    @property
    def action_by_name(self) -> dict[str, int]:
        return {a.name: a.id for a in self.actions}

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": [{"id": f.id, "name": f.name, "normalization": f.normalization} for f in self.features],
            "actions": [{"id": a.id, "name": a.name} for a in self.actions],
            "tags": self.tags,
            "action_names": self.action_names,
            "obs_height": self.obs_height,
            "obs_width": self.obs_width,
        }


@dataclass
class EpisodeState:
    episode_id: str
    game_rules: GameRules
    agent_ids: list[int]
    step_count: int = 0
    policy_state: dict = field(default_factory=dict)


def parse_triplet_v1(
    data: bytes, features: dict[int, GameFeature], obs_height: int = 13, obs_width: int = 13
) -> list[ObservationToken]:
    """Parse TRIPLET_V1 observation format.

    Each token is 3 bytes: (loc_byte, feature_id, value).
    loc_byte encodes row in upper nibble, col in lower nibble.
    0xFF loc_byte means skip/empty.
    """
    tokens = []
    for i in range(0, len(data) - 2, 3):
        loc_byte, feature_id, value = data[i], data[i + 1], data[i + 2]
        if loc_byte == 0xFF:
            continue
        row = (loc_byte >> 4) & 0x0F
        col = loc_byte & 0x0F
        feature = features.get(feature_id)
        if feature is None:
            continue
        tokens.append(
            ObservationToken(
                row=row,
                col=col,
                feature_id=feature_id,
                feature_name=feature.name,
                value=value,
            )
        )
    return tokens


def parse_prepare_request(message: str) -> tuple[str, GameRules, list[int]]:
    """Parse a PreparePolicyRequest JSON message.

    Returns (episode_id, game_rules, agent_ids).
    """
    data = json.loads(message)

    features = []
    actions = []
    tags = []
    action_names = []
    obs_height = 13
    obs_width = 13

    if "gameRules" in data:
        gr = data["gameRules"]
        features = [
            GameFeature(id=f["id"], name=f["name"], normalization=f.get("normalization", 1.0))
            for f in gr.get("features", [])
        ]
        actions = [GameAction(id=a["id"], name=a["name"]) for a in gr.get("actions", [])]
        action_names = [a.name for a in actions]

    if "envInterface" in data:
        ei = data["envInterface"]
        tags = ei.get("tags", [])
        if "actionNames" in ei:
            action_names = ei["actionNames"]
        obs_height = ei.get("obsHeight", 13)
        obs_width = ei.get("obsWidth", 13)

    game_rules = GameRules(
        features=features,
        actions=actions,
        tags=tags,
        action_names=action_names,
        obs_height=obs_height,
        obs_width=obs_width,
    )

    agent_ids = data.get("agentIds", [])
    episode_id = data.get("episodeId", "unknown")

    return episode_id, game_rules, agent_ids


def build_prepare_response() -> str:
    """Build a PreparePolicyResponse JSON message (empty object)."""
    return "{}"


def parse_batch_step_request(data: bytes, game_rules: GameRules) -> tuple[int, list[AgentObs]]:
    """Parse a BatchStepRequest binary protobuf message.

    Returns (step_id, list of AgentObs).

    NOTE: This is a pure-Python implementation that parses the protobuf
    wire format without requiring the generated protobuf code. For production
    use, import mettagrid.protobuf.sim.policy_v1.policy_pb2 directly.
    """
    # For the skeleton, we use a simplified approach:
    # In production, this should use the actual protobuf library.
    # For now, return a placeholder that the adapter can override
    # with the real protobuf parsing.
    raise NotImplementedError(
        "Use parse_batch_step_request_pb() with the protobuf library, "
        "or implement wire-format parsing."
    )


def build_batch_step_response(agent_actions: dict[int, list[int]]) -> bytes:
    """Build a BatchStepResponse binary protobuf message.

    NOTE: Same as above — skeleton for the wire format.
    In production, use the protobuf library.
    """
    raise NotImplementedError(
        "Use build_batch_step_response_pb() with the protobuf library, "
        "or implement wire-format encoding."
    )


def obs_to_dict(
    agent_obs_list: list[AgentObs], game_rules: GameRules
) -> dict[int, list[tuple[int, int, str, int]]]:
    """Convert parsed observations to the dict format expected by policy.py.

    Returns: {agent_id: [(row, col, feature_name, value), ...]}
    """
    result = {}
    for agent_obs in agent_obs_list:
        result[agent_obs.agent_id] = [
            (t.row, t.col, t.feature_name, t.value) for t in agent_obs.tokens
        ]
    return result


def actions_to_ids(
    actions: dict[int, str], game_rules: GameRules
) -> dict[int, list[int]]:
    """Convert action names back to protobuf action IDs.

    Returns: {agent_id: [action_id]}
    """
    name_to_id = game_rules.action_by_name
    result = {}
    for agent_id, action_name in actions.items():
        action_id = name_to_id.get(action_name)
        if action_id is None:
            logger.warning("Unknown action name %r for agent %d, defaulting to 0 (noop)", action_name, agent_id)
            action_id = 0
        result[agent_id] = [action_id]
    return result
