"""Starter policy for MettaGrid — random movement with basic resource seeking."""

import math
import random


def step(obs, game_rules, state):
    """Compute actions for all agents.

    Simple starter policy:
    - If a resource (mine/generator) is visible, move toward it
    - If an altar is visible and we have inventory, move toward it
    - Otherwise, random movement

    Args:
        obs: {agent_id: [(row, col, feature_name, value), ...]}
        game_rules: dict with features, actions, tags, obs_height, obs_width
        state: persistent dict across steps

    Returns:
        (actions, state)
    """
    actions = {}
    center = game_rules.get("obs_height", 13) // 2
    move_actions = ["move_north", "move_south", "move_east", "move_west"]

    for agent_id, tokens in obs.items():
        # Parse what we see
        resources = []
        altars = []
        enemies = []
        inventory = {}

        for row, col, feature, value in tokens:
            if feature in ("mine", "generator"):
                resources.append((row, col, feature, value))
            elif feature == "altar":
                altars.append((row, col))
            elif feature == "agent" and (row != center or col != center):
                enemies.append((row, col))
            elif feature.startswith("inv:"):
                inventory[feature] = value

        # Decision logic
        has_inventory = any(v > 0 for v in inventory.values())

        target = None
        if has_inventory and altars:
            # Carry resources to altar
            target = min(altars, key=lambda p: _dist(p, center))
        elif resources:
            # Go collect resources
            closest = min(resources, key=lambda r: _dist((r[0], r[1]), center))
            target = (closest[0], closest[1])

        if target:
            actions[agent_id] = _move_toward(target[0], target[1], center)
        else:
            actions[agent_id] = random.choice(move_actions)

    return actions, state


def _dist(pos, center):
    """Manhattan distance from center."""
    return abs(pos[0] - center) + abs(pos[1] - center)


def _move_toward(row, col, center):
    """Pick a movement action toward a target position."""
    dr = row - center
    dc = col - center

    if abs(dr) > abs(dc):
        return "move_south" if dr > 0 else "move_north"
    elif dc != 0:
        return "move_east" if dc > 0 else "move_west"
    else:
        return "noop"
