# Coglet Protocol: MettaGrid Integration Design

## Overview

This document describes how to integrate MettaGrid game server connectivity into cogents-v1, enabling `dr.alpha` (a cogent) to play in MettaGrid tournaments. The integration introduces a **coglet** — a CogOS process tree that connects to a MettaGrid game server via WebSocket, speaks the MettaGrid protobuf policy protocol, and uses an LLM to dynamically rewrite game policy based on observations.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  CogOS                                                       │
│                                                              │
│  ┌──────────┐   channel:cvc/game_events   ┌──────────────┐  │
│  │          │ ◄────────────────────────── │              │  │
│  │   cog    │                             │  cog-policy  │  │
│  │ (daemon) │ ──────────────────────────► │  (daemon)    │  │
│  │          │   file: cvc/policy.py       │              │  │
│  └──────────┘                             └──────┬───────┘  │
│       │                                          │          │
│       │ reads cvc/episode.log                    │ WebSocket │
│       │ rewrites cvc/policy.py                   │          │
│       │                                          │          │
│       │                                    ┌─────▼───────┐  │
│       │                                    │  MettaGrid  │  │
│       │                                    │  IO Adapter  │  │
│       │                                    │  (WS client) │  │
│       │                                    └─────┬───────┘  │
└───────┼──────────────────────────────────────────┼──────────┘
        │                                          │
        │                                          │ protobuf over WS
        │                                          │
                                             ┌─────▼───────┐
                                             │  MettaGrid  │
                                             │ Game Server  │
                                             └─────────────┘
```

### Two-Process Model

**`cog-policy`** (daemon) — The game-facing process:
- Listens on a WebSocket for incoming game server connections (tournament mode) OR connects outbound to a local game server (dev mode)
- Receives observations via the MettaGrid protobuf protocol (`BatchStepRequest`)
- Executes `policy.py` (a Python file in its sandbox) to compute actions
- Returns actions via protobuf (`BatchStepResponse`)
- Logs each step's observations and actions to `episode.log`
- Emits game events to the `cvc/game_events` channel

**`cog`** (daemon) — The strategist process:
- Reads `episode.log` to understand game state and performance
- Uses the LLM (Bedrock converse) to analyze strategy and rewrite `policy.py`
- Monitors game events from the `cvc/game_events` channel
- This is the standard CogOS process execution model (search + run_code tools)

## MettaGrid Policy Protocol

The protocol is defined in `mettagrid.protobuf.sim.policy_v1.policy_pb2` (source: [Metta-AI/mettagrid](https://github.com/Metta-AI/mettagrid)).

### Connection Lifecycle

```
Game Server ──► WebSocket connect ──► Policy (coglet)

1. PREPARE (JSON):
   Server sends: PreparePolicyRequest {
     episode_id: str,
     game_rules: GameRules { features[], actions[] },
     agent_ids: int[],
     observations_format: TRIPLET_V1,
     env_interface: PolicyEnvInterface { obs_features, tags, action_names, ... }
   }
   Policy replies: PreparePolicyResponse {}

2. STEP LOOP (binary protobuf):
   Server sends: BatchStepRequest {
     episode_id: str,
     step_id: int,
     agent_observations: [{ agent_id, observations: bytes }]
   }
   Policy replies: BatchStepResponse {
     agent_actions: [{ agent_id, action_id: int[] }]
   }

3. Server closes WebSocket when episode ends.
```

### Observation Format (TRIPLET_V1)

Observations are packed as `bytes` — a sequence of 3-byte triplets:
- Byte 0: `loc_byte` — packed row/col in a 13x13 egocentric grid (upper nibble = row, lower = col; 0xFF = skip)
- Byte 1: `feature_id` — maps to `GameRules.Feature` (name like "tag", "inv:heart", etc.)
- Byte 2: `value` — feature value (0-255)

### Action Space

Actions are integer IDs mapping to `GameRules.Action` names:
- Primary: `noop`, `move_north`, `move_south`, `move_east`, `move_west`, etc.
- Vibe: `change_vibe_happy`, `change_vibe_sad`, etc.
- Composite: primary × vibe encoded as offset

## Components to Build

### 1. MettaGrid IO Adapter (`src/cogos/io/mettagrid/`)

A new IO adapter that bridges the MettaGrid WebSocket protocol into CogOS.

```python
# src/cogos/io/mettagrid/adapter.py

class MettaGridAdapter(IOAdapter):
    """Bridges MettaGrid game server WebSocket to CogOS channels."""

    mode = IOMode.LIVE  # persistent WebSocket connection

    def __init__(self, name: str, config: MettaGridConfig):
        super().__init__(name)
        self.config = config
        self._ws = None
        self._episode = None    # current episode state
        self._game_rules = None

    async def start(self):
        """Either connect to a game server or start listening for connections."""
        if self.config.mode == "connect":
            # Dev mode: connect outbound to local game server
            self._ws = await websocket_connect(self.config.server_url)
        elif self.config.mode == "listen":
            # Tournament mode: listen for incoming connections
            self._server = await websocket_serve(self._handler, ...)

    async def poll(self) -> list[InboundEvent]:
        """Receive next BatchStepRequest, return as InboundEvent."""
        ...

    async def send(self, message: str, target: str, **kwargs):
        """Send BatchStepResponse back to the game server."""
        ...
