-- Add idle_timeout_ms column to cogos_process for daemon idle reaping
ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS idle_timeout_ms BIGINT;
