ALTER TABLE tasks ADD COLUMN catalog_binding_hash TEXT;
CREATE TABLE task_catalog_locks (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id),
    binding_hash TEXT NOT NULL,
    binding_json TEXT NOT NULL
);
PRAGMA user_version = 5;
