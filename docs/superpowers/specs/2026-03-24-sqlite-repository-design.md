# SqliteRepository Design

Replace `LocalRepository` (JSON file) with `SqliteRepository` (SQLite) as the default local dev backend.

## Problem

Local process runs are bottlenecked by JSON I/O. `LocalRepository._save()` serializes, merges, and writes a ~15MB `cogos_data.json` file on every mutation. Even after PR #213 batched writes:

- diagnostics: 2.2s total, 1.8s (81%) I/O
- init: 6.6s total, 6.4s (97%) I/O

SQLite makes each write microseconds, projecting ~0.4s diagnostics and ~0.2s init.

## Architecture

### New File

`src/cogos/db/sqlite_repository.py` — standalone implementation of `CogosRepositoryInterface` (130 methods). Mechanical port of `repository.py` SQL patterns translated from Postgres to SQLite dialect, using Python's `sqlite3` module.

### Schema

Single consolidated migration derived from the 27 Aurora migration files, translated to SQLite syntax:

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

Schema lives as a string constant `_SCHEMA_SQL` in `sqlite_repository.py`. No separate migration files — SQLite DB is disposable (can always regenerate from JSON or fresh).

### Storage Location

Same directory structure as today: `~/.cogos/cogtainers/{name}/{cogent}/cogos.db` (or `~/.cogos/local/cogos.db` for default). Replaces `cogos_data.json` in the same directory.

### Concurrency

- SQLite WAL mode (`PRAGMA journal_mode=WAL`) for concurrent readers + single writer
- No file locking, no mtime checking, no merge logic
- The entire `_writing()` / `_maybe_reload()` / `_merge_serialized_data()` machinery (~150 lines) is not needed
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

These follow the same logic as `LocalRepository` but call SQL methods instead of mutating dicts.

### Factory Wiring

```python
# factory.py
def create_repository(..., nudge_callback=None) -> Any:
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.sqlite_repository import SqliteRepository
        return SqliteRepository(nudge_callback=nudge_callback)
    if os.environ.get("USE_LOCAL_DB") == "json":
        from cogos.db.local_repository import LocalRepository
        return LocalRepository()
    from cogos.db.repository import Repository
    return Repository.create(..., nudge_callback=nudge_callback)
```

- `USE_LOCAL_DB=1` (default local) → SqliteRepository (was LocalRepository)
- `USE_LOCAL_DB=json` → LocalRepository (escape hatch)
- No env var → Aurora Repository (unchanged)

### JSON Migration Tool

One-time converter: `cogos_data.json` → `cogos.db`:

- On `SqliteRepository.__init__()`, if `cogos.db` doesn't exist but `cogos_data.json` does, auto-migrate
- Reads JSON, inserts all records into SQLite tables
- Renames `cogos_data.json` → `cogos_data.json.bak`
- No ongoing migration — this is a one-shot on first use

### Raw SQL Support

`query()` and `execute()` pass through directly to sqlite3. LocalRepository stubs these (returns `[]` / `0`), but SqliteRepository supports them natively.

## What Doesn't Change

- `CogosRepositoryInterface` protocol — no changes
- Aurora `Repository` — no changes
- `LocalRepository` — kept as escape hatch, no changes
- All existing tests — should pass against SqliteRepository
- Data models (`Process`, `Run`, etc.) — no changes
- `_nudge_ingress()` — inherited from `Repository` base class (SqliteRepository extends Repository)

## Inheritance

`SqliteRepository` extends `Repository` (same as `LocalRepository` does today). This gives it `_nudge_ingress()` and the base class structure. It overrides all data methods with SQLite implementations.

Constructor takes `data_dir` (same as LocalRepository) and optional `ingress_queue_url` / `nudge_callback`. **Does NOT call `super().__init__()`** — manually sets `self._ingress_queue_url` and `self._nudge_callback` (same pattern as `LocalRepository`).

## Testing Strategy

- Existing db tests in `tests/cogos/db/` run against `LocalRepository` directly
- Add a conftest fixture that creates a `SqliteRepository` with a temp directory
- Parameterize existing tests to run against both backends where feasible
- Add specific tests for: migration from JSON, WAL mode, concurrent access, batch transactions

## Scope

~2500-3000 lines for `sqlite_repository.py`:
- ~100 lines: schema, init, connection management
- ~300 lines: helpers (_execute, _query, _row_to_X converters for ~24 model types)
- ~1800 lines: 130 method implementations (avg ~14 lines each)
- ~100 lines: migration tool
- ~50 lines: regexp function registration, pragma setup

Plus:
- ~20 lines: factory.py changes
- ~100 lines: new tests / test parameterization
