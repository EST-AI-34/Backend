-- Allen API and AI operations briefing demo data for FEST-ON Backend.
-- Source schema checked against origin/main 25b4035ce929a25c1d6b898d135c0b56ffdc33ac.
-- This file is intentionally INSERT-only plus verification SELECTs.
-- Do not run this against production.

-- Stable demo identifiers.
-- Organization: 11111111-1111-4111-8111-111111111111
-- Festival:     22222222-2222-4222-8222-222222222222
-- Area A:       33333333-3333-4333-8333-333333333301
-- Area B:       33333333-3333-4333-8333-333333333302
-- Area C:       33333333-3333-4333-8333-333333333303

INSERT INTO organizations (id, name, status, created_at)
VALUES
  ('11111111-1111-4111-8111-111111111111', 'FEST-ON Allen Demo Organization', 'ACTIVE', now())
ON CONFLICT DO NOTHING;

INSERT INTO users (id, email, password_hash, name, status, created_at)
VALUES
  ('11111111-2222-4222-8222-111111111101', 'allen-demo-manager@example.invalid', 'demo-disabled-password-hash', 'Allen Demo Manager', 'ACTIVE', now()),
  ('11111111-2222-4222-8222-111111111102', 'allen-demo-operator@example.invalid', 'demo-disabled-password-hash', 'Allen Demo Operator', 'ACTIVE', now()),
  ('11111111-2222-4222-8222-111111111103', 'allen-demo-reviewer@example.invalid', 'demo-disabled-password-hash', 'Allen Demo Reviewer', 'ACTIVE', now())
ON CONFLICT DO NOTHING;

