-- Immediate CogOS event wakeups: idempotent deliveries + transactional outbox

DO $$
BEGIN
    DELETE FROM cogos_event_delivery
    WHERE id IN (
        SELECT id
        FROM (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY event, handler
                       ORDER BY created_at ASC, id ASC
                   ) AS row_num
            FROM cogos_event_delivery
        ) duplicates
        WHERE row_num > 1
    );

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'cogos_event_delivery_event_handler_unique'
    ) THEN
        ALTER TABLE cogos_event_delivery
            ADD CONSTRAINT cogos_event_delivery_event_handler_unique
            UNIQUE (event, handler);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS cogos_event_outbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event           UUID NOT NULL REFERENCES cogos_event(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    claimed_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event)
);

CREATE INDEX IF NOT EXISTS idx_cogos_event_outbox_status_created
    ON cogos_event_outbox (status, created_at);

CREATE INDEX IF NOT EXISTS idx_cogos_event_outbox_claimed_at
    ON cogos_event_outbox (claimed_at)
    WHERE status = 'processing';

CREATE OR REPLACE FUNCTION cogos_event_outbox_trigger() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO cogos_event_outbox (event, status)
    VALUES (NEW.id, 'pending')
    ON CONFLICT (event) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cogos_event_outbox_after_insert ON cogos_event;
CREATE TRIGGER cogos_event_outbox_after_insert
    AFTER INSERT ON cogos_event
    FOR EACH ROW
    EXECUTE FUNCTION cogos_event_outbox_trigger();
