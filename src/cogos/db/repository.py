from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

logger = logging.getLogger(__name__)


class RdsBackend:

    def __init__(
        self,
        client: Any,
        resource_arn: str,
        secret_arn: str,
        database: str,
        region: str = "us-east-1",
    ) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database
        self._region = region

    @classmethod
    def create(
        cls,
        resource_arn: str | None = None,
        secret_arn: str | None = None,
        database: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> RdsBackend:
        resource_arn = resource_arn or os.environ.get("DB_RESOURCE_ARN", "") or os.environ.get("DB_CLUSTER_ARN", "")
        secret_arn = secret_arn or os.environ.get("DB_SECRET_ARN", "")
        database = database or os.environ.get("DB_NAME", "")
        region = region or os.environ.get("AWS_REGION", "us-east-1")

        if not all([resource_arn, secret_arn, database]):
            raise ValueError(
                "Must provide resource_arn, secret_arn, and database "
                "via arguments or environment variables "
                "(DB_RESOURCE_ARN/DB_CLUSTER_ARN, DB_SECRET_ARN, DB_NAME)"
            )
        if client is None:
            raise ValueError(
                "client parameter is required. The caller must create and pass "
                "an rds-data client (e.g. via runtime.get_rds_data_client())."
            )
        return cls(client, resource_arn, secret_arn, database, region)

    def _to_param(self, name: str, value: Any) -> dict:
        param: dict[str, Any] = {"name": name}
        if value is None:
            param["value"] = {"isNull": True}
        elif isinstance(value, bool):
            param["value"] = {"booleanValue": value}
        elif isinstance(value, int):
            param["value"] = {"longValue": value}
        elif isinstance(value, float):
            param["value"] = {"doubleValue": value}
        elif isinstance(value, Decimal):
            param["value"] = {"stringValue": str(value)}
        elif isinstance(value, UUID):
            param["value"] = {"stringValue": str(value)}
            param["typeHint"] = "UUID"
        elif isinstance(value, datetime):
            param["value"] = {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S.%f")}
            param["typeHint"] = "TIMESTAMP"
        elif isinstance(value, (dict, list)):
            param["value"] = {"stringValue": json.dumps(value, default=str)}
        elif isinstance(value, str):
            param["value"] = {"stringValue": value}
        else:
            logger.debug("Param %s has non-standard type %s; converting via str()", name, type(value).__name__)
            param["value"] = {"stringValue": str(value)}
        return param

    def _execute_raw(self, sql: str, params: list[dict] | None = None) -> dict:
        kwargs: dict[str, Any] = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "includeResultMetadata": True,
        }
        if params:
            kwargs["parameters"] = params
        try:
            return self._client.execute_statement(**kwargs)
        except Exception:
            import re as _re
            jsonb_params = set(_re.findall(r":(\w+)::jsonb", sql))
            if jsonb_params and params:
                for p in params:
                    name = p.get("name", "?")
                    if name in jsonb_params:
                        sv = p.get("value", {}).get("stringValue")
                        if sv is not None:
                            logger.debug("JSONB param %s value (first 200 chars): %s", name, sv[:200])
            logger.warning("Failing SQL: %s", sql[:500])
            raise

    @staticmethod
    def _extract_value(cell: dict) -> Any:
        if "isNull" in cell and cell["isNull"]:
            return None
        if "stringValue" in cell:
            return cell["stringValue"]
        if "longValue" in cell:
            return cell["longValue"]
        if "doubleValue" in cell:
            return cell["doubleValue"]
        if "booleanValue" in cell:
            return cell["booleanValue"]
        return None

    def _rows_to_dicts(self, response: dict) -> list[dict[str, Any]]:
        if "records" not in response or not response["records"]:
            return []
        column_names = [col["name"] for col in response.get("columnMetadata", [])]
        rows = []
        for record in response["records"]:
            row = {}
            for col_name, cell in zip(column_names, record, strict=False):
                row[col_name] = self._extract_value(cell)
            rows.append(row)
        return rows

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        api_params = [self._to_param(k, v) for k, v in params.items()] if params else None
        response = self._execute_raw(sql, api_params)
        return response.get("numberOfRecordsUpdated", 0)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        api_params = [self._to_param(k, v) for k, v in params.items()] if params else None
        return self._rows_to_dicts(self._execute_raw(sql, api_params))

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def batch_execute(self, sql: str, param_sets: list[dict[str, Any]]) -> int:
        api_param_sets = [
            [self._to_param(k, v) for k, v in ps.items()]
            for ps in param_sets
        ]
        self._client.batch_execute_statement(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            database=self._database,
            sql=sql,
            parameterSets=api_param_sets,
        )
        return len(param_sets)

    def json_param(self, name: str) -> str:
        return f":{name}::jsonb"

    @staticmethod
    def json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(json.dumps(value, default=str))
        except (TypeError, ValueError):
            logger.warning("json_safe: could not serialize %s, wrapping as string", type(value).__name__)
            return {"_raw": str(value)}

    def json_safe_dict(self, value: Any) -> dict:
        result = self.json_safe(value)
        if result is None:
            return {}
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"
        return result

    def json_safe_list(self, value: Any) -> list:
        result = self.json_safe(value)
        if result is None:
            return []
        assert isinstance(result, list), f"Expected list, got {type(result).__name__}"
        return result

    def json_decode(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value

    def json_decode_dict(self, value: Any) -> dict:
        result = self.json_decode(value)
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        return {}

    def json_decode_list(self, value: Any) -> list:
        result = self.json_decode(value)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return []

    def ilike(self, col: str, param: str) -> str:
        return f"{col} ILIKE :{param}"

    def regex_match(self, col: str, param: str) -> str:
        return f"{col} ~ :{param}"

    def t(self, canonical_name: str) -> str:
        mapping = {
            "cron": "cron",
            "alerts": "alerts",
            "resources": "resources",
        }
        return mapping.get(canonical_name, canonical_name)

    def cron_col(self, canonical: str) -> str:
        mapping = {
            "expression": "cron_expression",
            "payload": "metadata",
        }
        return mapping.get(canonical, canonical)

    @property
    def reboot_epoch(self) -> int:
        meta = self.get_meta("reboot_epoch")
        if meta and meta.get("value"):
            return int(meta["value"])
        return 0

    def increment_epoch(self) -> int:
        new_epoch = self.reboot_epoch + 1
        self.set_meta("reboot_epoch", str(new_epoch))
        return new_epoch

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            """INSERT INTO cogos_meta (key, value, updated_at)
               VALUES (:key, :value, now())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            {"key": key, "value": value},
        )

    def get_meta(self, key: str) -> dict[str, str] | None:
        row = self.query_one(
            "SELECT key, value, updated_at FROM cogos_meta WHERE key = :key",
            {"key": key},
        )
        if not row:
            return None
        updated_at = row.get("updated_at", "")
        if updated_at and isinstance(updated_at, str):
            dt = datetime.fromisoformat(updated_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            updated_at = str(dt)
        return {"key": row["key"], "value": row.get("value", ""), "updated_at": updated_at or ""}