INSERT INTO memberships (id, organization_id, user_id, role, festival_scope, status, created_at)
VALUES
  (
    '11111111-3333-4333-8333-111111111201',
    '11111111-1111-4111-8111-111111111111',
    '11111111-2222-4222-8222-111111111101',
    'FESTIVAL_MANAGER',
    '["22222222-2222-4222-8222-222222222222"]'::jsonb,
    'ACTIVE',
    now()
  ),
  (
    '11111111-3333-4333-8333-111111111202',
    '11111111-1111-4111-8111-111111111111',
    '11111111-2222-4222-8222-111111111102',
    'FIELD_OPERATOR',
    '["22222222-2222-4222-8222-222222222222"]'::jsonb,
    'ACTIVE',
    now()
  ),
  (
    '11111111-3333-4333-8333-111111111203',
    '11111111-1111-4111-8111-111111111111',
    '11111111-2222-4222-8222-111111111103',
    'REVIEWER',
    '["22222222-2222-4222-8222-222222222222"]'::jsonb,
    'ACTIVE',
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO festivals (
  id,
  organization_id,
  code,
  name,
  description,
  timezone,
  starts_at,
  ends_at,
  status,
  default_language,
  supported_languages,
  version,
  created_at,
  updated_at
)
VALUES (
  '22222222-2222-4222-8222-222222222222',
  '11111111-1111-4111-8111-111111111111',
  'ALLEN-DEMO-2026',
  'Allen Demo Festival 2026',
  'Synthetic demo festival for Allen API and AI operations briefing tests.',
  'Asia/Seoul',
  now() - interval '1 day',
  now() + interval '2 days',
  'PUBLISHED',
  'ko',
  '["ko", "en"]'::jsonb,
  1,
  now(),
  now()
)
ON CONFLICT DO NOTHING;

INSERT INTO festival_areas (
  id,
  festival_id,
  name,
  area_type,
  latitude,
  longitude,
  status,
  version,
  created_at,
  updated_at
)
VALUES
  (
    '33333333-3333-4333-8333-333333333301',
    '22222222-2222-4222-8222-222222222222',
    'A Zone Main Stage',
    'STAGE',
    37.566500,
    126.978000,
    'ACTIVE',
    1,
    now(),
    now()
  ),
  (
    '33333333-3333-4333-8333-333333333302',
    '22222222-2222-4222-8222-222222222222',
    'B Zone Food Court',
    'FOOD',
    37.566900,
    126.979200,
    'ACTIVE',
    1,
    now(),
    now()
  ),
  (
    '33333333-3333-4333-8333-333333333303',
    '22222222-2222-4222-8222-222222222222',
    'C Zone Family Lawn',
    'REST',
    37.565900,
    126.977200,
    'ACTIVE',
    1,
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO facilities (
  id,
  festival_id,
  area_id,
  name,
  facility_type,
  accessibility,
  operating_hours,
  status,
  version,
  created_at,
  updated_at
)
VALUES
  (
    '44444444-4444-4444-8444-444444444401',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'A구역 화장실',
    'RESTROOM',
    '{"wheelchair_accessible": true}'::jsonb,
    '{"open": "09:00", "close": "23:00"}'::jsonb,
    'ACTIVE',
    1,
    now(),
    now()
  ),
  (
    '44444444-4444-4444-8444-444444444402',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'B구역 화장실',
    'RESTROOM',
    '{"wheelchair_accessible": true}'::jsonb,
    '{"open": "09:00", "close": "23:00"}'::jsonb,
    'ACTIVE',
    1,
    now(),
    now()
  ),
  (
    '44444444-4444-4444-8444-444444444403',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333303',
    '종합 안내소',
    'INFO',
    '{"wheelchair_accessible": true, "interpreter": true}'::jsonb,
    '{"open": "09:00", "close": "23:00"}'::jsonb,
    'ACTIVE',
    1,
    now(),
    now()
  ),
  (
    '44444444-4444-4444-8444-444444444404',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    '의무실',
    'MEDICAL',
    '{"wheelchair_accessible": true, "first_aid": true}'::jsonb,
    '{"open": "09:00", "close": "23:00"}'::jsonb,
    'ACTIVE',
    1,
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO staff_assignments (
  id,
  festival_id,
  membership_id,
  area_id,
  duty_role,
  task,
  starts_at,
  ends_at,
  created_by,
  created_at,
  updated_at
)
VALUES
  (
    '55555555-5555-4555-8555-555555555502',
    '22222222-2222-4222-8222-222222222222',
    '11111111-3333-4333-8333-111111111202',
    '33333333-3333-4333-8333-333333333302',
    'FIELD_OPERATOR',
    'Monitor B Zone queue and refill station status.',
    now() - interval '1 hour',
    now() + interval '4 hours',
    '11111111-2222-4222-8222-111111111101',
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO programs (
  id,
  festival_id,
  slug,
  title,
  summary,
  category,
  accessibility,
  status,
  version,
  created_at,
  updated_at
)
VALUES
  (
    '66666666-6666-4666-8666-666666666601',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-main-parade',
    '메인 퍼레이드',
    'A구역 급증을 유발하는 데모 헤드라이너 행사. 시작 시간이 변경됐다(program_sessions.updated_at 참고).',
    'PARADE',
    '{"captioning": true, "large_text_supported": true}'::jsonb,
    'PUBLISHED',
    1,
    now(),
    now()
  ),
  (
    '66666666-6666-4666-8666-666666666602',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-local-food-showcase',
    'B구역 로컬 푸드쇼',
    'B구역 안정 상태 비교용 데모 프로그램(일정 변경 없음).',
    'FOOD',
    '{"wheelchair_route": true}'::jsonb,
    'PUBLISHED',
    1,
    now(),
    now()
  ),
  (
    '66666666-6666-4666-8666-666666666603',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-kpop-concert',
    'K-POP 공연',
    '메인 스테이지에서 열리는 데모 K-POP 공연.',
    'MUSIC',
    '{"captioning": true}'::jsonb,
    'PUBLISHED',
    1,
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO program_sessions (
  id,
  festival_id,
  program_id,
  area_id,
  starts_at,
  ends_at,
  capacity,
  status,
  version,
  created_at,
  updated_at
)
VALUES
  -- 메인 퍼레이드: 원래 등록 시각(created_at)보다 한참 뒤(updated_at)에 시작 시각이 바뀌었다
  -- (18:00 -> 18:30에 대응하는 30분 지연). "변경된 일정 있어?"에 이 세션이 잡혀야 한다.
  (
    '66666666-7777-4777-8777-666666666701',
    '22222222-2222-4222-8222-222222222222',
    '66666666-6666-4666-8666-666666666601',
    '33333333-3333-4333-8333-333333333301',
    now() + interval '2 hours',
    now() + interval '3 hours',
    1200,
    'OPEN',
    1,
    now() - interval '2 hours',
    now() - interval '20 minutes'
  ),
  (
    '66666666-7777-4777-8777-666666666702',
    '22222222-2222-4222-8222-222222222222',
    '66666666-6666-4666-8666-666666666602',
    '33333333-3333-4333-8333-333333333302',
    now() + interval '90 minutes',
    now() + interval '150 minutes',
    300,
    'OPEN',
    1,
    now() - interval '2 hours',
    now() - interval '2 hours'
  ),
  -- K-POP 공연: 변경 없이 등록 그대로(created_at == updated_at) — 일정 변경 질문에서 제외돼야 한다.
  (
    '66666666-7777-4777-8777-666666666703',
    '22222222-2222-4222-8222-222222222222',
    '66666666-6666-4666-8666-666666666603',
    '33333333-3333-4333-8333-333333333301',
    now() + interval '3 hours 30 minutes',
    now() + interval '5 hours',
    2000,
    'OPEN',
    1,
    now() - interval '2 hours',
    now() - interval '2 hours'
  )
ON CONFLICT DO NOTHING;

INSERT INTO crowd_snapshots (
  id,
  festival_id,
  area_id,
  source_type,
  captured_at,
  crowd_level,
  people_count,
  expires_at,
  created_by,
  created_at
)
VALUES
  -- A구역: 30분 동안 250 -> 520 -> 780 -> 950명으로 급격히 증가 (rapidly_increasing 추세).
  (
    '77777777-7777-4777-8777-777777777701',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'SENSOR',
    now() - interval '30 minutes',
    'MODERATE',
    250,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777702',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'SENSOR',
    now() - interval '20 minutes',
    'BUSY',
    520,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777703',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'SENSOR',
    now() - interval '10 minutes',
    'BUSY',
    780,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777708',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'SENSOR',
    now(),
    'FULL',
    950,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  -- B구역: 같은 30분 동안 180 -> 190 -> 185 -> 200명으로 안정적(stable 추세) — A와 비교되는 대조군.
  (
    '77777777-7777-4777-8777-777777777704',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'SENSOR',
    now() - interval '30 minutes',
    'MODERATE',
    180,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777705',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'SENSOR',
    now() - interval '20 minutes',
    'MODERATE',
    190,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777706',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'SENSOR',
    now() - interval '10 minutes',
    'MODERATE',
    185,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777709',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'SENSOR',
    now(),
    'MODERATE',
    200,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  ),
  (
    '77777777-7777-4777-8777-777777777707',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333303',
    'SENSOR',
    now() - interval '9 minutes',
    'QUIET',
    90,
    now() + interval '2 hours',
    '11111111-2222-4222-8222-111111111102',
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO ops_tickets (
  id,
  festival_id,
  area_id,
  ticket_type,
  priority,
  status,
  title,
  description,
  created_by,
  created_at,
  updated_at
)
VALUES
  (
    '88888888-8888-4888-8888-888888888801',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'INCIDENT',
    'HIGH',
    'OPEN',
    'A Zone barrier pressure',
    'Synthetic ticket: barrier line pressure increased after headliner queue formed.',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '24 minutes',
    now() - interval '4 minutes'
  ),
  (
    '88888888-8888-4888-8888-888888888802',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'INCIDENT',
    'EMERGENCY',
    'IN_PROGRESS',
    'A Zone exit lane blocked',
    'Synthetic ticket: temporary blockage near the east exit lane.',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '16 minutes',
    now() - interval '3 minutes'
  ),
  (
    '88888888-8888-4888-8888-888888888805',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333301',
    'INCIDENT',
    'HIGH',
    'OPEN',
    'A Zone first-aid request',
    'Synthetic ticket: visitor reported feeling unwell near the main stage crowd line.',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '8 minutes',
    now() - interval '2 minutes'
  ),
  (
    '88888888-8888-4888-8888-888888888803',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333302',
    'COMPLAINT',
    'NORMAL',
    'OPEN',
    'B Zone waiting line delay',
    'Synthetic ticket: food court queue is longer than expected but stable.',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '35 minutes',
    now() - interval '12 minutes'
  ),
  (
    '88888888-8888-4888-8888-888888888804',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333303',
    'COMPLAINT',
    'LOW',
    'RESOLVED',
    'C Zone signage replacement',
    'Synthetic ticket: wayfinding sign replaced.',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '3 hours',
    now() - interval '90 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO ops_ticket_events (
  id,
  ticket_id,
  actor_id,
  from_status,
  to_status,
  note,
  created_at
)
VALUES
  (
    '88888888-9999-4999-8999-888888888901',
    '88888888-8888-4888-8888-888888888801',
    '11111111-2222-4222-8222-111111111102',
    NULL,
    'OPEN',
    'Initial report created from demo field observation.',
    now() - interval '24 minutes'
  ),
  (
    '88888888-9999-4999-8999-888888888902',
    '88888888-8888-4888-8888-888888888802',
    '11111111-2222-4222-8222-111111111102',
    'OPEN',
    'IN_PROGRESS',
    'Crowd control staff dispatched to east exit.',
    now() - interval '3 minutes'
  ),
  (
    '88888888-9999-4999-8999-888888888903',
    '88888888-8888-4888-8888-888888888804',
    '11111111-2222-4222-8222-111111111102',
    'OPEN',
    'RESOLVED',
    'Signage replacement completed.',
    now() - interval '90 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO content_items (
  id,
  festival_id,
  slug,
  content_type,
  lifecycle_status,
  published_version_id,
  created_at,
  updated_at
)
VALUES
  (
    '99999999-9999-4999-8999-999999999901',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-a-zone-entry-control',
    'ANNOUNCEMENT',
    'PUBLISHED',
    NULL,
    now(),
    now()
  ),
  (
    '99999999-9999-4999-8999-999999999902',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-b-zone-food-notice',
    'ANNOUNCEMENT',
    'PUBLISHED',
    NULL,
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO content_versions (
  id,
  content_item_id,
  author_id,
  version_no,
  language,
  body,
  change_note,
  status,
  created_at
)
VALUES
  (
    '99999999-aaaa-4aaa-8aaa-999999999a01',
    '99999999-9999-4999-8999-999999999901',
    '11111111-2222-4222-8222-111111111101',
    1,
    'ko',
    '{"title": "A Zone entry is temporarily controlled", "body": "Demo announcement: A Zone entry is being paced while staff clear the east exit lane."}'::jsonb,
    'Initial demo announcement.',
    'APPROVED',
    now() - interval '12 minutes'
  ),
  (
    '99999999-aaaa-4aaa-8aaa-999999999a02',
    '99999999-9999-4999-8999-999999999902',
    '11111111-2222-4222-8222-111111111101',
    1,
    'ko',
    '{"title": "B Zone food court remains open", "body": "Demo announcement: B Zone queues are stable and refill stations are operating normally."}'::jsonb,
    'Initial demo announcement.',
    'APPROVED',
    now() - interval '40 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO content_approvals (
  id,
  content_version_id,
  reviewer_id,
  decision,
  comment,
  decided_at
)
VALUES
  (
    '99999999-bbbb-4bbb-8bbb-999999999b01',
    '99999999-aaaa-4aaa-8aaa-999999999a01',
    '11111111-2222-4222-8222-111111111103',
    'APPROVED',
    'Synthetic demo announcement approved.',
    now() - interval '11 minutes'
  ),
  (
    '99999999-bbbb-4bbb-8bbb-999999999b02',
    '99999999-aaaa-4aaa-8aaa-999999999a02',
    '11111111-2222-4222-8222-111111111103',
    'APPROVED',
    'Synthetic demo announcement approved.',
    now() - interval '39 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO announcements (
  id,
  festival_id,
  content_version_id,
  title,
  severity,
  audience,
  target_area_ids,
  starts_at,
  ends_at,
  status,
  version,
  created_by,
  created_at
)
VALUES
  (
    '99999999-cccc-4ccc-8ccc-999999999c01',
    '22222222-2222-4222-8222-222222222222',
    '99999999-aaaa-4aaa-8aaa-999999999a01',
    'A구역 혼잡으로 우회 동선을 이용해 주세요.',
    'WARNING',
    '["VISITOR"]'::jsonb,
    '["33333333-3333-4333-8333-333333333301"]'::jsonb,
    now() - interval '10 minutes',
    now() + interval '90 minutes',
    'ACTIVE',
    1,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '10 minutes'
  ),
  (
    '99999999-cccc-4ccc-8ccc-999999999c02',
    '22222222-2222-4222-8222-222222222222',
    '99999999-aaaa-4aaa-8aaa-999999999a02',
    '메인 퍼레이드 시작 시간이 18:00에서 18:30으로 변경되었습니다.',
    'WARNING',
    '["VISITOR"]'::jsonb,
    '[]'::jsonb,
    now() - interval '40 minutes',
    now() + interval '3 hours',
    'ACTIVE',
    1,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '40 minutes'
  ),
  (
    '99999999-cccc-4ccc-8ccc-999999999c03',
    '22222222-2222-4222-8222-222222222222',
    NULL,
    '우천으로 일부 프로그램 장소가 변경되었습니다.',
    'INFO',
    '["VISITOR"]'::jsonb,
    '[]'::jsonb,
    now() - interval '70 minutes',
    now() + interval '4 hours',
    'ACTIVE',
    1,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '70 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO visitor_sessions (
  id,
  festival_id,
  anonymous_token_hash,
  language,
  accessibility_preferences,
  consents,
  expires_at,
  created_at
)
VALUES
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa01',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-session-token-hash-01',
    'ko',
    '{"large_text": true, "voice_guide": false}'::jsonb,
    '{"analytics": true, "personalization": false}'::jsonb,
    now() + interval '8 hours',
    now() - interval '35 minutes'
  ),
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa02',
    '22222222-2222-4222-8222-222222222222',
    'allen-demo-session-token-hash-02',
    'ko',
    '{"large_text": false, "voice_guide": false}'::jsonb,
    '{"analytics": true, "personalization": false}'::jsonb,
    now() + interval '8 hours',
    now() - interval '22 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO businesses (
  id,
  organization_id,
  registration_no,
  name,
  address,
  status,
  created_at,
  updated_at
)
VALUES
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb01',
    '11111111-1111-4111-8111-111111111111',
    'ALLEN-DEMO-BIZ-001',
    'Demo Reuse Cup Cafe',
    '{"text": "Synthetic address for demo data only"}'::jsonb,
    'ACTIVE',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02',
    '11111111-1111-4111-8111-111111111111',
    'ALLEN-DEMO-BIZ-002',
    'Demo Local Grill',
    '{"text": "Synthetic address for demo data only"}'::jsonb,
    'ACTIVE',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb03',
    '11111111-1111-4111-8111-111111111111',
    'ALLEN-DEMO-BIZ-003',
    'Demo Quiet Tea',
    '{"text": "Synthetic address for demo data only"}'::jsonb,
    'ACTIVE',
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO festival_businesses (
  id,
  festival_id,
  business_id,
  owner_membership_id,
  category,
  description,
  menu,
  operating_hours,
  accessibility,
  participation_status,
  review_comment,
  approved_by,
  approved_at,
  version,
  is_sponsored,
  esg_participating,
  created_at,
  updated_at
)
VALUES
  (
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb11',
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb01',
    NULL,
    'BEVERAGE',
    'Uses reusable cups and bottle refill operations.',
    '[{"name": "Iced tea", "price": 4500}, {"name": "Refill discount", "price": 1000}]'::jsonb,
    '{"open": "10:00", "close": "22:00"}'::jsonb,
    '{"wheelchair_counter": true}'::jsonb,
    'APPROVED',
    'Approved synthetic demo business.',
    '11111111-2222-4222-8222-111111111101',
    now() - interval '2 days',
    1,
    false,
    true,
    now(),
    now()
  ),
  (
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb12',
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02',
    NULL,
    'FOOD',
    'Sponsored booth with high visibility in recommendation tests.',
    '[{"name": "Local grill plate", "price": 12000}]'::jsonb,
    '{"open": "11:00", "close": "21:00"}'::jsonb,
    '{"allergy_labels": true}'::jsonb,
    'APPROVED',
    'Approved synthetic demo business.',
    '11111111-2222-4222-8222-111111111101',
    now() - interval '2 days',
    1,
    true,
    false,
    now(),
    now()
  ),
  (
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb13',
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb03',
    NULL,
    'BEVERAGE',
    'Quiet rest-area tea booth used as an underexposure comparison.',
    '[{"name": "Herbal tea", "price": 5000}]'::jsonb,
    '{"open": "10:00", "close": "20:00"}'::jsonb,
    '{"quiet_zone": true}'::jsonb,
    'APPROVED',
    'Approved synthetic demo business.',
    '11111111-2222-4222-8222-111111111101',
    now() - interval '2 days',
    1,
    false,
    true,
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO booths (
  id,
  festival_business_id,
  area_id,
  booth_no,
  status
)
VALUES
  (
    'bbbbbbbb-dddd-4ddd-8ddd-bbbbbbbbbb21',
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb11',
    '33333333-3333-4333-8333-333333333302',
    'B-12',
    'ACTIVE'
  ),
  (
    'bbbbbbbb-dddd-4ddd-8ddd-bbbbbbbbbb22',
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb12',
    '33333333-3333-4333-8333-333333333302',
    'B-08',
    'ACTIVE'
  ),
  (
    'bbbbbbbb-dddd-4ddd-8ddd-bbbbbbbbbb23',
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb13',
    '33333333-3333-4333-8333-333333333303',
    'C-03',
    'ACTIVE'
  )
ON CONFLICT DO NOTHING;

INSERT INTO coupons (
  id,
  festival_business_id,
  name,
  description,
  benefit_type,
  benefit_value,
  issue_limit,
  per_visitor_limit,
  valid_from,
  valid_until,
  status,
  created_by,
  created_at,
  updated_at
)
VALUES
  (
    'bbbbbbbb-eeee-4eee-8eee-bbbbbbbbbb31',
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb11',
    'Reusable cup refill discount',
    'Synthetic coupon for ESG-friendly recommendation testing.',
    'FIXED',
    1000,
    300,
    1,
    now() - interval '1 day',
    now() + interval '2 days',
    'ACTIVE',
    '11111111-2222-4222-8222-111111111101',
    now(),
    now()
  ),
  (
    'bbbbbbbb-eeee-4eee-8eee-bbbbbbbbbb32',
    'bbbbbbbb-cccc-4ccc-8ccc-bbbbbbbbbb12',
    'Lunch queue fast coupon',
    'Synthetic coupon for sponsored recommendation testing.',
    'PERCENT',
    10,
    500,
    1,
    now() - interval '1 day',
    now() + interval '2 days',
    'ACTIVE',
    '11111111-2222-4222-8222-111111111101',
    now(),
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO business_recommendation_events (
  id,
  festival_id,
  request_snapshot,
  response_snapshot,
  policy_version,
  created_at
)
VALUES
  (
    'cccccccc-1111-4111-8111-cccccccccc01',
    '22222222-2222-4222-8222-222222222222',
    '{"visitor_area": "B Zone Food Court", "intent": "beverage", "demo": true}'::jsonb,
    '{
      "items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb01", "name": "Demo Reuse Cup Cafe", "category": "BEVERAGE", "score": 18, "is_sponsored": false}
      ],
      "sponsored_items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02", "name": "Demo Local Grill", "category": "FOOD", "score": 13, "is_sponsored": true}
      ]
    }'::jsonb,
    'demo-v1',
    now() - interval '50 minutes'
  ),
  (
    'cccccccc-1111-4111-8111-cccccccccc02',
    '22222222-2222-4222-8222-222222222222',
    '{"visitor_area": "A Zone Main Stage", "intent": "food", "demo": true}'::jsonb,
    '{
      "items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb01", "name": "Demo Reuse Cup Cafe", "category": "BEVERAGE", "score": 12, "is_sponsored": false}
      ],
      "sponsored_items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02", "name": "Demo Local Grill", "category": "FOOD", "score": 20, "is_sponsored": true}
      ]
    }'::jsonb,
    'demo-v1',
    now() - interval '30 minutes'
  ),
  (
    'cccccccc-1111-4111-8111-cccccccccc03',
    '22222222-2222-4222-8222-222222222222',
    '{"visitor_area": "C Zone Family Lawn", "intent": "quiet", "demo": true}'::jsonb,
    '{
      "items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb03", "name": "Demo Quiet Tea", "category": "BEVERAGE", "score": 11, "is_sponsored": false}
      ],
      "sponsored_items": [
        {"business_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02", "name": "Demo Local Grill", "category": "FOOD", "score": 19, "is_sponsored": true}
      ]
    }'::jsonb,
    'demo-v1',
    now() - interval '10 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO esg_metrics (
  id,
  festival_id,
  name,
  category,
  status,
  created_by,
  created_at
)
VALUES
  (
    'dddddddd-1111-4111-8111-dddddddddd01',
    '22222222-2222-4222-8222-222222222222',
    '다회용기 사용률',
    'E',
    'ACTIVE',
    '11111111-2222-4222-8222-111111111101',
    now()
  ),
  (
    'dddddddd-1111-4111-8111-dddddddddd02',
    '22222222-2222-4222-8222-222222222222',
    '대중교통 이용률',
    'E',
    'ACTIVE',
    '11111111-2222-4222-8222-111111111101',
    now()
  ),
  (
    'dddddddd-1111-4111-8111-dddddddddd03',
    '22222222-2222-4222-8222-222222222222',
    '재활용률',
    'E',
    'ACTIVE',
    '11111111-2222-4222-8222-111111111101',
    now()
  )
