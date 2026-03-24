-- Spawn-time wait: allow WaitConditions linked directly to a process (no run yet).

ALTER TABLE cogos_wait_condition ALTER COLUMN run DROP NOT NULL;
ALTER TABLE cogos_wait_condition ADD COLUMN IF NOT EXISTS process UUID REFERENCES cogos_process(id);

CREATE INDEX IF NOT EXISTS idx_wait_condition_process ON cogos_wait_condition(process) WHERE process IS NOT NULL;
