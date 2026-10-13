PRAGMA application_id = 1465201712;
PRAGMA user_version = 2;
CREATE TABLE workspace_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    scope TEXT NOT NULL UNIQUE,
    root_hash TEXT NOT NULL,
    last_clock_ms INTEGER NOT NULL CHECK(last_clock_ms>=0)
);
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    graph_revision INTEGER NOT NULL CHECK(graph_revision>=1),
    release_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    max_parallel INTEGER NOT NULL CHECK(max_parallel>=0),
    retry_cap INTEGER NOT NULL CHECK(retry_cap>=0),
    retries_used INTEGER NOT NULL DEFAULT 0 CHECK(retries_used>=0),
    revision_cap INTEGER NOT NULL CHECK(revision_cap>=0),
    revisions_used INTEGER NOT NULL DEFAULT 0 CHECK(revisions_used>=0),
    deadline_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('planned','active','blocked','cancel_requested','cancelled','succeeded'))
);
CREATE TABLE nodes (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    owner TEXT NOT NULL,
    form TEXT NOT NULL CHECK(form IN ('model','program','native_action')),
    spec_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('planned','ready','claimed','running','produced','validating','succeeded','blocked','failed','cancel_requested','cancelled','superseded')),
    input_hash TEXT NOT NULL,
    attempts_used INTEGER NOT NULL DEFAULT 0 CHECK(attempts_used>=0),
    PRIMARY KEY(task_id,id)
);
CREATE TABLE dependencies (
    task_id TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    PRIMARY KEY(task_id,source,target),
    FOREIGN KEY(task_id,source) REFERENCES nodes(task_id,id),
    FOREIGN KEY(task_id,target) REFERENCES nodes(task_id,id),
    CHECK(source<>target)
);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    graph_revision INTEGER NOT NULL,
    node_revision INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    owner TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('claimed','dispatched','produced','accepted','failed','unknown','expired','superseded')),
    spec_json TEXT NOT NULL,
    FOREIGN KEY(task_id,node_id) REFERENCES nodes(task_id,id)
);
CREATE UNIQUE INDEX live_attempt ON attempts(task_id,node_id) WHERE state IN ('claimed','dispatched','produced','unknown');
CREATE TABLE leases (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
    owner TEXT NOT NULL,
    expires_ms INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','ended','expired'))
);
CREATE TABLE slots (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
    host_class TEXT NOT NULL CHECK(host_class IN ('test_local','codex_native','trusted_tool')),
    state TEXT NOT NULL CHECK(state IN ('reserved','open','completed_open','closing','release_unverified','closed')),
    close_evidence TEXT
);
CREATE TABLE invocations (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
    request_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('intent','dispatching','observed','unknown')),
    effect_class TEXT NOT NULL CHECK(effect_class IN ('project_write')),
    expected_output_path TEXT,
    expected_output_hash TEXT,
    expected_output_bytes INTEGER,
    result_hash TEXT
);
CREATE TABLE events (
    event_key TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE artifacts (
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
CREATE UNIQUE INDEX live_artifact_path ON artifacts(path) WHERE state IN ('produced','validated','adopted');
CREATE TABLE validations (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    artifact_hash TEXT NOT NULL,
    graph_revision INTEGER NOT NULL,
    validator TEXT NOT NULL,
    requirement_ids_json TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('pass','fail'))
);
CREATE TABLE acceptance_links (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    node_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    validation_id TEXT NOT NULL REFERENCES validations(id),
    PRIMARY KEY(task_id,node_id,requirement_id),
    FOREIGN KEY(task_id,node_id) REFERENCES nodes(task_id,id)
);
CREATE TABLE input_files (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes>=0),
    scope TEXT NOT NULL,
    release_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('adopted_user_input','invalidated','superseded')),
    PRIMARY KEY(id,revision)
);
CREATE UNIQUE INDEX current_input ON input_files(id) WHERE state='adopted_user_input';
CREATE TABLE task_plans (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    graph_revision INTEGER NOT NULL CHECK(graph_revision>=1),
    plan_hash TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    PRIMARY KEY(task_id,graph_revision)
);
CREATE TABLE invalidations (
    id INTEGER PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    node_id TEXT NOT NULL,
    graph_revision INTEGER NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY(task_id,node_id) REFERENCES nodes(task_id,id)
);
