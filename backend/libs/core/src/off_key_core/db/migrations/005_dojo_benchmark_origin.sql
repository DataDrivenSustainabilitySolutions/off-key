-- A dataset can now be imported from a public benchmark collection.
ALTER TABLE dojo_datasets DROP CONSTRAINT IF EXISTS ck_dojo_dataset_origin;
ALTER TABLE dojo_datasets ADD CONSTRAINT ck_dojo_dataset_origin
    CHECK (origin IN ('csv', 'history', 'benchmark'));
