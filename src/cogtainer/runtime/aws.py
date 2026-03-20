"""AwsRuntime — run cogents on AWS (S3, DynamoDB, Lambda, EventBridge)."""

from __future__ import annotations

import json
import logging
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)

_STATUS_TABLE = "cogent-status"


class AwsRuntime(CogtainerRuntime):
    """Cogtainer runtime backed by AWS services."""

    def __init__(
        self,
        entry: CogtainerEntry,
        llm: LLMProvider,
        session: Any,
    ) -> None:
        self._entry = entry
        self._llm = llm
        self._session = session
        self._region = entry.region or "us-east-1"

    # ── Repository ───────────────────────────────────────────

    def get_repository(self, cogent_name: str) -> Any:
        from cogos.db.repository import Repository

        ddb = self._session.resource("dynamodb", region_name=self._region)
        item = (
            ddb.Table(_STATUS_TABLE)
            .get_item(Key={"cogent_name": cogent_name})
            .get("Item", {})
        )
        db_info = item.get("database", {})
        cluster_arn = db_info.get("cluster_arn", "")
        secret_arn = db_info.get("secret_arn", "")
        db_name = db_info.get("db_name", f"cogent_{cogent_name.replace('.', '_')}")

        client = self._session.client("rds-data", region_name=self._region)
        return Repository(
            client=client,
            resource_arn=cluster_arn,
            secret_arn=secret_arn,
            database=db_name,
            region=self._region,
        )

    # ── LLM ──────────────────────────────────────────────────

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        return self._llm.converse(
            messages=messages,
            system=system,
            tool_config=tool_config,
            model=model,
        )

    # ── File storage ─────────────────────────────────────────

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        from polis.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        s3.put_object(
            Bucket=bucket_name(cogent_name),
            Key=key,
            Body=data,
        )
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        from polis.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        resp = s3.get_object(
            Bucket=bucket_name(cogent_name),
            Key=key,
        )
        return resp["Body"].read()

    # ── Events ───────────────────────────────────────────────

    def emit_event(self, cogent_name: str, event: dict) -> None:
        from polis.naming import safe

        eb = self._session.client("events", region_name=self._region)
        safe_name = safe(cogent_name)
        eb.put_events(
            Entries=[
                {
                    "Source": f"cogent.{cogent_name}",
                    "DetailType": event.get("type", "cogent.event"),
                    "Detail": json.dumps(event),
                    "EventBusName": f"cogent-{safe_name}",
                },
            ],
        )

    # ── Executor ─────────────────────────────────────────────

    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        from polis.naming import safe

        lam = self._session.client("lambda", region_name=self._region)
        safe_name = safe(cogent_name)
        lam.invoke(
            FunctionName=f"cogent-{safe_name}-executor",
            InvocationType="Event",
            Payload=json.dumps({"process_id": process_id}).encode(),
        )

    # ── Cogent lifecycle ─────────────────────────────────────

    def list_cogents(self) -> list[str]:
        ddb = self._session.resource("dynamodb", region_name=self._region)
        table = ddb.Table(_STATUS_TABLE)
        resp = table.scan()
        items = resp.get("Items", [])
        return sorted(item["cogent_name"] for item in items)

    def create_cogent(self, name: str) -> None:
        raise NotImplementedError("Cogent provisioning is handled by CDK")

    def destroy_cogent(self, name: str) -> None:
        raise NotImplementedError("Cogent destruction is handled by CDK")
