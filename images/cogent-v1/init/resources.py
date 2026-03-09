"""Resources and capabilities to install on a fresh cogent."""

from cogos.capabilities import BUILTIN_CAPABILITIES

# ── Resource pools ──────────────────────────────────────────
RESOURCES = [
    {
        "name": "lambda_slots",
        "resource_type": "pool",
        "capacity": 5.0,
        "metadata": {"description": "Concurrent Lambda executor slots"},
    },
    {
        "name": "ecs_slots",
        "resource_type": "pool",
        "capacity": 2.0,
        "metadata": {"description": "Concurrent ECS task slots"},
    },
]

# ── Capabilities ────────────────────────────────────────────
# Re-export the full built-in set. Images can extend this list
# with additional capabilities specific to this cogent version.
CAPABILITIES = list(BUILTIN_CAPABILITIES)
