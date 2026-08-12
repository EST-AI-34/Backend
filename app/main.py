from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logger import setup_logging

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="FEST backend with verified festival data, search-based AI retrieval, and LLM answer composition",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", summary="Health check")
def health_check() -> dict:
    return {"status": "ok", "service": settings.PROJECT_NAME}


@app.get("/health/ready", summary="Readiness check")
def readiness_check() -> dict:
    return {"status": "ready", "service": settings.PROJECT_NAME}
