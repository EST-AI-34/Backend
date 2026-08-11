from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder


def ok(data: object) -> dict:
    return {
        "data": jsonable_encoder(data),
        "meta": {
            "requestId": f"req_{uuid4().hex}",
            "serverTime": datetime.now(timezone.utc).isoformat(),
        },
    }


def listed(data: object, limit: int = 20) -> dict:
    return {
        "data": jsonable_encoder(data),
        "page": {
            "nextCursor": None,
            "hasNext": False,
            "limit": limit,
        },
        "meta": {
            "requestId": f"req_{uuid4().hex}",
            "serverTime": datetime.now(timezone.utc).isoformat(),
        },
    }
