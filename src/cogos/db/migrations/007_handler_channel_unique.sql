-- Add unique constraint on (process, channel) for channel-based handlers
ALTER TABLE cogos_handler ADD CONSTRAINT cogos_handler_process_channel_key UNIQUE (process, channel);
