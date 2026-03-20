-- Change process unique constraint from (name) to (name, epoch)
-- so that reboots can create fresh processes with the same name in a new epoch.
ALTER TABLE cogos_process DROP CONSTRAINT IF EXISTS cogos_process_name_key;
ALTER TABLE cogos_process ADD CONSTRAINT cogos_process_name_epoch_key UNIQUE (name, epoch);
