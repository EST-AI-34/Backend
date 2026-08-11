-- FESTAI Supabase POC schema
--
-- Purpose:
-- - Keep only the tables needed by the current POC screens and API flow.
-- - Avoid loading the full enterprise ERD into Supabase before the product
--   workflow is stable.
-- - Store raw operation data in Postgres, let the backend calculate/validate
--   statistics, and let Alan/LLM use only retrieved verified results.
--
-- Recommended Supabase use:
-- - Run this file from the Supabase SQL Editor or through scripts/migrate.py
--   after replacing the migration target with this file.
-- - Do not put service-role keys or real secrets in SQL.
-- - Add RLS policies later when direct browser access is introduced. In the
--   current POC, the frontend should call the FastAPI backend instead.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS festivals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  location text,
  timezone text NOT NULL DEFAULT 'Asia/Seoul',
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','ONGOING','ENDED','ARCHIVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (starts_at < ends_at)
);

CREATE TABLE IF NOT EXISTS festival_areas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  name text NOT NULL,
  area_type text NOT NULL,
  latitude numeric(10,7),
  longitude numeric(10,7),
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS programs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid REFERENCES festival_areas(id),
  slug text NOT NULL,
  title text NOT NULL,
  summary text,
  category text NOT NULL,
  starts_at timestamptz,
  ends_at timestamptz,
  capacity integer,
  reserved_count integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('DRAFT','OPEN','SCHEDULED','CROWDED','CLOSED','CANCELLED')),
  tags jsonb NOT NULL DEFAULT '[]',
  accessibility jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (festival_id, slug),
  CHECK (capacity IS NULL OR capacity >= 0),
  CHECK (reserved_count >= 0),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR starts_at < ends_at)
);

CREATE TABLE IF NOT EXISTS facilities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid REFERENCES festival_areas(id),
  name text NOT NULL,
  facility_type text NOT NULL,
  description text,
  accessibility jsonb NOT NULL DEFAULT '{}',
  operating_hours jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid REFERENCES festival_areas(id),
  name text NOT NULL,
  category text NOT NULL,
  description text,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coupons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  store_id uuid REFERENCES stores(id) ON DELETE SET NULL,
  title text NOT NULL,
  description text,
  issued_count integer NOT NULL DEFAULT 0,
  used_count integer NOT NULL DEFAULT 0,
  expires_at timestamptz,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (issued_count >= 0),
  CHECK (used_count >= 0),
  CHECK (used_count <= issued_count)
);

CREATE TABLE IF NOT EXISTS announcements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  title text NOT NULL,
  body text NOT NULL,
  severity text NOT NULL DEFAULT 'INFO' CHECK (severity IN ('INFO','WARNING','EMERGENCY')),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','CLOSED')),
  starts_at timestamptz,
  ends_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR starts_at < ends_at)
);

CREATE TABLE IF NOT EXISTS visitor_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  anonymous_token_hash text NOT NULL UNIQUE,
  language text NOT NULL DEFAULT 'ko',
  accessibility_preferences jsonb NOT NULL DEFAULT '{}',
  consents jsonb NOT NULL DEFAULT '{}',
  expires_at timestamptz NOT NULL,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS visitor_count_samples (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid REFERENCES festival_areas(id) ON DELETE SET NULL,
  count integer NOT NULL CHECK (count >= 0),
  source text NOT NULL DEFAULT 'manual',
  measured_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS congestion_samples (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid NOT NULL REFERENCES festival_areas(id) ON DELETE CASCADE,
  level text NOT NULL CHECK (level IN ('LOW','MEDIUM','HIGH','CROWDED')),
  wait_minutes integer NOT NULL DEFAULT 0 CHECK (wait_minutes >= 0),
  source text NOT NULL DEFAULT 'manual',
  measured_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  program_id uuid NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  visitor_session_id uuid REFERENCES visitor_sessions(id) ON DELETE SET NULL,
  party_size integer NOT NULL DEFAULT 1 CHECK (party_size > 0),
  status text NOT NULL DEFAULT 'CONFIRMED' CHECK (status IN ('REQUESTED','CONFIRMED','WAITLISTED','CANCELLED','USED','NO_SHOW')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops_tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  ticket_type text NOT NULL CHECK (ticket_type IN ('COMPLAINT','INCIDENT')),
  category text NOT NULL,
  title text NOT NULL,
  description text NOT NULL,
  area_id uuid REFERENCES festival_areas(id) ON DELETE SET NULL,
  priority text NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW','NORMAL','HIGH','EMERGENCY')),
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ASSIGNED','IN_PROGRESS','RESOLVED','CLOSED')),
  ai_tag text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

CREATE TABLE IF NOT EXISTS surveys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  title text NOT NULL,
  description text,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','CLOSED')),
  prevent_duplicates boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS survey_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
  prompt text NOT NULL,
  question_type text NOT NULL CHECK (question_type IN ('RATING','SINGLE_CHOICE','MULTIPLE_CHOICE','TEXT')),
  options jsonb NOT NULL DEFAULT '[]',
  required boolean NOT NULL DEFAULT false,
  position integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS survey_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
  visitor_session_id uuid REFERENCES visitor_sessions(id) ON DELETE SET NULL,
  anonymous_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS survey_answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  response_id uuid NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES survey_questions(id) ON DELETE CASCADE,
  value jsonb NOT NULL,
  UNIQUE (response_id, question_id)
);

CREATE TABLE IF NOT EXISTS esg_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  name text NOT NULL,
  category text NOT NULL CHECK (category IN ('E','S','G')),
  formula text,
  unit text NOT NULL,
  target numeric,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS esg_measurements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  metric_id uuid NOT NULL REFERENCES esg_metrics(id) ON DELETE CASCADE,
  value numeric NOT NULL,
  source_type text NOT NULL,
  source_ref text,
  measured_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'APPROVED' CHECK (status IN ('DRAFT','APPROVED','REJECTED')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  visitor_session_id uuid REFERENCES visitor_sessions(id) ON DELETE SET NULL,
  language text NOT NULL DEFAULT 'ko',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
  question text NOT NULL,
  search_query text,
  retrieved_context jsonb NOT NULL DEFAULT '[]',
  verified_result jsonb NOT NULL DEFAULT '{}',
  answer text,
  safety_status text NOT NULL DEFAULT 'ALLOWED' CHECK (safety_status IN ('ALLOWED','BLOCKED','INSUFFICIENT_GROUNDING')),
  model_version text NOT NULL DEFAULT 'search-grounded-answer-v1',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS programs_festival_status_idx ON programs(festival_id, status, starts_at);
CREATE INDEX IF NOT EXISTS facilities_festival_type_idx ON facilities(festival_id, facility_type);
CREATE INDEX IF NOT EXISTS announcements_festival_status_idx ON announcements(festival_id, status, starts_at);
CREATE INDEX IF NOT EXISTS visitor_count_samples_time_idx ON visitor_count_samples(festival_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS congestion_samples_area_time_idx ON congestion_samples(area_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS reservations_program_status_idx ON reservations(program_id, status);
CREATE INDEX IF NOT EXISTS ops_tickets_festival_status_idx ON ops_tickets(festival_id, status, priority);
CREATE INDEX IF NOT EXISTS survey_responses_survey_time_idx ON survey_responses(survey_id, created_at DESC);
CREATE INDEX IF NOT EXISTS esg_measurements_metric_time_idx ON esg_measurements(metric_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS ai_messages_conversation_time_idx ON ai_messages(conversation_id, created_at);