```

**Key design decisions:**
- Uses `IOMode.LIVE` — the adapter maintains a persistent WebSocket connection
- In **tournament mode**: listens on a port; game server connects to us
- In **dev mode**: connects outbound to a local game server
- Translates protobuf messages to/from CogOS `InboundEvent` payloads
- The adapter does NOT contain policy logic — it's pure transport

### 2. Coglet Capability (`src/cogos/capabilities/coglet.py`)

A new capability that gives `cog-policy` the ability to interact with the game.

```python
class CogletCapability:
    """Capability for MettaGrid game interaction."""

    # Injected into cog-policy's sandbox as proxy functions:

    def get_observation(self) -> dict:
        """Get the current game observation as parsed tokens."""
        ...

    def send_actions(self, actions: dict[int, int]):
        """Send action IDs for each agent back to the game server."""
        ...

    def get_game_rules(self) -> dict:
        """Get the game rules (features, actions, tags)."""
        ...

    def get_episode_info(self) -> dict:
        """Get current episode metadata."""
        ...

    def log_step(self, step_data: dict):
        """Append step data to episode.log."""
        ...
```

### 3. CvC App Image (`images/cogent-v1/apps/cvc/`)

Following the pattern of existing apps (like `recruiter`):

```
images/cogent-v1/apps/cvc/
├── init/
│   ├── processes.py     # defines cog + cog-policy processes
│   ├── channels.py      # cvc/game_events channel
│   └── schemas.py       # game event schema
├── files/
│   ├── cog/
│   │   └── system.md    # system prompt for the strategist
│   ├── cog-policy/
│   │   ├── system.md    # system prompt for the policy executor
│   │   └── policy.py    # initial starter policy
│   └── shared/
│       └── game_rules.md  # MettaGrid game documentation
└── README.md
```

#### Process Definitions

```python
# images/cogent-v1/apps/cvc/init/processes.py

def init(t):
    # The policy executor — runs the game loop
    t.add_process(
        name="cog-policy",
        mode="daemon",
        content="files://cvc/cog-policy/system.md",
        runner="lambda",  # or "ecs" for tournament
        priority=10,  # high priority — game loop is time-sensitive
        capabilities=["file", "coglet", "channels"],
        handlers=[{"channel": "cvc/game_events", "enabled": True}],
    )

    # The strategist — observes and rewrites policy
    t.add_process(
        name="cog",
        mode="daemon",
        content="files://cvc/cog/system.md",
        runner="lambda",
        priority=5,
        capabilities=["file", "procs", "channels", "web_search"],
        handlers=[{"channel": "cvc/game_events", "enabled": True}],
    )
```

### 4. Policy Execution Model

The `cog-policy` process has a fundamentally different execution model from standard CogOS processes. Standard processes run an LLM converse loop (prompt → tool_use → result → repeat). `cog-policy` instead runs a **game loop**:

```
┌─────────────────────────────────────────┐
│  cog-policy game loop                   │
│                                         │
│  1. Receive PreparePolicyRequest        │
│  2. Parse game rules, set up env        │
│  3. Load policy.py from file store      │
│  4. Loop:                               │
│     a. Receive BatchStepRequest         │
│     b. Parse observations               │
│     c. Execute policy.py in sandbox     │
│     d. Encode actions                   │
│     e. Send BatchStepResponse           │
│     f. Log step to episode.log          │
│     g. Every N steps: emit summary      │
│        to cvc/game_events channel       │
│  5. Episode ends → write final log      │
│                                         │
└─────────────────────────────────────────┘
```

This requires a **new runner type** or a specialized execution path in the existing handler. Options:

**Option A: Custom runner type `coglet`**
- Add `runner="coglet"` to the process model
- New executor module `src/cogos/executor/coglet.py` that implements the game loop
- Clean separation, but more code to maintain

**Option B: Sandbox-based execution within existing runner**
- `cog-policy` is a standard process, but its system prompt instructs it to use `run_code` tool calls in a loop
- The LLM calls `coglet.get_observation()` → `run_code(policy.py)` → `coglet.send_actions()` in a loop
- Works within existing architecture, but adds latency per step (LLM round trip)

**Option C: Hybrid — fast-path game loop with LLM fallback**
- `cog-policy` starts as a standard process but immediately enters a fast-path game loop via a special `coglet.run_game_loop()` capability call
- The game loop runs Python directly (no LLM), executing `policy.py` in the sandbox
- If `policy.py` errors or the strategist signals a reload, the process briefly enters LLM mode to handle the error/reload, then returns to the fast path

**Recommended: Option C (Hybrid)**. This gives us:
- Sub-millisecond action latency (no LLM in the hot path)
- Clean fallback to LLM for error handling and policy reloads
- Compatible with the existing process model

### 5. The Strategist's Role (`cog` process)

The `cog` process runs as a standard CogOS daemon process using the LLM:

1. **Monitors** `episode.log` via the `file` capability
2. **Receives** periodic game summaries via `cvc/game_events` channel
3. **Analyzes** game performance: reward trends, actions taken, observations seen
4. **Rewrites** `cvc/cog-policy/policy.py` using `run_code` tool
5. **Signals** `cog-policy` via channel message to reload the policy

The system prompt for `cog` includes:
- MettaGrid game rules documentation
- The observation/action format
- The `policy.py` API contract
- Strategy guidance (CogsGuard roles, territory control, etc.)

### 6. Tournament Submission

For tournament play, the coglet exposes a WebSocket endpoint:

```
Tournament Server ──► WebSocket ──► coglet (listening on port)
```

Submission type: **WebSocket endpoint URL**

The deployment would be:
1. `cog-policy` runs in ECS (long-running container)
2. Exposes a WebSocket port via ALB
3. Tournament server connects to the endpoint
4. `cog` runs alongside, rewriting policy in real-time

For the `cogames submit` flow, we'd package the coglet as a Docker container that:
- Starts the WebSocket policy server
- Runs the CogOS local executor with the cvc app image
- Exposes port 8765 (or configurable)

## Channels & Schemas

### `cvc/game_events` channel

```json
{
  "type": "object",
  "properties": {
    "event_type": {
      "enum": ["episode_start", "step_summary", "episode_end", "policy_reload_request"]
    },
    "episode_id": { "type": "string" },
    "step_id": { "type": "integer" },
    "data": { "type": "object" }
  }
}
```

Event types:
- `episode_start` — game rules, agent IDs, map info
- `step_summary` — every N steps: reward, actions taken, notable observations
- `episode_end` — final stats, total reward
- `policy_reload_request` — from `cog` to `cog-policy`: reload `policy.py`

## Policy.py Contract

The `policy.py` file that the strategist writes must conform to:

```python
def step(obs: dict, game_rules: dict, state: dict) -> tuple[dict, dict]:
    """
    Compute actions for all agents given observations.

    Args:
        obs: {agent_id: [list of (row, col, feature_name, value) tokens]}
        game_rules: {features: [...], actions: [...], tags: [...]}
        state: persistent dict across steps (mutable)

    Returns:
        (actions, state) where actions = {agent_id: action_name}
    """
    ...
