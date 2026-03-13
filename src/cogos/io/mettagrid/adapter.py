"""MettaGrid IO Adapter.

Bridges the MettaGrid game server WebSocket protocol into CogOS channels.
Supports two modes:
- CONNECT: outbound connection to a game server (local dev)
- LISTEN: inbound connections from tournament servers
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from cogos.io.base import InboundEvent, IOAdapter, IOMode
from cogos.io.mettagrid.config import MettaGridConfig, MettaGridMode
from cogos.io.mettagrid.protocol import (
    AgentObs,
    EpisodeState,
    GameRules,
    ObservationToken,
    build_prepare_response,
    obs_to_dict,
    parse_prepare_request,
    parse_triplet_v1,
)

logger = logging.getLogger(__name__)


class MettaGridAdapter(IOAdapter):
    """IO adapter that connects to a MettaGrid game server via WebSocket.

    Translates the MettaGrid protobuf policy protocol into CogOS InboundEvents
    and accepts action responses via send().
    """

    mode = IOMode.LIVE
    name = "mettagrid"

    def __init__(self, name: str = "mettagrid", config: Optional[MettaGridConfig] = None):
        super().__init__(name)
        self.config = config or MettaGridConfig()
        self._ws: Any = None
        self._server: Any = None
        self._episode: Optional[EpisodeState] = None
        self._pending_events: list[InboundEvent] = []
        self._action_future: Optional[asyncio.Future] = None
        self._connected = asyncio.Event()

    async def start(self) -> None:
        """Start the adapter in the configured mode."""
        if self.config.mode == MettaGridMode.CONNECT:
            if not self.config.server_url:
                raise ValueError("server_url is required in connect mode")
            logger.info("MettaGrid adapter connecting to %s", self.config.server_url)
            await self._connect(self.config.server_url)
        elif self.config.mode == MettaGridMode.LISTEN:
            logger.info(
                "MettaGrid adapter listening on %s:%d",
                self.config.listen_host,
                self.config.listen_port,
            )
            await self._listen(self.config.listen_host, self.config.listen_port)

    async def stop(self) -> None:
        """Close connections and stop the server."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def poll(self) -> list[InboundEvent]:
        """Return any pending game events.

        In the game loop, the adapter receives observations and emits them
        as InboundEvents for the cog-policy process to consume.
        """
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    async def send(self, message: str, target: str, **kwargs: Any) -> None:
        """Send an action response back to the game server.

        The message should be a JSON-encoded dict of {agent_id: action_name}.
        """
        if self._action_future and not self._action_future.done():
            self._action_future.set_result(message)

    async def _connect(self, url: str) -> None:
        """Connect to a game server (dev mode)."""
        try:
            import websockets  # noqa: PLC0415

            self._ws = await websockets.connect(url)
            self._connected.set()
            logger.info("Connected to MettaGrid server at %s", url)
        except ImportError:
            raise ImportError("websockets package required: pip install websockets")

    async def _listen(self, host: str, port: int) -> None:
        """Start a WebSocket server for tournament mode."""
        try:
            import websockets  # noqa: PLC0415

            self._server = await websockets.serve(self._handle_connection, host, port)
            logger.info("MettaGrid policy server listening on %s:%d", host, port)
        except ImportError:
            raise ImportError("websockets package required: pip install websockets")

    async def _handle_connection(self, ws: Any) -> None:
        """Handle an incoming WebSocket connection from a game server."""
        logger.info("Game server connected")
        self._ws = ws
        self._connected.set()

        try:
            # Phase 1: Prepare (JSON)
            prepare_msg = await ws.recv()
            if not isinstance(prepare_msg, str):
                logger.error("Expected JSON prepare message, got binary")
                return

            episode_id, game_rules, agent_ids = parse_prepare_request(prepare_msg)
            self._episode = EpisodeState(
                episode_id=episode_id,
                game_rules=game_rules,
                agent_ids=agent_ids,
            )

            # Emit episode_start event
            self._pending_events.append(
                InboundEvent(
                    source="mettagrid",
                    message_type="episode_start",
                    payload={
                        "episode_id": episode_id,
                        "agent_ids": agent_ids,
                        "game_rules": game_rules.to_dict(),
                    },
                    raw_content=prepare_msg,
                )
            )

            # Send prepare response
            await ws.send(build_prepare_response())
            logger.info("Episode %s prepared with %d agents", episode_id, len(agent_ids))

            # Phase 2: Step loop (binary protobuf)
            async for message in ws:
                if not isinstance(message, bytes):
                    logger.warning("Expected binary step message, got text")
                    continue

                await self._handle_step(ws, message)

        except Exception:
            logger.exception("Error in game connection")
        finally:
            logger.info("Game server disconnected")
            if self._episode:
                self._pending_events.append(
                    InboundEvent(
                        source="mettagrid",
                        message_type="episode_end",
                        payload={
                            "episode_id": self._episode.episode_id,
                            "total_steps": self._episode.step_count,
                        },
                    )
                )
            self._episode = None
            self._connected.clear()

    async def _handle_step(self, ws: Any, raw_message: bytes) -> None:
        """Handle a single BatchStepRequest.

        Parses observations, emits an event, waits for actions, sends response.
        """
        if not self._episode:
            logger.error("Received step message without active episode")
            return

        episode = self._episode
        episode.step_count += 1

        # Parse observations from the raw protobuf
        # In the full implementation, this uses policy_pb2.BatchStepRequest.ParseFromString()
        # For the skeleton, we emit the raw bytes for the executor to handle
        self._pending_events.append(
            InboundEvent(
                source="mettagrid",
                message_type="step",
                payload={
                    "episode_id": episode.episode_id,
                    "step_id": episode.step_count,
                    "raw_size": len(raw_message),
                },
                raw_content=f"step:{episode.step_count}",
            )
        )

        # Emit periodic summaries for the strategist
        if episode.step_count % self.config.step_summary_interval == 0:
            self._pending_events.append(
                InboundEvent(
                    source="mettagrid",
                    message_type="step_summary",
                    payload={
                        "episode_id": episode.episode_id,
                        "step_id": episode.step_count,
                    },
                )
            )