ON CONFLICT DO NOTHING;

INSERT INTO esg_metric_versions (
  id,
  metric_id,
  version_no,
  formula,
  unit,
  target,
  source_requirements,
  evidence_required,
  created_by,
  created_at
)
VALUES
  (
    'dddddddd-2222-4222-8222-dddddddddd11',
    'dddddddd-1111-4111-8111-dddddddddd01',
    1,
    'reusable_container_transactions / total_food_beverage_transactions * 100',
    '%',
    80,
    '{"required_sources": ["pos_aggregate"], "contains_pii": false}'::jsonb,
    true,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '7 days'
  ),
  (
    'dddddddd-2222-4222-8222-dddddddddd12',
    'dddddddd-1111-4111-8111-dddddddddd02',
    1,
    'public_transit_and_shuttle_arrivals / estimated_total_arrivals * 100',
    '%',
    60,
    '{"required_sources": ["gate_survey_aggregate"], "contains_pii": false}'::jsonb,
    false,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '7 days'
  ),
  (
    'dddddddd-2222-4222-8222-dddddddddd13',
    'dddddddd-1111-4111-8111-dddddddddd03',
    1,
    'correctly_sorted_bags / inspected_bags * 100',
    '%',
    75,
    '{"required_sources": ["manual_inspection_aggregate"], "contains_pii": false}'::jsonb,
    true,
    '11111111-2222-4222-8222-111111111101',
    now() - interval '7 days'
  )
