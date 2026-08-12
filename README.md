# FEST FastAPI Backend

FastAPI backend for the FEST MVP. It provides QR visitor guide data, AI guide
answers, course recommendations, map/facility data, operations incidents, and
basic ESG reporting.

## 📋 기능 진행 상황

현재 구현 상태를 확인하려면 [**FEATURE_STATUS.md**](../FEATURE_STATUS.md) 참고:

| 기능 | 상태 | 주요 내용 |
|------|------|---------|
| AI 휴먼 안내 | 백엔드 완료 | 일정·길찾기·문화관광·안전·ESG·업체추천 시나리오 응답, 화면/음성 텍스트 제공 |
| BIZ-03 실질 추천 | 백엔드 완료 | 추천 API 구현, 프론트 연동 검증 필요 |
| 소음·네트워크 장애 | 백엔드 완료 | 터치형 액션, 직원 호출 액션, 외부 AI 장애 fallback 응답 제공 |
| **추천 편향 점검** | **백엔드 완료** | **이벤트 저장, 일반/후원 분리 집계, 업체·카테고리 기준 초과 점검** |
| 운영 대시보드 | 프론트 데모 | 백엔드 API 연동 필요 |
| ESG 성과관리 | 백엔드 기초 | 공식 AI 토큰 후 재검증 필요 |

## Architecture

- `app/api`: HTTP controllers and routing
- `app/services`: business logic
- `app/repositories`: data access and external API integration
- `app/schemas`: request/response models
- `app/core`: configuration and logging
- `db/migrations`: PostgreSQL schema migrations
- `scripts`: local maintenance scripts

## Features

- Visitor festival overview for QR mobile pages
- Registered festival data: programs, notices, facilities, stores, coupons
- AI guide Q&A over verified database/API results using Allen only
- Personalized course recommendation by visitor type, interests, and stay time
- Map locations with simple congestion status
- Operator dashboard stats and incident registration
- ESG metrics, dashboard summary, report draft generation, and Allen-only admin one-line briefing
- Admin risk brief from verified PostgreSQL operations signals, with Allen-disabled fallback
- Visitor business recommendations from approved PostgreSQL participating businesses, with sponsored results separated
- Admin API Bearer token authorization with role and festival scope checks
- Required Alan/Allen integration for AI answer/report generation using the myAlan API, fixed Alan v4.0 persona, and one explicit auth mode

## AI Role Policy

Alan AI and LLMs are not the source of truth for FESTAI data. The database stores
raw operation records, the backend validates and calculates statistics, Alan AI
or another search tool retrieves relevant information, and the LLM only turns
verified results into a natural answer.

See [docs/ai-role-policy.md](docs/ai-role-policy.md) for the full data flow,
role boundaries, LLM guardrails, and POC voice-recognition scope.

## Run locally

1. Create a Python environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Create `.env`:

```env
PROJECT_NAME=FEST Backend
ENVIRONMENT=development
DATABASE_URL=postgresql://postgres.[PROJECT_REF]:[DATABASE_PASSWORD]@aws-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
SUPABASE_URL=https://[PROJECT_REF].supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
JWT_SECRET=replace-with-at-least-32-random-characters
JWT_ISSUER=festai-admin
JWT_AUDIENCE=festai-admin-api
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7
VISITOR_SESSION_HOURS=24
BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ALLEN_API_BASE_URL=https://api.myalan.ai/api/v1
ALLEN_AUTH_MODE=bearer
ALLEN_AUTH_BASE_URL=https://api.myalan.ai
ALLEN_CLIENT_ID=
ALLEN_LLM_ENDPOINT=/channels
ALLEN_PERSONA_ID=69ce0aeab459faf50a427005
ALLEN_MODEL=
ALLEN_API_KEY=
ALLEN_CONNECT_TIMEOUT_SECONDS=3
ALLEN_READ_TIMEOUT_SECONDS=30
ALLEN_MAX_RETRIES=2
ALLEN_MESSAGE_POLL_SECONDS=2
ALLEN_MESSAGE_POLL_ATTEMPTS=20
```

`ALLEN_AUTH_MODE=bearer` is the default operation mode and requires
`ALLEN_API_KEY`. For development POC checks, `ALLEN_AUTH_MODE=implicit` requires
`ALLEN_CLIENT_ID`; it does not reuse `ALLEN_API_KEY` as a client id and does not
fall back to bearer or any other model.

