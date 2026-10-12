-- The Python upgrade hook converts saved catalogue and monitoring configuration
-- in this same transaction. Old configuration tables are retained as an archive.
-- Stable storage identities let existing measurements remain usable without a
-- legacy runtime. This upgrade does not delete measurements or latest values.
SELECT 1;
