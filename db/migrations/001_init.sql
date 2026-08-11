CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL CHECK (role IN ('SUPER_ADMIN','FESTIVAL_MANAGER','FIELD_OPERATOR','MERCHANT','REVIEWER')),
  festival_scope jsonb NOT NULL DEFAULT '[]',
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);

CREATE TABLE festivals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  timezone text NOT NULL DEFAULT 'Asia/Seoul',
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','ONGOING','ENDED','ARCHIVED')),
  default_language text NOT NULL DEFAULT 'ko',
  supported_languages jsonb NOT NULL DEFAULT '["ko","en"]',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (starts_at < ends_at)
);

CREATE TABLE festival_areas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  name text NOT NULL,
  area_type text NOT NULL,
  latitude numeric(10,7),
  longitude numeric(10,7),
  status text NOT NULL DEFAULT 'ACTIVE',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE facilities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  area_id uuid NOT NULL REFERENCES festival_areas(id),
  name text NOT NULL,
  facility_type text NOT NULL,
  accessibility jsonb NOT NULL DEFAULT '{}',
  operating_hours jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'ACTIVE',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE programs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  slug text NOT NULL,
  title text NOT NULL,
  summary text,
  category text NOT NULL,
  accessibility jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'DRAFT',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (festival_id, slug)
);

CREATE TABLE program_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  program_id uuid NOT NULL REFERENCES programs(id),
  area_id uuid NOT NULL REFERENCES festival_areas(id),
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  capacity integer,
  status text NOT NULL DEFAULT 'OPEN',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (starts_at < ends_at),
  CHECK (capacity IS NULL OR capacity >= 0)
);

CREATE TABLE content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  content_type text NOT NULL,
  resource_type text,
  resource_id uuid,
  slug text NOT NULL,
  lifecycle_status text NOT NULL DEFAULT 'DRAFT' CHECK (lifecycle_status IN ('DRAFT','PUBLISHED','UNPUBLISHED','ARCHIVED')),
  published_version_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (festival_id, slug)
);

CREATE TABLE content_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_item_id uuid NOT NULL REFERENCES content_items(id),
  author_id uuid NOT NULL REFERENCES users(id),
  version_no integer NOT NULL,
  language text NOT NULL,
  body jsonb NOT NULL,
  change_note text,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (content_item_id, language, version_no)
);

ALTER TABLE content_items ADD CONSTRAINT content_items_published_version_fk
  FOREIGN KEY (published_version_id) REFERENCES content_versions(id);

CREATE TABLE content_approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_version_id uuid NOT NULL REFERENCES content_versions(id),
  reviewer_id uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL CHECK (decision IN ('APPROVED','REJECTED')),
  comment text,
  decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE announcements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  title text NOT NULL,
  content_version_id uuid REFERENCES content_versions(id),
  severity text NOT NULL DEFAULT 'INFO' CHECK (severity IN ('INFO','WARNING','EMERGENCY')),
  audience jsonb NOT NULL DEFAULT '["VISITOR"]',
  target_area_ids jsonb NOT NULL DEFAULT '[]',
  starts_at timestamptz,
  ends_at timestamptz,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SCHEDULED','ACTIVE','CLOSED')),
  version integer NOT NULL DEFAULT 1,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR starts_at < ends_at)
);

CREATE TABLE ops_tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  ticket_type text NOT NULL CHECK (ticket_type IN ('COMPLAINT','INCIDENT')),
  title text NOT NULL,
  description text NOT NULL,
  area_id uuid REFERENCES festival_areas(id),
  priority text NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW','NORMAL','HIGH','EMERGENCY')),
  assignee_id uuid REFERENCES users(id),
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ASSIGNED','IN_PROGRESS','RESOLVED','CLOSED')),
  version integer NOT NULL DEFAULT 1,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  closed_at timestamptz
);

CREATE TABLE ops_ticket_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id uuid NOT NULL REFERENCES ops_tickets(id),
  actor_id uuid NOT NULL REFERENCES users(id),
  from_status text,
  to_status text NOT NULL,
  note text,
  attachments jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE visitor_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  anonymous_token_hash text NOT NULL UNIQUE,
  language text NOT NULL DEFAULT 'ko',
  accessibility_preferences jsonb NOT NULL DEFAULT '{}',
  consents jsonb NOT NULL DEFAULT '{}',
  expires_at timestamptz NOT NULL,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  language text NOT NULL DEFAULT 'ko',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES ai_conversations(id),
  question text NOT NULL,
  answer text,
  safety_status text NOT NULL CHECK (safety_status IN ('ALLOWED','BLOCKED','INSUFFICIENT_GROUNDING')),
  model_version text NOT NULL DEFAULT 'approved-content-search-v1',
  freshness_at timestamptz,
  fallback jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_message_sources (
  message_id uuid NOT NULL REFERENCES ai_messages(id),
  content_version_id uuid NOT NULL REFERENCES content_versions(id),
  rank integer NOT NULL,
  PRIMARY KEY (message_id, content_version_id)
);

