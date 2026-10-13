CREATE TABLE artifacts_next (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    node_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    producer TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('produced','validated','adopted','invalidated')),
    FOREIGN KEY(task_id,node_id) REFERENCES nodes(task_id,id)
);
INSERT INTO artifacts_next SELECT id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state FROM artifacts;
DROP TABLE artifacts;
ALTER TABLE artifacts_next RENAME TO artifacts;
CREATE UNIQUE INDEX live_artifact_path ON artifacts(path) WHERE state IN ('produced','validated','adopted');
PRAGMA user_version = 7;
