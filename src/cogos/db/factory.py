"""Repository selection helpers for local and remote CogOS runtimes."""

from __future__ import annotations

import os
from typing import Any


def create_repository(
    *,
    resource_arn: str | None = None,
    secret_arn: str | None = None,
    database: str | None = None,
    region: str | None = None,
) -> Any:
    """Create the active repository implementation for the current environment."""
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.local_repository import LocalRepository

        return LocalRepository()

    from cogos.db.repository import Repository

    return Repository.create(
        resource_arn=resource_arn,
        secret_arn=secret_arn,
        database=database,
        region=region,
    )
