# SqliteRepository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSON-file-backed LocalRepository with a SQLite-backed SqliteRepository for local dev, rename Repository to RdsDataApiRepository, and have both implement CogosRepositoryInterface directly with no inheritance between them.

**Architecture:** Two independent implementations of CogosRepositoryInterface — RdsDataApiRepository (Postgres via RDS Data API, renamed from Repository) and SqliteRepository (SQLite via Python sqlite3). No base class, no inheritance. `_nudge_ingress` added to the protocol so both implement it.

**Tech Stack:** Python sqlite3 (stdlib), existing Pydantic models, existing CogosRepositoryInterface protocol.

**Spec:** `docs/superpowers/specs/2026-03-24-sqlite-repository-design.md`

---

## Phase 1: Foundation (no breaking changes)

### Task 1: Add `_nudge_ingress` to CogosRepositoryInterface

**Files:**
- Modify: `src/cogos/db/protocol.py`

- [ ] **Step 1: Add `_nudge_ingress` method to the protocol**

In `src/cogos/db/protocol.py`, add to the `# ── Lifecycle` section at the bottom:

```python
def _nudge_ingress(self, *, process_id: UUID | None = None) -> None: ...
```

- [ ] **Step 2: Verify no import issues**

Run: `python -c "from cogos.db.protocol import CogosRepositoryInterface"`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/cogos/db/protocol.py
git commit -m "add _nudge_ingress to CogosRepositoryInterface protocol"
```

---

### Task 2: Create SqliteRepository — schema and connection management

**Files:**
- Create: `src/cogos/db/sqlite_repository.py`
- Create: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write a basic test**

Create `tests/cogos/db/test_sqlite_repository.py`:

```python
from cogos.db.sqlite_repository import SqliteRepository