ON CONFLICT DO NOTHING;

INSERT INTO esg_measurements (
  id,
  festival_id,
  metric_version_id,
  value,
  source_type,
  source_ref,
  dedupe_key,
  measured_at,
  status,
  supersedes_id,
  created_by,
  created_at,
  updated_at
)
VALUES
  -- 다회용기 사용률 추세: 55 -> 58 -> 61 (목표 80, 개선 중). 앞의 두 건은 세 번째 건이
  -- supersedes_id로 대체해 "정정 이력"을 만든다 — 최신 승인값만 Context에 남는다.
  (
    'dddddddd-3333-4333-8333-dddddddddd21',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd11',
    55,
    'POS_AGGREGATE',
    'demo://allen/reusable-container-pos-t1',
    'allen-demo-reuse-t1',
    now() - interval '6 hours',
    'SUPERSEDED',
    NULL,
    '11111111-2222-4222-8222-111111111102',
    now() - interval '6 hours',
    now() - interval '4 hours'
  ),
  (
    'dddddddd-3333-4333-8333-dddddddddd25',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd11',
    58,
    'POS_AGGREGATE',
    'demo://allen/reusable-container-pos-t2',
    'allen-demo-reuse-t2',
    now() - interval '4 hours',
    'SUPERSEDED',
    'dddddddd-3333-4333-8333-dddddddddd21',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '4 hours',
    now() - interval '2 hours'
  ),
  (
    'dddddddd-3333-4333-8333-dddddddddd22',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd11',
    61,
    'POS_AGGREGATE',
    'demo://allen/reusable-container-pos-latest',
    'allen-demo-reuse-latest',
    now() - interval '2 hours',
    'APPROVED',
    'dddddddd-3333-4333-8333-dddddddddd25',
    '11111111-2222-4222-8222-111111111102',
    now() - interval '2 hours',
    now() - interval '90 minutes'
  ),
  -- 대중교통 이용률: 목표 60, 현재 67(목표 초과 달성).
  (
    'dddddddd-3333-4333-8333-dddddddddd23',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd12',
    67,
    'SURVEY_AGGREGATE',
    'demo://allen/transit-share-gate-summary',
    'allen-demo-transit-latest',
    now() - interval '3 hours',
    'APPROVED',
    NULL,
    '11111111-2222-4222-8222-111111111102',
    now() - interval '3 hours',
    now() - interval '2 hours'
  ),
  -- 재활용률: 목표 75, 현재 72(목표 근접, 미달). 승인 완료라 Context에 들어간다.
  (
    'dddddddd-3333-4333-8333-dddddddddd24',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd13',
    72,
    'MANUAL_INSPECTION',
    'demo://allen/recycling-rate-approved',
    'allen-demo-recycling-approved',
    now() - interval '4 hours',
    'APPROVED',
    NULL,
    '11111111-2222-4222-8222-111111111102',
    now() - interval '4 hours',
    now() - interval '3 hours'
  ),
  -- 검토 대기 중인 재활용률 최신 집계 — 증빙 없이 제출된 상태(Evidence 없음 사례).
  (
    'dddddddd-3333-4333-8333-dddddddddd26',
    '22222222-2222-4222-8222-222222222222',
    'dddddddd-2222-4222-8222-dddddddddd13',
    74,
    'MANUAL_INSPECTION',
    'demo://allen/recycling-rate-pending',
    'allen-demo-recycling-pending',
    now() - interval '30 minutes',
    'IN_REVIEW',
    NULL,
    '11111111-2222-4222-8222-111111111102',
    now() - interval '30 minutes',
    now() - interval '30 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO esg_evidence (
  id,
  measurement_id,
  file_id,
  file_hash,
  evidence_type,
  issued_at,
  created_at
)
VALUES
  (
    'dddddddd-4444-4444-8444-dddddddddd31',
    'dddddddd-3333-4333-8333-dddddddddd22',
    'demo-reusable-container-pos-summary',
    'sha256:allen-demo-reuse-summary',
    'DOCUMENT',
    now() - interval '95 minutes',
    now() - interval '90 minutes'
  ),
  (
    'dddddddd-4444-4444-8444-dddddddddd32',
    'dddddddd-3333-4333-8333-dddddddddd23',
    'demo-transit-share-gate-summary',
    'sha256:allen-demo-transit-summary',
    'DOCUMENT',
    now() - interval '125 minutes',
    now() - interval '2 hours'
  )
