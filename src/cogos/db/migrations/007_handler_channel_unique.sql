-- Add unique constraint on (process, channel) for channel-based handlers
CREATE UNIQUE INDEX IF NOT EXISTS idx_cogos_handler_process_channel ON cogos_handler(process, channel) WHERE channel IS NOT NULL;
