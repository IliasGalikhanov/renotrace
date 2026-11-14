-- Backend-only schema. No anon/authenticated grants, no public REST exposure.
CREATE SCHEMA IF NOT EXISTS guest_review;
CREATE TABLE IF NOT EXISTS guest_review.sessions (
    secret_hash text PRIMARY KEY,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_review.projects (
    id text PRIMARY KEY,
    owner_hash text NOT NULL REFERENCES guest_review.sessions(secret_hash),
    expires_at timestamptz NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS projects_expiry ON guest_review.projects(expires_at);
CREATE TABLE IF NOT EXISTS guest_review.objects (
    key text PRIMARY KEY,
    project_id text NOT NULL,
    file_id text NOT NULL,
    size bigint NOT NULL,
    state text NOT NULL CHECK (state IN ('garbage','active')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS guest_review.jobs (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    file_id text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    attempts integer NOT NULL DEFAULT 0,
    lease_token text,
    lease_until timestamptz,
    UNIQUE(project_id, file_id)
);
CREATE TABLE IF NOT EXISTS guest_review.tickets (
    secret_hash text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    purpose text NOT NULL,
    file_id text,
    name text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_review.audit (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    data jsonb NOT NULL
);
REVOKE ALL ON SCHEMA guest_review FROM PUBLIC;
-- Additive stage 7 migration: existing audit rows are not calculation snapshots.
CREATE TABLE IF NOT EXISTS guest_review.snapshots (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_review.question_cards (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_review.replies (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_review.discussion_operations (
    project_id text NOT NULL REFERENCES guest_review.projects(id) ON DELETE CASCADE,
    id text NOT NULL,
    fingerprint text NOT NULL,
    resource_id text NOT NULL,
    PRIMARY KEY (project_id, id)
);
CREATE INDEX IF NOT EXISTS snapshots_project ON guest_review.snapshots(project_id, created_at);
CREATE INDEX IF NOT EXISTS cards_project ON guest_review.question_cards(project_id);
CREATE INDEX IF NOT EXISTS replies_project ON guest_review.replies(project_id);
CREATE OR REPLACE FUNCTION guest_review.immutable_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Calculation snapshots cannot be updated'; END $$;
DROP TRIGGER IF EXISTS immutable_snapshot ON guest_review.snapshots;
CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON guest_review.snapshots
FOR EACH ROW EXECUTE FUNCTION guest_review.immutable_snapshot();
REVOKE ALL ON ALL TABLES IN SCHEMA guest_review FROM PUBLIC;
