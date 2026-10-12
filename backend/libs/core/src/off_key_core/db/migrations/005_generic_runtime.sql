-- The Python upgrade hook converts saved catalogue and monitoring configuration
-- in this same transaction. Old configuration tables are retained as an archive.
-- Measurement history is disposable for this clean break. This runs once, under
-- the migration ledger; subsequent releases preserve newly recorded history.
TRUNCATE TABLE telemetry, collection_state;