3. Apply migrations to Supabase:

```bash
python -m scripts.migrate
```

Current migration chain:

- `001_init.sql`: core FEST schema
- `002_ai_risk_and_business_recommendations.sql`: risk brief cache, recommendation policy, recommendation events
- `003_harden_insight_tables.sql`: NOT VALID integrity constraints for generated insight tables
- `004_participating_businesses.sql`: approved business source table for BIZ-03
- `005_validate_insight_constraints.sql`: validates the 003 constraints after data checks
- `006_participating_business_seed_key.sql`: idempotent demo business seed key

This backend uses Supabase as managed PostgreSQL through `DATABASE_URL`. Use the
Transaction pooler connection string when the runtime is serverless or IPv4-only.
It should use a `pooler.supabase.com` host and port `6543`. The `SUPABASE_URL`
and key values are available for auth, storage, realtime, or REST API features
when those are added.

For local-only development, you can still start the included Postgres container
and set `DATABASE_URL=postgres://festival:festival@localhost:5432/festival`.

Seed approved demo businesses for BIZ-03 after migrations:

```bash
python -m scripts.seed_businesses
```

The seed is idempotent through the `(festival_id, name)` unique index and stores
only operational demo rows in `participating_businesses`; recommendation code
does not hard-code business data.

4. Start the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Example endpoints

- `GET /health`
- `GET /health/ready`
- `GET /api/v1/festival/overview`
- `GET /api/v1/festival/programs`
- `GET /api/v1/festival/facilities`
- `GET /api/v1/festival/stores`
- `GET /api/v1/festival/coupons`
- `GET /api/v1/festival/notices`
- `GET /api/v1/map/locations`
- `POST /api/v1/ai/guide/ask`
- `POST /api/v1/ai/guide/course`
- `POST /api/v1/ai/vision/analyze`
- `POST /api/v1/ai/llm/reply`
- `GET /api/v1/operations/dashboard`
- `GET /api/v1/operations/incidents`
- `POST /api/v1/operations/incidents`
- `GET /api/v1/esg/metrics`
- `POST /api/v1/esg/metrics`
- `GET /api/v1/esg/summary`
- `GET /api/v1/esg/briefing`
- `POST /api/v1/esg/report`
- `GET /api/v1/admin/festivals/{festival_id}/risk-brief`
- `GET /api/v1/visitor/festivals/{festival_id}/business-recommendations`

Admin endpoints require an `Authorization: Bearer <HS256 JWT>` header. The
backend verifies the HS256 signature with `JWT_SECRET`, fixed `alg`, `exp`,
optional `nbf`, `iss=JWT_ISSUER`, and `aud=JWT_AUDIENCE`. Tokens are issued by
the external admin authentication system and delivered to clients through the
frontend/admin identity flow; this backend only validates them and does not
provide a temporary login endpoint. In non-development environments, placeholder
or empty `JWT_SECRET` values fail closed.

Admin roles are enforced per endpoint:

- `SUPER_ADMIN`: all admin reads and writes, with `festival_scope=["*"]` allowed
- `FESTIVAL_MANAGER`: festival admin reads and writes within scope
- `FIELD_OPERATOR`: admin reads and operations ticket writes within scope
- `REVIEWER`: admin reads and ESG/AI review reads within scope

`festival_scope` must contain the requested festival code/id or `"*"`.
AI-04 schedule-change risk uses `program_sessions` when that table exists. In
deployments where it is absent, the repository falls back to existing `programs`
update timestamps; if neither source exists, schedule-change evidence is simply
omitted rather than treated as a normal/zero signal.

Frontend integration examples for AI-04 and BIZ-03 are in
[`docs/frontend-ai04-biz03-integration.md`](docs/frontend-ai04-biz03-integration.md).

## Example requests

```bash
curl -X POST http://localhost:8000/api/v1/ai/guide/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"가족이 볼 만한 프로그램 추천해줘\",\"visitor_type\":\"family\",\"interests\":[\"kids\",\"craft\"],\"stay_minutes\":180}"
```

```bash
curl -X POST http://localhost:8000/api/v1/ai/guide/course \
  -H "Content-Type: application/json" \
  -d "{\"visitor_type\":\"family\",\"interests\":[\"craft\",\"food\"],\"stay_minutes\":180,\"accessibility_required\":false}"
```
