import base64
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response

from .config import settings
from .errors import bad_request
from .schemas import camel


def client_ip(request: Request) -> str:
    """요청 출처 IP.

    프록시 뒤에서 request.client.host는 프록시 주소라 모든 방문자가 한 값을 공유한다
    (레이트 리밋 버킷 하나를 나눠 쓰면 보호도 안 되고 정상 사용자도 막힌다).
    TRUST_PROXY_HEADERS를 켠 배포에서만 X-Forwarded-For의 첫 항목을 쓴다 — 직결 배포에서
    무조건 신뢰하면 클라이언트가 헤더를 위조해 한도를 우회할 수 있다.
    """
    if settings.trust_proxy_headers:
        first = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


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


def keyset(column: str = "created_at", alias: str = "") -> str:
    """`(정렬 컬럼, id)` 키셋 조건. cursor_params가 채우는 이름 파라미터를 참조한다.

    f-string으로 SQL에 그대로 들어가므로 컬럼·별칭은 상수여야 한다(사용자 입력 금지).
    """
    prefix = f"{alias}." if alias else ""
    return (f"(%(after_at)s::timestamptz IS NULL OR ({prefix}{column},{prefix}id) < "
            f"(%(after_at)s::timestamptz,%(after_id)s::uuid))")


def cursor_params(cursor: str | None, limit: int) -> dict:
    """keyset()이 참조하는 파라미터. limit는 한 건 더 읽어 paged()가 다음 페이지를 판단하게 한다."""
    after = decode_cursor(cursor)
    return {"after_at": after[0] if after else None, "after_id": after[1] if after else None, "limit": limit + 1}


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
