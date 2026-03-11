-- Coalesce ingress nudges so high event rates do not enqueue one wake per event.

CREATE TABLE IF NOT EXISTS cogos_ingress_wake (
    key         TEXT PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
