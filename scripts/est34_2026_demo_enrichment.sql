-- Rich demo data for the REAL production festival EST34-2026 (not the separate
-- ALLEN-DEMO-2026 sandbox in scripts/allen_demo_data.sql). The actual Frontend
-- (FEST-Client) hardcodes festival code EST34-2026 everywhere, so festival_context-
-- driven AI Guide answers need real operational data attached to THIS festival.
-- INSERT-only, idempotent (ON CONFLICT DO NOTHING), safe to re-run.
-- Do not run this against production.

-- Existing IDs (verified via read-only SELECT before writing this file):
-- Festival EST34-2026:      00c0bf7d-31e1-4170-a4f4-c89bae88f995
-- Organization:              53523600-d69d-4f2b-b71b-c94e28a2554c
-- Area 메인 광장 (existing):  e991dee5-ff3b-44db-a0db-508df59e45d6
-- admin@example.com:        d9821c52-d4bf-482f-b2a1-03ea1486cca1
-- manager@example.com:      621796d5-f061-4113-a6fb-b4713c2bd728
-- reviewer@example.com:     f7895017-930a-4c89-88ed-2e9eb877441e
-- operator@example.com:     83534e58-ddc0-4a83-9df1-1f3dd1e88151

INSERT INTO festival_areas (id, festival_id, name, area_type, latitude, longitude, status, version, created_at, updated_at)
VALUES
  ('ee340000-3333-4333-8333-ee3400000302', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'B구역 푸드존', 'FOOD', 37.566900, 126.979200, 'ACTIVE', 1, now(), now()),
  ('ee340000-3333-4333-8333-ee3400000303', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'C구역 체험존', 'REST', 37.565900, 126.977200, 'ACTIVE', 1, now(), now())
ON CONFLICT DO NOTHING;

