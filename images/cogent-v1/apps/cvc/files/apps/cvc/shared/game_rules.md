# MettaGrid Game Rules

## Overview

MettaGrid is a multi-agent competitive grid world. Agents navigate a 2D map, interact with objects and other agents, collect resources, and earn rewards.

## Observation Format (TRIPLET_V1)

Each agent sees a **13x13 egocentric grid** centered on itself. Observations are a list of tokens:

```
(row, col, feature_name, value)
```

- `row`, `col`: Position relative to the agent (0-12, agent is at center ~6,6)
- `feature_name`: What the agent sees at that position
- `value`: Feature-specific value (0-255)

### Common Features

| Feature | Description |
|---------|-------------|
| `agent` | Another agent (value = agent type/team) |
| `wall` | Impassable wall |
| `mine` | Resource mine (value = resource type) |
| `generator` | Resource generator |
| `altar` | Altar for scoring |
| `heart` | Heart item |
| `inv:heart` | Hearts in inventory |
| `inv:ore` | Ore in inventory |
| `tag` | Tag status (can tag/be tagged) |
| `hp` | Hit points |
| `frozen` | Agent is frozen |
| `energy` | Agent energy level |

## Action Space

### Movement Actions
- `noop` — do nothing
- `move_north` — move up
- `move_south` — move down
- `move_east` — move right
- `move_west` — move left
- `rotate_cw` — rotate clockwise
- `rotate_ccw` — rotate counter-clockwise

### Interaction Actions
- `use` — interact with object in front
- `attack` — attack agent in front
- `gift` — give resource to agent in front
- `swap` — swap position with agent in front

### Vibe Actions (modifiers)
- `change_vibe_happy` — set vibe to happy
- `change_vibe_sad` — set vibe to sad
- `change_vibe_neutral` — set vibe to neutral

Actions are submitted as string names and encoded to integer IDs by the protocol layer.

## Strategy Concepts

### Roles
Agents can be assigned different roles:
- **Miner**: Navigate to mines, collect resources
- **Scorer**: Carry resources to altars for points
- **Guard**: Protect miners and scorers from opponents
- **Scout**: Explore the map, find resources and threats

### Key Tactics
- **Resource chains**: Miners collect → pass to scorers → scorers deposit at altars
- **Territory control**: Guard key resources and chokepoints
- **Opponent disruption**: Tag opponents to freeze them temporarily
- **Energy management**: Movement costs energy; plan efficient paths

## policy.py Template

```python
import math
import random

def step(obs, game_rules, state):
    """Compute actions for all agents.

    Args:
        obs: {agent_id: [(row, col, feature_name, value), ...]}
        game_rules: {features, actions, tags, action_names, obs_height, obs_width}
        state: persistent dict, mutable

    Returns:
        (actions, state) where actions = {agent_id: action_name}
    """
    actions = {}
    center = game_rules.get("obs_height", 13) // 2

    for agent_id, tokens in obs.items():
        # Default: random movement
        moves = ["move_north", "move_south", "move_east", "move_west"]
        actions[agent_id] = random.choice(moves)

    return actions, state
```
