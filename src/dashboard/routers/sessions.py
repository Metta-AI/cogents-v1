from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from brain.db.models import RunStatus
from dashboard.db import get_repo
from dashboard.models import Session, SessionsResponse

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
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


@router.get("/sessions", response_model=SessionsResponse)
def get_sessions(name: str):
    repo = get_repo()
    db_convs = repo.list_conversations()
    all_runs = repo.query_runs(limit=10000)

    runs_by_conv: dict[str, list] = {}
    for r in all_runs:
        if r.conversation_id:
            cid = str(r.conversation_id)
            runs_by_conv.setdefault(cid, []).append(r)

    sessions: list[Session] = []
    for c in db_convs:
        cid = str(c.id)
        conv_runs = runs_by_conv.get(cid, [])
        ok = sum(1 for r in conv_runs if r.status == RunStatus.COMPLETED)
        fail = sum(1 for r in conv_runs if r.status == RunStatus.FAILED)
        tokens_in = sum(r.tokens_input for r in conv_runs)
        tokens_out = sum(r.tokens_output for r in conv_runs)
        total_cost = float(sum(r.cost_usd for r in conv_runs))

        sessions.append(
            Session(
                id=cid,
                context_key=c.context_key,
                status=c.status.value if c.status else None,
                cli_session_id=c.cli_session_id,
                started_at=str(c.started_at) if c.started_at else None,
                last_active=str(c.last_active) if c.last_active else None,
                metadata=_try_parse_json(c.metadata),
                runs=len(conv_runs),
                ok=ok,
                fail=fail,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                total_cost=total_cost,
            )
        )

    return SessionsResponse(cogent_name=name, count=len(sessions), sessions=sessions)
