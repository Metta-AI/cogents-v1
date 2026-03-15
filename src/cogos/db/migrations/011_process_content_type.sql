-- Add content_type column to cogos_process for direct Python execution support
ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'llm';
