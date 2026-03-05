from __future__ import annotations

from fastapi import APIRouter

from dashboard.database import execute, fetch_all
from dashboard.models import ToggleRequest, ToggleResponse, Trigger, TriggersResponse

router = APIRouter(tags=["triggers"])


@router.get("/triggers", response_model=TriggersResponse)
async def list_triggers(name: str) -> TriggersResponse:
    sql = """
    SELECT t.id::text, t.trigger_type, t.event_pattern, t.cron_expression,
      t.skill_name, t.priority, t.enabled, t.created_at::text,
      (SELECT count(*) FROM executions s WHERE s.cogent_id = $1
        AND s.skill_name = t.skill_name AND s.started_at > now() - interval '1 minute') AS fired_1m,
      (SELECT count(*) FROM executions s WHERE s.cogent_id = $1
        AND s.skill_name = t.skill_name AND s.started_at > now() - interval '5 minutes') AS fired_5m,
      (SELECT count(*) FROM executions s WHERE s.cogent_id = $1
        AND s.skill_name = t.skill_name AND s.started_at > now() - interval '1 hour') AS fired_1h,
      (SELECT count(*) FROM executions s WHERE s.cogent_id = $1
        AND s.skill_name = t.skill_name AND s.started_at > now() - interval '24 hours') AS fired_24h
    FROM triggers t WHERE t.cogent_id = $1 ORDER BY t.priority
    """
    rows = await fetch_all(sql, name)

    triggers = []
    for r in rows:
        skill = r.get("skill_name") or ""
        pattern = r.get("event_pattern") or r.get("cron_expression") or ""
        trigger_name = f"{skill}:{pattern}" if pattern else skill

        triggers.append(
            Trigger(
                id=r["id"],
                name=trigger_name,
                trigger_type=r.get("trigger_type"),
                event_pattern=r.get("event_pattern"),
                cron_expression=r.get("cron_expression"),
                skill_name=r.get("skill_name"),
                priority=r.get("priority"),
                enabled=r.get("enabled", True),
                created_at=r.get("created_at"),
                fired_1m=r.get("fired_1m", 0),
                fired_5m=r.get("fired_5m", 0),
                fired_1h=r.get("fired_1h", 0),
                fired_24h=r.get("fired_24h", 0),
            )
        )

    return TriggersResponse(cogent_id=name, count=len(triggers), triggers=triggers)


@router.post("/triggers/toggle", response_model=ToggleResponse)
async def toggle_triggers(name: str, body: ToggleRequest) -> ToggleResponse:
    sql = "UPDATE triggers SET enabled = $1 WHERE id = ANY($2::uuid[]) AND cogent_id = $3"
    result = await execute(sql, body.enabled, body.ids, name)
    # asyncpg returns e.g. "UPDATE 3"
    count = int(result.split()[-1]) if result else 0
    return ToggleResponse(updated=count, enabled=body.enabled)
