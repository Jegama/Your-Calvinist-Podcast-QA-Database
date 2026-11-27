BEGIN;

CREATE TABLE IF NOT EXISTS classification_batches (
    id uuid PRIMARY KEY,
    remote_name text,
    recovery_cursor text,
    next_check timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_classification_batches_next_check ON classification_batches (next_check);

ALTER TABLE qa_items
    ADD COLUMN IF NOT EXISTS classification_state text,
    ADD COLUMN IF NOT EXISTS classification_batch_id uuid REFERENCES classification_batches(id),
    ADD COLUMN IF NOT EXISTS classification_error text;
CREATE INDEX IF NOT EXISTS ix_qa_items_classification_batch_id ON qa_items (classification_batch_id);
CREATE INDEX IF NOT EXISTS ix_qa_items_classification_queued ON qa_items (created_at, id)
    WHERE classification_state = 'queued';

COMMIT;
