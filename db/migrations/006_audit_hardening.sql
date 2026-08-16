-- 감사에서 나온 데이터 계층 문제들을 한 번에 정리한다.

-- 1. 복호화 경로가 없는 연락처 암호문을 없앤다.
--    JWT 서명 키를 대칭 암호 키로 재사용하고 있었고(키 유출 시 토큰 위조와 PII 노출이 같이 뚫린다),
--    저장소 전체에 pgp_sym_decrypt 호출이 하나도 없어 읽을 수도 없는 쓰기 전용 데이터였다.
ALTER TABLE bookings DROP COLUMN IF EXISTS contact_encrypted;
ALTER TABLE businesses DROP COLUMN IF EXISTS contact_encrypted;

-- 2. 지도 위치 설명. 운영자 화면에 입력란이 있었지만 저장할 컬럼이 없어 매번 버려졌다.
ALTER TABLE festival_areas ADD COLUMN IF NOT EXISTS description text;

-- 3. status 컬럼에 허용값 제약이 없어 PATCH로 임의 문자열이 들어갈 수 있었다.
--    잘못된 값이 들어가면 공개 목록의 status 필터에서 조용히 사라진다.
UPDATE festival_areas SET status='ACTIVE' WHERE status NOT IN ('ACTIVE','INACTIVE','ARCHIVED');
UPDATE facilities SET status='ACTIVE' WHERE status NOT IN ('ACTIVE','INACTIVE','ARCHIVED');
UPDATE programs SET status='DRAFT' WHERE status NOT IN ('DRAFT','PUBLISHED','UNPUBLISHED','ARCHIVED');
UPDATE program_sessions SET status='OPEN' WHERE status NOT IN ('OPEN','CLOSED','CANCELLED','ENDED');

-- DROP IF EXISTS를 앞에 두어 이 파일 전체가 여러 번 돌아도 안전하게 한다.
ALTER TABLE festival_areas DROP CONSTRAINT IF EXISTS festival_areas_status_check;
ALTER TABLE festival_areas ADD CONSTRAINT festival_areas_status_check
  CHECK (status IN ('ACTIVE','INACTIVE','ARCHIVED'));
ALTER TABLE facilities DROP CONSTRAINT IF EXISTS facilities_status_check;
ALTER TABLE facilities ADD CONSTRAINT facilities_status_check
  CHECK (status IN ('ACTIVE','INACTIVE','ARCHIVED'));
ALTER TABLE programs DROP CONSTRAINT IF EXISTS programs_status_check;
ALTER TABLE programs ADD CONSTRAINT programs_status_check
  CHECK (status IN ('DRAFT','PUBLISHED','UNPUBLISHED','ARCHIVED'));
ALTER TABLE program_sessions DROP CONSTRAINT IF EXISTS program_sessions_status_check;
ALTER TABLE program_sessions ADD CONSTRAINT program_sessions_status_check
  CHECK (status IN ('OPEN','CLOSED','CANCELLED','ENDED'));

-- 3b. 방문객 AI 요청 맥락(채널·입력 방식). 스키마로 받기만 하고 버려지던 값이다.
ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS context jsonb NOT NULL DEFAULT '{}';

-- 4. 잡 재시도. 실패한 잡이 FAILED로 굳어 수동 재요청 외에 방법이 없었다.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS jobs_pending_idx ON jobs(status, created_at);

-- 5. AI 근거 검색이 cv.body::text ILIKE로 전문 스캔을 돌고 JSON 키 이름까지 매칭했다.
--    본문 텍스트 필드만 대상으로 좁히고 trigram 인덱스를 붙인다.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS content_versions_body_text_idx ON content_versions
  USING gin ((coalesce(body->>'title','') || ' ' || coalesce(body->>'summary','') || ' ' ||
              coalesce(body->>'description','') || ' ' || coalesce(body->>'text','')) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS internal_documents_body_idx ON internal_documents USING gin (body gin_trgm_ops);

-- 6. 감사 로그 키셋 페이지네이션용 정렬 키(created_at DESC, id DESC).
CREATE INDEX IF NOT EXISTS audit_festival_keyset_idx ON audit_logs(festival_id, created_at DESC, id DESC);

-- 7. 만료 데이터 정리용 인덱스. 잡 워커가 주기적으로 지운다.
CREATE INDEX IF NOT EXISTS idempotency_created_idx ON idempotency_records(created_at);
CREATE INDEX IF NOT EXISTS refresh_tokens_expiry_idx ON refresh_tokens(expires_at);
