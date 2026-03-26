from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID, uuid4

from cogos.db.backend import DatabaseBackend
from cogos.db.models import (
    ALL_EPOCHS,
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    CogosOperation,
    Cron,
    Delivery,
    DeliveryStatus,
    Executor,
    ExecutorStatus,
    ExecutorToken,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    Run,
    RunStatus,
    Schema,
    Span,
    SpanEvent,
    SpanStatus,
    Trace,
)
from cogos.db.models.alert import Alert, AlertSeverity
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.db.models.trace import RequestTrace
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _uuid(val: Any) -> UUID:
    return UUID(val) if isinstance(val, str) else val


def _opt_uuid(val: Any) -> UUID | None:
    if not val:
        return None
    return UUID(val) if isinstance(val, str) else val


def _dt(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class UnifiedRepository:

    def __init__(
        self,
        backend: DatabaseBackend,
        nudge_callback: Any | None = None,
    ) -> None:
        self._b = backend
        self._ingress_queue_url = os.environ.get("COGOS_INGRESS_QUEUE_URL", "")
        self._nudge_callback = nudge_callback

    # ── Batch / Transaction ───────────────────────────────────

    @contextmanager
    def batch(self) -> Iterator[None]:
        with self._b.transaction():
            yield

    # ── Raw SQL ───────────────────────────────────────────────

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return self._b.query(sql, params)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return self._b.execute(sql, params)

    # ── Epoch ─────────────────────────────────────────────────

    @property
    def reboot_epoch(self) -> int:
        return self._b.reboot_epoch

    def increment_epoch(self) -> int:
        return self._b.increment_epoch()

    # ── Nudge ─────────────────────────────────────────────────

    def _nudge_ingress(self, *, process_id: UUID | None = None) -> None:
        if not self._ingress_queue_url or self._nudge_callback is None:
            return
        try:
            body: dict = {"source": "channel_message"}
            if process_id is not None:
                body["process_id"] = str(process_id)
            self._nudge_callback(self._ingress_queue_url, json.dumps(body))
        except Exception:
            logger.debug("Failed to nudge ingress queue", exc_info=True)

    # ── Bulk Clear ────────────────────────────────────────────

    _ALL_TABLES = [
        "cogos_span_event", "cogos_span", "cogos_request_trace",
        "cogos_trace", "cogos_delivery", "cogos_channel_message",
        "cogos_run", "cogos_handler", "cogos_process_capability",
        "{alerts}", "{cron}",
        "cogos_file_version", "cogos_file",
        "cogos_channel", "cogos_schema",
        "cogos_process", "cogos_capability",
        "cogos_operation", "{resources}", "cogos_meta",
        "cogos_executor", "cogos_executor_token",
        "cogos_discord_channel", "cogos_discord_guild",
        "cogos_wait_condition",
    ]

    _CONFIG_TABLES = [
        "cogos_span_event", "cogos_span", "cogos_request_trace",
        "cogos_trace", "cogos_delivery", "cogos_channel_message",
        "cogos_run", "cogos_handler", "cogos_process_capability",
        "{cron}",
    ]

    _CONFIG_TABLES_FINAL = ["cogos_process", "cogos_capability"]

    def clear_all(self) -> None:
        for table in self._ALL_TABLES:
            self._b.execute(f"DELETE FROM {self._b.t(table.strip('{}')) if '{' in table else table}")
        self._b.execute("UPDATE cogos_epoch SET epoch = 0 WHERE id = 1")

    def clear_config(self) -> None:
        for table in self._CONFIG_TABLES:
            self._b.execute(f"DELETE FROM {self._b.t(table.strip('{}')) if '{' in table else table}")
        self._b.execute(
            "UPDATE cogos_channel SET owner_process = NULL WHERE owner_process IS NOT NULL"
        )
        for table in self._CONFIG_TABLES_FINAL:
            self._b.execute(f"DELETE FROM {table}")

    def delete_files_by_prefixes(self, prefixes: list[str]) -> int:
        total = 0
        for prefix in prefixes:
            self._b.execute(
                "DELETE FROM cogos_file_version WHERE file_id IN "
                "(SELECT id FROM cogos_file WHERE key LIKE :prefix)",
                {"prefix": prefix + "%"},
            )
            total += self._b.execute(
                "DELETE FROM cogos_file WHERE key LIKE :prefix",
                {"prefix": prefix + "%"},
            )
        return total

    # ── Row Converters ────────────────────────────────────────

    def _row_to_process(self, row: dict) -> Process:
        resources_raw = self._b.json_decode_list(row.get("resources"))
        resources = [UUID(r) for r in resources_raw] if resources_raw else []
        status_raw = row["status"]
        status = ProcessStatus({"running": "waiting", "completed": "disabled"}.get(status_raw, status_raw))
        return Process(
            id=_uuid(row["id"]),
            epoch=row.get("epoch", 0),
            name=row["name"],
            mode=ProcessMode(row["mode"]),
            content=row.get("content", ""),
            priority=row.get("priority", 0.0),
            resources=resources,
            required_tags=self._b.json_decode_list(row.get("required_tags")),
            executor=row.get("executor", "llm"),
            status=status,
            runnable_since=_dt(row.get("runnable_since")),
            parent_process=_opt_uuid(row.get("parent_process")),
            preemptible=bool(row.get("preemptible", False)),
            model=row.get("model"),
            model_constraints=self._b.json_decode_dict(row.get("model_constraints")),
            return_schema=self._b.json_decode(row.get("return_schema")),
            idle_timeout_ms=row.get("idle_timeout_ms"),
            max_duration_ms=row.get("max_duration_ms"),
            max_retries=row.get("max_retries", 0),
            retry_count=row.get("retry_count", 0),
            retry_backoff_ms=row.get("retry_backoff_ms"),
            clear_context=bool(row.get("clear_context", False)),
            tty=bool(row.get("tty", False)),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            output_events=self._b.json_decode_list(row.get("output_events")) if row.get("output_events") else [],
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
        )

    def _row_to_capability(self, row: dict) -> Capability:
        return Capability(
            id=_uuid(row["id"]),
            name=row["name"],
            description=row.get("description", ""),
            instructions=row.get("instructions", ""),
            handler=row.get("handler", ""),
            schema=self._b.json_decode_dict(row.get("schema")),
            iam_role_arn=row.get("iam_role_arn"),
            enabled=bool(row.get("enabled", True)),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
        )

    def _row_to_handler(self, row: dict) -> Handler:
        return Handler(
            id=_uuid(row["id"]),
            epoch=row.get("epoch", 0),
            process=_uuid(row["process"]),
            channel=_opt_uuid(row.get("channel")),
            enabled=bool(row.get("enabled", True)),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_process_capability(self, row: dict) -> ProcessCapability:
        return ProcessCapability(
            id=_uuid(row["id"]),
            process=_uuid(row["process"]),
            capability=_opt_uuid(row.get("capability")),
            name=row.get("name", ""),
            config=self._b.json_decode(row.get("config")),
            epoch=row.get("epoch", 0),
        )

    def _row_to_file(self, row: dict) -> File:
        return File(
            id=_uuid(row["id"]),
            key=row["key"],
            includes=self._b.json_decode_list(row.get("includes")),
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
        )

    def _row_to_file_version(self, row: dict) -> FileVersion:
        return FileVersion(
            id=_uuid(row["id"]),
            file_id=_uuid(row["file_id"]),
            version=row["version"],
            read_only=bool(row.get("read_only", False)),
            content=row.get("content", ""),
            source=row.get("source", "cogent"),
            is_active=bool(row.get("is_active", True)),
            run_id=_opt_uuid(row.get("run_id")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_resource(self, row: dict) -> Resource:
        return Resource(
            name=row["name"],
            resource_type=ResourceType(row["resource_type"]),
            capacity=float(row.get("capacity", 1.0)),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_cron(self, row: dict) -> Cron:
        return Cron(
            id=_uuid(row["id"]),
            expression=row[self._b.cron_col("expression")],
            channel_name=row.get("channel_name", ""),
            payload=self._b.json_decode_dict(row.get(self._b.cron_col("payload"))),
            enabled=bool(row.get("enabled", True)),
        )

    def _row_to_delivery(self, row: dict) -> Delivery:
        return Delivery(
            id=_uuid(row["id"]),
            epoch=row.get("epoch", 0),
            message=_uuid(row["message"]),
            handler=_uuid(row["handler"]),
            status=DeliveryStatus(row["status"]),
            run=_opt_uuid(row.get("run")),
            trace_id=_opt_uuid(row.get("trace_id")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_run(self, row: dict) -> Run:
        return Run(
            id=_uuid(row["id"]),
            epoch=row.get("epoch", 0),
            process=_uuid(row["process"]),
            message=_opt_uuid(row.get("message")),
            conversation=_opt_uuid(row.get("conversation")),
            status=RunStatus(row["status"]),
            tokens_in=row.get("tokens_in", 0),
            tokens_out=row.get("tokens_out", 0),
            cost_usd=Decimal(str(row.get("cost_usd", 0))),
            duration_ms=row.get("duration_ms"),
            error=row.get("error"),
            model_version=row.get("model_version"),
            result=self._b.json_decode(row.get("result")),
            snapshot=self._b.json_decode(row.get("snapshot")),
            scope_log=self._b.json_decode_list(row.get("scope_log")),
            trace_id=_opt_uuid(row.get("trace_id")),
            parent_trace_id=_opt_uuid(row.get("parent_trace_id")),
            metadata=self._b.json_decode(row.get("metadata")),
            created_at=_dt(row.get("created_at")),
            completed_at=_dt(row.get("completed_at")),
        )

    def _row_to_schema(self, row: dict) -> Schema:
        return Schema(
            id=_uuid(row["id"]),
            name=row["name"],
            definition=self._b.json_decode_dict(row.get("definition")),
            file_id=_opt_uuid(row.get("file_id")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_channel(self, row: dict) -> Channel:
        return Channel(
            id=_uuid(row["id"]),
            name=row["name"],
            owner_process=_opt_uuid(row.get("owner_process")),
            schema_id=_opt_uuid(row.get("schema_id")),
            inline_schema=self._b.json_decode(row.get("inline_schema")),
            channel_type=ChannelType(row["channel_type"]),
            auto_close=bool(row.get("auto_close", False)),
            closed_at=_dt(row.get("closed_at")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_channel_message(self, row: dict) -> ChannelMessage:
        return ChannelMessage(
            id=_uuid(row["id"]),
            channel=_uuid(row["channel"]),
            sender_process=_opt_uuid(row.get("sender_process")),
            sender_run_id=_opt_uuid(row.get("sender_run_id")),
            payload=self._b.json_decode_dict(row.get("payload")),
            trace_id=_opt_uuid(row.get("trace_id")),
            trace_meta=self._b.json_decode(row.get("trace_meta")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_executor(self, row: dict) -> Executor:
        run_id = row.get("current_run_id")
        return Executor(
            id=_uuid(row["id"]),
            executor_id=row["executor_id"],
            channel_type=row.get("channel_type", "claude-code"),
            executor_tags=self._b.json_decode_list(row.get("executor_tags")),
            dispatch_type=row.get("dispatch_type", "channel"),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            status=ExecutorStatus(row.get("status", "idle")),
            current_run_id=_opt_uuid(run_id),
            last_heartbeat_at=_dt(row.get("last_heartbeat_at")),
            registered_at=_dt(row.get("registered_at")),
        )

    def _row_to_executor_token(self, row: dict) -> ExecutorToken:
        return ExecutorToken(
            id=_uuid(row["id"]),
            name=row["name"],
            token_hash=row["token_hash"],
            scope=row.get("scope", "executor"),
            created_at=_dt(row.get("created_at")),
            revoked_at=_dt(row.get("revoked_at")),
        )

    def _row_to_wait_condition(self, row: dict) -> WaitCondition:
        return WaitCondition(
            id=_uuid(row["id"]),
            run=_opt_uuid(row.get("run")),
            process=_opt_uuid(row.get("process")),
            type=WaitConditionType(row["type"]),
            status=WaitConditionStatus(row["status"]),
            pending=self._b.json_decode_list(row.get("pending")),
            created_at=_dt(row.get("created_at")),
            resolved_at=_dt(row.get("resolved_at")),
        )

    def _row_to_trace(self, row: dict) -> Trace:
        return Trace(
            id=_uuid(row["id"]),
            run=_uuid(row["run"]),
            capability_calls=self._b.json_decode_list(row.get("capability_calls")),
            file_ops=self._b.json_decode_list(row.get("file_ops")),
            model_version=row.get("model_version"),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_alert(self, row: dict) -> Alert:
        return Alert(
            id=_uuid(row["id"]) if isinstance(row.get("id"), str) else row.get("id"),
            severity=AlertSeverity(row["severity"]),
            alert_type=row["alert_type"],
            source=row["source"],
            message=row.get("message", ""),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            acknowledged_at=_dt(row.get("acknowledged_at")),
            resolved_at=_dt(row.get("resolved_at")),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_discord_guild(self, row: dict) -> DiscordGuild:
        return DiscordGuild(
            guild_id=row["guild_id"],
            cogent_name=row["cogent_name"],
            name=row["name"],
            icon_url=row.get("icon_url"),
            member_count=row.get("member_count"),
            synced_at=_dt(row.get("synced_at")),
        )

    def _row_to_discord_channel(self, row: dict) -> DiscordChannel:
        return DiscordChannel(
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            name=row["name"],
            topic=row.get("topic"),
            category=row.get("category"),
            channel_type=row["channel_type"],
            position=row.get("position", 0),
            synced_at=_dt(row.get("synced_at")),
        )

    def _row_to_request_trace(self, row: dict) -> RequestTrace:
        return RequestTrace(
            id=_uuid(row["id"]),
            cogent_id=row.get("cogent_id", ""),
            source=row.get("source", ""),
            source_ref=row.get("source_ref"),
            created_at=_dt(row.get("created_at")),
        )

    def _row_to_span(self, row: dict) -> Span:
        return Span(
            id=_uuid(row["id"]),
            trace_id=_uuid(row["trace_id"]),
            parent_span_id=_opt_uuid(row.get("parent_span_id")),
            name=row["name"],
            coglet=row.get("coglet"),
            status=SpanStatus(row["status"]),
            started_at=_dt(row.get("started_at")),
            ended_at=_dt(row.get("ended_at")),
            metadata=self._b.json_decode_dict(row.get("metadata")),
        )

    def _row_to_span_event(self, row: dict) -> SpanEvent:
        return SpanEvent(
            id=_uuid(row["id"]),
            span_id=_uuid(row["span_id"]),
            event=row["event"],
            message=row.get("message"),
            timestamp=_dt(row.get("timestamp")),
            metadata=self._b.json_decode_dict(row.get("metadata")),
        )

    def _row_to_operation(self, row: dict) -> CogosOperation:
        return CogosOperation(
            id=_uuid(row["id"]),
            epoch=row.get("epoch", 0),
            type=row.get("type", ""),
            metadata=self._b.json_decode_dict(row.get("metadata")),
            created_at=_dt(row.get("created_at")),
        )

    # ── Meta ──────────────────────────────────────────────────

    def set_meta(self, key: str, value: str = "") -> None:
        self._b.set_meta(key, value)

    def get_meta(self, key: str) -> dict[str, str] | None:
        return self._b.get_meta(key)

    # ── Operations ────────────────────────────────────────────

    def add_operation(self, op: CogosOperation) -> UUID:
        now = op.created_at.isoformat() if op.created_at else _now()
        self._b.execute(
            f"""INSERT INTO cogos_operation (id, epoch, type, metadata, created_at)
               VALUES (:id, :epoch, :type, {self._b.json_param('metadata')}, :created_at)""",
            {"id": op.id, "epoch": op.epoch, "type": op.type,
             "metadata": self._b.json_safe_dict(op.metadata), "created_at": now},
        )
        return op.id

    def list_operations(self, limit: int = 50) -> list[CogosOperation]:
        rows = self._b.query(
            "SELECT * FROM cogos_operation ORDER BY created_at DESC LIMIT :limit",
            {"limit": limit},
        )
        return [self._row_to_operation(r) for r in rows]

    # ── Processes ─────────────────────────────────────────────

    def upsert_process(self, p: Process) -> UUID:
        if not p.epoch:
            p.epoch = self.reboot_epoch
        now = _now()
        jp = self._b.json_param
        row = self._b.query_one(
            f"""INSERT INTO cogos_process
                   (id, name, mode, content, priority, resources, required_tags, executor,
                    status, runnable_since, parent_process, preemptible,
                    model, model_constraints, return_schema,
                    idle_timeout_ms, max_duration_ms, max_retries, retry_count, retry_backoff_ms,
                    clear_context, tty, metadata, output_events, epoch, schema_id,
                    created_at, updated_at)
               VALUES (:id, :name, :mode, :content, :priority, {jp('resources')}, {jp('required_tags')}, :executor,
                       :status, :runnable_since, :parent_process, :preemptible,
                       :model, {jp('model_constraints')}, {jp('return_schema')},
                       :idle_timeout_ms, :max_duration_ms, :max_retries, :retry_count, :retry_backoff_ms,
                       :clear_context, :tty, {jp('metadata')}, {jp('output_events')}, :epoch, :schema_id,
                       :created_at, :updated_at)
               ON CONFLICT (name, epoch) DO UPDATE SET
                   mode = EXCLUDED.mode, content = EXCLUDED.content,
                   priority = EXCLUDED.priority,
                   status = EXCLUDED.status,
                   resources = EXCLUDED.resources, required_tags = EXCLUDED.required_tags,
                   executor = EXCLUDED.executor,
                   preemptible = EXCLUDED.preemptible, model = EXCLUDED.model,
                   model_constraints = EXCLUDED.model_constraints,
                   return_schema = EXCLUDED.return_schema,
                   idle_timeout_ms = EXCLUDED.idle_timeout_ms,
                   max_duration_ms = EXCLUDED.max_duration_ms,
                   max_retries = EXCLUDED.max_retries,
                   retry_backoff_ms = EXCLUDED.retry_backoff_ms,
                   clear_context = EXCLUDED.clear_context,
                   tty = EXCLUDED.tty,
                   metadata = EXCLUDED.metadata,
                   output_events = EXCLUDED.output_events,
                   epoch = EXCLUDED.epoch,
                   schema_id = EXCLUDED.schema_id,
                   updated_at = EXCLUDED.updated_at
               RETURNING id, created_at, updated_at""",
            {
                "id": p.id, "name": p.name, "mode": p.mode.value,
                "content": p.content, "priority": p.priority,
                "resources": self._b.json_safe([str(r) for r in p.resources]),
                "required_tags": self._b.json_safe(p.required_tags),
                "executor": p.executor,
                "status": p.status.value,
                "runnable_since": p.runnable_since.isoformat() if p.runnable_since else None,
                "parent_process": p.parent_process,
                "preemptible": p.preemptible,
                "model": p.model,
                "model_constraints": self._b.json_safe_dict(p.model_constraints),
                "return_schema": self._b.json_safe(p.return_schema),
                "idle_timeout_ms": p.idle_timeout_ms,
                "max_duration_ms": p.max_duration_ms,
                "max_retries": p.max_retries,
                "retry_count": p.retry_count,
                "retry_backoff_ms": p.retry_backoff_ms,
                "clear_context": p.clear_context,
                "tty": p.tty,
                "metadata": self._b.json_safe_dict(p.metadata),
                "output_events": self._b.json_safe(getattr(p, "output_events", [])),
                "epoch": p.epoch,
                "schema_id": getattr(p, "schema_id", None),
                "created_at": now, "updated_at": now,
            },
        )
        if not row:
            raise RuntimeError("Failed to upsert process")
        p.id = _uuid(row["id"])
        p.created_at = _dt(row["created_at"])
        p.updated_at = _dt(row["updated_at"])

        for stream in ("stdin", "stdout", "stderr"):
            ch = Channel(
                name=f"io:{stream}:{p.name}",
                owner_process=p.id,
                channel_type=ChannelType.NAMED,
            )
            self.upsert_channel(ch)

        stdin_ch = self.get_channel_by_name(f"io:stdin:{p.name}")
        if stdin_ch:
            existing = self._b.query_one(
                "SELECT id FROM cogos_handler WHERE process = :pid AND channel = :cid",
                {"pid": p.id, "cid": stdin_ch.id},
            )
            if not existing:
                self._b.execute(
                    """INSERT INTO cogos_handler (id, process, channel, enabled)
                       VALUES (:id, :pid, :cid, :enabled)
                       ON CONFLICT DO NOTHING""",
                    {"id": Handler(process=p.id, channel=stdin_ch.id).id,
                     "pid": p.id, "cid": stdin_ch.id, "enabled": True},
                )

        return p.id

    def get_process(self, process_id: UUID) -> Process | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_process WHERE id = :id", {"id": process_id},
        )
        return self._row_to_process(row) if row else None

    def get_process_by_name(self, name: str) -> Process | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_process WHERE name = :name AND epoch = :epoch",
            {"name": name, "epoch": self.reboot_epoch},
        )
        return self._row_to_process(row) if row else None

    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params["epoch"] = effective_epoch
        if status:
            conditions.append("status = :status")
            params["status"] = status.value
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._b.query(
            f"SELECT * FROM cogos_process{where} ORDER BY name LIMIT :limit", params,
        )
        return [self._row_to_process(r) for r in rows]

    def try_transition_process(
        self, process_id: UUID, from_status: ProcessStatus, to_status: ProcessStatus,
    ) -> bool:
        now = _now()
        count = self._b.execute(
            """UPDATE cogos_process SET status = :to_status, updated_at = :now
               WHERE id = :id AND status = :from_status""",
            {"id": process_id, "to_status": to_status.value,
             "from_status": from_status.value, "now": now},
        )
        return count > 0

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        now = _now()
        params: dict[str, Any] = {"id": process_id, "status": status.value, "now": now}
        if status == ProcessStatus.RUNNABLE:
            existing = self._b.query_one(
                "SELECT runnable_since FROM cogos_process WHERE id = :id", {"id": process_id},
            )
            runnable_since = existing.get("runnable_since") if existing else None
            params["runnable_since"] = runnable_since or now
        else:
            params["runnable_since"] = None
        count = self._b.execute(
            """UPDATE cogos_process SET status = :status,
               runnable_since = :runnable_since, updated_at = :now
               WHERE id = :id""",
            params,
        )
        if status == ProcessStatus.DISABLED:
            self._cascade_disable(process_id)
            self.resolve_wait_conditions_for_process(process_id)
        return count > 0

    def _cascade_disable(self, parent_id: UUID) -> None:
        children = self._b.query(
            "SELECT id FROM cogos_process WHERE parent_process = :pid AND status != 'disabled'",
            {"pid": parent_id},
        )
        for row in children:
            child_id = _uuid(row["id"])
            self._b.execute(
                "UPDATE cogos_process SET status = 'disabled', updated_at = :now WHERE id = :id",
                {"id": child_id, "now": _now()},
            )
            self._cascade_disable(child_id)

    def delete_process(self, process_id: UUID) -> bool:
        return self._b.execute(
            "DELETE FROM cogos_process WHERE id = :id", {"id": process_id},
        ) > 0

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        rows = self._b.query(
            """SELECT * FROM cogos_process
               WHERE status = 'runnable' AND epoch = :epoch
               ORDER BY priority DESC, runnable_since ASC, name ASC
               LIMIT :limit""",
            {"epoch": self.reboot_epoch, "limit": limit},
        )
        return [self._row_to_process(r) for r in rows]

    def increment_retry(self, process_id: UUID) -> bool:
        return self._b.execute(
            "UPDATE cogos_process SET retry_count = retry_count + 1, updated_at = :now WHERE id = :id",
            {"id": process_id, "now": _now()},
        ) > 0

    # ── Wait Conditions ───────────────────────────────────────

    def create_wait_condition(self, wc: WaitCondition) -> UUID:
        now = _now()
        self._b.execute(
            f"""INSERT INTO cogos_wait_condition (id, run, process, type, status, pending, created_at)
               VALUES (:id, :run, :process, :type, :status, {self._b.json_param('pending')}, :created_at)""",
            {"id": wc.id, "run": wc.run, "process": wc.process,
             "type": wc.type.value, "status": wc.status.value,
             "pending": self._b.json_safe(wc.pending), "created_at": now},
        )
        return wc.id

    def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_wait_condition WHERE process = :pid AND status = 'pending'",
            {"pid": process_id},
        )
        if row:
            return self._row_to_wait_condition(row)
        row = self._b.query_one(
            """SELECT wc.* FROM cogos_wait_condition wc
               JOIN cogos_run r ON r.id = wc.run
               WHERE r.process = :pid AND wc.status = 'pending'
               ORDER BY wc.created_at DESC LIMIT 1""",
            {"pid": process_id},
        )
        return self._row_to_wait_condition(row) if row else None

    def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]:
        row = self._b.query_one(
            "SELECT pending FROM cogos_wait_condition WHERE id = :id", {"id": wc_id},
        )
        if not row:
            return []
        pending = self._b.json_decode_list(row.get("pending"))
        remaining = [p for p in pending if p != child_pid]
        self._b.execute(
            f"UPDATE cogos_wait_condition SET pending = {self._b.json_param('pending')} WHERE id = :id",
            {"id": wc_id, "pending": self._b.json_safe(remaining)},
        )
        return remaining

    def resolve_wait_condition(self, wc_id: UUID) -> None:
        self._b.execute(
            "UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now WHERE id = :id",
            {"id": wc_id, "now": _now()},
        )

    def resolve_wait_conditions_for_process(self, process_id: UUID) -> None:
        now = _now()
        self._b.execute(
            """UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now
               WHERE process = :pid AND status = 'pending'""",
            {"pid": process_id, "now": now},
        )
        self._b.execute(
            """UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now
               WHERE status = 'pending' AND run IN (
                   SELECT id FROM cogos_run WHERE process = :pid
               )""",
            {"pid": process_id, "now": now},
        )

    # ── Process Capabilities ──────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        row = self._b.query_one(
            f"""INSERT INTO cogos_process_capability (id, process, capability, name, config, epoch)
               VALUES (:id, :process, :capability, :name, {self._b.json_param('config')}, :epoch)
               ON CONFLICT (process, name) DO UPDATE SET
                   capability = EXCLUDED.capability, config = EXCLUDED.config
               RETURNING id""",
            {"id": pc.id, "process": pc.process, "capability": pc.capability,
             "name": pc.name, "config": self._b.json_safe(pc.config or {}),
             "epoch": pc.epoch},
        )
        return _uuid(row["id"]) if row else pc.id

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]:
        rows = self._b.query(
            "SELECT * FROM cogos_process_capability WHERE process = :process",
            {"process": process_id},
        )
        return [self._row_to_process_capability(r) for r in rows]

    def delete_process_capability(self, pc_id: UUID) -> bool:
        return self._b.execute(
            "DELETE FROM cogos_process_capability WHERE id = :id", {"id": pc_id},
        ) > 0

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]:
        rows = self._b.query(
            """SELECT pc.*, p.name AS process_name, p.status AS process_status
               FROM cogos_process_capability pc
               JOIN cogos_process p ON p.id = pc.process
               WHERE pc.capability = :cap_id""",
            {"cap_id": capability_id},
        )
        result = []
        for r in rows:
            result.append({
                "id": _uuid(r["id"]),
                "process": _uuid(r["process"]),
                "capability": _opt_uuid(r.get("capability")),
                "name": r.get("name", ""),
                "config": self._b.json_decode(r.get("config")),
                "process_name": r.get("process_name"),
                "process_status": r.get("process_status"),
            })
        return result

    # ── Handlers ──────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID:
        if h.channel:
            existing = self._b.query_one(
                "SELECT id, enabled FROM cogos_handler WHERE process = :pid AND channel = :cid",
                {"pid": h.process, "cid": h.channel},
            )
            if existing:
                if not existing["enabled"]:
                    self._b.execute(
                        "UPDATE cogos_handler SET enabled = :enabled WHERE id = :id",
                        {"id": existing["id"], "enabled": True},
                    )
                return _uuid(existing["id"])

        now = _now()
        self._b.execute(
            """INSERT INTO cogos_handler (id, process, channel, enabled, epoch, created_at)
               VALUES (:id, :pid, :cid, :enabled, :epoch, :created_at)
               ON CONFLICT DO NOTHING""",
            {"id": h.id, "pid": h.process, "cid": h.channel,
             "enabled": h.enabled, "epoch": h.epoch or self.reboot_epoch,
             "created_at": now},
        )
        return h.id

    def list_handlers(
        self,
        *,
        process_id: UUID | None = None,
        enabled_only: bool = False,
        epoch: int | None = None,
        limit: int = 0,
    ) -> list[Handler]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if process_id:
            conditions.append("process = :pid")
            params["pid"] = process_id
        if enabled_only:
            conditions.append("enabled = :enabled")
            params["enabled"] = True
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params["epoch"] = effective_epoch
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = " LIMIT :limit" if limit > 0 else ""
        if limit > 0:
            params["limit"] = limit
        rows = self._b.query(
            f"SELECT * FROM cogos_handler{where} ORDER BY created_at{limit_clause}", params,
        )
        return [self._row_to_handler(r) for r in rows]

    def delete_handler(self, handler_id: UUID) -> bool:
        return self._b.execute(
            "DELETE FROM cogos_handler WHERE id = :id", {"id": handler_id},
        ) > 0

    def match_handlers(self, event_type: str) -> list[Handler]:
        return []

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        rows = self._b.query(
            "SELECT * FROM cogos_handler WHERE channel = :cid AND enabled = :enabled",
            {"cid": channel_id, "enabled": True},
        )
        return [self._row_to_handler(r) for r in rows]

    # ── Deliveries ────────────────────────────────────────────

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]:
        existing = self._b.query_one(
            "SELECT id, created_at FROM cogos_delivery WHERE message = :mid AND handler = :hid",
            {"mid": ed.message, "hid": ed.handler},
        )
        if existing:
            ed.created_at = _dt(existing.get("created_at"))
            return _uuid(existing["id"]), False
        now = _now()
        self._b.execute(
            """INSERT INTO cogos_delivery (id, message, handler, status, run, trace_id, epoch, created_at)
               VALUES (:id, :message, :handler, :status, :run, :trace_id, :epoch, :created_at)""",
            {"id": ed.id, "message": ed.message, "handler": ed.handler,
             "status": ed.status.value, "run": ed.run,
             "trace_id": ed.trace_id, "epoch": ed.epoch or self.reboot_epoch,
             "created_at": now},
        )
        ed.created_at = _dt(now)
        return ed.id, True

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]:
        rows = self._b.query(
            """SELECT d.* FROM cogos_delivery d
               JOIN cogos_handler h ON h.id = d.handler
               WHERE h.process = :pid AND d.status = 'pending'
               ORDER BY d.created_at""",
            {"pid": process_id},
        )
        return [self._row_to_delivery(r) for r in rows]

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params["epoch"] = effective_epoch
        if message_id:
            conditions.append("message = :mid")
            params["mid"] = message_id
        if handler_id:
            conditions.append("handler = :hid")
            params["hid"] = handler_id
        if run_id:
            conditions.append("run = :rid")
            params["rid"] = run_id
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._b.query(
            f"SELECT * FROM cogos_delivery{where} ORDER BY created_at DESC LIMIT :limit", params,
        )
        return [self._row_to_delivery(r) for r in rows]

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        row = self._b.query_one(
            """SELECT 1 FROM cogos_delivery d
               JOIN cogos_handler h ON h.id = d.handler
               WHERE h.process = :pid AND d.status = 'pending'
               LIMIT 1""",
            {"pid": process_id},
        )
        return row is not None

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        return self._b.execute(
            "UPDATE cogos_delivery SET status = 'delivered', run = :rid WHERE id = :id",
            {"id": delivery_id, "rid": run_id},
        ) > 0

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        return self._b.execute(
            "UPDATE cogos_delivery SET status = 'queued', run = :rid WHERE id = :id",
            {"id": delivery_id, "rid": run_id},
        ) > 0

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        return self._b.execute(
            "UPDATE cogos_delivery SET status = 'pending', run = NULL WHERE id = :id",
            {"id": delivery_id},
        ) > 0

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        return self._b.execute(
            "UPDATE cogos_delivery SET status = 'delivered' WHERE run = :rid AND status IN ('pending', 'queued')",
            {"rid": run_id},
        )

    def rollback_dispatch(
        self,
        process_id: UUID,
        run_id: UUID,
        delivery_id: UUID | None = None,
        *,
        error: str | None = None,
    ) -> None:
        if delivery_id:
            self.requeue_delivery(delivery_id)
        self.complete_run(run_id, status=RunStatus.FAILED, error=error or "dispatch rollback")
        proc = self.get_process(process_id)
        if proc and proc.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            self.update_process_status(process_id, ProcessStatus.RUNNABLE)

    def get_latest_delivery_time(self, handler_id: UUID) -> datetime | None:
        row = self._b.query_one(
            """SELECT MAX(cm.created_at) AS latest
               FROM cogos_delivery d
               JOIN cogos_channel_message cm ON d.message = cm.id
               WHERE d.handler = :handler""",
            {"handler": handler_id},
        )
        return _dt(row.get("latest")) if row and row.get("latest") else None

    # ── Cron Rules ────────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID:
        t = self._b.t("cron")
        expr_col = self._b.cron_col("expression")
        payload_col = self._b.cron_col("payload")
        existing = self._b.query_one(
            f"SELECT id FROM {t} WHERE {expr_col} = :expr AND channel_name = :channel_name",
            {"expr": c.expression, "channel_name": c.channel_name},
        )
        if existing:
            c.id = _uuid(existing["id"])
            self._b.execute(
                f"UPDATE {t} SET {payload_col} = {self._b.json_param('payload')}, enabled = :enabled WHERE id = :id",
                {"id": c.id, "payload": self._b.json_safe_dict(c.payload), "enabled": c.enabled},
            )
        else:
            self._b.execute(
                f"""INSERT INTO {t} (id, {expr_col}, channel_name, {payload_col}, enabled)
                   VALUES (:id, :expression, :channel_name, {self._b.json_param('payload')}, :enabled)""",
                {"id": c.id, "expression": c.expression, "channel_name": c.channel_name,
                 "payload": self._b.json_safe_dict(c.payload), "enabled": c.enabled},
            )
        return c.id

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        t = self._b.t("cron")
        expr_col = self._b.cron_col("expression")
        where = " WHERE enabled = :enabled" if enabled_only else ""
        params = {"enabled": True} if enabled_only else None
        rows = self._b.query(f"SELECT * FROM {t}{where} ORDER BY {expr_col}", params)
        return [self._row_to_cron(r) for r in rows]

    def delete_cron(self, cron_id: UUID) -> bool:
        return self._b.execute(
            f"DELETE FROM {self._b.t('cron')} WHERE id = :id", {"id": cron_id},
        ) > 0

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        return self._b.execute(
            f"UPDATE {self._b.t('cron')} SET enabled = :enabled WHERE id = :id",
            {"id": cron_id, "enabled": enabled},
        ) > 0

    # ── Files ─────────────────────────────────────────────────

    def insert_file(self, f: File) -> UUID:
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_file (id, key, includes, created_at, updated_at)
               VALUES (:id, :key, {self._b.json_param('includes')}, :now, :now)
               ON CONFLICT (key) DO UPDATE SET
                   includes = EXCLUDED.includes, updated_at = EXCLUDED.updated_at
               RETURNING id, created_at""",
            {"id": f.id, "key": f.key,
             "includes": self._b.json_safe(f.includes), "now": now},
        )
        if row:
            f.id = _uuid(row["id"])
            f.created_at = _dt(row["created_at"])
        return f.id

    def get_file_by_key(self, key: str) -> File | None:
        row = self._b.query_one("SELECT * FROM cogos_file WHERE key = :key", {"key": key})
        return self._row_to_file(row) if row else None

    def get_file_by_id(self, file_id: UUID) -> File | None:
        row = self._b.query_one("SELECT * FROM cogos_file WHERE id = :id", {"id": file_id})
        return self._row_to_file(row) if row else None

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        if prefix:
            rows = self._b.query(
                "SELECT * FROM cogos_file WHERE key LIKE :prefix ORDER BY key LIMIT :limit",
                {"prefix": prefix + "%", "limit": limit},
            )
        else:
            rows = self._b.query(
                "SELECT * FROM cogos_file ORDER BY key LIMIT :limit", {"limit": limit},
            )
        return [self._row_to_file(r) for r in rows]

    def list_files_with_content(
        self,
        *,
        prefix: str | None = None,
        exclude_prefix: str | None = None,
        limit: int = 200,
    ) -> list[tuple[str, str]]:
        conditions = ["fv.is_active = :active"]
        params: dict[str, Any] = {"active": True, "limit": limit}
        if prefix:
            conditions.append("f.key LIKE :prefix")
            params["prefix"] = prefix + "%"
        if exclude_prefix:
            conditions.append("f.key NOT LIKE :exclude_prefix")
            params["exclude_prefix"] = exclude_prefix + "%"
        where = " AND ".join(conditions)
        rows = self._b.query(
            f"""SELECT f.key, fv.content
               FROM cogos_file f
               JOIN cogos_file_version fv ON fv.file_id = f.id
               WHERE {where}
               ORDER BY f.key LIMIT :limit""",
            params,
        )
        return [(r["key"], r["content"]) for r in rows]

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100,
    ) -> list[tuple[str, str]]:
        conditions = ["fv.is_active = :active", self._b.regex_match("fv.content", "pattern")]
        params: dict[str, Any] = {"active": True, "pattern": pattern, "limit": limit}
        if prefix:
            conditions.append("f.key LIKE :prefix")
            params["prefix"] = prefix + "%"
        where = " AND ".join(conditions)
        rows = self._b.query(
            f"""SELECT f.key, fv.content
               FROM cogos_file f
               JOIN cogos_file_version fv ON fv.file_id = f.id
               WHERE {where}
               ORDER BY f.key LIMIT :limit""",
            params,
        )
        return [(r["key"], r["content"]) for r in rows]

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        parts: list[str] = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
                parts.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                continue
            elif c == "*":
                parts.append("[^/]*")
                i += 1
                continue
            elif c == "?":
                parts.append("[^/]")
                i += 1
                continue
            else:
                parts.append(re.escape(c))
                i += 1
        return "^" + "".join(parts) + "$"

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200,
    ) -> list[str]:
        regex = self._glob_to_regex(pattern)
        conditions = [self._b.regex_match("f.key", "regex")]
        params: dict[str, Any] = {"regex": regex, "limit": limit}
        if prefix:
            conditions.append("f.key LIKE :prefix")
            params["prefix"] = prefix + "%"
        where = " AND ".join(conditions)
        rows = self._b.query(
            f"SELECT f.key FROM cogos_file f WHERE {where} ORDER BY f.key LIMIT :limit",
            params,
        )
        return [r["key"] for r in rows]

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool:
        return self._b.execute(
            f"UPDATE cogos_file SET includes = {self._b.json_param('includes')}, updated_at = :now WHERE id = :id",
            {"id": file_id, "includes": self._b.json_safe(includes), "now": _now()},
        ) > 0

    def delete_file(self, file_id: UUID) -> bool:
        self._b.execute(
            "DELETE FROM cogos_file_version WHERE file_id = :fid", {"fid": file_id},
        )
        return self._b.execute(
            "DELETE FROM cogos_file WHERE id = :id", {"id": file_id},
        ) > 0

    def bulk_upsert_files(
        self,
        files: list[tuple[str, str, str, list[str]]],
        *,
        batch_size: int = 100,
    ) -> int:
        with self.batch():
            for key, content, source, includes in files:
                f = self.get_file_by_key(key)
                if not f:
                    f = File(key=key, includes=includes)
                    self.insert_file(f)
                else:
                    if includes != f.includes:
                        self.update_file_includes(f.id, includes)

                self._b.execute(
                    "UPDATE cogos_file_version SET is_active = :inactive WHERE file_id = :fid AND is_active = :active",
                    {"fid": f.id, "inactive": False, "active": True},
                )
                max_v = self.get_max_file_version(f.id)
                fv = FileVersion(
                    file_id=f.id,
                    version=max_v + 1,
                    content=content,
                    source=source,
                    is_active=True,
                )
                self.insert_file_version(fv)
        return len(files)

    # ── File Versions ─────────────────────────────────────────

    def insert_file_version(self, fv: FileVersion) -> None:
        now = _now()
        if fv.is_active:
            self._b.execute(
                "UPDATE cogos_file_version SET is_active = :inactive WHERE file_id = :fid AND is_active = :active",
                {"fid": fv.file_id, "inactive": False, "active": True},
            )
        self._b.execute(
            """INSERT INTO cogos_file_version
                   (id, file_id, version, read_only, content, source, is_active, run_id, created_at)
               VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active, :run_id,
                       :created_at)
               ON CONFLICT (file_id, version) DO UPDATE SET
                   content = EXCLUDED.content, source = EXCLUDED.source,
                   is_active = EXCLUDED.is_active,
                   run_id = COALESCE(EXCLUDED.run_id, cogos_file_version.run_id)""",
            {"id": fv.id, "file_id": fv.file_id, "version": fv.version,
             "read_only": fv.read_only, "content": fv.content,
             "source": fv.source, "is_active": fv.is_active,
             "run_id": fv.run_id, "created_at": now},
        )
        self._b.execute(
            "UPDATE cogos_file SET updated_at = :now WHERE id = :id",
            {"id": fv.file_id, "now": now},
        )

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None:
        row = self._b.query_one(
            """SELECT * FROM cogos_file_version
               WHERE file_id = :fid AND is_active = :active
               ORDER BY version DESC LIMIT 1""",
            {"fid": file_id, "active": True},
        )
        return self._row_to_file_version(row) if row else None

    def get_max_file_version(self, file_id: UUID) -> int:
        row = self._b.query_one(
            "SELECT MAX(version) as max_v FROM cogos_file_version WHERE file_id = :fid",
            {"fid": file_id},
        )
        return row["max_v"] if row and row["max_v"] is not None else 0

    def list_file_versions(self, file_id: UUID, *, limit: int | None = None) -> list[FileVersion]:
        if limit is not None:
            rows = self._b.query(
                "SELECT * FROM cogos_file_version WHERE file_id = :fid ORDER BY version DESC LIMIT :limit",
                {"fid": file_id, "limit": limit},
            )
        else:
            rows = self._b.query(
                "SELECT * FROM cogos_file_version WHERE file_id = :fid ORDER BY version",
                {"fid": file_id},
            )
        return [self._row_to_file_version(r) for r in rows]

    def set_active_file_version(self, file_id: UUID, version: int) -> None:
        self._b.execute(
            "UPDATE cogos_file_version SET is_active = :inactive WHERE file_id = :fid",
            {"fid": file_id, "inactive": False},
        )
        self._b.execute(
            "UPDATE cogos_file_version SET is_active = :active WHERE file_id = :fid AND version = :v",
            {"fid": file_id, "v": version, "active": True},
        )

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        return self._b.execute(
            "UPDATE cogos_file_version SET content = :content WHERE file_id = :fid AND version = :v",
            {"fid": file_id, "v": version, "content": content},
        ) > 0

    def delete_file_version(self, file_id: UUID, version: int) -> bool:
        return self._b.execute(
            "DELETE FROM cogos_file_version WHERE file_id = :fid AND version = :v",
            {"fid": file_id, "v": version},
        ) > 0

    # ── Capabilities ──────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_capability
                   (id, name, description, instructions, handler, schema,
                    iam_role_arn, enabled, metadata, event_types, created_at, updated_at)
               VALUES (:id, :name, :description, :instructions, :handler, {jp('schema')},
                       :iam_role_arn, :enabled, {jp('metadata')}, {jp('event_types')}, :now, :now)
               ON CONFLICT (name) DO UPDATE SET
                   description = EXCLUDED.description, instructions = EXCLUDED.instructions,
                   handler = EXCLUDED.handler, schema = EXCLUDED.schema,
                   iam_role_arn = EXCLUDED.iam_role_arn, enabled = EXCLUDED.enabled,
                   metadata = EXCLUDED.metadata, event_types = EXCLUDED.event_types,
                   updated_at = EXCLUDED.updated_at
               RETURNING id, created_at""",
            {"id": cap.id, "name": cap.name, "description": cap.description,
             "instructions": cap.instructions, "handler": cap.handler,
             "schema": self._b.json_safe_dict(cap.schema),
             "iam_role_arn": cap.iam_role_arn, "enabled": cap.enabled,
             "metadata": self._b.json_safe_dict(cap.metadata),
             "event_types": self._b.json_safe(getattr(cap, "event_types", [])),
             "now": now},
        )
        if row:
            cap.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        return cap.id

    def get_capability(self, cap_id: UUID) -> Capability | None:
        row = self._b.query_one("SELECT * FROM cogos_capability WHERE id = :id", {"id": cap_id})
        return self._row_to_capability(row) if row else None

    def get_capability_by_name(self, name: str) -> Capability | None:
        row = self._b.query_one("SELECT * FROM cogos_capability WHERE name = :name", {"name": name})
        return self._row_to_capability(row) if row else None

    def get_capability_by_handler(self, handler: str) -> Capability | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_capability WHERE handler = :handler", {"handler": handler},
        )
        return self._row_to_capability(row) if row else None

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]:
        if enabled_only:
            rows = self._b.query(
                "SELECT * FROM cogos_capability WHERE enabled = :enabled ORDER BY name",
                {"enabled": True},
            )
        else:
            rows = self._b.query("SELECT * FROM cogos_capability ORDER BY name")
        return [self._row_to_capability(r) for r in rows]

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]:
        like = f"%{query}%"
        name_cond = self._b.ilike("c.name", "q")
        desc_cond = self._b.ilike("c.description", "q")
        if process_id:
            rows = self._b.query(
                f"""SELECT DISTINCT c.* FROM cogos_capability c
                   JOIN cogos_process_capability pc ON pc.capability = c.id
                   WHERE pc.process = :pid
                     AND ({name_cond} OR {desc_cond})""",
                {"pid": process_id, "q": like},
            )
        else:
            name_cond = self._b.ilike("name", "q")
            desc_cond = self._b.ilike("description", "q")
            rows = self._b.query(
                f"""SELECT * FROM cogos_capability
                   WHERE {name_cond} OR {desc_cond}""",
                {"q": like},
            )
        return [self._row_to_capability(r) for r in rows]

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, resource: Resource) -> str:
        t = self._b.t("resources")
        row = self._b.query_one(
            f"""INSERT INTO {t} (name, resource_type, capacity, metadata)
               VALUES (:name, :resource_type, :capacity, {self._b.json_param('metadata')})
               ON CONFLICT (name) DO UPDATE SET
                   resource_type = EXCLUDED.resource_type,
                   capacity = EXCLUDED.capacity,
                   metadata = EXCLUDED.metadata
               RETURNING name, created_at""",
            {"name": resource.name, "resource_type": resource.resource_type.value,
             "capacity": resource.capacity,
             "metadata": self._b.json_safe_dict(resource.metadata)},
        )
        if row:
            resource.created_at = _dt(row.get("created_at"))
            return row["name"]
        raise RuntimeError("Failed to upsert resource")

    def list_resources(self) -> list[Resource]:
        rows = self._b.query(f"SELECT * FROM {self._b.t('resources')} ORDER BY name")
        return [self._row_to_resource(r) for r in rows]

    # ── Runs ──────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        if not run.epoch:
            run.epoch = self.reboot_epoch
        now = _now()
        jp = self._b.json_param
        row = self._b.query_one(
            f"""INSERT INTO cogos_run
                   (id, process, message, conversation, status,
                    tokens_in, tokens_out, cost_usd, duration_ms,
                    error, model_version, result, snapshot, scope_log,
                    trace_id, parent_trace_id, epoch, metadata, created_at)
               VALUES (:id, :process, :message, :conversation, :status,
                       :tokens_in, :tokens_out, :cost_usd, :duration_ms,
                       :error, :model_version, {jp('result')}, {jp('snapshot')}, {jp('scope_log')},
                       :trace_id, :parent_trace_id, :epoch, {jp('metadata')}, :created_at)
               RETURNING id, created_at""",
            {"id": run.id, "process": run.process,
             "message": run.message, "conversation": run.conversation,
             "status": run.status.value,
             "tokens_in": run.tokens_in, "tokens_out": run.tokens_out,
             "cost_usd": str(run.cost_usd), "duration_ms": run.duration_ms,
             "error": run.error, "model_version": run.model_version,
             "result": self._b.json_safe(run.result),
             "snapshot": self._b.json_safe(run.snapshot),
             "scope_log": self._b.json_safe(run.scope_log),
             "trace_id": run.trace_id, "parent_trace_id": run.parent_trace_id,
             "epoch": run.epoch,
             "metadata": self._b.json_safe(run.metadata),
             "created_at": now},
        )
        if row:
            run.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        raise RuntimeError("Failed to create run")

    def complete_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: Decimal = Decimal("0"),
        duration_ms: int | None = None,
        error: str | None = None,
        model_version: str | None = None,
        result: dict | None = None,
        snapshot: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool:
        now = _now()
        jp = self._b.json_param
        sets = [
            "status = :status", "tokens_in = :tokens_in", "tokens_out = :tokens_out",
            "cost_usd = :cost_usd", "duration_ms = :duration_ms", "error = :error",
            f"result = {jp('result')}", "completed_at = :now",
        ]
        params: dict[str, Any] = {
            "id": run_id, "status": status.value,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": str(cost_usd), "duration_ms": duration_ms,
            "error": error, "result": self._b.json_safe(result), "now": now,
        }
        if model_version is not None:
            sets.append("model_version = :model_version")
            params["model_version"] = model_version
        else:
            sets.append("model_version = COALESCE(:model_version, model_version)")
            params["model_version"] = None
        if snapshot is not None:
            sets.append(f"snapshot = {jp('snapshot')}")
            params["snapshot"] = self._b.json_safe(snapshot)
        if scope_log is not None:
            sets.append(f"scope_log = {jp('scope_log')}")
            params["scope_log"] = self._b.json_safe(scope_log)
        set_clause = ", ".join(sets)
        return self._b.execute(
            f"UPDATE cogos_run SET {set_clause} WHERE id = :id", params,
        ) > 0

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int:
        threshold = datetime.now(UTC)
        from datetime import timedelta
        threshold -= timedelta(milliseconds=max_age_ms)
        now = _now()
        return self._b.execute(
            """UPDATE cogos_run SET
                   status = 'timeout',
                   error = 'Run exceeded maximum duration and was reaped by dispatcher',
                   completed_at = :now
               WHERE status = 'running' AND created_at < :threshold""",
            {"now": now, "threshold": threshold.isoformat()},
        )

    def get_run(self, run_id: UUID, *, slim: bool = False) -> Run | None:
        columns = self._RUN_SLIM_COLUMNS if slim else "*"
        row = self._b.query_one(
            f"SELECT {columns} FROM cogos_run WHERE id = :id", {"id": run_id},
        )
        return self._row_to_run(row) if row else None

    _RUN_SLIM_COLUMNS = (
        "id, epoch, process, message, conversation, status, tokens_in, tokens_out, "
        "cost_usd, duration_ms, error, model_version, trace_id, parent_trace_id, "
        "created_at, completed_at"
    )

    def get_run_results(self, run_ids: list[UUID]) -> dict[UUID, dict[str, Any] | None]:
        if not run_ids:
            return {}
        placeholders = ", ".join(f":id_{i}" for i in range(len(run_ids)))
        params = {f"id_{i}": rid for i, rid in enumerate(run_ids)}
        rows = self._b.query(
            f"SELECT id, result FROM cogos_run WHERE id IN ({placeholders})", params,
        )
        return {_uuid(r["id"]): self._b.json_decode(r.get("result")) for r in rows}

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(milliseconds=max_age_ms)).isoformat()
        rows = self._b.query(
            """SELECT * FROM cogos_run
               WHERE status IN ('failed', 'timeout', 'throttled')
                 AND epoch = :epoch
                 AND (completed_at >= :cutoff OR created_at >= :cutoff)
               ORDER BY completed_at DESC""",
            {"epoch": self.reboot_epoch, "cutoff": cutoff},
        )
        return [self._row_to_run(r) for r in rows]

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None:
        existing = self._b.query_one("SELECT metadata FROM cogos_run WHERE id = :id", {"id": run_id})
        current = self._b.json_decode_dict(existing.get("metadata")) if existing else {}
        current.update(metadata)
        self._b.execute(
            f"UPDATE cogos_run SET metadata = {self._b.json_param('metadata')} WHERE id = :id",
            {"id": run_id, "metadata": self._b.json_safe_dict(current)},
        )

    def list_runs(
        self,
        *,
        process_id: UUID | None = None,
        process_ids: list[UUID] | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
        epoch: int | None = None,
        slim: bool = False,
    ) -> list[Run]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params["epoch"] = effective_epoch
        if process_id:
            conditions.append("process = :process")
            params["process"] = process_id
        if process_ids:
            placeholders = ", ".join(f":pid_{i}" for i in range(len(process_ids)))
            conditions.append(f"process IN ({placeholders})")
            for i, pid in enumerate(process_ids):
                params[f"pid_{i}"] = pid
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if since:
            conditions.append("created_at >= :since")
            params["since"] = since
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        columns = self._RUN_SLIM_COLUMNS if slim else "*"
        rows = self._b.query(
            f"SELECT {columns} FROM cogos_run{where} ORDER BY created_at DESC LIMIT :limit", params,
        )
        return [self._row_to_run(r) for r in rows]

    def list_file_mutations(self, run_id: UUID) -> list[dict]:
        return self._b.query(
            """SELECT f.key, fv.file_id, fv.version, fv.content, fv.created_at
               FROM cogos_file_version fv
               JOIN cogos_file f ON f.id = fv.file_id
               WHERE fv.run_id = :run_id
               ORDER BY fv.created_at""",
            {"run_id": run_id},
        )

    def get_file_version_content(self, file_id: UUID, version: int) -> str | None:
        row = self._b.query_one(
            "SELECT content FROM cogos_file_version WHERE file_id = :fid AND version = :v",
            {"fid": file_id, "v": version},
        )
        return row["content"] if row else None

    def list_messages_sent_by_run(self, run_id: UUID) -> list[dict]:
        rows = self._b.query(
            """SELECT cm.id, cm.payload, cm.created_at, c.name AS channel_name
               FROM cogos_channel_message cm
               JOIN cogos_channel c ON c.id = cm.channel
               WHERE cm.sender_run_id = :rid
               ORDER BY cm.created_at""",
            {"rid": run_id},
        )
        for r in rows:
            r["payload"] = self._b.json_decode_dict(r.get("payload"))
        return rows

    def list_child_runs(self, process_id: UUID) -> list[Run]:
        rows = self._b.query(
            """SELECT r.* FROM cogos_run r
               JOIN cogos_process p ON p.id = r.process
               WHERE p.parent_process = :pid
               ORDER BY r.created_at""",
            {"pid": process_id},
        )
        return [self._row_to_run(r) for r in rows]

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        like_pattern = name_pattern.replace("*", "%").replace("?", "_")
        conditions = ["p.name LIKE :name_pattern", "r.epoch = :epoch"]
        params: dict[str, Any] = {
            "name_pattern": like_pattern,
            "epoch": self.reboot_epoch,
            "limit": limit,
        }
        if status:
            conditions.append("r.status = :status")
            params["status"] = status
        if since:
            conditions.append("r.created_at >= :since")
            params["since"] = since
        where = " AND ".join(conditions)
        rows = self._b.query(
            f"""SELECT r.* FROM cogos_run r
                JOIN cogos_process p ON p.id = r.process
                WHERE {where}
                ORDER BY r.created_at DESC LIMIT :limit""",
            params,
        )
        return [self._row_to_run(r) for r in rows]

    # ── Traces ────────────────────────────────────────────────

    def create_trace(self, trace: Trace) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_trace (id, run, capability_calls, file_ops, model_version, created_at)
               VALUES (:id, :run, {jp('capability_calls')}, {jp('file_ops')}, :model_version, :created_at)
               RETURNING id, created_at""",
            {"id": trace.id, "run": trace.run,
             "capability_calls": self._b.json_safe(trace.capability_calls),
             "file_ops": self._b.json_safe(trace.file_ops),
             "model_version": trace.model_version, "created_at": now},
        )
        if row:
            trace.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        return trace.id

    # ── Request Traces & Spans ────────────────────────────────

    def create_request_trace(self, trace: RequestTrace) -> UUID:
        now = _now()
        row = self._b.query_one(
            """INSERT INTO cogos_request_trace (id, cogent_id, source, source_ref, created_at)
               VALUES (:id, :cogent_id, :source, :source_ref, :created_at)
               ON CONFLICT (id) DO NOTHING
               RETURNING id, created_at""",
            {"id": trace.id, "cogent_id": trace.cogent_id,
             "source": trace.source, "source_ref": trace.source_ref,
             "created_at": now},
        )
        if row:
            trace.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        return trace.id

    def get_request_trace(self, trace_id: UUID) -> RequestTrace | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_request_trace WHERE id = :id", {"id": trace_id},
        )
        return self._row_to_request_trace(row) if row else None

    def create_span(self, span: Span) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_span
                   (id, trace_id, parent_span_id, name, coglet, status, metadata, started_at)
               VALUES (:id, :trace_id, :parent_span_id, :name, :coglet, :status, {jp('metadata')}, :started_at)
               RETURNING id, started_at""",
            {"id": span.id, "trace_id": span.trace_id,
             "parent_span_id": span.parent_span_id,
             "name": span.name, "coglet": span.coglet,
             "status": span.status.value,
             "metadata": self._b.json_safe_dict(span.metadata),
             "started_at": now},
        )
        if row:
            span.started_at = _dt(row["started_at"])
            return _uuid(row["id"])
        raise RuntimeError("Failed to create span")

    def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool:
        now = _now()
        if metadata:
            existing = self._b.query_one(
                "SELECT metadata FROM cogos_span WHERE id = :id", {"id": span_id},
            )
            current = self._b.json_decode_dict(existing.get("metadata")) if existing else {}
            current.update(metadata)
            return self._b.execute(
                f"""UPDATE cogos_span SET status = :status, ended_at = :now,
                       metadata = {self._b.json_param('metadata')}
                   WHERE id = :id""",
                {"id": span_id, "status": status, "now": now,
                 "metadata": self._b.json_safe_dict(current)},
            ) > 0
        return self._b.execute(
            "UPDATE cogos_span SET status = :status, ended_at = :now WHERE id = :id",
            {"id": span_id, "status": status, "now": now},
        ) > 0

    def list_spans(self, trace_id: UUID) -> list[Span]:
        rows = self._b.query(
            "SELECT * FROM cogos_span WHERE trace_id = :tid ORDER BY started_at",
            {"tid": trace_id},
        )
        return [self._row_to_span(r) for r in rows]

    def create_span_event(self, event: SpanEvent) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_span_event (id, span_id, event, message, metadata, timestamp)
               VALUES (:id, :span_id, :event, :message, {jp('metadata')}, :timestamp)
               RETURNING id, timestamp""",
            {"id": event.id, "span_id": event.span_id,
             "event": event.event, "message": event.message,
             "metadata": self._b.json_safe_dict(event.metadata),
             "timestamp": now},
        )
        if row:
            event.timestamp = _dt(row["timestamp"])
            return _uuid(row["id"])
        raise RuntimeError("Failed to create span event")

    def list_span_events(self, span_id: UUID) -> list[SpanEvent]:
        rows = self._b.query(
            "SELECT * FROM cogos_span_event WHERE span_id = :sid ORDER BY timestamp",
            {"sid": span_id},
        )
        return [self._row_to_span_event(r) for r in rows]

    def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]:
        rows = self._b.query(
            """SELECT e.* FROM cogos_span_event e
               JOIN cogos_span s ON s.id = e.span_id
               WHERE s.trace_id = :tid
               ORDER BY e.timestamp""",
            {"tid": trace_id},
        )
        return [self._row_to_span_event(r) for r in rows]

    # ── Alerts ────────────────────────────────────────────────

    def create_alert(
        self, severity: str, alert_type: str, source: str, message: str, metadata: dict | None = None,
    ) -> None:
        t = self._b.t("alerts")
        now = _now()
        self._b.execute(
            f"""INSERT INTO {t}
                   (id, severity, alert_type, source, message, metadata, created_at)
               VALUES (:id, :severity, :alert_type, :source, :message,
                       {self._b.json_param('metadata')}, :created_at)""",
            {"id": uuid4(), "severity": severity, "alert_type": alert_type,
             "source": source, "message": message,
             "metadata": self._b.json_safe_dict(metadata),
             "created_at": now},
        )

    def list_alerts(self, *, resolved: bool = False, limit: int = 50) -> list[Alert]:
        t = self._b.t("alerts")
        where = "" if resolved else " WHERE resolved_at IS NULL"
        rows = self._b.query(
            f"SELECT * FROM {t}{where} ORDER BY created_at DESC LIMIT :limit",
            {"limit": limit},
        )
        return [self._row_to_alert(r) for r in rows]

    def resolve_alert(self, alert_id: UUID) -> None:
        self._b.execute(
            f"UPDATE {self._b.t('alerts')} SET resolved_at = :now WHERE id = :id",
            {"id": alert_id, "now": _now()},
        )

    def resolve_all_alerts(self) -> int:
        return self._b.execute(
            f"UPDATE {self._b.t('alerts')} SET resolved_at = :now WHERE resolved_at IS NULL",
            {"now": _now()},
        )

    def delete_alert(self, alert_id: UUID) -> None:
        self._b.execute(
            f"DELETE FROM {self._b.t('alerts')} WHERE id = :id", {"id": alert_id},
        )

    # ── Schemas ───────────────────────────────────────────────

    def upsert_schema(self, s: Schema) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_schema (id, name, definition, file_id, created_at)
               VALUES (:id, :name, {jp('definition')}, :file_id, :created_at)
               ON CONFLICT (name) DO UPDATE SET
                   definition = EXCLUDED.definition, file_id = EXCLUDED.file_id
               RETURNING id, created_at""",
            {"id": s.id, "name": s.name,
             "definition": self._b.json_safe_dict(s.definition),
             "file_id": s.file_id, "created_at": now},
        )
        if row:
            s.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        raise RuntimeError("Failed to upsert schema")

    def get_schema(self, schema_id: UUID) -> Schema | None:
        row = self._b.query_one("SELECT * FROM cogos_schema WHERE id = :id", {"id": schema_id})
        return self._row_to_schema(row) if row else None

    def get_schema_by_name(self, name: str) -> Schema | None:
        row = self._b.query_one("SELECT * FROM cogos_schema WHERE name = :name", {"name": name})
        return self._row_to_schema(row) if row else None

    def list_schemas(self) -> list[Schema]:
        rows = self._b.query("SELECT * FROM cogos_schema ORDER BY name")
        return [self._row_to_schema(r) for r in rows]

    # ── Channels ──────────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> UUID:
        jp = self._b.json_param
        now = _now()
        row = self._b.query_one(
            f"""INSERT INTO cogos_channel
                   (id, name, owner_process, schema_id, inline_schema,
                    channel_type, auto_close, closed_at, created_at)
               VALUES (:id, :name, :owner_process, :schema_id, {jp('inline_schema')},
                       :channel_type, :auto_close, :closed_at, :created_at)
               ON CONFLICT (name) DO UPDATE SET
                   owner_process = EXCLUDED.owner_process,
                   schema_id = EXCLUDED.schema_id,
                   inline_schema = EXCLUDED.inline_schema,
                   channel_type = EXCLUDED.channel_type,
                   auto_close = EXCLUDED.auto_close,
                   closed_at = EXCLUDED.closed_at
               RETURNING id, created_at""",
            {"id": ch.id, "name": ch.name,
             "owner_process": ch.owner_process,
             "schema_id": ch.schema_id,
             "inline_schema": self._b.json_safe(ch.inline_schema),
             "channel_type": ch.channel_type.value,
             "auto_close": ch.auto_close,
             "closed_at": ch.closed_at.isoformat() if ch.closed_at else None,
             "created_at": now},
        )
        if row:
            ch.created_at = _dt(row["created_at"])
            return _uuid(row["id"])
        raise RuntimeError("Failed to upsert channel")

    def get_channel(self, channel_id: UUID) -> Channel | None:
        row = self._b.query_one("SELECT * FROM cogos_channel WHERE id = :id", {"id": channel_id})
        return self._row_to_channel(row) if row else None

    def get_channel_by_name(self, name: str) -> Channel | None:
        row = self._b.query_one("SELECT * FROM cogos_channel WHERE name = :name", {"name": name})
        return self._row_to_channel(row) if row else None

    _CHANNEL_LIST_COLS = "id, name, channel_type, owner_process, schema_id, auto_close, closed_at, created_at"

    def list_channels(self, *, owner_process: UUID | None = None, limit: int = 0) -> list[Channel]:
        cols = self._CHANNEL_LIST_COLS
        if owner_process is not None:
            rows = self._b.query(
                f"SELECT {cols} FROM cogos_channel WHERE owner_process = :owner ORDER BY name",
                {"owner": owner_process},
            )
        elif limit > 0:
            rows = self._b.query(
                f"SELECT {cols} FROM cogos_channel ORDER BY name LIMIT :limit",
                {"limit": limit},
            )
        else:
            rows = self._b.query(f"SELECT {cols} FROM cogos_channel ORDER BY name")
        return [self._row_to_channel(r) for r in rows]

    def close_channel(self, channel_id: UUID) -> bool:
        return self._b.execute(
            "UPDATE cogos_channel SET closed_at = :now WHERE id = :id AND closed_at IS NULL",
            {"id": channel_id, "now": _now()},
        ) > 0

    # ── Channel Messages ──────────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        jp = self._b.json_param
        now = _now()

        if msg.idempotency_key:
            existing = self._b.query_one(
                "SELECT id, created_at FROM cogos_channel_message WHERE channel = :channel AND idempotency_key = :key",
                {"channel": msg.channel, "key": msg.idempotency_key},
            )
            if existing:
                logger.info("Duplicate channel message (idempotency_key=%s), skipping", msg.idempotency_key)
                return _uuid(existing["id"])

        row = self._b.query_one(
            f"""INSERT INTO cogos_channel_message
                   (id, channel, sender_process, sender_run_id, payload,
                    idempotency_key, trace_id, trace_meta, created_at)
               VALUES (:id, :channel, :sender_process, :sender_run_id, {jp('payload')},
                       :idempotency_key, :trace_id, {jp('trace_meta')}, :created_at)
               RETURNING id, created_at""",
            {"id": msg.id, "channel": msg.channel,
             "sender_process": msg.sender_process,
             "sender_run_id": msg.sender_run_id,
             "payload": self._b.json_safe_dict(msg.payload),
             "idempotency_key": msg.idempotency_key,
             "trace_id": msg.trace_id,
             "trace_meta": self._b.json_safe(msg.trace_meta),
             "created_at": now},
        )
        if not row:
            raise RuntimeError("Failed to append channel message")

        msg.created_at = _dt(row["created_at"])
        msg_id = _uuid(row["id"])

        handlers = self.match_handlers_by_channel(msg.channel)
        for handler in handlers:
            delivery = Delivery(message=msg_id, handler=handler.id, trace_id=msg.trace_id)
            _delivery_id, inserted = self.create_delivery(delivery)
            if inserted:
                proc = self.get_process(handler.process)
                if proc and proc.status == ProcessStatus.WAITING:
                    wc = self.get_pending_wait_condition_for_process(handler.process)
                    if wc is None:
                        self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                        self._nudge_ingress(process_id=handler.process)
                    else:
                        payload = msg.payload if isinstance(msg.payload, dict) else {}
                        if payload.get("type") == "child:exited":
                            sender_pid = str(msg.sender_process)
                            remaining = self.remove_from_pending(wc.id, sender_pid)
                            should_wake = (
                                wc.type.value in ("wait", "wait_any")
                                or (wc.type.value == "wait_all" and len(remaining) == 0)
                            )
                            if should_wake:
                                self.resolve_wait_condition(wc.id)
                                self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                                self._nudge_ingress(process_id=handler.process)

        return msg_id

    def get_channel_message(self, message_id: UUID) -> ChannelMessage | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_channel_message WHERE id = :id", {"id": message_id},
        )
        return self._row_to_channel_message(row) if row else None

    def list_channel_messages(
        self, channel_id: UUID | None = None, *, limit: int = 100, since: datetime | None = None,
    ) -> list[ChannelMessage]:
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        order = "DESC"
        if channel_id is not None:
            conditions.append("channel = :channel")
            params["channel"] = channel_id
            if since:
                order = "ASC"
        if since:
            conditions.append("created_at > :since")
            params["since"] = since.isoformat()
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._b.query(
            f"SELECT * FROM cogos_channel_message{where} ORDER BY created_at {order} LIMIT :limit",
            params,
        )
        return [self._row_to_channel_message(r) for r in rows]

    # ── Discord Metadata ──────────────────────────────────────

    def upsert_discord_guild(self, guild: DiscordGuild) -> None:
        now = _now()
        self._b.execute(
            """INSERT INTO cogos_discord_guild
                   (guild_id, cogent_name, name, icon_url, member_count, synced_at)
               VALUES (:guild_id, :cogent_name, :name, :icon_url, :member_count, :synced_at)
               ON CONFLICT (guild_id) DO UPDATE SET
                   cogent_name = EXCLUDED.cogent_name,
                   name = EXCLUDED.name,
                   icon_url = EXCLUDED.icon_url,
                   member_count = EXCLUDED.member_count,
                   synced_at = EXCLUDED.synced_at""",
            {"guild_id": guild.guild_id, "cogent_name": guild.cogent_name,
             "name": guild.name, "icon_url": guild.icon_url,
             "member_count": guild.member_count, "synced_at": now},
        )

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_discord_guild WHERE guild_id = :gid", {"gid": guild_id},
        )
        return self._row_to_discord_guild(row) if row else None

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
        if cogent_name:
            rows = self._b.query(
                "SELECT * FROM cogos_discord_guild WHERE cogent_name = :cn ORDER BY name",
                {"cn": cogent_name},
            )
        else:
            rows = self._b.query("SELECT * FROM cogos_discord_guild ORDER BY name")
        return [self._row_to_discord_guild(r) for r in rows]

    def delete_discord_guild(self, guild_id: str) -> None:
        self._b.execute(
            "DELETE FROM cogos_discord_channel WHERE guild_id = :gid", {"gid": guild_id},
        )
        self._b.execute(
            "DELETE FROM cogos_discord_guild WHERE guild_id = :gid", {"gid": guild_id},
        )

    def upsert_discord_channel(self, channel: DiscordChannel) -> None:
        now = _now()
        self._b.execute(
            """INSERT INTO cogos_discord_channel
                   (channel_id, guild_id, name, topic, category, channel_type, position, synced_at)
               VALUES (:channel_id, :guild_id, :name, :topic, :category, :channel_type, :position, :synced_at)
               ON CONFLICT (channel_id) DO UPDATE SET
                   guild_id = EXCLUDED.guild_id,
                   name = EXCLUDED.name,
                   topic = EXCLUDED.topic,
                   category = EXCLUDED.category,
                   channel_type = EXCLUDED.channel_type,
                   position = EXCLUDED.position,
                   synced_at = EXCLUDED.synced_at""",
            {"channel_id": channel.channel_id, "guild_id": channel.guild_id,
             "name": channel.name, "topic": channel.topic,
             "category": channel.category, "channel_type": channel.channel_type,
             "position": channel.position, "synced_at": now},
        )

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_discord_channel WHERE channel_id = :cid", {"cid": channel_id},
        )
        return self._row_to_discord_channel(row) if row else None

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
        if guild_id:
            rows = self._b.query(
                "SELECT * FROM cogos_discord_channel WHERE guild_id = :gid ORDER BY position",
                {"gid": guild_id},
            )
        else:
            rows = self._b.query("SELECT * FROM cogos_discord_channel ORDER BY position")
        return [self._row_to_discord_channel(r) for r in rows]

    def delete_discord_channel(self, channel_id: str) -> None:
        self._b.execute(
            "DELETE FROM cogos_discord_channel WHERE channel_id = :cid", {"cid": channel_id},
        )

    # ── Executors ─────────────────────────────────────────────

    def register_executor(self, executor: Executor) -> UUID:
        now = _now()
        jp = self._b.json_param
        existing = self._b.query_one(
            "SELECT id FROM cogos_executor WHERE executor_id = :eid",
            {"eid": executor.executor_id},
        )
        if existing:
            executor.id = _uuid(existing["id"])
            self._b.execute(
                f"""UPDATE cogos_executor
                   SET channel_type = :channel_type,
                       executor_tags = {jp('executor_tags')},
                       dispatch_type = :dispatch_type,
                       metadata = {jp('metadata')},
                       status = 'idle',
                       current_run_id = NULL,
                       last_heartbeat_at = :now,
                       registered_at = :now
                   WHERE id = :id""",
                {"id": executor.id, "channel_type": executor.channel_type,
                 "executor_tags": self._b.json_safe(executor.executor_tags),
                 "dispatch_type": executor.dispatch_type,
                 "metadata": self._b.json_safe_dict(executor.metadata),
                 "now": now},
            )
            return executor.id

        self._b.execute(
            f"""INSERT INTO cogos_executor
               (id, executor_id, channel_type, executor_tags, dispatch_type,
                metadata, status, last_heartbeat_at, registered_at)
               VALUES (:id, :executor_id, :channel_type, {jp('executor_tags')},
                :dispatch_type, {jp('metadata')}, 'idle', :now, :now)""",
            {"id": executor.id, "executor_id": executor.executor_id,
             "channel_type": executor.channel_type,
             "executor_tags": self._b.json_safe(executor.executor_tags),
             "dispatch_type": executor.dispatch_type,
             "metadata": self._b.json_safe_dict(executor.metadata),
             "now": now},
        )
        return executor.id

    def get_executor(self, executor_id: str) -> Executor | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_executor WHERE executor_id = :eid", {"eid": executor_id},
        )
        return self._row_to_executor(row) if row else None

    def get_executor_by_id(self, id: UUID) -> Executor | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_executor WHERE id = :id", {"id": id},
        )
        return self._row_to_executor(row) if row else None

    def list_executors(self, status: ExecutorStatus | None = None) -> list[Executor]:
        if status:
            rows = self._b.query(
                "SELECT * FROM cogos_executor WHERE status = :status ORDER BY registered_at DESC",
                {"status": status.value},
            )
        else:
            rows = self._b.query("SELECT * FROM cogos_executor ORDER BY registered_at DESC")
        return [self._row_to_executor(r) for r in rows]

    def select_executor(
        self,
        required_tags: list[str] | None = None,
        preferred_tags: list[str] | None = None,
    ) -> Executor | None:
        idle = self.list_executors(status=ExecutorStatus.IDLE)
        if not idle:
            return None
        candidates = idle
        if required_tags:
            req = set(required_tags)
            candidates = [e for e in candidates if req.issubset(set(e.executor_tags))]
        if not candidates:
            return None
        if preferred_tags:
            pref = set(preferred_tags)
            candidates.sort(key=lambda e: len(pref & set(e.executor_tags)), reverse=True)
        return candidates[0]

    def heartbeat_executor(
        self,
        executor_id: str,
        status: ExecutorStatus = ExecutorStatus.IDLE,
        current_run_id: UUID | None = None,
        resource_usage: dict | None = None,
    ) -> bool:
        now = _now()
        params: dict[str, Any] = {
            "executor_id": executor_id, "status": status.value,
            "current_run_id": current_run_id, "now": now,
        }
        if resource_usage:
            existing = self._b.query_one(
                "SELECT metadata FROM cogos_executor WHERE executor_id = :eid",
                {"eid": executor_id},
            )
            meta = self._b.json_decode_dict(existing.get("metadata")) if existing else {}
            meta["resource_usage"] = resource_usage
            params["metadata"] = self._b.json_safe_dict(meta)
            return self._b.execute(
                f"""UPDATE cogos_executor
                   SET last_heartbeat_at = :now, status = :status,
                       current_run_id = :current_run_id,
                       metadata = {self._b.json_param('metadata')}
                   WHERE executor_id = :executor_id""",
                params,
            ) > 0
        return self._b.execute(
            """UPDATE cogos_executor
               SET last_heartbeat_at = :now, status = :status,
                   current_run_id = :current_run_id
               WHERE executor_id = :executor_id""",
            params,
        ) > 0

    def update_executor_status(
        self, executor_id: str, status: ExecutorStatus, current_run_id: UUID | None = None,
    ) -> None:
        self._b.execute(
            """UPDATE cogos_executor
               SET status = :status, current_run_id = :current_run_id
               WHERE executor_id = :executor_id""",
            {"executor_id": executor_id, "status": status.value,
             "current_run_id": current_run_id},
        )

    def delete_executor(self, executor_id: str) -> None:
        self._b.execute(
            "DELETE FROM cogos_executor WHERE executor_id = :eid", {"eid": executor_id},
        )

    def reap_stale_executors(self, heartbeat_interval_s: int = 30) -> int:
        from datetime import timedelta
        now_dt = datetime.now(UTC)
        stale_threshold = (now_dt - timedelta(seconds=heartbeat_interval_s * 3)).isoformat()
        dead_threshold = (now_dt - timedelta(seconds=heartbeat_interval_s * 10)).isoformat()

        self._b.execute(
            """UPDATE cogos_executor SET status = 'stale'
               WHERE status = 'idle' AND last_heartbeat_at < :threshold""",
            {"threshold": stale_threshold},
        )
        return self._b.execute(
            """UPDATE cogos_executor SET status = 'dead'
               WHERE status IN ('idle', 'busy', 'stale')
                 AND last_heartbeat_at < :threshold""",
            {"threshold": dead_threshold},
        )

    # ── Executor Tokens ───────────────────────────────────────

    def create_executor_token(self, token: ExecutorToken) -> UUID:
        now = _now()
        self._b.execute(
            """INSERT INTO cogos_executor_token (id, name, token_hash, scope, created_at)
               VALUES (:id, :name, :token_hash, :scope, :created_at)""",
            {"id": token.id, "name": token.name,
             "token_hash": token.token_hash, "scope": token.scope,
             "created_at": now},
        )
        return token.id

    def get_executor_token_by_hash(self, token_hash: str) -> ExecutorToken | None:
        row = self._b.query_one(
            "SELECT * FROM cogos_executor_token WHERE token_hash = :hash AND revoked_at IS NULL",
            {"hash": token_hash},
        )
        return self._row_to_executor_token(row) if row else None

    def list_executor_tokens(self) -> list[ExecutorToken]:
        rows = self._b.query("SELECT * FROM cogos_executor_token ORDER BY created_at DESC")
        return [self._row_to_executor_token(r) for r in rows]

    def revoke_executor_token(self, name: str) -> bool:
        return self._b.execute(
            "UPDATE cogos_executor_token SET revoked_at = :now WHERE name = :name AND revoked_at IS NULL",
            {"name": name, "now": _now()},
        ) > 0

    # ── Lifecycle ─────────────────────────────────────────────

    def reload(self) -> None:
        pass
