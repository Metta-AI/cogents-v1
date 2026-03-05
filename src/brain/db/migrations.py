"""Simple migration runner: apply schema.sql, track version."""

from __future__ import annotations

from pathlib import Path

import asyncpg

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


async def get_current_version(conn: asyncpg.Connection) -> int | None:
    try:
        row = await conn.fetchrow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        return row["version"] if row else None
    except asyncpg.UndefinedTableError:
        return None


# Incremental migrations keyed by target version.
# Add new migrations here as the schema evolves.
MIGRATIONS: dict[int, str] = {
    3: """
        ALTER TABLE memory DROP COLUMN IF EXISTS type;
        ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_keys JSONB NOT NULL DEFAULT '[]';
        INSERT INTO schema_version (version) VALUES (3) ON CONFLICT DO NOTHING;
    """,
    4: """
        -- New task columns
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS program_name TEXT NOT NULL DEFAULT 'do-content';
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS memory_keys JSONB NOT NULL DEFAULT '[]';
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]';
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS runner TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS clear_context BOOLEAN NOT NULL DEFAULT false;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resources JSONB NOT NULL DEFAULT '[]';

        -- Change priority from int to double precision
        ALTER TABLE tasks ALTER COLUMN priority TYPE DOUBLE PRECISION;

        -- Update status CHECK constraint
        ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
        ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
            CHECK (status IN ('runnable', 'running', 'completed', 'disabled'));
        UPDATE tasks SET status = 'runnable' WHERE status = 'pending';
        UPDATE tasks SET status = 'runnable' WHERE status = 'failed';
        ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'runnable';

        -- Unique index on tasks.name
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_unique_name ON tasks (name);

        -- Add runner column to programs
        ALTER TABLE programs ADD COLUMN IF NOT EXISTS runner TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL;

        -- Add FK from tasks.program_name to programs.name (ensure program exists first)
        INSERT INTO programs (name, content) VALUES ('do-content', '')
            ON CONFLICT (name) DO NOTHING;
        ALTER TABLE tasks ADD CONSTRAINT tasks_program_name_fkey
            FOREIGN KEY (program_name) REFERENCES programs(name);

        -- Resources tables
        CREATE TABLE IF NOT EXISTS resources (
            name          TEXT PRIMARY KEY,
            resource_type TEXT NOT NULL CHECK (resource_type IN ('pool', 'consumable')),
            capacity      DOUBLE PRECISION NOT NULL DEFAULT 1,
            metadata      JSONB NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS resource_usage (
            id            BIGSERIAL PRIMARY KEY,
            resource_name TEXT NOT NULL REFERENCES resources(name),
            run_id        UUID NOT NULL REFERENCES runs(id),
            amount        DOUBLE PRECISION NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_resource_usage_resource ON resource_usage (resource_name);
        CREATE INDEX IF NOT EXISTS idx_resource_usage_run ON resource_usage (run_id);

        INSERT INTO schema_version (version) VALUES (4) ON CONFLICT DO NOTHING;
    """,
}


async def apply_schema(dsn: str) -> int:
    """Apply schema.sql if not already applied, then run incremental migrations."""
    conn = await asyncpg.connect(dsn)
    try:
        current = await get_current_version(conn)
        if current is None:
            schema_sql = SCHEMA_FILE.read_text()
            await conn.execute(schema_sql)
            row = await conn.fetchrow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            return row["version"]

        for version in sorted(MIGRATIONS.keys()):
            if version > current:
                await conn.execute(MIGRATIONS[version])
                current = version

        return current
    finally:
        await conn.close()


async def reset_schema(dsn: str) -> int:
    """Drop all tables and re-apply schema. For testing only."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("""
            DROP TABLE IF EXISTS resource_usage CASCADE;
            DROP TABLE IF EXISTS resources CASCADE;
            DROP TABLE IF EXISTS traces CASCADE;
            DROP TABLE IF EXISTS runs CASCADE;
            DROP TABLE IF EXISTS conversations CASCADE;
            DROP TABLE IF EXISTS tasks CASCADE;
            DROP TABLE IF EXISTS channels CASCADE;
            DROP TABLE IF EXISTS triggers CASCADE;
            DROP TABLE IF EXISTS programs CASCADE;
            DROP TABLE IF EXISTS memory CASCADE;
            DROP TABLE IF EXISTS events CASCADE;
            DROP TABLE IF EXISTS alerts CASCADE;
            DROP TABLE IF EXISTS budget CASCADE;
            DROP TABLE IF EXISTS schema_version CASCADE;
        """)
        schema_sql = SCHEMA_FILE.read_text()
        await conn.execute(schema_sql)

        row = await conn.fetchrow("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        return row["version"]
    finally:
        await conn.close()
