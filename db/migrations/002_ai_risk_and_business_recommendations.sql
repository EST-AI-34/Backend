CREATE TABLE IF NOT EXISTS ai_risk_briefs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_code text NOT NULL,
  include_resolved boolean NOT NULL DEFAULT false,
  source_hash text NOT NULL,
  payload jsonb NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (festival_code, include_resolved, source_hash)
);

CREATE INDEX IF NOT EXISTS ai_risk_briefs_lookup_idx
  ON ai_risk_briefs(festival_code, include_resolved, generated_at DESC);

CREATE TABLE IF NOT EXISTS recommendation_policy_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_version text NOT NULL UNIQUE,
  weights jsonb NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO recommendation_policy_configs(policy_version, weights)
VALUES (
  'biz-rec-v1',
  '{
    "base_open": 0.25,
    "category_match": 0.25,
    "distance": 0.25,
    "coupon": 0.15,
    "esg": 0.10,
    "sponsorship_affects_regular_score": false
  }'::jsonb
)
ON CONFLICT (policy_version) DO NOTHING;

CREATE TABLE IF NOT EXISTS business_recommendation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_code text NOT NULL,
  request_snapshot jsonb NOT NULL,
  response_snapshot jsonb NOT NULL,
  policy_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS business_recommendation_events_festival_idx
  ON business_recommendation_events(festival_code, created_at DESC);
