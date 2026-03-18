-- Add run_id to file versions for mutation tracking
ALTER TABLE cogos_file_version
  ADD COLUMN IF NOT EXISTS run_id UUID;

-- Drop old constraint if it exists (no ON DELETE), re-add with SET NULL
ALTER TABLE cogos_file_version
  DROP CONSTRAINT IF EXISTS cogos_file_version_run_id_fkey;

ALTER TABLE cogos_file_version
  ADD CONSTRAINT cogos_file_version_run_id_fkey
  FOREIGN KEY (run_id) REFERENCES cogos_run(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_file_version_run_id
  ON cogos_file_version(run_id);
