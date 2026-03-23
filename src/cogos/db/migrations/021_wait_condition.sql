-- Process wait conditions for wait/wait_any/wait_all synchronization.

CREATE TABLE IF NOT EXISTS cogos_wait_condition (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run        UUID NOT NULL REFERENCES cogos_run(id),
    type       TEXT NOT NULL CHECK (type IN ('wait', 'wait_any', 'wait_all')),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
    pending    JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wait_condition_run ON cogos_wait_condition(run);
CREATE INDEX IF NOT EXISTS idx_wait_condition_status ON cogos_wait_condition(status) WHERE status = 'pending';
