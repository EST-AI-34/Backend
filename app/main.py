import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from .db import one, pool
from .errors import AppError
from .http import meta
from .jobs import start_worker
from .routes import (admin_content, admin_core, admin_esg, admin_ops, auth, merchant, p2_admin,
                     p2_visitor, public, visitor)


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


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4()}"
    path = request.url.path
    limit = 20 if "/visitor/ai/" in path else 10 if path.endswith("/auth/login") else 60 if "/admin/" in path and request.method != "GET" else 120 if "/public/" in path else None
    if limit:
        # ponytail: process-local limiter; use Redis when multiple API instances are deployed.
        window = int(time.time() // 60)
        key = (request.client.host if request.client else "unknown", "/".join(path.split("/")[:6]), window)
        counts[key] += 1
        if counts[key] > limit:
            return JSONResponse(status_code=429, content={"error":{"code":"RATE_LIMITED","message":"호출 한도를 초과했습니다.","details":[],"retryable":True},"meta":meta(request)})
        if len(counts) > 10_000:
            for old in list(counts):
                if old[2] != window:
                    counts.pop(old, None)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(AppError)
async def app_error(request: Request, error: AppError):
    return JSONResponse(status_code=error.status, content={"error":{"code":error.code,"message":error.message,"details":error.details,"retryable":error.retryable},"meta":meta(request)})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    details=[{"field":".".join(str(part) for part in issue["loc"] if part!="body"),"reason":issue["msg"]} for issue in error.errors()]
    return JSONResponse(status_code=400,content={"error":{"code":"VALIDATION_ERROR","message":"요청 값을 확인해 주세요.","details":details,"retryable":False},"meta":meta(request)})


@app.exception_handler(UniqueViolation)
async def duplicate_error(request:Request,_:UniqueViolation):
    return await app_error(request,AppError(409,"DUPLICATE_ACTION","이미 존재하는 값입니다."))


@app.exception_handler(ForeignKeyViolation)
async def reference_error(request:Request,_:ForeignKeyViolation):
    return await app_error(request,AppError(422,"REFERENCE_CONSTRAINT","연결된 리소스를 확인해 주세요."))


@app.get("/health/live")
def live(request:Request):
    return {"data":{"status":"UP"},"meta":meta(request)}


@app.get("/health/ready")
def ready(request:Request):
    with pool.connection() as connection:
        one(connection,"SELECT 1")
    return {"data":{"status":"UP"},"meta":meta(request)}


for route in (auth.router,public.router,visitor.router,p2_visitor.router,admin_core.router,admin_content.router,
              admin_ops.router,admin_esg.router,p2_admin.router,merchant.router):
    app.include_router(route,prefix="/api/v1")
