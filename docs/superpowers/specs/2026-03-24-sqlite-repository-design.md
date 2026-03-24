# SqliteRepository Design

Replace `LocalRepository` (JSON file) with `SqliteRepository` (SQLite) as the default local dev backend. Delete `LocalRepository`. Rename `Repository` to `RdsDataApiRepository`.

## Problem

Local process runs are bottlenecked by JSON I/O. `LocalRepository._save()` serializes, merges, and writes a ~15MB `cogos_data.json` file on every mutation. Even after PR #213 batched writes:

- diagnostics: 2.2s total, 1.8s (81%) I/O
- init: 6.6s total, 6.4s (97%) I/O

SQLite makes each write microseconds, projecting ~0.4s diagnostics and ~0.2s init.

## Architecture

### Class Hierarchy

```
CogosRepositoryInterface (protocol.py)
    │   - all 130 public methods (unchanged)
    │   - _nudge_ingress() (NEW — added to protocol)
    │
    ├── RdsDataApiRepository (repository.py — renamed from Repository)
    │       - RDS Data API transport
    │       - Postgres SQL dialect
    │
    ├── SqliteRepository (sqlite_repository.py — new)
    │       - sqlite3 transport
    │       - SQLite SQL dialect
    │
    └── LocalRepository (local_repository.py — DELETED)
```

No base class. No inheritance between implementations. Both `RdsDataApiRepository` and `SqliteRepository` independently implement `CogosRepositoryInterface`.

### Protocol Change

Add `_nudge_ingress` to `CogosRepositoryInterface` in `protocol.py`:

```python
def _nudge_ingress(self, *, process_id: UUID | None = None) -> None: ...
```

Both implementations provide their own `_nudge_ingress`:
- `RdsDataApiRepository`: existing SQS-based implementation (moved from current `Repository`)
- `SqliteRepository`: same pattern — checks `_ingress_queue_url` and `_nudge_callback`, sends if configured

### Rename: Repository → RdsDataApiRepository

`src/cogos/db/repository.py` — class renamed from `Repository` to `RdsDataApiRepository`. No longer a base class for anything. All existing imports updated directly (no alias).

### New File: SqliteRepository

`src/cogos/db/sqlite_repository.py` — implementation of `CogosRepositoryInterface` (130 methods + `_nudge_ingress`) using Python's `sqlite3` module.

### Delete: LocalRepository

`src/cogos/db/local_repository.py` — deleted entirely. All references updated to `SqliteRepository`.

### Schema

Single consolidated schema derived from the 27 Aurora migration files, translated to SQLite syntax:

