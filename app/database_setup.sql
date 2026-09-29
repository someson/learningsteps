-- LearningSteps API Database Setup
--
-- Applied by api/migrate.py, locally (the `migrate` service in
-- docker-compose.yml) and in AKS (the db-migrate Job), on every start or
-- deploy. It must stay plain, idempotent SQL: no psql meta-commands, only
-- IF NOT EXISTS / IF EXISTS forms.
--
-- Runs as the admin role, which owns every object. The application role gets
-- data privileges only (granted by migrate.py): it can read and write rows
-- but cannot create, alter or drop tables.

-- Accounts. Usernames are stored lower-case; the hash string carries its own
-- algorithm parameters (see api/security.py).
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Server-side sessions. Only a SHA-256 of the cookie token is stored, so a
-- database leak does not hand out live sessions.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash BYTEA PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- Failed logins, for throttling brute force across all API replicas.
CREATE TABLE IF NOT EXISTS login_failures (
    username VARCHAR(64) NOT NULL,
    client_ip VARCHAR(64) NOT NULL,
    failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_login_failures_username ON login_failures(username, failed_at);
CREATE INDEX IF NOT EXISTS idx_login_failures_client_ip ON login_failures(client_ip, failed_at);

-- Journal entries
CREATE TABLE IF NOT EXISTS entries (
    id VARCHAR PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Owner of the entry. NULL only for rows created before accounts existed;
-- those are invisible until `create_user.py --adopt-orphans` assigns them.
ALTER TABLE entries ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;

-- Soft delete: DELETE marks the row, so a mistaken delete can be undone.
ALTER TABLE entries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at);
CREATE INDEX IF NOT EXISTS idx_entries_data_gin ON entries USING GIN (data);
CREATE INDEX IF NOT EXISTS idx_entries_user_live ON entries(user_id, created_at) WHERE deleted_at IS NULL;
