from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import Alert, AlertsResponse

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
def list_alerts(name: str) -> AlertsResponse:
    repo = get_repo()
    db_alerts = repo.get_unresolved_alerts()
    alerts = [
        Alert(
            id=str(a.id),
            severity=a.severity.value if a.severity else None,
            alert_type=a.alert_type,
            source=a.source,
            message=a.message,
            metadata=a.metadata,
            created_at=str(a.created_at) if a.created_at else None,
        )
        for a in db_alerts
    ]
    return AlertsResponse(cogent_name=name, count=len(alerts), alerts=alerts)
