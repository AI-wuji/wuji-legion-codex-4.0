CREATE TABLE resource_transfers (
    transfer_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('KnowledgeRecord','ExperienceCandidate')),
    resource_id TEXT NOT NULL,
    resource_revision INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('transfer_pending','shared_ref')),
    ack_json TEXT,
    UNIQUE(kind,resource_id)
);
CREATE TABLE received_resources (
    transfer_id TEXT PRIMARY KEY,
    source_scope TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('KnowledgeRecord','ExperienceCandidate')),
    resource_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    owner_revision INTEGER NOT NULL CHECK(owner_revision>=1),
    state TEXT NOT NULL CHECK(state IN ('active_local','retired')),
    UNIQUE(source_scope,kind,resource_id)
);
PRAGMA user_version = 4;
