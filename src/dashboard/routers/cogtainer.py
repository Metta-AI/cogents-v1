"""Cogtainer-level endpoints (not cogent-scoped)."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogtainer"])

_LIST_TIMEOUT_S = 5


def _fetch_cogent_names() -> list[str]:
    from cogtainer.runtime.factory import create_executor_runtime

    runtime = create_executor_runtime()
    return runtime.list_cogents()


@router.get("/api/cogtainer/cogents")
def list_cogents() -> dict:
    """List all cogents on the current cogtainer, plus the current cogent name."""
    current = os.environ.get("COGENT", "")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            names = pool.submit(_fetch_cogent_names).result(timeout=_LIST_TIMEOUT_S)
    except TimeoutError:
        logger.warning("list_cogents timed out after %ss", _LIST_TIMEOUT_S)
        names = []
    except Exception:
        logger.warning("Could not list cogents from runtime", exc_info=True)
        names = []
    return {"cogents": names, "current": current}
