# Mind Memory System

Hierarchical memory store and context engine, ported from metta-ai/cogents.

## Scope

**Implemented:** MemoryStore, ContextEngine, Memory CLI, executor integration.
**Not yet implemented:** Promotion gates, sanitizer, redactor, access control, pgvector semantic search via Data API.

## Architecture

```
ContextEngine (prompt assembly)        src/memory/context_engine.py
  ↓ reads from
MemoryStore (hierarchical resolution)  src/memory/store.py
  ↓ delegates to
Repository (RDS Data API CRUD)         src/brain/db/repository.py
  ↓ backed by
PostgreSQL + pgvector                  src/brain/db/schema.sql
```

Memory is a top-level package (`src/memory/`) independent of brain. Brain's executor imports from memory for context assembly. The `brain create` CLI command invokes `memory create` to ensure schema is applied.

Each cogent has its own database — there is no `cogent_id` column in any table. The `cogent_id` is only used in the CLI layer to identify which cogent's infrastructure to target.

## Data Model

Reuses the `memory` table. Key fields:

- `scope`: `polis` (org-wide) or `cogent` (per-agent)
- `name`: hierarchical `/`-separated path (e.g., `/mind/channels/discord/api`)
- `content`: the memory text
- `embedding`: vector(1536) column exists for future semantic search
- `provenance`: JSONB metadata (source, timestamps)

Unique constraint on `(scope, name)` enables upsert behavior.

Programs have `memory_keys` and `metadata` JSONB columns. `memory_keys` lists which memory paths to load into context.

## MemoryStore (`src/memory/store.py`)

Wraps Repository with three capabilities:

### 1. Hierarchical Key Resolution

When a program declares `memory_keys: ["/mind/channels/discord/api"]`, `resolve_keys()` expands to:

```
Requested: /mind/channels/discord/api

Resolved (ordered root → leaf by path depth):
  /mind/init                          ← ancestor init
  /mind/channels/init                 ← ancestor init
  /mind/channels/discord/init         ← ancestor init
  /mind/channels/discord/api          ← exact match
  /mind/channels/discord/api/*/init   ← child inits (if any exist)
```

Algorithm:
1. For each key, walk up the path collecting `/init` at each level.
2. Add the key itself.
3. Batch fetch all exact names via `repo.get_memories_by_names()`.
4. Query for child records matching `key/` prefix via `repo.query_memory_by_prefixes()`, keep only those ending in `/init`.
5. Deduplicate: COGENT-scoped records shadow POLIS-scoped records with the same name (scope sorts ASC so cogent overwrites polis in the dict).
6. Sort by path depth (root first).

### 2. Scope-Aware Overrides

Both POLIS and COGENT records are fetched. COGENT-scoped records with the same `name` shadow POLIS-scoped records. This allows org-wide defaults with per-agent customization.

### 3. Embedding Generation

`upsert()` calls Bedrock Titan (`amazon.titan-embed-text-v2:0`) to compute embeddings before insert. Failures are logged and non-fatal — the record is still stored without an embedding.

### Interface

```python
class MemoryStore:
    def __init__(self, repo: Repository, *, embed_model: str = "amazon.titan-embed-text-v2:0")
    def resolve_keys(keys: list[str]) -> list[MemoryRecord]
    def upsert(name, content, *, scope, provenance, generate_embedding) -> MemoryRecord
    def get(name: str) -> MemoryRecord | None
    def list_memories(*, prefix, scope, limit) -> list[MemoryRecord]
    def delete_by_prefix(prefix, *, scope) -> int
    def search_similar(query, *, limit) -> list[MemoryRecord]  # stub, not yet wired
```

## ContextEngine (`src/memory/context_engine.py`)

Builds layered system prompts for Bedrock converse API calls. Programs declare which memory keys they need via `memory_keys`.

### Program Model

`memory_keys: list[str]` on `Program`. Example:

```json
{
  "name": "discord-responder",
  "content": "You are a helpful assistant...",
  "memory_keys": ["/mind/identity", "/mind/channels/discord", "/mind/policies/tone"]
}
```

### Context Layers (descending priority)

| Priority | Layer | Source | Truncatable? |
|----------|-------|--------|-------------|
| 90 | Program | `program.content` | No |
| 80 | Declared memories | `resolve_keys(program.memory_keys)`, wrapped in `<memory name="...">` tags | Yes (max 30K tokens) |
| 70 | Event context | Event type + payload | No |

### Interface

```python
@dataclass
class ContextLayer:
    name: str
    content: str
    priority: int
    max_tokens: int = 0
    truncatable: bool = True

class ContextEngine:
    def __init__(self, memory_store: MemoryStore, *, total_budget: int = 50_000)
    def build_system_prompt(program, event_data) -> list[dict]  # Bedrock system blocks
```

Budget enforcement: layers sorted by priority descending; truncatable layers are trimmed to fit within `total_budget` (estimated at 4 chars/token).

### Executor Integration

