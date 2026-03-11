-- Simple key-value metadata table (scheduler heartbeat, etc.)
CREATE TABLE IF NOT EXISTS cogos_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
