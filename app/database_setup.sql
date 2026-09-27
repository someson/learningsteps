-- LearningSteps API Database Setup
--
-- Applied in two places, so it must stay plain, idempotent SQL (no psql
-- meta-commands such as \d):
--   - locally: mounted into /docker-entrypoint-initdb.d/ by docker-compose.yml,
--     run once when the postgres volume is empty
--   - in AKS: run by api/migrate.py (the db-migrate Job) as the app role

-- Creates the entries table
CREATE TABLE IF NOT EXISTS entries (
    id VARCHAR PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Creates an index on created_at for faster queries
CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at);

-- Creates an index on the JSON data for faster searches
CREATE INDEX IF NOT EXISTS idx_entries_data_gin ON entries USING GIN (data);
