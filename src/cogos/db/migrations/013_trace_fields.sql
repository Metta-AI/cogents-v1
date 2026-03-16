-- Add trace profiling columns to CogOS tables
ALTER TABLE cogos_channel_message ADD COLUMN IF NOT EXISTS trace_id UUID;
ALTER TABLE cogos_channel_message ADD COLUMN IF NOT EXISTS trace_meta JSONB;

ALTER TABLE cogos_delivery ADD COLUMN IF NOT EXISTS trace_id UUID;

ALTER TABLE cogos_run ADD COLUMN IF NOT EXISTS trace_id UUID;
ALTER TABLE cogos_run ADD COLUMN IF NOT EXISTS parent_trace_id UUID;

CREATE INDEX IF NOT EXISTS idx_cogos_channel_message_trace ON cogos_channel_message(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cogos_run_trace ON cogos_run(trace_id) WHERE trace_id IS NOT NULL;
