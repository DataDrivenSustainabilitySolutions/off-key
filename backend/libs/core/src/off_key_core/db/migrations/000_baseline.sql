-- The schema baseline. A fresh, empty database receives the current schema
-- from the ORM bootstrap and records this version first. Databases created
-- before the baseline carry the retired migration history and are refused:
-- they are reset, not upgraded. Later migrations follow this file in order.
SELECT 1;
