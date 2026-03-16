"""Shared capability resolution for coglet spawn."""

from __future__ import annotations

import importlib
import logging
from uuid import UUID

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


def build_spawn_caps(
    capabilities: list,
    repo: Repository,
    parent_process_id: UUID,
    overrides: dict | None = None,
) -> dict:
    """Build a spawn-compatible capabilities dict from coglet meta capabilities.

    Handles dict entries like {"name": "dir", "alias": "data", "config": {"prefix": "..."}}
    by using the "alias:name" grant syntax and creating scoped capability instances.
    """
    spawn_caps: dict = {}

    for cap_entry in capabilities:
        if isinstance(cap_entry, dict):
            cap_name = cap_entry["name"]
            alias = cap_entry.get("alias", cap_name)
            config = cap_entry.get("config")

            # Use "alias:capability" syntax so spawn resolves the real capability
            grant_key = f"{alias}:{cap_name}" if alias != cap_name else cap_name

            if config:
                instance = _make_scoped_instance(repo, parent_process_id, cap_name, config)
                spawn_caps[grant_key] = instance  # instance or None
            else:
                spawn_caps[grant_key] = None
        else:
            spawn_caps[cap_entry] = None

    if overrides:
        spawn_caps.update(overrides)

    return spawn_caps


def _make_scoped_instance(
    repo: Repository,
    process_id: UUID,
    cap_name: str,
    config: dict,
):
    """Look up a capability by name and return a scoped instance, or None on failure."""
    cap = repo.get_capability_by_name(cap_name)
    if not cap or not cap.handler:
        logger.warning("Capability '%s' not found or has no handler", cap_name)
        return None

    handler_path = cap.handler
    if ":" in handler_path:
        mod_path, attr_name = handler_path.rsplit(":", 1)
    elif "." in handler_path:
        mod_path, attr_name = handler_path.rsplit(".", 1)
    else:
        logger.warning("Cannot parse handler path '%s' for capability '%s'", handler_path, cap_name)
        return None

    try:
        mod = importlib.import_module(mod_path)
        handler_cls = getattr(mod, attr_name)
        instance = handler_cls(repo, process_id)
        return instance.scope(**config)
    except Exception:
        logger.warning("Could not scope capability '%s' with config %s", cap_name, config, exc_info=True)
        return None
