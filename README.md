# FEST FastAPI Backend

FastAPI backend for the FEST MVP. It provides QR visitor guide data, AI guide
answers, course recommendations, map/facility data, operations incidents, and
basic ESG reporting.

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
- AI guide Q&A over verified database/API results with local fallback
- Personalized course recommendation by visitor type, interests, and stay time
- Map locations with simple congestion status
- Operator dashboard stats and incident registration
- ESG metrics, dashboard summary, and report draft generation
- Optional Alan/Allen search integration using `ALLEN_API_BASE_URL` and `ALLEN_API_KEY`

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
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7
VISITOR_SESSION_HOURS=24
BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ALLEN_API_BASE_URL=https://api.allen.ai
ALLEN_API_KEY=
```

3. Apply migrations to Supabase:

```bash
python -m scripts.migrate
```

This backend uses Supabase as managed PostgreSQL through `DATABASE_URL`. Use the
Transaction pooler connection string when the runtime is serverless or IPv4-only.
It should use a `pooler.supabase.com` host and port `6543`. The `SUPABASE_URL`
and key values are available for auth, storage, realtime, or REST API features
when those are added.

For local-only development, you can still start the included Postgres container
and set `DATABASE_URL=postgres://festival:festival@localhost:5432/festival`.

4. Start the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Example endpoints

- `GET /health`
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
- `POST /api/v1/esg/report`

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