`src/brain/lambdas/executor/handler.py` `execute_program()` creates a `MemoryStore` and `ContextEngine`, replacing the previous static `[{"text": program.content}]` system prompt with `context_engine.build_system_prompt()`.

## Memory CLI (`src/memory/cli.py`)

Registered under `cogent <name> memory` via `src/cli/__main__.py`.

### Commands

```
cogent dr.alpha memory create                                          # apply schema
cogent dr.alpha memory list [--prefix /mind/channels] [--scope cogent|polis]
cogent dr.alpha memory get <name>
cogent dr.alpha memory delete <prefix> [--scope cogent|polis] [--yes]
cogent dr.alpha memory put <path> [--prefix /mind] [--scope cogent] [--no-embed]
```

### `create`

Runs `brain.db.migrations.apply_schema()` to ensure the memory table and latest schema version exist. Also invoked automatically by `cogent <name> brain create`.

### `put`

- Walks a directory recursively, upserts each `.md` file as a memory record.
- `--prefix` mounts files at a point in the tree.
  - `cogent dr.alpha memory put ./guides/ --prefix /mind/channels/discord`
  - Maps `./guides/api.md` → `/mind/channels/discord/api`
- Single file: `cogent dr.alpha memory put ./tone.md --prefix /mind/policies` → `/mind/policies/tone`
- Generates embeddings at write time (skip with `--no-embed`).
- Provenance: `{"source": "cli:put", "file": "<path>", "timestamp": "..."}`.

### `list`

Shows scope tag (`[C]`/`[P]`), name, and content preview (first 80 chars). Supports `--prefix` and `--scope` filters.

### `delete`

Previews matching records, confirms, then deletes all matching the prefix. Supports `--scope` filter and `--yes` to skip confirmation.

## Schema Changes (v2 → v3)

### Base schema (`schema.sql`)

- `memory` table: `type` column removed, `CHECK` constraint removed
- `programs` table: `memory_keys JSONB NOT NULL DEFAULT '[]'` and `metadata JSONB NOT NULL DEFAULT '{}'` added
- Indexes use `(scope, name)` — no `cogent_id` in any table
- Schema version bumped to 3

### Migration (`migrations.py`)

```sql
ALTER TABLE memory DROP COLUMN IF EXISTS type;
ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_keys JSONB NOT NULL DEFAULT '[]';
INSERT INTO schema_version (version) VALUES (3) ON CONFLICT DO NOTHING;
```

### New repository methods (`repository.py`)

- `get_memories_by_names(names)` — batch fetch by exact name using `IN` clause
- `delete_memories_by_prefix(prefix, scope)` — delete by name LIKE prefix
- `query_memory_by_prefixes(prefixes)` — fetch records matching multiple name prefixes with COGENT-over-POLIS dedup
- `query_memory()` gained a `prefix` parameter (name LIKE filter)
- `upsert_program()` and `_program_from_row()` handle `memory_keys`

### Removed

- `MemoryType` enum from `models.py` and `__init__.py`
- `type` parameter from `insert_memory()`, `query_memory()`, `_memory_from_row()`
- `cogent_id` from all data store interfaces (each cogent has its own database)

## File Layout

### New files

```
src/memory/
├── __init__.py           # exports ContextEngine, MemoryStore
├── store.py              # MemoryStore
├── context_engine.py     # ContextEngine
└── cli.py                # Click command group (create, list, get, delete, put)

src/cli/__init__.py        # get_cogent_name() shared utility
```

### Modified files

| File | Change |
|------|--------|
| `src/brain/db/models.py` | Removed `MemoryType` enum, removed `type` from `MemoryRecord`, added `memory_keys` and `metadata` to `Program` |
| `src/brain/db/repository.py` | Removed `MemoryType`, added `get_memories_by_names`, `delete_memories_by_prefix`, `query_memory_by_prefixes`, `prefix` param on `query_memory`, `memory_keys` on program methods |
| `src/brain/db/__init__.py` | Removed `MemoryType` export |
| `src/brain/db/schema.sql` | Dropped `type` from memory, added `memory_keys` and `metadata` to programs, bumped to v3 |
| `src/brain/db/migrations.py` | Added migration v3 |
| `src/brain/lambdas/executor/handler.py` | Replaced static prompt with `ContextEngine.build_system_prompt()` |
| `src/brain/cli.py` | `brain create` invokes `memory create`; `get_cogent_name` imported from `cli` |
| `src/cli/__main__.py` | Registered `memory` command group, added `memory` to `_COMMANDS` |
| `src/dashboard/routers/memory.py` | Removed `type` from SQL queries |
| `src/dashboard/models.py` | Removed `type` from `MemoryItem` |

## Future Work

- Wire pgvector semantic search through RDS Data API (currently stubbed in `search_similar`)
- Promotion gates: rule-based + LLM pipeline controlling what session outputs become durable memory
- Sanitizer: prompt injection detection before content enters memory
- Redactor: strip secrets (API keys, tokens) from memory content
- Access control: VSM scope-based read/write enforcement
