CREATE TABLE businesses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  registration_no text NOT NULL,
  name text NOT NULL,
  contact_encrypted bytea,
  address jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, registration_no)
);

CREATE TABLE festival_businesses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  business_id uuid NOT NULL REFERENCES businesses(id),
  owner_membership_id uuid REFERENCES memberships(id),
  category text NOT NULL,
  description text,
  menu jsonb NOT NULL DEFAULT '[]',
  operating_hours jsonb NOT NULL DEFAULT '{}',
  accessibility jsonb NOT NULL DEFAULT '{}',
  participation_status text NOT NULL DEFAULT 'SUBMITTED'
    CHECK (participation_status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED','INACTIVE')),
  review_comment text,
  approved_by uuid REFERENCES users(id),
  approved_at timestamptz,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (festival_id, business_id)
);

CREATE TABLE booths (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_business_id uuid NOT NULL REFERENCES festival_businesses(id),
  area_id uuid NOT NULL REFERENCES festival_areas(id),
  booth_no text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE',
  UNIQUE (festival_business_id, booth_no)
);

CREATE TABLE staff_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  membership_id uuid NOT NULL REFERENCES memberships(id),
  area_id uuid NOT NULL REFERENCES festival_areas(id),
  duty_role text NOT NULL,
  task text,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  acknowledged_at timestamptz,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (starts_at < ends_at)
);

CREATE TABLE crowd_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  area_id uuid NOT NULL REFERENCES festival_areas(id),
  program_session_id uuid REFERENCES program_sessions(id),
  source_type text NOT NULL CHECK (source_type IN ('MANUAL','ENTRY','RESERVATION','SENSOR')),
  crowd_level text NOT NULL CHECK (crowd_level IN ('QUIET','MODERATE','BUSY','FULL')),
  people_count integer CHECK (people_count IS NULL OR people_count >= 0),
  estimated_wait_min integer CHECK (estimated_wait_min IS NULL OR estimated_wait_min >= 0),
  captured_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (captured_at < expires_at)
);

CREATE TABLE bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  program_session_id uuid NOT NULL REFERENCES program_sessions(id),
  status text NOT NULL CHECK (status IN ('CONFIRMED','WAITING','CALLED','CANCELLED','NO_SHOW','COMPLETED')),
  party_size integer NOT NULL CHECK (party_size > 0 AND party_size <= 20),
  queue_number integer,
  contact_encrypted bytea,
  called_at timestamptz,
  cancelled_at timestamptz,
  completed_at timestamptz,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (visitor_session_id, program_session_id)
);

CREATE TABLE course_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  input_preferences jsonb NOT NULL,
  expected_duration_min integer NOT NULL CHECK (expected_duration_min > 0),
  generated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE course_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_plan_id uuid NOT NULL REFERENCES course_plans(id),
  program_session_id uuid NOT NULL REFERENCES program_sessions(id),
  sequence_no integer NOT NULL,
  recommendation_reason text NOT NULL,
  UNIQUE (course_plan_id, sequence_no),
  UNIQUE (course_plan_id, program_session_id)
);

CREATE TABLE coupons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_business_id uuid NOT NULL REFERENCES festival_businesses(id),
  name text NOT NULL,
  description text,
  benefit_type text NOT NULL CHECK (benefit_type IN ('FIXED','PERCENT','GIFT')),
  benefit_value numeric NOT NULL CHECK (benefit_value >= 0),
  issue_limit integer NOT NULL CHECK (issue_limit > 0),
  per_visitor_limit integer NOT NULL DEFAULT 1 CHECK (per_visitor_limit > 0),
  valid_from timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','PAUSED','ENDED')),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (valid_from < valid_until)
);

CREATE TABLE coupon_issues (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  coupon_id uuid NOT NULL REFERENCES coupons(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  issue_token_hash text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'ISSUED' CHECK (status IN ('ISSUED','REDEEMED','EXPIRED','CANCELLED')),
  issued_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE TABLE coupon_redemptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  coupon_issue_id uuid NOT NULL UNIQUE REFERENCES coupon_issues(id),
  festival_business_id uuid NOT NULL REFERENCES festival_businesses(id),
  processed_by uuid NOT NULL REFERENCES users(id),
  status text NOT NULL DEFAULT 'REDEEMED' CHECK (status IN ('REDEEMED','REVERSED')),
  redeemed_at timestamptz NOT NULL DEFAULT now(),
  reversed_at timestamptz,
  reversal_reason text
);

CREATE TABLE reward_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  name text NOT NULL,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  daily_point_limit integer NOT NULL CHECK (daily_point_limit > 0),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','PAUSED','ENDED')),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (starts_at < ends_at)
);

CREATE TABLE reward_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES reward_campaigns(id),
  action_type text NOT NULL,
  verification_type text NOT NULL,
  points integer NOT NULL CHECK (points > 0),
  per_user_limit integer NOT NULL DEFAULT 1 CHECK (per_user_limit > 0),
  rule jsonb NOT NULL DEFAULT '{}',
  UNIQUE (campaign_id, action_type)
);

CREATE TABLE reward_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reward_action_id uuid NOT NULL REFERENCES reward_actions(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  verification_key text NOT NULL,
  verification_status text NOT NULL DEFAULT 'VERIFIED' CHECK (verification_status IN ('VERIFIED','REJECTED','FLAGGED')),
  evidence jsonb NOT NULL DEFAULT '{}',
  occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (reward_action_id, visitor_session_id, verification_key)
);

CREATE TABLE point_ledger (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  reward_event_id uuid UNIQUE REFERENCES reward_events(id),
  points_delta integer NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE business_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_business_id uuid NOT NULL REFERENCES festival_businesses(id),
  visitor_session_id uuid REFERENCES visitor_sessions(id),
  event_type text NOT NULL CHECK (event_type IN ('IMPRESSION','VISIT','COUPON_ISSUE','COUPON_REDEEM','SALE')),
  sales_amount numeric CHECK (sales_amount IS NULL OR sales_amount >= 0),
  source text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE internal_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  title text NOT NULL,
  document_type text NOT NULL,
  body text NOT NULL,
  source_url text,
  allowed_roles jsonb NOT NULL DEFAULT '["SUPER_ADMIN","FESTIVAL_MANAGER"]',
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ARCHIVED')),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE issue_analysis_overrides (
  ticket_id uuid PRIMARY KEY REFERENCES ops_tickets(id),
  topic text NOT NULL,
  sentiment text NOT NULL,
  urgent boolean NOT NULL DEFAULT false,
  note text,
  updated_by uuid NOT NULL REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX businesses_festival_idx ON festival_businesses(festival_id, participation_status, updated_at DESC);
CREATE INDEX staff_assignments_schedule_idx ON staff_assignments(festival_id, membership_id, starts_at, ends_at);
CREATE INDEX crowd_latest_idx ON crowd_snapshots(festival_id, area_id, captured_at DESC);
CREATE INDEX bookings_session_idx ON bookings(program_session_id, status, created_at);
CREATE INDEX coupons_active_idx ON coupons(festival_business_id, status, valid_from, valid_until);
CREATE INDEX coupon_issues_visitor_idx ON coupon_issues(coupon_id, visitor_session_id, issued_at);
CREATE INDEX rewards_visitor_day_idx ON point_ledger(visitor_session_id, created_at);
CREATE INDEX business_events_performance_idx ON business_events(festival_business_id, event_type, occurred_at);
CREATE INDEX internal_documents_search_idx ON internal_documents(festival_id, status, updated_at DESC);
