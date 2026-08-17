-- 기능 명세서 잔여 항목(BIZ-05, VIS-11, VIS-12, OPS-10, OPS-11, BIZ-04)의 데이터 계층.

-- BIZ-05 참여 상인 계정·인증.
-- 상인 계정은 이미 memberships(role='MERCHANT')로 존재하지만 발급 경로가 최고 관리자의
-- 일반 멤버십 생성뿐이라 "업체 지정 초대 링크로만 발급"이 성립하지 않았다.
-- 초대는 업체를 지정해 발급하고, 수락 시 계정과 업체 연결(owner_membership_id)이 함께 생긴다.
CREATE TABLE merchant_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_business_id uuid NOT NULL REFERENCES festival_businesses(id),
  email text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACCEPTED','REVOKED')),
  membership_id uuid REFERENCES memberships(id),
  invited_by uuid NOT NULL REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX merchant_invitations_business_idx ON merchant_invitations(festival_business_id, status, created_at DESC);

-- 상인 계정 비활성화 시각. 보유기간(비활성화 후 1년, OPS-11)의 기준점이다.
ALTER TABLE memberships ADD COLUMN IF NOT EXISTS deactivated_at timestamptz;

-- VIS-12 방문객 구역 식별. 위치정보는 쓰지 않고 진입 QR 지점과 수동 선택만 기록한다.
ALTER TABLE visitor_sessions
  ADD COLUMN IF NOT EXISTS current_area_id uuid REFERENCES festival_areas(id),
  ADD COLUMN IF NOT EXISTS area_source text,
  ADD COLUMN IF NOT EXISTS area_assigned_at timestamptz;
ALTER TABLE visitor_sessions DROP CONSTRAINT IF EXISTS visitor_sessions_area_source_check;
ALTER TABLE visitor_sessions ADD CONSTRAINT visitor_sessions_area_source_check
  CHECK (area_source IS NULL OR area_source IN ('QR','MANUAL'));

-- VIS-11 식별자 재발급 이력. 기기 변경·저장소 초기화로 익명 식별자가 새로 발급되면
-- 기능별 1인 한도가 초기화되므로, 같은 기기 버킷에서 몇 번째 발급인지를 남겨 둔다.
-- device_key는 원문을 저장하지 않는 해시 버킷이다(app/privacy.py).
CREATE TABLE visitor_identity_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  device_key text NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('ISSUED','REISSUED')),
  prior_session_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX visitor_identity_device_idx ON visitor_identity_events(festival_id, device_key, created_at DESC);

-- OPS-10 알림 전달 결과. 비로그인 웹 폴링이 1차 범위의 유일한 채널이라, 도달 여부는
-- "해당 화면을 열어 둔 세션의 폴링 응답에 실제로 실렸는가"로만 확인할 수 있다.
CREATE TABLE notification_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  resource_type text NOT NULL CHECK (resource_type IN ('ANNOUNCEMENT','BOOKING_CALL')),
  resource_id uuid NOT NULL,
  visitor_session_id uuid NOT NULL REFERENCES visitor_sessions(id),
  channel text NOT NULL DEFAULT 'WEB_POLL' CHECK (channel IN ('WEB_POLL')),
  delivered_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (resource_type, resource_id, visitor_session_id)
);
CREATE INDEX notification_deliveries_resource_idx ON notification_deliveries(festival_id, resource_type, resource_id);

-- OPS-11 정보주체 열람·삭제 요구. 본인확인은 방문객이 제시한 VIS-11 식별자로 갈음하므로
-- 접수 자체가 방문 세션 인증 경로로만 들어온다. 상태 변경 이력은 audit_logs가 남긴다.
CREATE TABLE privacy_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id),
  visitor_session_id uuid REFERENCES visitor_sessions(id),
  request_type text NOT NULL CHECK (request_type IN ('ACCESS','DELETE')),
  status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','IN_PROGRESS','COMPLETED','REJECTED')),
  detail text,
  result jsonb,
  handled_by uuid REFERENCES users(id),
  handled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX privacy_requests_festival_idx ON privacy_requests(festival_id, status, created_at DESC);

-- BIZ-04 매출 데이터는 업체 동의가 있을 때만 수집·표시한다. 동의를 철회하면 즉시 파기한다.
ALTER TABLE festival_businesses ADD COLUMN IF NOT EXISTS sales_consent boolean NOT NULL DEFAULT false;
