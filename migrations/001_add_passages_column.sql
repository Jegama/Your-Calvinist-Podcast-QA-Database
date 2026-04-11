-- Migration 001: add `passages` column to qa_items
--
-- Adds a TEXT[] column for Bible passages cited/discussed in each Q&A.
-- Idempotent: safe to re-run.
--
-- Apply against Neon before deploying the code that populates this column,
-- otherwise inserts/selects referencing `qa_items.passages` will fail.
--
--   psql "$DATABASE_URL" -f migrations/001_add_passages_column.sql

ALTER TABLE qa_items
    ADD COLUMN IF NOT EXISTS passages TEXT[] NOT NULL DEFAULT '{}';
