"""Resource definitions for this cogent."""

from mind.loader import CogentMindResource

resources = [
    CogentMindResource(
        name="concurrent-tasks",
        resource_type="pool",
        capacity=3,
        metadata={"description": "Max concurrent task executions"},
    ),
    CogentMindResource(
        name="lambda",
        resource_type="pool",
        capacity=5,
        metadata={"description": "Lambda executor concurrency"},
    ),
    CogentMindResource(
        name="ecs",
        resource_type="pool",
        capacity=2,
        metadata={"description": "ECS executor concurrency"},
    ),
    CogentMindResource(
        name="daily-token-budget",
        resource_type="consumable",
        capacity=1_000_000,
        metadata={"description": "Daily token spending limit"},
    ),
]
