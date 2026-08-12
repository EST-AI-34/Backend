ALTER TABLE ai_risk_briefs
  ADD CONSTRAINT ai_risk_briefs_payload_object_chk
  CHECK (jsonb_typeof(payload) = 'object') NOT VALID;

ALTER TABLE ai_risk_briefs
  ADD CONSTRAINT ai_risk_briefs_risk_level_chk
  CHECK (
    payload ? 'risk_level'
    AND payload->>'risk_level' IN ('normal', 'warning', 'critical', 'insufficient_data')
  ) NOT VALID;

ALTER TABLE ai_risk_briefs
  ADD CONSTRAINT ai_risk_briefs_risk_score_chk
  CHECK (
    payload ? 'risk_score'
    AND (payload->>'risk_score') ~ '^[0-9]+$'
    AND (payload->>'risk_score')::integer BETWEEN 0 AND 100
  ) NOT VALID;

ALTER TABLE business_recommendation_events
  ADD CONSTRAINT business_recommendation_events_request_object_chk
  CHECK (jsonb_typeof(request_snapshot) = 'object') NOT VALID;

ALTER TABLE business_recommendation_events
  ADD CONSTRAINT business_recommendation_events_response_object_chk
  CHECK (jsonb_typeof(response_snapshot) = 'object') NOT VALID;

ALTER TABLE business_recommendation_events
  ADD CONSTRAINT business_recommendation_events_policy_nonempty_chk
  CHECK (length(trim(policy_version)) > 0) NOT VALID;
