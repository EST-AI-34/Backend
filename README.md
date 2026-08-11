# FEST FastAPI Backend

FastAPI backend for the FEST MVP. It provides QR visitor guide data, AI guide
answers, course recommendations, map/facility data, operations incidents, and
basic ESG reporting.

## Deployed API

- Swagger UI: https://backend-production-8532.up.railway.app/docs
- OpenAPI JSON: https://backend-production-8532.up.railway.app/openapi.json
- API base URL: https://backend-production-8532.up.railway.app/api/v1

## Architecture

- `app/api`: HTTP controllers and routing
- `app/services`: business logic
- `app/repositories`: data access and external API integration
- `app/schemas`: request/response models
- `app/core`: configuration and logging

## Features

- Visitor festival overview for QR mobile pages
- Registered festival data: programs, notices, facilities, stores, coupons
- AI guide Q&A with local fallback and optional Allen/LLM integration
- Personalized course recommendation by visitor type, interests, and stay time
- Map locations with simple congestion status
- Operator dashboard stats and incident registration
- ESG metrics, dashboard summary, and report draft generation
- Optional external Allen API integration using `ALLEN_API_BASE_URL` and `ALLEN_API_KEY`

## Run locally

1. Create a Python environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Create `.env` only when external services are needed:

```env
PROJECT_NAME=FEST Backend
BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ALLEN_API_BASE_URL=https://api.allen.ai
ALLEN_API_KEY=
```

3. Start the server:

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
