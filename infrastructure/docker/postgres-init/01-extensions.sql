-- Enable the extensions CareerIQ depends on.
--
-- Scripts in /docker-entrypoint-initdb.d run ONCE, when the data directory is
-- first created. They do not re-run on container restart. If you need to re-run
-- this, you must `docker compose down -v` to drop the volume.
--
-- Alembic's first migration also creates these (docs/database.md §5) so that a
-- managed database such as Cloud SQL, which never runs this script, gets them too.
-- CREATE EXTENSION IF NOT EXISTS is idempotent, so both paths are safe.

CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector: embedding storage + HNSW search (ADR-002)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram search for skill/title fuzzy matching
CREATE EXTENSION IF NOT EXISTS citext;    -- case-insensitive email column (database.md §3.1)
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() for server-side defaults

-- Test database. Integration tests need a database they can drop and recreate
-- without touching development data.
SELECT 'CREATE DATABASE careeriq_test OWNER careeriq'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'careeriq_test')\gexec

\connect careeriq_test

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