ON CONFLICT DO NOTHING;

INSERT INTO esg_reviews (
  id,
  measurement_id,
  reviewer_id,
  decision,
  comment,
  created_at
)
VALUES
  (
    'dddddddd-5555-4555-8555-dddddddddd41',
    'dddddddd-3333-4333-8333-dddddddddd22',
    '11111111-2222-4222-8222-111111111103',
    'APPROVED',
    'Reusable container aggregate evidence is attached for demo briefing.',
    now() - interval '80 minutes'
  ),
  (
    'dddddddd-5555-4555-8555-dddddddddd42',
    'dddddddd-3333-4333-8333-dddddddddd23',
    '11111111-2222-4222-8222-111111111103',
    'APPROVED',
    'Transit share aggregate is approved for demo briefing.',
    now() - interval '110 minutes'
  )
ON CONFLICT DO NOTHING;

-- Verification queries.
-- These SELECT statements do not mutate data.

SELECT
  'festival' AS check_name,
  id,
  code,
  name,
  status
FROM festivals
WHERE id = '22222222-2222-4222-8222-222222222222';

SELECT
  'crowd_trend' AS check_name,
  area.name AS area_name,
  snapshot.captured_at,
  snapshot.crowd_level,
  snapshot.people_count
FROM crowd_snapshots snapshot
JOIN festival_areas area ON area.id = snapshot.area_id
WHERE snapshot.festival_id = '22222222-2222-4222-8222-222222222222'
ORDER BY area.name, snapshot.captured_at;