def test_creates_db_file(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert (tmp_path / "cogos.db").exists()


def test_tables_created(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    tables = repo.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    table_names = [t["name"] for t in tables]
    assert "cogos_process" in table_names
    assert "cogos_file" in table_names
    assert "cogos_run" in table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/db/test_sqlite_repository.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `sqlite_repository.py` with schema, init, and helpers**

Create `src/cogos/db/sqlite_repository.py` with:

1. **Imports** — `sqlite3`, `json`, `logging`, `re`, `os`, `uuid4`, `datetime`, `Decimal`, `Path`, all model imports (copy from `local_repository.py` imports section)

2. **`_SCHEMA_SQL`** — consolidated CREATE TABLE statements derived from the 27 Aurora migration files. Translation rules from spec:
   - `gen_random_uuid()` defaults removed (Python generates UUIDs)
   - `TIMESTAMPTZ` → `TEXT`
   - `JSONB` → `TEXT`
   - `NUMERIC(12,6)` → `TEXT`
   - `CHECK` constraints kept, `UNIQUE` constraints kept, foreign keys kept (with `ON DELETE CASCADE`)
   - Include all tables: `cogos_file`, `cogos_file_version`, `cogos_capability`, `cogos_process`, `cogos_process_capability`, `cogos_handler`, `cogos_delivery`, `cogos_cron`, `cogos_channel`, `cogos_channel_message`, `cogos_schema`, `cogos_run`, `cogos_trace`, `cogos_request_trace`, `cogos_span`, `cogos_span_event`, `cogos_resource`, `cogos_operation`, `cogos_executor`, `cogos_executor_token`, `cogos_alert`, `cogos_meta`, `cogos_discord_guild`, `cogos_discord_channel`, `cogos_wait_condition`
   - Add `cogos_epoch` table (single row: `id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER NOT NULL DEFAULT 0`)
   - Include indexes from the migration files

   Reference files:
   - `src/cogos/db/migrations/001_create_tables.sql` through `023_*.sql`
   - `src/cogos/db/local_repository.py` lines 79-103 for entity type list
   - `src/cogos/db/models/` for field types

3. **`__init__(self, data_dir: str, *, ingress_queue_url: str = "", nudge_callback: Any = None)`** — `data_dir` is the first positional parameter (required). Creates directory, opens sqlite3 connection with `check_same_thread=False`, sets `conn.row_factory = sqlite3.Row`, sets pragmas (`journal_mode=WAL`, `foreign_keys=ON`), registers regexp function, runs schema, inserts epoch row if missing.

4. **Regexp function** — `sqlite3.create_function("regexp", 2, lambda pattern, string: bool(re.search(pattern, string or "")))`

5. **Helper methods:**
   - `_execute(sql, params=None) -> int` — `cursor.execute(sql, params or {}); return cursor.rowcount`
   - `_query(sql, params=None) -> list[dict]` — `cursor.execute; return [dict(row) for row in cursor.fetchall()]`
   - `_query_one(sql, params=None) -> dict | None` — first row or None
   - `query(sql, params=None) -> list[dict]` — public passthrough
   - `execute(sql, params=None) -> int` — public passthrough
   - `_now() -> str` — `datetime.now(UTC).isoformat()`
   - `_json_dumps(obj) -> str` — `json.dumps(obj, default=_json_serial)`
   - `_json_loads(s) -> Any` — `json.loads(s) if s else None`

6. **`_nudge_ingress`** — copy implementation from `src/cogos/db/repository.py:76-98`

7. **Stub all 130 protocol methods** with `raise NotImplementedError`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/db/test_sqlite_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "add SqliteRepository with schema and connection management"
```

---

### Task 3: Implement SqliteRepository — row converters

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Add `_row_to_X` converter methods for all 24 model types**

Each converter takes a `dict` (from sqlite3 Row) and returns the model. Handle: UUID parsing, datetime parsing from ISO strings, JSON loads for TEXT columns, Decimal from TEXT, enum reconstruction, None checks.

Models (reference `src/cogos/db/models/` for fields):
`_row_to_process`, `_row_to_capability`, `_row_to_handler`, `_row_to_process_capability`, `_row_to_file`, `_row_to_file_version`, `_row_to_resource`, `_row_to_cron`, `_row_to_delivery`, `_row_to_run`, `_row_to_schema`, `_row_to_channel`, `_row_to_channel_message`, `_row_to_discord_guild`, `_row_to_discord_channel`, `_row_to_operation`, `_row_to_request_trace`, `_row_to_span`, `_row_to_span_event`, `_row_to_executor`, `_row_to_executor_token`, `_row_to_wait_condition`, `_row_to_trace`, `_row_to_alert`

Also reference `src/cogos/db/local_repository.py:283-361` (`_populate_from_data`) for how JSON maps to constructors.

- [ ] **Step 2: Write a round-trip smoke test**

```python
def test_process_round_trip(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="rt", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING,
                metadata={"key": "val"}, required_tags=["gpu"])
    repo.upsert_process(p)
    got = repo.get_process(p.id)
    assert got.name == "rt"
    assert got.metadata == {"key": "val"}
    assert got.required_tags == ["gpu"]
```

This test will fail until Task 5 implements process methods — that's expected. Just write it now as a target.

- [ ] **Step 3: Verify module imports cleanly**

Run: `python -c "from cogos.db.sqlite_repository import SqliteRepository"`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "add row-to-model converters for SqliteRepository"
```

---

### Task 4: Implement SqliteRepository — epoch, batch, lifecycle, meta, alerts, operations

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write tests**

Tests for epoch, batch transactionality, meta, clear_all, reload (see spec for expected behavior). Include a test that batch rollback works (set meta inside batch, raise, verify meta not persisted).

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement methods**

Epoch (`reboot_epoch` property, `increment_epoch`), batch (context manager with BEGIN/COMMIT/ROLLBACK, track nesting depth), lifecycle (`reload` no-op, `clear_all`, `clear_config`, `delete_files_by_prefixes`), meta (`set_meta`, `get_meta`), alerts (5 methods), operations (2 methods).

Reference `src/cogos/db/repository.py` for SQL patterns, `src/cogos/db/local_repository.py` for business logic.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement epoch, batch, meta, alerts, operations in SqliteRepository"
```

---

### Task 5: Implement SqliteRepository — processes

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write tests for process CRUD + cascade disable**

- [ ] **Step 2: Implement all 9 process methods**

Key: `update_process_status` must cascade DISABLE to children via Python-level recursion (not SQL). Reference `src/cogos/db/local_repository.py:648-694`.

- [ ] **Step 3: Run tests — expect PASS (including the round-trip test from Task 3)**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement process methods in SqliteRepository"
```

---

### Task 6: Implement SqliteRepository — files, file versions, capabilities, resources, schemas

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write smoke tests** — at minimum: insert file + get by key, bulk upsert files, grep files, glob files, insert capability + get by name

- [ ] **Step 2: Implement methods** — 10 file methods, 7 file version methods, 6 capability methods, 2 resource methods, 4 schema methods (29 total)

`grep_files()`: use registered `regexp` function. `glob_files()`: translate glob to SQL LIKE or use Python `fnmatch`. `search_capabilities()`: use `LIKE '%' || :query || '%'`. `bulk_upsert_files()`: batch INSERT in a transaction.

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement files, capabilities, resources, schemas in SqliteRepository"
```

---

### Task 7: Implement SqliteRepository — handlers, deliveries, cron

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write smoke tests** — create handler + match, create delivery + mark delivered, rollback dispatch

- [ ] **Step 2: Implement methods** — 5 handler, 10 delivery, 4 cron (19 total)

`create_delivery()` returns `(id, True)` for new, `(existing_id, False)` for duplicate. `rollback_dispatch()` resets delivery + process status atomically. Reference `src/cogos/db/local_repository.py:840-1050`.

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement handlers, deliveries, cron in SqliteRepository"
```

---

### Task 8: Implement SqliteRepository — channels, messages, wait conditions

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write smoke tests** — append channel message triggers delivery creation and process wake-up

- [ ] **Step 2: Implement methods** — 5 channel, 3 message (with side effects), 5 wait condition (13 total)

`append_channel_message()` is the most complex method — reference `src/cogos/db/local_repository.py:1379-1418` carefully. It must: insert message, idempotency check, auto-create deliveries for matching handlers, wake WAITING processes (transition to RUNNABLE), handle wait condition resolution for `child:exited` messages, nudge ingress.

`remove_from_pending()`: load JSON array, remove child PID, save back, return remaining list.

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement channels, messages, wait conditions in SqliteRepository"
```

---

### Task 9: Implement SqliteRepository — runs, traces, spans

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write smoke tests** — create run, complete run, list runs

- [ ] **Step 2: Implement methods** — 9 run, 1 trace, 8 request trace/span (18 total)

`complete_run()`: COALESCE for snapshot (only update if provided). `list_runs()` with `slim=True` omits snapshot/scope_log/result. `list_runs_by_process_glob()`: JOIN with cogos_process, use GLOB operator. `update_run_metadata()`: read current JSON, merge, write back.

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement runs, traces, spans in SqliteRepository"
```

---

### Task 10: Implement SqliteRepository — executors, tokens, discord metadata, process capabilities

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write smoke tests** — register executor + select, discord guild CRUD

- [ ] **Step 2: Implement methods** — 9 executor, 4 token, 8 discord, 4 process capability (25 total)

`select_executor()`: tag matching — must have all required_tags, prefer most preferred_tags, pick IDLE first. `reap_stale_executors()`: UPDATE to OFFLINE where heartbeat too old.

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "implement executors, discord metadata, process capabilities in SqliteRepository"
```

---

### Task 11: JSON migration tool

**Files:**
- Modify: `src/cogos/db/sqlite_repository.py`
- Modify: `tests/cogos/db/test_sqlite_repository.py`

- [ ] **Step 1: Write migration test**

Test: write a `cogos_data.json` to tmp_path, create SqliteRepository, verify data migrated and json renamed to `.bak`.

- [ ] **Step 2: Implement `_migrate_from_json()`**

In `__init__`, after schema creation: if epoch == 0 AND `cogos_data.json` exists in `data_dir`, call `_migrate_from_json()`.

**Critical: wrap the entire migration in a single transaction.** If any insert fails, the transaction rolls back and the JSON file is untouched.

`_migrate_from_json(path)`:
1. Read and parse JSON
2. BEGIN transaction
3. Handle legacy migrations (runner → required_tags, old status values) — reference `src/cogos/db/local_repository.py:362-401`
4. Insert all records into SQLite tables
5. Set epoch from JSON data
6. COMMIT
7. Only after successful commit: rename json → `.bak`

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "add JSON-to-SQLite auto-migration"
```

---

## Phase 2: Atomic switchover (rename + delete + rewire in one commit)

### Task 12: Rename Repository, delete LocalRepository, update all imports, switch factory

This is one atomic operation to avoid broken intermediate states. `LocalRepository` extends `Repository`, so renaming one without deleting the other breaks imports.

**Files:**
- Modify: `src/cogos/db/repository.py` (rename class)
- Delete: `src/cogos/db/local_repository.py`
- Modify: `src/cogos/db/factory.py`
- Modify: `src/cogos/db/protocol.py` (if __init__ re-exports)
- Modify: ~20 source files (update imports/type annotations)
- Modify: ~60 test files (LocalRepository → SqliteRepository)
- Delete: `tests/cogos/test_local_repository_prompt_migration.py` (JSON-specific tests)

- [ ] **Step 1: Rename class in `repository.py`**

`class Repository:` → `class RdsDataApiRepository:`
`def create(...) -> Repository:` → `def create(...) -> RdsDataApiRepository:`

- [ ] **Step 2: Update factory.py**

```python
def create_repository(
    *,
    data_dir: str | None = None,
    resource_arn: str | None = None,
    secret_arn: str | None = None,
    database: str | None = None,
    region: str | None = None,
    client: Any | None = None,
    nudge_callback: Any | None = None,
) -> Any:
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.sqlite_repository import SqliteRepository
        if data_dir is None:
            raise ValueError("data_dir is required for local SQLite repository")
        return SqliteRepository(data_dir, nudge_callback=nudge_callback)
    from cogos.db.repository import RdsDataApiRepository
    return RdsDataApiRepository.create(
        resource_arn=resource_arn, secret_arn=secret_arn,
        database=database, region=region, client=client,
        nudge_callback=nudge_callback,
    )
```

- [ ] **Step 3: Update source files — type annotations**

All files that import `from cogos.db.repository import Repository` for **type hints** — change to `from cogos.db.protocol import CogosRepositoryInterface`:

- `src/cogos/executor/capabilities.py`
- `src/cogos/executor/handler.py` (many type hints)
- `src/cogos/executor/agent_sdk.py`
- `src/cogos/sandbox/server.py`
- `src/cogos/capabilities/loader.py`
- `src/cogents/loader/process.py`
- `src/cogents/loader/capability.py`
- `src/cogents/cogos/cli.py`
- `src/cogos/api/db.py`

Files that **construct** Repository — change to `RdsDataApiRepository`:

- `src/cogtainer/runtime/aws.py`
- `src/cogtainer/update_cli.py` (4 occurrences)

- [ ] **Step 4: Update source files — LocalRepository callsites**

- `src/cogtainer/runtime/local.py:51-56` — change to `SqliteRepository(data_dir=str(cogent_dir), ...)`
- `src/cogos/api/db.py:35-38` — change fallback to `SqliteRepository` with proper data_dir resolution from cogtainer config
- `src/cogos/cli/__main__.py:1676-1677` — change to `SqliteRepository` with data_dir from context
- `src/cogos/runtime/local_ingress_queue.py` — update import/construction

- [ ] **Step 5: Delete LocalRepository**

```bash
git rm src/cogos/db/local_repository.py
```

- [ ] **Step 6: Update all test files**

In every test file that imports `from cogos.db.local_repository import LocalRepository`:
- Change to: `from cogos.db.sqlite_repository import SqliteRepository`
- Change all: `LocalRepository(str(tmp_path))` → `SqliteRepository(str(tmp_path))`
- Change all: `LocalRepository(data_dir=str(tmp_path))` → `SqliteRepository(data_dir=str(tmp_path))`

~60 test files need this change (full list in spec exploration results).

Also:
- `tests/cogos/db/test_repository_runs.py` — change `from cogos.db.repository import Repository` to `RdsDataApiRepository`
- Same for `test_repository_channels.py`, `test_repo_grep.py`, `test_repo_glob.py`, `test_jsonb_safe.py`

Delete: `tests/cogos/test_local_repository_prompt_migration.py` (JSON-specific migration tests no longer apply)

- [ ] **Step 7: Check `src/cogos/db/__init__.py` for re-exports**

Update any re-exports of `Repository` or `LocalRepository`.

- [ ] **Step 8: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: PASS (may need iteration)

- [ ] **Step 9: Commit**

```bash
git add -u
git add src/cogos/db/sqlite_repository.py tests/cogos/db/test_sqlite_repository.py
git commit -m "switch to SqliteRepository, rename Repository to RdsDataApiRepository, delete LocalRepository"
```

---

## Phase 3: Verify

### Task 13: Final verification and cleanup

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -50`
Expected: all pass

- [ ] **Step 2: Run linter**

Run: `ruff check src/cogos/db/ tests/cogos/db/`
Fix any issues.

- [ ] **Step 3: Verify protocol compliance**

```python
python -c "
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.protocol import CogosRepositoryInterface
import tempfile, os
d = tempfile.mkdtemp()
assert isinstance(SqliteRepository(d), CogosRepositoryInterface)
print('Protocol compliance: OK')
"
```

- [ ] **Step 4: Verify RdsDataApiRepository imports**

```python
python -c "from cogos.db.repository import RdsDataApiRepository; print('OK')"
```

- [ ] **Step 5: Commit any final fixes**

```bash
git add -u
git commit -m "final cleanup for SqliteRepository"
```
