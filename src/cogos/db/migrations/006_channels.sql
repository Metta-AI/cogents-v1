-- Channels migration: add schema, channel, channel_message tables;
-- drop event, event_delivery, event_outbox, event_type tables;
-- modify handler to use channel FK instead of event_pattern.

-- ═══════════════════════════════════════════════════════════
-- NEW TABLES
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_schema (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    definition  JSONB NOT NULL DEFAULT '{}',
    file_id     UUID REFERENCES cogos_file(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cogos_channel (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    owner_process   UUID REFERENCES cogos_process(id),
    schema_id       UUID REFERENCES cogos_schema(id),
    inline_schema   JSONB,
    channel_type    TEXT NOT NULL DEFAULT 'named'
                    CHECK (channel_type IN ('implicit', 'spawn', 'named')),
    auto_close      BOOLEAN NOT NULL DEFAULT FALSE,
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cogos_channel_owner ON cogos_channel(owner_process);
CREATE INDEX IF NOT EXISTS idx_cogos_channel_type ON cogos_channel(channel_type);

CREATE TABLE IF NOT EXISTS cogos_channel_message (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel         UUID NOT NULL REFERENCES cogos_channel(id) ON DELETE CASCADE,
    sender_process  UUID REFERENCES cogos_process(id),
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cogos_channel_message_channel ON cogos_channel_message(channel, created_at);

-- ═══════════════════════════════════════════════════════════
-- MODIFY HANDLER: add channel FK, drop event_pattern
-- ═══════════════════════════════════════════════════════════

ALTER TABLE cogos_handler ADD COLUMN IF NOT EXISTS channel UUID REFERENCES cogos_channel(id);
ALTER TABLE cogos_handler DROP CONSTRAINT IF EXISTS cogos_handler_process_event_pattern_key;
ALTER TABLE cogos_handler DROP COLUMN IF EXISTS event_pattern;

-- ═══════════════════════════════════════════════════════════
-- MODIFY PROCESS: add schema_id, drop output_events
-- ═══════════════════════════════════════════════════════════

ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS schema_id UUID REFERENCES cogos_schema(id);
ALTER TABLE cogos_process DROP COLUMN IF EXISTS output_events;

-- ═══════════════════════════════════════════════════════════
-- DROP OLD EVENT TABLES
-- ═══════════════════════════════════════════════════════════

DROP TABLE IF EXISTS cogos_event_outbox CASCADE;
DROP TABLE IF EXISTS cogos_event_delivery CASCADE;
DROP TABLE IF EXISTS cogos_event_type CASCADE;
DROP TABLE IF EXISTS cogos_event CASCADE;
