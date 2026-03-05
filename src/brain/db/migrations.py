"""Simple migration runner: apply schema.sql, track version."""

from __future__ import annotations

from pathlib import Path

import asyncpg

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


async def get_current_version(conn: asyncpg.Connection) -> int | None:
    try:
        row = await conn.fetchrow(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        return row["version"] if row else None
    except asyncpg.UndefinedTableError:
        return None


# Incremental migrations keyed by target version.
# Add new migrations here as the schema evolves.
MIGRATIONS: dict[int, str] = {}


async def apply_schema(dsn: str) -> int:
    """Apply schema.sql if not already applied, then run incremental migrations."""
    conn = await asyncpg.connect(dsn)
    try:
        current = await get_current_version(conn)
        if current is None:
            schema_sql = SCHEMA_FILE.read_text()
            await conn.execute(schema_sql)
            row = await conn.fetchrow(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
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

        row = await conn.fetchrow(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        return row["version"]
    finally:
        await conn.close()
