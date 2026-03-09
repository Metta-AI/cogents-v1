"""Resource capabilities — check resource availability."""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.db.repository import Repository
from cogos.sandbox.executor import CapabilityResult

logger = logging.getLogger(__name__)


def check(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    """Check resource availability for the calling process.

    Queries each resource the process requires and reports capacity vs current
    usage.  Since the repository does not yet have a dedicated resource-usage
    query, we fetch the process's resource list and look up each Resource record
    directly.
    """
    proc = repo.get_process(process_id)
    if proc is None:
        return CapabilityResult(content={"error": "process not found"})

    if not proc.resources:
        return CapabilityResult(content={"resources": [], "available": True})

    results = []
    all_available = True
    for resource_id in proc.resources:
        # Query current usage for this resource via a simple SQL count.
        rows = repo.query(
            """SELECT COALESCE(SUM(amount), 0) AS used
               FROM cogos_resource_usage ru
               JOIN cogos_run r ON r.id = ru.run
               WHERE ru.resource = :resource_id AND r.status = 'running'""",
            {"resource_id": resource_id},
        )
        used = float(rows[0]["used"]) if rows else 0.0

        # Fetch the resource record for capacity.
        res_rows = repo.query(
            "SELECT * FROM cogos_resource WHERE id = :id",
            {"id": resource_id},
        )
        if not res_rows:
            results.append({"id": str(resource_id), "error": "not found"})
            all_available = False
            continue

        res = res_rows[0]
        capacity = float(res.get("capacity", 0))
        remaining = capacity - used
        available = remaining > 0

        if not available:
            all_available = False

        results.append({
            "id": str(resource_id),
            "name": res.get("name", ""),
            "capacity": capacity,
            "used": used,
            "remaining": remaining,
            "available": available,
        })

    return CapabilityResult(
        content={"resources": results, "available": all_available},
    )
