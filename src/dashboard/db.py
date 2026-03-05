"""Singleton Repository for dashboard handlers.

Uses RDS Data API when credentials are configured, otherwise falls back to
LocalRepository for local development with persistent in-memory data.
"""

from __future__ import annotations

import logging

from brain.db.local_repository import LocalRepository
from brain.db.repository import Repository

logger = logging.getLogger(__name__)

_repo: Repository | LocalRepository | None = None


def get_repo() -> Repository | LocalRepository:
    """Return cached Repository singleton (reads env vars on first call).

    If Data API credentials are not set, returns a LocalRepository that
    stores data in-memory with JSON file persistence so the dashboard
    works with local data from the mind CLI.
    """
    global _repo
    if _repo is None:
        try:
            _repo = Repository.create()
            logger.info("Connected to database via Data API")
        except (ValueError, Exception) as exc:
            logger.warning("Database not configured, using local repository: %s", exc)
            _repo = LocalRepository()
    return _repo