-- 메인 광장(기존 area)에 급증 추세, B구역엔 안정 추세를 심는다.
INSERT INTO crowd_snapshots (id, festival_id, area_id, source_type, captured_at, crowd_level, people_count, expires_at, created_by, created_at)
VALUES
  ('ee340000-7777-4777-8777-ee3400000701', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'SENSOR', now() - interval '30 minutes', 'MODERATE', 250, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000702', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'SENSOR', now() - interval '20 minutes', 'BUSY',     520, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000703', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'SENSOR', now() - interval '10 minutes', 'BUSY',     780, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000704', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'SENSOR', now(),                        'FULL',     950, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000705', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-3333-4333-8333-ee3400000302', 'SENSOR', now() - interval '30 minutes', 'MODERATE', 180, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000706', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-3333-4333-8333-ee3400000302', 'SENSOR', now() - interval '20 minutes', 'MODERATE', 190, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000707', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-3333-4333-8333-ee3400000302', 'SENSOR', now() - interval '10 minutes', 'MODERATE', 185, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now()),
  ('ee340000-7777-4777-8777-ee3400000708', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-3333-4333-8333-ee3400000302', 'SENSOR', now(),                        'MODERATE', 200, now() + interval '2 hours', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now())
ON CONFLICT DO NOTHING;

INSERT INTO ops_tickets (id, festival_id, area_id, ticket_type, priority, status, title, description, created_by, created_at, updated_at)
VALUES
  ('ee340000-8888-4888-8888-ee3400000801', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'INCIDENT', 'HIGH', 'OPEN', '메인 광장 안전펜스 압력 증가', '급증한 인파로 안전펜스에 압력이 높아져 현장 인력이 확인 중입니다.', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '20 minutes', now() - interval '5 minutes'),
  ('ee340000-8888-4888-8888-ee3400000802', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', 'INCIDENT', 'HIGH', 'OPEN', '메인 광장 응급 이송 요청', '경미한 부상자 발생으로 의무실 이송을 진행하고 있습니다.', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '12 minutes', now() - interval '3 minutes')
ON CONFLICT DO NOTHING;

INSERT INTO content_items (id, festival_id, slug, content_type, lifecycle_status, published_version_id, created_at, updated_at)
VALUES
  ('ee340000-9999-4999-8999-ee3400000901', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'est34-main-congestion-detour', 'ANNOUNCEMENT', 'PUBLISHED', NULL, now(), now()),
  ('ee340000-9999-4999-8999-ee3400000902', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'est34-parade-time-change', 'ANNOUNCEMENT', 'PUBLISHED', NULL, now(), now()),
  ('ee340000-9999-4999-8999-ee3400000903', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'est34-rain-venue-change', 'ANNOUNCEMENT', 'PUBLISHED', NULL, now(), now())
ON CONFLICT DO NOTHING;

INSERT INTO content_versions (id, content_item_id, author_id, version_no, language, body, change_note, status, created_at)
VALUES
  ('ee340000-aaaa-4aaa-8aaa-ee340000aa01', 'ee340000-9999-4999-8999-ee3400000901', '621796d5-f061-4113-a6fb-b4713c2bd728', 1, 'ko', '{"title": "메인 광장 혼잡 안내", "body": "메인 광장이 혼잡하여 우회 동선을 이용해 주세요."}'::jsonb, '초기 공지', 'APPROVED', now() - interval '10 minutes'),
  ('ee340000-aaaa-4aaa-8aaa-ee340000aa02', 'ee340000-9999-4999-8999-ee3400000902', '621796d5-f061-4113-a6fb-b4713c2bd728', 1, 'ko', '{"title": "메인 퍼레이드 시간 변경", "body": "메인 퍼레이드 시작 시간이 18:00에서 18:30으로 변경되었습니다."}'::jsonb, '초기 공지', 'APPROVED', now() - interval '40 minutes'),
  ('ee340000-aaaa-4aaa-8aaa-ee340000aa03', 'ee340000-9999-4999-8999-ee3400000903', '621796d5-f061-4113-a6fb-b4713c2bd728', 1, 'ko', '{"title": "우천시 장소 변경 안내", "body": "우천으로 일부 프로그램 장소가 변경되었습니다."}'::jsonb, '초기 공지', 'APPROVED', now() - interval '70 minutes')
ON CONFLICT DO NOTHING;

INSERT INTO content_approvals (id, content_version_id, reviewer_id, decision, comment, decided_at)
VALUES
  ('ee340000-bbbb-4bbb-8bbb-ee340000bb01', 'ee340000-aaaa-4aaa-8aaa-ee340000aa01', 'f7895017-930a-4c89-88ed-2e9eb877441e', 'APPROVED', '승인', now() - interval '9 minutes'),
  ('ee340000-bbbb-4bbb-8bbb-ee340000bb02', 'ee340000-aaaa-4aaa-8aaa-ee340000aa02', 'f7895017-930a-4c89-88ed-2e9eb877441e', 'APPROVED', '승인', now() - interval '39 minutes'),
  ('ee340000-bbbb-4bbb-8bbb-ee340000bb03', 'ee340000-aaaa-4aaa-8aaa-ee340000aa03', 'f7895017-930a-4c89-88ed-2e9eb877441e', 'APPROVED', '승인', now() - interval '69 minutes')
ON CONFLICT DO NOTHING;

INSERT INTO announcements (id, festival_id, content_version_id, title, severity, audience, target_area_ids, starts_at, ends_at, status, version, created_by, created_at)
VALUES
  ('ee340000-cccc-4ccc-8ccc-ee340000cc01', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-aaaa-4aaa-8aaa-ee340000aa01', '메인 광장 혼잡 안내', 'WARNING', '["VISITOR"]'::jsonb, '["e991dee5-ff3b-44db-a0db-508df59e45d6"]'::jsonb, now() - interval '10 minutes', now() + interval '90 minutes', 'ACTIVE', 1, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '10 minutes'),
  ('ee340000-cccc-4ccc-8ccc-ee340000cc02', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-aaaa-4aaa-8aaa-ee340000aa02', '메인 퍼레이드 시간 변경', 'WARNING', '["VISITOR"]'::jsonb, '[]'::jsonb, now() - interval '40 minutes', now() + interval '3 hours', 'ACTIVE', 1, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '40 minutes'),
  ('ee340000-cccc-4ccc-8ccc-ee340000cc03', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-aaaa-4aaa-8aaa-ee340000aa03', '우천시 장소 변경 안내', 'INFO', '["VISITOR"]'::jsonb, '[]'::jsonb, now() - interval '70 minutes', now() + interval '4 hours', 'ACTIVE', 1, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '70 minutes')
ON CONFLICT DO NOTHING;

INSERT INTO programs (id, festival_id, slug, title, summary, category, accessibility, status, version, created_at, updated_at)
VALUES
  ('ee340000-6666-4666-8666-ee3400000601', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'est34-main-parade', '메인 퍼레이드', '축제 대표 퍼레이드', 'PARADE', '{"captioning": true}'::jsonb, 'PUBLISHED', 1, now(), now()),
  ('ee340000-6666-4666-8666-ee3400000602', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'est34-kpop-stage', 'K-POP 공연', '메인 스테이지 K-POP 공연', 'MUSIC', '{}'::jsonb, 'PUBLISHED', 1, now(), now())
ON CONFLICT DO NOTHING;

-- /map, /schedule 등 공개 엔드포인트는 programs를 resource_type='PROGRAM' AND
-- resource_id=program.id로 연결된 PUBLISHED content_items가 있어야 노출한다
-- (app/routes/public.py festival_map 쿼리 참고) — festival_context(context_repository.py)
-- 쪽은 이 연결이 필요 없지만, Frontend 화면 노출까지 맞추기 위해 함께 만든다.
INSERT INTO content_items (id, festival_id, content_type, resource_type, resource_id, slug, lifecycle_status, published_version_id, created_at, updated_at)
VALUES
  ('ee340000-9999-4999-8999-ee3400000904', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'PROGRAM', 'PROGRAM', 'ee340000-6666-4666-8666-ee3400000601', 'est34-main-parade-content', 'PUBLISHED', NULL, now(), now()),
  ('ee340000-9999-4999-8999-ee3400000905', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'PROGRAM', 'PROGRAM', 'ee340000-6666-4666-8666-ee3400000602', 'est34-kpop-stage-content', 'PUBLISHED', NULL, now(), now())
ON CONFLICT DO NOTHING;

INSERT INTO program_sessions (id, festival_id, program_id, area_id, starts_at, ends_at, capacity, status, version, created_at, updated_at)
VALUES
  -- 18:00 -> 18:30로 30분 지연된 것으로 보이게 created_at보다 한참 뒤에 updated_at을 둔다.
  ('ee340000-7777-4777-8777-ee3400000709', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-6666-4666-8666-ee3400000601', 'e991dee5-ff3b-44db-a0db-508df59e45d6', now() + interval '2 hours', now() + interval '3 hours', 1200, 'OPEN', 1, now() - interval '2 hours', now() - interval '20 minutes'),
  ('ee340000-7777-4777-8777-ee3400000710', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-6666-4666-8666-ee3400000602', 'e991dee5-ff3b-44db-a0db-508df59e45d6', now() + interval '4 hours', now() + interval '5 hours', 1200, 'OPEN', 1, now() - interval '2 hours', now() - interval '2 hours')
ON CONFLICT DO NOTHING;

INSERT INTO esg_metrics (id, festival_id, name, category, status, created_by, created_at)
VALUES
  ('ee340000-dddd-4ddd-8ddd-ee340000dd01', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', '다회용기 사용률', 'E', 'ACTIVE', '621796d5-f061-4113-a6fb-b4713c2bd728', now()),
  ('ee340000-dddd-4ddd-8ddd-ee340000dd02', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', '대중교통 이용률', 'E', 'ACTIVE', '621796d5-f061-4113-a6fb-b4713c2bd728', now()),
  ('ee340000-dddd-4ddd-8ddd-ee340000dd03', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', '재활용률', 'E', 'ACTIVE', '621796d5-f061-4113-a6fb-b4713c2bd728', now())
ON CONFLICT DO NOTHING;

INSERT INTO esg_metric_versions (id, metric_id, version_no, formula, unit, target, source_requirements, evidence_required, created_by, created_at)
VALUES
  ('ee340000-eeee-4eee-8eee-ee340000ee01', 'ee340000-dddd-4ddd-8ddd-ee340000dd01', 1, 'reusable_container_transactions / total_food_beverage_transactions * 100', '%', 80, '{"required_sources": ["pos_aggregate"], "contains_pii": false}'::jsonb, true, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '7 days'),
  ('ee340000-eeee-4eee-8eee-ee340000ee02', 'ee340000-dddd-4ddd-8ddd-ee340000dd02', 1, 'public_transit_and_shuttle_arrivals / estimated_total_arrivals * 100', '%', 60, '{"required_sources": ["gate_survey_aggregate"], "contains_pii": false}'::jsonb, false, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '7 days'),
  ('ee340000-eeee-4eee-8eee-ee340000ee03', 'ee340000-dddd-4ddd-8ddd-ee340000dd03', 1, 'recycled_waste_kg / total_waste_kg * 100', '%', 75, '{"required_sources": ["waste_vendor_aggregate"], "contains_pii": false}'::jsonb, false, '621796d5-f061-4113-a6fb-b4713c2bd728', now() - interval '7 days')
ON CONFLICT DO NOTHING;

INSERT INTO esg_measurements (id, festival_id, metric_version_id, value, source_type, source_ref, dedupe_key, measured_at, status, supersedes_id, created_by, created_at, updated_at)
VALUES
  ('ee340000-ffff-4fff-8fff-ee340000ff01', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-eeee-4eee-8eee-ee340000ee01', 55, 'POS_AGGREGATE', 'demo://est34/reuse-early', 'est34-reuse-early', now() - interval '6 hours', 'SUPERSEDED', NULL, '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '6 hours', now() - interval '5 hours'),
  ('ee340000-ffff-4fff-8fff-ee340000ff02', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-eeee-4eee-8eee-ee340000ee01', 58, 'POS_AGGREGATE', 'demo://est34/reuse-mid', 'est34-reuse-mid', now() - interval '4 hours', 'SUPERSEDED', 'ee340000-ffff-4fff-8fff-ee340000ff01', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '4 hours', now() - interval '3 hours'),
  ('ee340000-ffff-4fff-8fff-ee340000ff03', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-eeee-4eee-8eee-ee340000ee01', 61, 'POS_AGGREGATE', 'demo://est34/reuse-latest', 'est34-reuse-latest', now() - interval '2 hours', 'APPROVED', 'ee340000-ffff-4fff-8fff-ee340000ff02', '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '2 hours', now() - interval '90 minutes'),
  ('ee340000-ffff-4fff-8fff-ee340000ff04', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-eeee-4eee-8eee-ee340000ee02', 67, 'SURVEY_AGGREGATE', 'demo://est34/transit-latest', 'est34-transit-latest', now() - interval '3 hours', 'APPROVED', NULL, '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '3 hours', now() - interval '2 hours'),
  ('ee340000-ffff-4fff-8fff-ee340000ff05', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-eeee-4eee-8eee-ee340000ee03', 72, 'WASTE_VENDOR_AGGREGATE', 'demo://est34/recycling-latest', 'est34-recycling-latest', now() - interval '4 hours', 'APPROVED', NULL, '83534e58-ddc0-4a83-9df1-1f3dd1e88151', now() - interval '4 hours', now() - interval '3 hours')
ON CONFLICT DO NOTHING;

INSERT INTO esg_evidence (id, measurement_id, file_id, file_hash, evidence_type, issued_at, created_at)
VALUES
  ('ee340000-1111-4111-8111-ee34000011a1', 'ee340000-ffff-4fff-8fff-ee340000ff03', 'est34-reuse-summary', 'sha256:est34-reuse-summary', 'DOCUMENT', now() - interval '95 minutes', now() - interval '90 minutes'),
  ('ee340000-1111-4111-8111-ee34000011a2', 'ee340000-ffff-4fff-8fff-ee340000ff04', 'est34-transit-summary', 'sha256:est34-transit-summary', 'DOCUMENT', now() - interval '125 minutes', now() - interval '2 hours')
ON CONFLICT DO NOTHING;

INSERT INTO facilities (id, festival_id, area_id, name, facility_type, accessibility, operating_hours, status, version, created_at, updated_at)
VALUES
  ('ee340000-4444-4444-8444-ee3400000401', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', '메인 광장 화장실', 'RESTROOM', '{"wheelchair_accessible": true}'::jsonb, '{"open": "09:00", "close": "23:00"}'::jsonb, 'ACTIVE', 1, now(), now()),
  ('ee340000-4444-4444-8444-ee3400000402', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'ee340000-3333-4333-8333-ee3400000302', 'B구역 화장실', 'RESTROOM', '{"wheelchair_accessible": true}'::jsonb, '{"open": "09:00", "close": "23:00"}'::jsonb, 'ACTIVE', 1, now(), now()),
  ('ee340000-4444-4444-8444-ee3400000403', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', '종합 안내소', 'INFO', '{"wheelchair_accessible": true, "interpreter": true}'::jsonb, '{"open": "09:00", "close": "23:00"}'::jsonb, 'ACTIVE', 1, now(), now()),
  ('ee340000-4444-4444-8444-ee3400000404', '00c0bf7d-31e1-4170-a4f4-c89bae88f995', 'e991dee5-ff3b-44db-a0db-508df59e45d6', '의무실', 'MEDICAL', '{"wheelchair_accessible": true, "first_aid": true}'::jsonb, '{"open": "09:00", "close": "23:00"}'::jsonb, 'ACTIVE', 1, now(), now())
ON CONFLICT DO NOTHING;