SELECT
  'open_high_risk_tickets' AS check_name,
  area.name AS area_name,
  ticket.ticket_type,
  ticket.priority,
  ticket.status,
  ticket.title
FROM ops_tickets ticket
LEFT JOIN festival_areas area ON area.id = ticket.area_id
WHERE ticket.festival_id = '22222222-2222-4222-8222-222222222222'
  AND ticket.status IN ('OPEN', 'IN_PROGRESS')
  AND ticket.priority IN ('HIGH', 'EMERGENCY')
ORDER BY ticket.created_at DESC;

SELECT
  'schedule_changes' AS check_name,
  program.title,
  session.starts_at,
  session.created_at,
  session.updated_at
FROM program_sessions session
JOIN programs program ON program.id = session.program_id
WHERE program.festival_id = '22222222-2222-4222-8222-222222222222'
  AND session.updated_at > session.created_at + interval '1 minute'
ORDER BY session.updated_at DESC;

SELECT
  'announcements' AS check_name,
  announcement.title,
  announcement.severity,
  announcement.status,
  announcement.starts_at,
  announcement.ends_at
FROM announcements announcement
WHERE announcement.festival_id = '22222222-2222-4222-8222-222222222222'
ORDER BY announcement.starts_at DESC;

SELECT
  'esg_dashboard_context' AS check_name,
  metric.name,
  metric.category,
  measurement.status,
  measurement.value,
  version.unit,
  version.target,
  COUNT(evidence.id) AS evidence_count
FROM esg_measurements measurement
JOIN esg_metric_versions version ON version.id = measurement.metric_version_id
JOIN esg_metrics metric ON metric.id = version.metric_id
LEFT JOIN esg_evidence evidence ON evidence.measurement_id = measurement.id
WHERE measurement.festival_id = '22222222-2222-4222-8222-222222222222'
GROUP BY metric.name, metric.category, measurement.status, measurement.value, version.unit, version.target, measurement.measured_at
ORDER BY metric.category, metric.name, measurement.measured_at;

SELECT
  'recommendation_exposure' AS check_name,
  event.policy_version,
  event.created_at,
  event.response_snapshot
FROM business_recommendation_events event
WHERE event.festival_id = '22222222-2222-4222-8222-222222222222'
ORDER BY event.created_at;

SELECT
  'facilities' AS check_name,
  facility.name,
  facility.facility_type,
  area.name AS area_name,
  facility.status
FROM facilities facility
LEFT JOIN festival_areas area ON area.id = facility.area_id
WHERE facility.festival_id = '22222222-2222-4222-8222-222222222222'
ORDER BY facility.facility_type, facility.name;
