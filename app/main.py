import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.errors import DataError, ForeignKeyViolation, UniqueViolation

from .db import one, pool
from .errors import AppError
from .http import client_ip, meta
from .jobs import start_worker
from .routes import (admin_content, admin_core, admin_esg, admin_ops, auth, insights, merchant,
                     p2_admin, p2_visitor, public, visitor)


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open(wait=True)
    stopped, worker = start_worker()
    yield
    stopped.set()
    worker.join(timeout=2)
    pool.close()


app = FastAPI(
    title="지역축제 DX API",
    version="1.1.0",
    description="AI·ESG 기반 지역축제 DX 플랫폼 1·2단계 백엔드",
    lifespan=lifespan,
)


counts: dict[tuple[str, str, int], int] = defaultdict(int)


def rate_limit(path: str, method: str) -> int | None:
    if "/visitor/ai/" in path:
        return 20
    if path.endswith("/visitor/complaints"):
        return 10
    if path.endswith("/auth/login"):
        return 10
    if "/admin/" in path and method != "GET":
        return 60
    if "/public/" in path:
        return 120
    return None


def error_response(request: Request, error: AppError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content={
        "error": {"code": error.code, "message": error.message, "details": error.details, "retryable": error.retryable},
        "meta": meta(request)})


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4()}"
    limit = rate_limit(request.url.path, request.method)
    if limit:
        # ponytail: process-local limiter; use Redis when multiple API instances are deployed.
        window = int(time.time() // 60)
        key = (client_ip(request), "/".join(request.url.path.split("/")[:6]), window)
        counts[key] += 1
        if counts[key] > limit:
            return error_response(request, AppError(429, "RATE_LIMITED", "호출 한도를 초과했습니다.", retryable=True))
        if len(counts) > 10_000:
            for old in list(counts):
                if old[2] != window:
                    counts.pop(old, None)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(AppError)
async def app_error(request: Request, error: AppError):
    return error_response(request, error)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    details = [{"field": ".".join(str(part) for part in issue["loc"] if part != "body"), "reason": issue["msg"]} for issue in error.errors()]
    return error_response(request, AppError(400, "VALIDATION_ERROR", "요청 값을 확인해 주세요.", details))


@app.exception_handler(UniqueViolation)
async def duplicate_error(request: Request, _: UniqueViolation):
    return error_response(request, AppError(409, "DUPLICATE_ACTION", "이미 존재하는 값입니다."))


@app.exception_handler(ForeignKeyViolation)
async def reference_error(request: Request, _: ForeignKeyViolation):
    return error_response(request, AppError(422, "REFERENCE_CONSTRAINT", "연결된 리소스를 확인해 주세요."))


@app.exception_handler(DataError)
async def data_error(request: Request, _: DataError):
    """빈 문자열 UUID처럼 형식이 어긋난 입력은 서버 오류가 아니라 잘못된 요청이다."""
    return error_response(request, AppError(400, "VALIDATION_ERROR", "요청 값의 형식을 확인해 주세요."))


@app.get("/health/live")
def live(request: Request):
    return {"data": {"status": "UP"}, "meta": meta(request)}


@app.get("/health/ready")
def ready(request: Request):
    with pool.connection() as connection:
        one(connection, "SELECT 1")
    return {"data": {"status": "UP"}, "meta": meta(request)}


for route in (auth, public, visitor, p2_visitor, admin_core, admin_content, admin_ops, admin_esg, p2_admin, merchant, insights):
    app.include_router(route.router, prefix="/api/v1")
