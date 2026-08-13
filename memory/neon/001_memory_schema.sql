CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS marketos_memory;

CREATE TABLE IF NOT EXISTS marketos_memory.sources (
  source_id text PRIMARY KEY,
  source_type text NOT NULL,
  title text NOT NULL,
  version text,
  authority_rank integer NOT NULL DEFAULT 100,
  status text NOT NULL,
  sha256 text,
  uri text,
  valid_from timestamptz,
  valid_to timestamptz,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.documents (
  document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id text NOT NULL REFERENCES marketos_memory.sources(source_id),
  canonical_id text,
  section_path text,
  content text NOT NULL,
  content_sha256 text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  valid_from timestamptz,
  valid_to timestamptz,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  superseded_by uuid REFERENCES marketos_memory.documents(document_id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(source_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS documents_tsv_gin ON marketos_memory.documents USING gin(tsv);
CREATE INDEX IF NOT EXISTS documents_canonical_id_idx ON marketos_memory.documents(canonical_id);
CREATE INDEX IF NOT EXISTS documents_source_id_idx ON marketos_memory.documents(source_id);

CREATE TABLE IF NOT EXISTS marketos_memory.embeddings (
  embedding_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES marketos_memory.documents(document_id) ON DELETE CASCADE,
  model_id text NOT NULL,
  model_version text,
  dimension integer NOT NULL,
  embedding vector NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(document_id, model_id, model_version)
);

CREATE TABLE IF NOT EXISTS marketos_memory.requirements (
  requirement_id text PRIMARY KEY,
  text text NOT NULL,
  authority text NOT NULL,
  status text NOT NULL,
  owner text,
  phase_targets text[] NOT NULL DEFAULT '{}',
  source_id text REFERENCES marketos_memory.sources(source_id),
  valid_from timestamptz,
  valid_to timestamptz,
  sha256 text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.decisions (
  decision_id text PRIMARY KEY,
  title text NOT NULL,
  decision text NOT NULL,
  rationale text,
  status text NOT NULL,
  authority text NOT NULL,
  source_id text REFERENCES marketos_memory.sources(source_id),
  decided_at timestamptz,
  supersedes text[],
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.open_loops (
  loop_id text PRIMARY KEY,
  description text NOT NULL,
  state text NOT NULL,
  phase_target text,
  blocker text,
  next_action text,
  source_id text REFERENCES marketos_memory.sources(source_id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.checkpoints (
  checkpoint_id text PRIMARY KEY,
  canon_version text NOT NULL,
  canon_sha256 text,
  manifest_sha256 text,
  merkle_root text,
  current_phase text,
  live_trading_state text NOT NULL,
  profitability_state text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.retrieval_receipts (
  receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query text NOT NULL,
  phase text,
  retrieved_document_ids uuid[] NOT NULL DEFAULT '{}',
  authority_filter jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  result_sha256 text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS marketos_memory.memory_events (
  event_id bigserial PRIMARY KEY,
  event_type text NOT NULL,
  entity_type text NOT NULL,
  entity_id text NOT NULL,
  event_time timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL,
  payload_sha256 text NOT NULL,
  previous_event_sha256 text,
  event_sha256 text NOT NULL UNIQUE
);

CREATE OR REPLACE VIEW marketos_memory.active_documents AS
SELECT d.* FROM marketos_memory.documents d
WHERE d.valid_to IS NULL AND d.superseded_by IS NULL;
