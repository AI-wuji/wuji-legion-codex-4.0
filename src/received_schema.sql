CREATE TABLE received_resource_versions (
    transfer_id TEXT NOT NULL REFERENCES received_resources(transfer_id),
    revision INTEGER NOT NULL CHECK(revision>=1),
    content_hash TEXT NOT NULL,
    version_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('candidate','active_local','superseded','retired')),
    PRIMARY KEY(transfer_id,revision)
);
PRAGMA user_version = 6;
