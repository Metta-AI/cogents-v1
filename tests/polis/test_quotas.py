from __future__ import annotations

from polis.config import ServiceQuotaTarget
from polis.quotas import ensure_service_quota_targets


class _FakeServiceQuotasClient:
    def __init__(self, *, quotas=None, history=None):
        self.quotas = quotas or {}
        self.history = history or {}
        self.requests: list[dict] = []

    def get_service_quota(self, *, ServiceCode: str, QuotaCode: str):
        return {"Quota": self.quotas[(ServiceCode, QuotaCode)]}

    def get_aws_default_service_quota(self, *, ServiceCode: str, QuotaCode: str):
        return {"Quota": self.quotas[(ServiceCode, QuotaCode)]}

    def list_requested_service_quota_change_history_by_quota(self, *, ServiceCode: str, QuotaCode: str):
        return {"RequestedQuotas": self.history.get((ServiceCode, QuotaCode), [])}

    def request_service_quota_increase(self, *, ServiceCode: str, QuotaCode: str, DesiredValue: float):
        request = {
            "ServiceCode": ServiceCode,
            "QuotaCode": QuotaCode,
            "DesiredValue": DesiredValue,
        }
        self.requests.append(request)
        return {"RequestedQuota": {"Id": "req-123", "DesiredValue": DesiredValue}}


class _FakeSession:
    def __init__(self, client):
        self._client = client

    def client(self, service_name: str, region_name: str | None = None):
        assert service_name == "service-quotas"
        assert region_name == "us-east-1"
        return self._client


def test_ensure_service_quota_targets_requests_increase_when_below_desired():
    client = _FakeServiceQuotasClient(
        quotas={
            ("bedrock", "L-1"): {
                "Value": 200,
                "Adjustable": True,
            }
        }
    )
    session = _FakeSession(client)
    targets = [
        ServiceQuotaTarget(
            quota_code="L-1",
            quota_name="Test quota",
            desired_value=500,
        )
    ]

    results = ensure_service_quota_targets(session, targets)

    assert client.requests == [{"ServiceCode": "bedrock", "QuotaCode": "L-1", "DesiredValue": 500}]
    assert results[0].status == "requested"
    assert results[0].current_value == 200


def test_ensure_service_quota_targets_skips_when_pending_request_is_already_open():
    client = _FakeServiceQuotasClient(
        quotas={
            ("bedrock", "L-1"): {
                "Value": 200,
                "Adjustable": True,
            }
        },
        history={
            ("bedrock", "L-1"): [
                {
                    "Id": "req-999",
                    "Status": "PENDING",
                    "DesiredValue": 500,
                }
            ]
        },
    )
    session = _FakeSession(client)
    targets = [
        ServiceQuotaTarget(
            quota_code="L-1",
            quota_name="Test quota",
            desired_value=500,
        )
    ]

    results = ensure_service_quota_targets(session, targets)

    assert client.requests == []
    assert results[0].status == "pending"
    assert results[0].request_id == "req-999"


def test_ensure_service_quota_targets_skips_when_current_value_is_sufficient():
    client = _FakeServiceQuotasClient(
        quotas={
            ("bedrock", "L-1"): {
                "Value": 750,
                "Adjustable": True,
            }
        }
    )
    session = _FakeSession(client)
    targets = [
        ServiceQuotaTarget(
            quota_code="L-1",
            quota_name="Test quota",
            desired_value=500,
        )
    ]

    results = ensure_service_quota_targets(session, targets)

    assert client.requests == []
    assert results[0].status == "satisfied"
    assert results[0].current_value == 750
