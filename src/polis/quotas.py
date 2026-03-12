"""Service Quotas helpers for polis account provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from polis.config import ServiceQuotaTarget

_ACTIVE_REQUEST_STATUSES = {"PENDING", "CASE_OPENED"}


@dataclass(frozen=True)
class QuotaEnsureResult:
    quota_code: str
    quota_name: str
    desired_value: float
    region: str
    status: str
    current_value: float | None = None
    request_id: str | None = None
    note: str = ""


def ensure_service_quota_targets(
    session: Any,
    targets: list[ServiceQuotaTarget],
) -> list[QuotaEnsureResult]:
    """Ensure each quota target has either enough headroom or an open request."""
    results: list[QuotaEnsureResult] = []
    clients: dict[tuple[str, str], Any] = {}

    for target in targets:
        client_key = (target.service_code, target.region)
        client = clients.get(client_key)
        if client is None:
            client = session.client("service-quotas", region_name=target.region)
            clients[client_key] = client
        results.append(_ensure_service_quota_target(client, target))

    return results


def _ensure_service_quota_target(client: Any, target: ServiceQuotaTarget) -> QuotaEnsureResult:
    quota = _get_quota(client, target)
    current_value = float(quota.get("Value", 0))
    adjustable = quota.get("Adjustable", False)

    if current_value >= target.desired_value:
        return QuotaEnsureResult(
            quota_code=target.quota_code,
            quota_name=target.quota_name,
            desired_value=target.desired_value,
            region=target.region,
            status="satisfied",
            current_value=current_value,
        )

    pending = _find_pending_request(client, target)
    if pending:
        pending_value = float(pending.get("DesiredValue", 0))
        status = "pending" if pending_value >= target.desired_value else "pending_lower_value"
        note = ""
        if pending_value < target.desired_value:
            note = f"open request targets {pending_value:g}, below desired {target.desired_value:g}"
        return QuotaEnsureResult(
            quota_code=target.quota_code,
            quota_name=target.quota_name,
            desired_value=target.desired_value,
            region=target.region,
            status=status,
            current_value=current_value,
            request_id=pending.get("Id"),
            note=note,
        )

    if not adjustable:
        return QuotaEnsureResult(
            quota_code=target.quota_code,
            quota_name=target.quota_name,
            desired_value=target.desired_value,
            region=target.region,
            status="not_adjustable",
            current_value=current_value,
            note="quota is not adjustable via Service Quotas",
        )

    try:
        response = client.request_service_quota_increase(
            ServiceCode=target.service_code,
            QuotaCode=target.quota_code,
            DesiredValue=target.desired_value,
        )
    except ClientError as exc:
        return QuotaEnsureResult(
            quota_code=target.quota_code,
            quota_name=target.quota_name,
            desired_value=target.desired_value,
            region=target.region,
            status="error",
            current_value=current_value,
            note=str(exc),
        )

    requested = response.get("RequestedQuota", {})
    return QuotaEnsureResult(
        quota_code=target.quota_code,
        quota_name=target.quota_name,
        desired_value=target.desired_value,
        region=target.region,
        status="requested",
        current_value=current_value,
        request_id=requested.get("Id"),
    )


def _get_quota(client: Any, target: ServiceQuotaTarget) -> dict[str, Any]:
    try:
        return client.get_service_quota(
            ServiceCode=target.service_code,
            QuotaCode=target.quota_code,
        )["Quota"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchResourceException":
            raise
        return client.get_aws_default_service_quota(
            ServiceCode=target.service_code,
            QuotaCode=target.quota_code,
        )["Quota"]


def _find_pending_request(client: Any, target: ServiceQuotaTarget) -> dict[str, Any] | None:
    response = client.list_requested_service_quota_change_history_by_quota(
        ServiceCode=target.service_code,
        QuotaCode=target.quota_code,
    )
    requested = response.get("RequestedQuotas", [])
    pending = [item for item in requested if item.get("Status") in _ACTIVE_REQUEST_STATUSES]
    if not pending:
        return None
    return max(pending, key=lambda item: float(item.get("DesiredValue", 0)))
