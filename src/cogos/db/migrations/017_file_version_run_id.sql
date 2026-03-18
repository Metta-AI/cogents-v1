-- Add run_id to file versions for mutation tracking
ALTER TABLE cogos_file_version
  ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES cogos_run(id);

CREATE INDEX IF NOT EXISTS idx_file_version_run_id
  ON cogos_file_version(run_id);
