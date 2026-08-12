from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response


def meta(request: Request) -> dict:
    return {"requestId": request.state.request_id, "serverTime": datetime.now(UTC).isoformat().replace("+00:00", "Z")}


def success(request: Request, data: Any, *, page: dict | None = None) -> dict:
    response = {"data": data}
    if page is not None:
        response["page"] = page
    response["meta"] = meta(request)
    return response


def idempotent_success(request: Request, response: Response, result: tuple[int, dict, bool]) -> dict:
    response.status_code, data, replayed = result
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return success(request, data)
