-- AI-04 운영 리스크 브리프, BIZ-03 지역상권 추천.
-- 업체 정보는 기존 festival_businesses를 재사용하고 부족한 두 컬럼만 추가한다.
ALTER TABLE festival_businesses
  ADD COLUMN is_sponsored boolean NOT NULL DEFAULT false,
  ADD COLUMN esg_participating boolean NOT NULL DEFAULT false;

-- 추천 노출 이력. 편향 점검(/recommendation-bias)의 유일한 입력값이다.
CREATE TABLE business_recommendation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  request_snapshot jsonb NOT NULL DEFAULT '{}',
  response_snapshot jsonb NOT NULL DEFAULT '{}',
  policy_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX recommendation_events_window_idx ON business_recommendation_events(festival_id, created_at DESC);
