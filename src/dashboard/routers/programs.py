from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from dashboard.database import fetch_all
from dashboard.models import (
    Execution,
    ExecutionsResponse,
    Program,
    ProgramsResponse,
)

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
    """Parse a JSONB field that might already be a dict/list or might be a JSON string."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


@router.get("/programs", response_model=ProgramsResponse)
async def get_programs(name: str):
    # Execution stats per skill
    stats_rows = await fetch_all(
        "SELECT skill_name, "
        "count(*) AS runs, "
        "count(*) FILTER (WHERE status = 'completed') AS ok, "
        "count(*) FILTER (WHERE status = 'failed') AS fail, "
        "COALESCE(SUM(cost_usd), 0)::float AS total_cost, "
        "MAX(started_at)::text AS last_run "
        "FROM executions WHERE cogent_id = $1 "
        "GROUP BY skill_name",
        name,
    )
    stats_by_name: dict[str, dict] = {r["skill_name"]: r for r in stats_rows}

    # Skill definitions
    skill_rows = await fetch_all(
        "SELECT name, skill_type, description, sla, triggers FROM skills WHERE cogent_id = $1",
        name,
    )

    programs: list[Program] = []
    seen: set[str] = set()

    for row in skill_rows:
        sname = row["name"]
        seen.add(sname)
        sla = _try_parse_json(row.get("sla")) or {}
        triggers_json = _try_parse_json(row.get("triggers")) or []
        stats = stats_by_name.get(sname, {})

        programs.append(
            Program(
                name=sname,
                type=row.get("skill_type") or "markdown",
                description=row.get("description") or "",
                complexity=sla.get("complexity"),
                model=sla.get("model"),
                trigger_count=len(triggers_json) if isinstance(triggers_json, list) else 0,
                runs=stats.get("runs", 0),
                ok=stats.get("ok", 0),
                fail=stats.get("fail", 0),
                total_cost=stats.get("total_cost", 0),
                last_run=stats.get("last_run"),
            )
        )

    # Include skills that have executions but no definition row
    for sname, stats in stats_by_name.items():
        if sname not in seen:
            programs.append(
                Program(
                    name=sname,
                    runs=stats.get("runs", 0),
                    ok=stats.get("ok", 0),
                    fail=stats.get("fail", 0),
                    total_cost=stats.get("total_cost", 0),
                    last_run=stats.get("last_run"),
                )
            )

    return ProgramsResponse(cogent_id=name, count=len(programs), programs=programs)


@router.get("/programs/{program_name}/executions", response_model=ExecutionsResponse)
async def get_program_executions(name: str, program_name: str):
    rows = await fetch_all(
        "SELECT id::text, skill_name AS program_name, conversation_id::text, status, "
        "started_at::text, completed_at::text, duration_ms, "
        "tokens_input, tokens_output, COALESCE(cost_usd, 0)::float AS cost_usd, error "
        "FROM executions WHERE cogent_id = $1 AND skill_name = $2 "
        "ORDER BY started_at DESC",
        name,
        program_name,
    )
    executions = [Execution(**r) for r in rows]
    return ExecutionsResponse(cogent_id=name, count=len(executions), executions=executions)
