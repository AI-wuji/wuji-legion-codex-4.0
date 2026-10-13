PRAGMA application_id = 1465201713;
PRAGMA user_version = 1;
CREATE TABLE registry_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    scope TEXT NOT NULL,
    root_hash TEXT NOT NULL,
    active_release TEXT,
    pointer_revision INTEGER NOT NULL DEFAULT 0 CHECK(pointer_revision>=0)
);
CREATE TABLE catalog_releases (
    release_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    validation_hash TEXT,
    state TEXT NOT NULL CHECK(state IN ('candidate','validated_local','published_local','withdrawn'))
);
CREATE TABLE catalog_consumers (
    release_id TEXT NOT NULL REFERENCES catalog_releases(release_id),
    source_id TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    PRIMARY KEY(release_id,source_id,consumer_id)
);
CREATE TABLE catalog_events (
    event_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
