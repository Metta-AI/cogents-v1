-- Recreate delivery table for channel message delivery tracking
-- The event field now references a channel message ID (not an event ID)

CREATE TABLE IF NOT EXISTS cogos_event_delivery (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event       UUID NOT NULL,  -- channel message ID
    handler     UUID NOT NULL REFERENCES cogos_handler(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'queued', 'delivered', 'skipped')),
    run         UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event, handler)
);
