CREATE TABLE knowledge_records (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    scope TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('candidate','active_local','superseded','retired')),
    PRIMARY KEY(id,revision)
);
CREATE UNIQUE INDEX active_local_knowledge ON knowledge_records(id) WHERE state='active_local';
CREATE TABLE experience_records (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    scope TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('candidate','active_local','superseded','retired')),
    PRIMARY KEY(id,revision)
);
CREATE UNIQUE INDEX active_local_experience ON experience_records(id) WHERE state='active_local';
CREATE TABLE resource_events (
    event_key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE local_resource_acl (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    acl_version INTEGER NOT NULL CHECK(acl_version=1),
    owner_sid TEXT NOT NULL,
    scope TEXT NOT NULL,
    root_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
);
PRAGMA user_version = 3;
