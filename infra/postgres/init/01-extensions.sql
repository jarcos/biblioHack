-- biblioHack — Postgres init.
-- Runs once at container creation thanks to Postgres' `docker-entrypoint-initdb.d`
-- convention. Idempotent (`IF NOT EXISTS`) so it's safe to re-run by hand.

CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector: embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- trigram similarity for fuzzy match
CREATE EXTENSION IF NOT EXISTS unaccent;     -- Spanish FTS with accent folding
CREATE EXTENSION IF NOT EXISTS btree_gin;    -- mixed btree + GIN indexes

-- A simple FTS configuration that strips Spanish accents.
-- We don't materialise this here — the catalog migrations in M1 will create
-- the actual tsvector columns. This is just the dictionary plumbing.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config WHERE cfgname = 'spanish_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION spanish_unaccent (COPY = spanish);
        ALTER TEXT SEARCH CONFIGURATION spanish_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, spanish_stem;
    END IF;
END
$$;
