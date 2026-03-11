ALTER TABLE cogos_run
    ADD COLUMN IF NOT EXISTS delivery UUID REFERENCES cogos_event_delivery(id);

CREATE INDEX IF NOT EXISTS idx_cogos_run_delivery
    ON cogos_run(delivery)
    WHERE delivery IS NOT NULL;
