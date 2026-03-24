-- Add required_tags column if missing (was added to 001 after initial deploy)
ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS required_tags JSONB NOT NULL DEFAULT '[]';
