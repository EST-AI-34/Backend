import base64
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response

from .errors import bad_request
from .schemas import camel


# snake_case 식별자로 보이는 키만 바꾼다. UUID·한국어·이미 camel인 키는 그대로 둔다 —
# jsonb 페이로드나 id로 묶은 목록의 키까지 건드리면 값이 망가진다.
SNAKE_KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


class Raw(dict):
    """키 자체가 데이터인 dict. 설문 보기처럼 사용자가 쓴 문자열이 키면 camel로 바꾸면 안 된다."""


def camelize(value: Any) -> Any:
    """응답 본문의 키를 camelCase로 통일한다. 요청 본문은 pydantic alias가 이미 맡고 있다."""
    if isinstance(value, Raw):
        return value
    if isinstance(value, dict):
        return {(camel(key) if isinstance(key, str) and SNAKE_KEY.match(key) else key): camelize(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value


def meta(request: Request) -> dict:
    return {"requestId": request.state.request_id, "serverTime": datetime.now(UTC).isoformat().replace("+00:00", "Z")}


def success(request: Request, data: Any, *, page: dict | None = None) -> dict:
    response = {"data": camelize(data)}
    if page is not None:
        response["page"] = camelize(page)
    response["meta"] = meta(request)
    return response


def encode_cursor(row: dict, column: str = "created_at") -> str:
    """`<정렬 시각 ISO>|<id>`를 base64url로 감싼다.

    ISO 타임스탬프의 `+00:00`을 그대로 내려주면 쿼리스트링에서 `+`가 공백으로 디코드돼
    다음 페이지 요청이 400으로 떨어진다. 커서는 클라이언트에게 불투명한 값이므로
    인코딩 규칙을 클라이언트가 알 필요가 없게 만든다.
    """
    return base64.urlsafe_b64encode(f"{row[column].isoformat()}|{row['id']}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    """encode_cursor의 역함수. 형식이 깨지면 조용히 첫 페이지로 돌아가지 않고 400."""
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        sort_value, _, resource_id = raw.partition("|")
        return datetime.fromisoformat(sort_value).isoformat(), str(uuid.UUID(resource_id))
    except (ValueError, UnicodeDecodeError) as error:
        raise bad_request("INVALID_CURSOR", "커서 값을 확인해 주세요.") from error


def paged(rows: list[dict], limit: int, column: str = "created_at") -> tuple[list[dict], dict]:
    """`limit+1`건을 읽어 온 목록을 (행, page) 로 자른다.

    목록 API가 전량 반환이라 축제가 커질수록 응답이 무한정 늘어났다. 감사 로그에만 있던
    키셋 페이지네이션을 같은 규칙으로 다른 목록에도 쓰기 위해 한 곳에 둔다.
    """
    has_next = len(rows) > limit
    rows = rows[:limit]
    return rows, {"nextCursor": encode_cursor(rows[-1], column) if has_next and rows else None,
                  "hasNext": has_next, "limit": limit}


def idempotent_success(request: Request, response: Response, result: tuple[int, dict, bool]) -> dict:
    response.status_code, data, replayed = result
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return success(request, data)