- `gen_random_uuid()` → Python-side `uuid4()`, stored as TEXT
- `TIMESTAMPTZ` → TEXT (ISO 8601 strings)
- `JSONB` → TEXT with `json.dumps()`/`json.loads()`; strip all `::jsonb` casts
- `NUMERIC(12,6)` → TEXT (lossless `str(Decimal)` / `Decimal(text)` round-tripping)
- `SERIAL` / `BIGSERIAL` → INTEGER PRIMARY KEY (where applicable)
- `now()` → Python-side `datetime.now(UTC).isoformat()` (not SQLite's `datetime('now')`)
- `~ :pattern` (Postgres regex) → register `sqlite3.create_function("regexp", 2, ...)` using Python `re`
- `ILIKE` → `LIKE` (SQLite LIKE is case-insensitive for ASCII by default)
- `jsonb_agg()` / `jsonb_set()` → Python-side JSON manipulation
- `string_to_array()` / `ANY()` → Python-side `IN` clause or post-query filtering
- Foreign keys enforced via `PRAGMA foreign_keys = ON`
- `ON CONFLICT ... DO UPDATE SET` works in SQLite 3.24+ (ships with Python 3.8+)

Schema lives as a string constant `_SCHEMA_SQL` in `sqlite_repository.py`. No separate migration files — SQLite DB is disposable (can always regenerate fresh).

### Storage Location

`{data_dir}/cogos.db` where `data_dir` is required (no default). Callers must provide it — typically the cogtainer runtime passes the per-cogent directory. The two fallback callsites (`cogos/cli/__main__.py:1677`, `cogos/api/db.py:38`) must be fixed to resolve a proper `data_dir` through the cogtainer runtime.

### Concurrency

- SQLite WAL mode (`PRAGMA journal_mode=WAL`) for concurrent readers + single writer
- No file locking, no mtime checking, no merge logic
- `batch()` maps to a SQLite transaction (BEGIN/COMMIT)
- `reload()` is a no-op

### Transport Layer

Each method follows this pattern:
```python
def get_process(self, process_id: UUID) -> Process | None:
    row = self._query_one(
        "SELECT * FROM cogos_process WHERE id = :id",
        {"id": str(process_id)},
    )
    return self._row_to_process(row) if row else None
```

Helper methods:
- `_execute(sql, params) -> int` — returns rowcount
- `_query(sql, params) -> list[dict]` — returns list of row dicts
- `_query_one(sql, params) -> dict | None` — returns first row or None
- `_row_to_X(row)` — converts a dict row to the corresponding model

### Business Logic Methods

Side-effect methods stay in Python, calling SQL primitives:

- `append_channel_message()` — inserts message, auto-creates deliveries for matching handlers, wakes waiting processes, nudges ingress
- `update_process_status()` — updates status, cascades DISABLE to children via Python-level recursion (loop + multiple UPDATEs in a transaction, same pattern as LocalRepository)
- `rollback_dispatch()` — resets delivery + process state atomically

### Factory Wiring

```python
# factory.py
def create_repository(..., nudge_callback=None) -> Any:
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.sqlite_repository import SqliteRepository
        return SqliteRepository(nudge_callback=nudge_callback)
    from cogos.db.repository import RdsDataApiRepository
    return RdsDataApiRepository.create(..., nudge_callback=nudge_callback)
```

- `USE_LOCAL_DB=1` → SqliteRepository
- No env var → RdsDataApiRepository
- No JSON escape hatch

### JSON Migration Tool

One-time converter: `cogos_data.json` → `cogos.db`:

- On `SqliteRepository.__init__()`, if `cogos.db` doesn't exist but `cogos_data.json` does, auto-migrate
- Reads JSON, inserts all records into SQLite tables
- Renames `cogos_data.json` → `cogos_data.json.bak`
- No ongoing migration — this is a one-shot on first use

### Raw SQL Support

`query()` and `execute()` pass through directly to sqlite3, same as `RdsDataApiRepository` passes through to RDS Data API.

## What Changes

- `CogosRepositoryInterface` — add `_nudge_ingress()` to protocol
- `Repository` → `RdsDataApiRepository` (rename, no longer a base class)
- `LocalRepository` → deleted
- New `SqliteRepository`
- `factory.py` updated
- All imports of `Repository` and `LocalRepository` updated throughout codebase

## What Doesn't Change

- Data models (`Process`, `Run`, etc.) — no changes
- `RdsDataApiRepository` behavior — identical, just renamed

## Testing Strategy

- Existing db tests updated: replace `LocalRepository` fixtures with `SqliteRepository`
- Add a conftest fixture that creates a `SqliteRepository` with a temp directory
- Add specific tests for: migration from JSON, WAL mode, batch transactions
- All 1552 existing tests should pass against SQLite backend

## Scope

New files:
- `src/cogos/db/sqlite_repository.py` (~2500-3000 lines)

Modified files:
- `src/cogos/db/protocol.py` — add `_nudge_ingress` to protocol
- `src/cogos/db/repository.py` — rename class to `RdsDataApiRepository`
- `src/cogos/db/factory.py` — update to new class names
- All files importing `Repository` or `LocalRepository` — update imports

Deleted files:
- `src/cogos/db/local_repository.py`
