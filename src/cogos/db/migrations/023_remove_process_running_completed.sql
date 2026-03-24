-- Remove 'running' and 'completed' from process status.
-- Process status now only tracks scheduling readiness;
-- execution state belongs to runs.

-- First migrate any existing rows
UPDATE cogos_process SET status = 'waiting' WHERE status = 'running';
UPDATE cogos_process SET status = 'disabled' WHERE status = 'completed';

-- Replace the CHECK constraint
ALTER TABLE cogos_process DROP CONSTRAINT IF EXISTS cogos_process_status_check;
ALTER TABLE cogos_process ADD CONSTRAINT cogos_process_status_check
    CHECK (status IN ('waiting', 'runnable', 'blocked', 'suspended', 'disabled'));