CREATE TABLE ai_message_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid NOT NULL REFERENCES ai_messages(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  reason text NOT NULL,
  detail text,
  status text NOT NULL DEFAULT 'OPEN',
  decision text,
  reviewer_id uuid REFERENCES users(id),
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE surveys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  title text NOT NULL,
  description text,
  starts_at timestamptz,
  ends_at timestamptz,
  status text NOT NULL DEFAULT 'DRAFT',
  prevent_duplicates boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE survey_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id),
  prompt text NOT NULL,
  question_type text NOT NULL CHECK (question_type IN ('RATING','SINGLE_CHOICE','MULTIPLE_CHOICE','TEXT')),
  options jsonb NOT NULL DEFAULT '[]',
  required boolean NOT NULL DEFAULT false,
  position integer NOT NULL DEFAULT 0
);

CREATE TABLE survey_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id),
  visitor_session_id uuid REFERENCES visitor_sessions(id),
  anonymous_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX survey_response_session_unique ON survey_responses(survey_id, visitor_session_id) WHERE visitor_session_id IS NOT NULL;

CREATE TABLE survey_answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  response_id uuid NOT NULL REFERENCES survey_responses(id),
  question_id uuid NOT NULL REFERENCES survey_questions(id),
  value jsonb NOT NULL,
  UNIQUE (response_id, question_id)
);

CREATE TABLE esg_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  name text NOT NULL,
  category text NOT NULL CHECK (category IN ('E','S','G')),
  status text NOT NULL DEFAULT 'ACTIVE',
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE esg_metric_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_id uuid NOT NULL REFERENCES esg_metrics(id),
  version_no integer NOT NULL,
  formula text NOT NULL,
  unit text NOT NULL,
  target numeric,
  source_requirements jsonb NOT NULL,
  evidence_required boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (metric_id, version_no)
);

CREATE TABLE esg_measurements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  metric_version_id uuid NOT NULL REFERENCES esg_metric_versions(id),
  value numeric NOT NULL,
  source_type text NOT NULL,
  source_ref text,
  dedupe_key text NOT NULL,
  measured_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
  supersedes_id uuid REFERENCES esg_measurements(id),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (metric_version_id, dedupe_key)
);

CREATE TABLE esg_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  measurement_id uuid NOT NULL REFERENCES esg_measurements(id),
  file_id text NOT NULL,
  file_hash text NOT NULL,
  evidence_type text NOT NULL,
  issued_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE esg_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  measurement_id uuid NOT NULL REFERENCES esg_measurements(id),
  reviewer_id uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL CHECK (decision IN ('APPROVED','REJECTED')),
  comment text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE esg_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  title text NOT NULL,
  period_from timestamptz NOT NULL,
  period_to timestamptz NOT NULL,
  compare_with_festival_id uuid REFERENCES festivals(id),
  format text NOT NULL,
  status text NOT NULL DEFAULT 'GENERATING' CHECK (status IN ('GENERATING','DRAFT','APPROVED','EXPORTED','FAILED')),
  snapshot jsonb NOT NULL DEFAULT '{}',
  edit_metadata jsonb NOT NULL DEFAULT '{}',
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (period_from < period_to)
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid REFERENCES festivals(id),
  job_type text NOT NULL,
  resource_type text NOT NULL,
  resource_id uuid,
  status text NOT NULL DEFAULT 'PENDING',
  result jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_records (
  scope text NOT NULL,
  key text NOT NULL,
  request_hash text NOT NULL,
  response_status integer NOT NULL,
  response_body jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, key)
);

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid REFERENCES festivals(id),
  actor_id uuid REFERENCES users(id),
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id uuid,
  before_data jsonb,
  after_data jsonb,
  request_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs are append-only';
END $$;

CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

CREATE INDEX programs_public_idx ON programs(festival_id, status, updated_at DESC);
CREATE INDEX sessions_program_idx ON program_sessions(program_id, starts_at);
CREATE INDEX content_public_idx ON content_items(festival_id, lifecycle_status);
CREATE INDEX announcements_public_idx ON announcements(festival_id, status, starts_at, ends_at);
CREATE INDEX tickets_festival_idx ON ops_tickets(festival_id, status, priority);
CREATE INDEX audit_festival_idx ON audit_logs(festival_id, created_at DESC);
CREATE INDEX measurements_festival_idx ON esg_measurements(festival_id, status, measured_at);
