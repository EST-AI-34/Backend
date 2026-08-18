-- KIOSK-A11Y-01 키오스크 연령대 추정 큰 글씨 모드 제안 + ESG-G-08 카메라·AI 투명성.
--
-- 얼굴 검출·연령대 추정은 키오스크 브라우저 안에서만 돌고 원본 영상·특징값·추정 연령은
-- 서버로 오지 않는다. 서버가 갖는 것은 (1) 축제별 카메라 제안 on/off와 중지 사유,
-- (2) 개인과 연결되지 않는 집계용 이벤트 카운트뿐이다.

-- ESG-G-08 카메라 제안 중지 스위치. 기본값 false — 운영자가 명시로 켜야 카메라를 쓴다.
-- 꺼져 있어도 수동 큰 글씨·음성 안내는 그대로 동작한다.
ALTER TABLE festivals
  ADD COLUMN IF NOT EXISTS kiosk_camera_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS kiosk_camera_stop_reason text;

-- 익명 효과 지표. visitor_session_id를 일부러 두지 않는다 — 세션과 이으면 "누가 고령으로
-- 추정됐는지"가 사실상 남는다. 완료 기준이 요구하는 실패율·수락률·수동 전환율·완료율은
-- 모두 건수 비율이라 세션 연결 없이 계산된다.
CREATE TABLE kiosk_assist_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  event_type text NOT NULL CHECK (event_type IN (
    'CONSENT_SHOWN','CONSENT_GRANTED','CONSENT_DECLINED','ESTIMATE_FAILED',
    'SUGGESTED','ACCEPTED','DISMISSED','MANUAL_LARGE_TEXT','TASK_COMPLETED')),
  model_version text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX kiosk_assist_events_idx ON kiosk_assist_events(festival_id, event_type, created_at DESC);
