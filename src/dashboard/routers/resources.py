from __future__ import annotations

from fastapi import APIRouter

from brain.db.models import ConversationStatus
from dashboard.db import get_repo
from dashboard.models import ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(name: str) -> ResourcesResponse:
    repo = get_repo()
    active = repo.list_conversations(status=ConversationStatus.ACTIVE)
    conversations = [
        {"id": str(c.id), "context_key": c.context_key, "cli_session_id": c.cli_session_id}
        for c in active
    ]
    return ResourcesResponse(
        cogent_name=name,
        active_sessions=len(conversations),
        conversations=conversations,
    )
