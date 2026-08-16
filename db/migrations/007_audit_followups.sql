-- 코드 감사 2차 정리. 데이터 계층에서만 고칠 수 있는 것들을 모은다.

-- 1. per_user_limit > 1인 리워드가 실제로는 1회에 막혀 있었다.
--    (reward_action_id, visitor_session_id, verification_key) UNIQUE 때문인데,
--    클라이언트가 보내는 인증 키는 스팟 식별자라 재참여 때도 같은 값이다.
--    중복 제출은 Idempotency-Key가, 횟수는 per_user_limit 검사가 이미 막는다.
--    (제약 이름은 PostgreSQL이 63바이트로 자른 자동 생성 이름이다.)
ALTER TABLE reward_events DROP CONSTRAINT IF EXISTS reward_events_reward_action_id_visitor_session_id_verificat_key;

-- 2. 방문객 화면에 노출할 교통 안내. 프론트 상수로 하드코딩돼 있어 운영자가 못 고쳤다.
ALTER TABLE festivals ADD COLUMN IF NOT EXISTS transport jsonb NOT NULL DEFAULT '[]';

-- 3. 설문 운영. 등록 API가 없어 시드로만 만들 수 있었다 — 수정 시각과 낙관적 잠금이 필요하다.
ALTER TABLE surveys ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE surveys ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE surveys DROP CONSTRAINT IF EXISTS surveys_status_check;
ALTER TABLE surveys ADD CONSTRAINT surveys_status_check CHECK (status IN ('DRAFT','ACTIVE','CLOSED'));

-- 4. 로그인 실패 잠금. 프로세스 로컬 카운터는 인스턴스를 늘리면 무력화되므로 DB에 둔다.
CREATE TABLE IF NOT EXISTS login_attempts (
  email text PRIMARY KEY,
  failures integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 5. 목록 커서 페이지네이션(created_at DESC, id DESC) 정렬 키.
CREATE INDEX IF NOT EXISTS ops_tickets_keyset_idx ON ops_tickets(festival_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS bookings_keyset_idx ON bookings(festival_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS measurements_keyset_idx ON esg_measurements(festival_id, measured_at DESC, id DESC);

-- 6. 방문 세션 정리에서 참조 검사를 빠뜨린 자식 테이블 조회용.
CREATE INDEX IF NOT EXISTS survey_responses_session_idx ON survey_responses(visitor_session_id);
CREATE INDEX IF NOT EXISTS reward_events_session_idx ON reward_events(visitor_session_id);
CREATE INDEX IF NOT EXISTS course_plans_session_idx ON course_plans(visitor_session_id);
CREATE INDEX IF NOT EXISTS ai_message_reports_session_idx ON ai_message_reports(visitor_session_id);
