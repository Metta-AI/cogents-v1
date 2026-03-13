"""Configuration for the MettaGrid IO adapter."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MettaGridMode(str, Enum):
    CONNECT = "connect"  # dev mode: connect outbound to a game server
    LISTEN = "listen"  # tournament mode: listen for incoming connections


class MettaGridConfig(BaseModel):
    mode: MettaGridMode = Field(
        default=MettaGridMode.CONNECT,
        description="Whether to connect to a game server or listen for connections.",
    )
    server_url: Optional[str] = Field(
        default=None,
        description="WebSocket URL to connect to (connect mode). e.g. ws://localhost:8765",
    )
    listen_host: str = Field(
        default="0.0.0.0",
        description="Host to bind to (listen mode).",
    )
    listen_port: int = Field(
        default=8765,
        description="Port to listen on (listen mode).",
    )
    step_summary_interval: int = Field(
        default=50,
        description="Emit a step summary event to the channel every N steps.",
    )
    episode_log_path: str = Field(
        default="cvc/episode.log",
        description="Path within the file store for episode logs.",
    )
    policy_path: str = Field(
        default="cvc/cog-policy/policy.py",
        description="Path within the file store for the policy script.",
    )