```

The coglet runtime:
1. Parses raw protobuf observations into the `obs` dict format
2. Calls `step(obs, game_rules, state)` in the sandbox
3. Encodes returned action names back to protobuf action IDs
4. Maintains `state` across steps within an episode

## Development Workflow

### Local Development

```bash
# 1. Start a local MettaGrid game
cogames play -p class=cogames.policy.starter_agent.StarterPolicy

# 2. Start the coglet connecting to local game
python -m cogos local --image cogent-v1 --app cvc \
    --env METTAGRID_MODE=connect \
    --env METTAGRID_SERVER_URL=ws://localhost:8765

# 3. Watch the strategist rewrite policy in real-time
tail -f data/cogent-v1/files/cvc/episode.log
```

### Tournament Play

```bash
# Build and submit the coglet container
cogames submit --name dr-alpha-coglet \
    --type websocket \
    --image ghcr.io/metta-ai/cogent-v1-cvc:latest
```

## File Manifest

New files to create:

```
src/cogos/io/mettagrid/
├── __init__.py
├── adapter.py          # MettaGridAdapter (WebSocket bridge)
├── protocol.py         # Protobuf message helpers (parse/encode)
└── config.py           # MettaGridConfig model

src/cogos/capabilities/coglet.py    # CogletCapability

src/cogos/executor/coglet.py        # Game loop executor (Option C fast-path)

images/cogent-v1/apps/cvc/
├── init/
│   ├── processes.py
│   ├── channels.py
│   └── schemas.py
├── files/
│   ├── cog/system.md
│   ├── cog-policy/system.md
│   ├── cog-policy/policy.py        # Initial starter policy
│   └── shared/game_rules.md
└── README.md
```

Modified files:

```
src/cogos/capabilities/__init__.py  # Register "coglet" capability
src/cogos/db/models/process.py      # Add "coglet" runner type (if Option A/C)
```

## Dependencies

New Python packages:
- `websockets` — async WebSocket client/server
- `protobuf` — Google Protocol Buffers runtime
- `mettagrid` — MettaGrid policy protocol (protobuf definitions only, vendored or dependency)

## Open Questions

1. **Protobuf vendoring**: Should we vendor the `policy_pb2` generated code, or take a dependency on `mettagrid`? Vendoring keeps us decoupled but requires manual sync.

2. **Action latency budget**: Tournament servers have a `max_action_time_ms` (seen as 10000ms in validation). The hybrid approach (Option C) gives us well within budget, but if we want to invoke the LLM per step (Option B), we need to verify the timeout.

3. **Multi-episode**: A tournament may run multiple episodes. The adapter should handle reconnection and episode lifecycle cleanly.

4. **Observation summarization**: Raw observations are large (hundreds of tokens × 3 bytes). The strategist needs a compressed summary, not raw bytes. The `step_summary` event should include human-readable state (position, inventory, nearby objects, reward).
