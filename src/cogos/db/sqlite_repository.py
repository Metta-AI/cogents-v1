from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

logger = logging.getLogger(__name__)


def _json_serial(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cogos_file (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    includes    TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_file_version (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES cogos_file(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    read_only   INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'cogent',
    is_active   INTEGER NOT NULL DEFAULT 1,
    run_id      TEXT,
    created_at  TEXT,
    UNIQUE (file_id, version)
);

CREATE TABLE IF NOT EXISTS cogos_capability (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    handler         TEXT NOT NULL DEFAULT '',
    schema          TEXT NOT NULL DEFAULT '{}',
    iam_role_arn    TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    metadata        TEXT NOT NULL DEFAULT '{}',
    event_types     TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_process (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    mode                TEXT NOT NULL DEFAULT 'one_shot',
    content             TEXT NOT NULL DEFAULT '',
    priority            REAL NOT NULL DEFAULT 0.0,
    resources           TEXT NOT NULL DEFAULT '[]',
    required_tags       TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'waiting'
                        CHECK (status IN ('waiting', 'runnable',
                                          'blocked', 'suspended', 'disabled')),
    runnable_since      TEXT,
    parent_process      TEXT REFERENCES cogos_process(id),
    preemptible         INTEGER NOT NULL DEFAULT 0,
    model               TEXT,
    model_constraints   TEXT NOT NULL DEFAULT '{}',
    return_schema       TEXT,
    idle_timeout_ms     INTEGER,
    max_duration_ms     INTEGER,
    max_retries         INTEGER NOT NULL DEFAULT 0,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    retry_backoff_ms    INTEGER,
    clear_context       INTEGER NOT NULL DEFAULT 0,
    metadata            TEXT NOT NULL DEFAULT '{}',
    output_events       TEXT NOT NULL DEFAULT '[]',
    epoch               INTEGER NOT NULL DEFAULT 0,
    tty                 INTEGER NOT NULL DEFAULT 0,
    executor            TEXT NOT NULL DEFAULT 'llm',
    schema_id           TEXT,
    created_at          TEXT,
    updated_at          TEXT,
    UNIQUE (name, epoch)
);

CREATE TABLE IF NOT EXISTS cogos_process_capability (
    id          TEXT PRIMARY KEY,
    process     TEXT NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    capability  TEXT NOT NULL REFERENCES cogos_capability(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT '',
    epoch       INTEGER NOT NULL DEFAULT 0,
    config      TEXT NOT NULL DEFAULT '{}',
    UNIQUE (process, name)
);

CREATE TABLE IF NOT EXISTS cogos_handler (
    id              TEXT PRIMARY KEY,
    process         TEXT NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    channel         TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    epoch           INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    UNIQUE (process, channel)
);

CREATE TABLE IF NOT EXISTS cogos_delivery (
    id          TEXT PRIMARY KEY,
    message     TEXT NOT NULL,
    handler     TEXT NOT NULL REFERENCES cogos_handler(id) ON DELETE CASCADE,
    trace_id    TEXT,
    epoch       INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'queued', 'delivered', 'skipped')),
    run         TEXT,
    created_at  TEXT,
    UNIQUE (message, handler)
);

CREATE TABLE IF NOT EXISTS cogos_cron (
    id              TEXT PRIMARY KEY,
    expression      TEXT NOT NULL,
    channel_name    TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_run        TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_channel (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    channel_type    TEXT NOT NULL DEFAULT 'implicit',
    owner_process   TEXT,
    schema_id       TEXT,
    inline_schema   TEXT,
    auto_close      INTEGER NOT NULL DEFAULT 0,
    closed_at       TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_channel_message (
    id                  TEXT PRIMARY KEY,
    channel             TEXT NOT NULL REFERENCES cogos_channel(id) ON DELETE CASCADE,
    sender_process      TEXT,
    sender_run_id       TEXT,
    payload             TEXT NOT NULL DEFAULT '{}',
    idempotency_key     TEXT,
    trace_id            TEXT,
    trace_meta          TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS cogos_schema (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    definition  TEXT NOT NULL DEFAULT '{}',
    file_id     TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_run (
    id              TEXT PRIMARY KEY,
    process         TEXT NOT NULL REFERENCES cogos_process(id),
    message         TEXT,
    conversation    TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'failed', 'timeout', 'suspended', 'throttled')),
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        TEXT NOT NULL DEFAULT '0',
    duration_ms     INTEGER,
    error           TEXT,
    model_version   TEXT,
    result          TEXT,
    snapshot        TEXT,
    scope_log       TEXT NOT NULL DEFAULT '[]',
    epoch           INTEGER NOT NULL DEFAULT 0,
    trace_id        TEXT,
    parent_trace_id TEXT,
    metadata        TEXT,
    created_at      TEXT,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS cogos_trace (
    id                  TEXT PRIMARY KEY,
    run                 TEXT NOT NULL REFERENCES cogos_run(id) ON DELETE CASCADE,
    capability_calls    TEXT NOT NULL DEFAULT '[]',
    file_ops            TEXT NOT NULL DEFAULT '[]',
    model_version       TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS cogos_request_trace (
    id          TEXT PRIMARY KEY,
    cogent_id   TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    source_ref  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_span (
    id              TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    name            TEXT NOT NULL,
    coglet          TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    metadata        TEXT NOT NULL DEFAULT '{}',
    started_at      TEXT,
    ended_at        TEXT
);

CREATE TABLE IF NOT EXISTS cogos_span_event (
    id          TEXT PRIMARY KEY,
    span_id     TEXT NOT NULL REFERENCES cogos_span(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    message     TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS cogos_resource (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    resource_type   TEXT NOT NULL DEFAULT 'pool',
    capacity        REAL NOT NULL DEFAULT 1.0,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_operation (
    id          TEXT PRIMARY KEY,
    epoch       INTEGER NOT NULL DEFAULT 0,
    type        TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_executor (
    id              TEXT PRIMARY KEY,
    executor_id     TEXT NOT NULL UNIQUE,
    channel_type    TEXT NOT NULL DEFAULT 'claude-code',
    executor_tags   TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'idle',
    current_run_id  TEXT,
    dispatch_type   TEXT NOT NULL DEFAULT 'channel',
    metadata        TEXT NOT NULL DEFAULT '{}',
    last_heartbeat_at TEXT,
    registered_at   TEXT
);

CREATE TABLE IF NOT EXISTS cogos_executor_token (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    token_hash  TEXT NOT NULL UNIQUE,
    token_raw   TEXT NOT NULL DEFAULT '',
    scope       TEXT NOT NULL DEFAULT 'executor',
    created_at  TEXT,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_alert (
    id              TEXT PRIMARY KEY,
    severity        TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    source          TEXT NOT NULL,
    message         TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    acknowledged_at TEXT,
    resolved_at     TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cogos_discord_guild (
    guild_id        TEXT PRIMARY KEY,
    cogent_name     TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    icon_url        TEXT,
    member_count    INTEGER,
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS cogos_discord_channel (
    channel_id      TEXT PRIMARY KEY,
    guild_id        TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    topic           TEXT,
    category        TEXT,
    channel_type    TEXT NOT NULL DEFAULT '',
    position        INTEGER NOT NULL DEFAULT 0,
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS cogos_wait_condition (
    id          TEXT PRIMARY KEY,
    run         TEXT,
    process     TEXT,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    pending     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS cogos_epoch (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    epoch   INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO cogos_epoch (id, epoch) VALUES (1, 0);
"""


class SqliteBackend:

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "cogos.db"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.create_function(
            "regexp", 2,
            lambda pattern, string: bool(re.search(pattern, string if string is not None else "")),
        )
        self._conn.executescript(_SCHEMA_SQL)
        self._batch_depth = 0

    def _prepare_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        if not params:
            return {}
        out: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, UUID):
                out[k] = str(v)
            elif isinstance(v, bool):
                out[k] = int(v)
            elif isinstance(v, (dict, list)):
                out[k] = json.dumps(v, default=_json_serial)
            elif isinstance(v, Decimal):
                out[k] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        cur = self._conn.execute(sql, self._prepare_params(params))
        if self._batch_depth == 0:
            self._conn.commit()
        return cur.rowcount

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, self._prepare_params(params))
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._batch_depth += 1
        if self._batch_depth == 1:
            self._conn.execute("BEGIN")
        try:
            yield
            if self._batch_depth == 1:
                self._conn.commit()
        except Exception:
            if self._batch_depth == 1:
                self._conn.rollback()
            raise
        finally:
            self._batch_depth -= 1

    def batch_execute(self, sql: str, param_sets: list[dict[str, Any]]) -> int:
        total = 0
        for params in param_sets:
            total += self.execute(sql, params)
        return total

    def json_param(self, name: str) -> str:
        return f":{name}"

    def json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(json.dumps(value, default=_json_serial))
        except (TypeError, ValueError):
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
        return f"{col} LIKE :{param}"

    def regex_match(self, col: str, param: str) -> str:
        return f"{col} REGEXP :{param}"

    def t(self, canonical_name: str) -> str:
        mapping = {
            "cron": "cogos_cron",
            "alerts": "cogos_alert",
            "resources": "cogos_resource",
        }
        return mapping.get(canonical_name, canonical_name)

    def cron_col(self, canonical: str) -> str:
        return canonical

    @property
    def reboot_epoch(self) -> int:
        row = self.query_one("SELECT epoch FROM cogos_epoch WHERE id = 1")
        return row["epoch"] if row else 0

    def increment_epoch(self) -> int:
        self.execute("UPDATE cogos_epoch SET epoch = epoch + 1 WHERE id = 1")
        return self.reboot_epoch

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT OR REPLACE INTO cogos_meta (key, value) VALUES (:key, :value)",
            {"key": key, "value": value},
        )

    def get_meta(self, key: str) -> dict[str, str] | None:
        row = self.query_one("SELECT * FROM cogos_meta WHERE key = :key", {"key": key})
        if not row:
            return None
        return {"key": row["key"], "value": row.get("value", "")}
