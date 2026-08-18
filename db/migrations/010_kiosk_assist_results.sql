-- KIOSK-A11Y-01: 관리자에게 익명 판정 범주를 보여주기 위한 결과 로그.
-- 영상·얼굴 특징값·추정 연령·방문객 세션은 저장하지 않는다.
ALTER TABLE kiosk_assist_events
  DROP CONSTRAINT IF EXISTS kiosk_assist_events_event_type_check;

ALTER TABLE kiosk_assist_events
  ADD CONSTRAINT kiosk_assist_events_event_type_check CHECK (event_type IN (
    'CONSENT_SHOWN','CONSENT_GRANTED','CONSENT_DECLINED','ESTIMATE_FAILED',
    'ESTIMATE_RESULT','SUGGESTED','ACCEPTED','DISMISSED','MANUAL_LARGE_TEXT','TASK_COMPLETED'));

ALTER TABLE kiosk_assist_events
  ADD COLUMN IF NOT EXISTS result text;

ALTER TABLE kiosk_assist_events
  ADD CONSTRAINT kiosk_assist_events_result_check CHECK (
    (event_type = 'ESTIMATE_RESULT' AND result IN ('SENIOR','OTHER','UNAVAILABLE'))
    OR (event_type <> 'ESTIMATE_RESULT' AND result IS NULL));

CREATE INDEX IF NOT EXISTS kiosk_assist_results_idx
  ON kiosk_assist_events(festival_id, event_type, result, created_at DESC);
