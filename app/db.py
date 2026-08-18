import hashlib
import json
from collections.abc import Callable, Generator
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings
from .errors import AppError, bad_request, conflict


# prepare_threshold=None: 트랜잭션 모드 pgbouncer(Supabase pooler 등) 뒤에서는 서버측
# prepared statement 캐시가 물리 커넥션 간에 섞여 DuplicatePreparedStatement로 죽는다
# (백그라운드 잡 폴러에서 실제 재현 확인). 세션 모드/직결에서도 부작용이 없어 항상 끈다.
pool = ConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row, "prepare_threshold": None},
)


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda data: json.dumps(data, default=str, ensure_ascii=False))


def database() -> Generator[Connection, None, None]:
    with pool.connection() as connection:
        yield connection


# 같은 값을 여러 번 쓰는 쿼리는 dict를 넘겨 %(name)s로 참조한다(위치 인자 중복을 없앤다).
Params = tuple | list | dict


def one(connection: Connection, sql: str, params: Params = ()) -> dict | None:
    return connection.execute(sql, params).fetchone()


def all_rows(connection: Connection, sql: str, params: Params = ()) -> list[dict]:
    return connection.execute(sql, params).fetchall()


def set_clause(values: dict) -> tuple[str, list]:
    """{"name":"봄축제","menu":[...]} -> ("name=%s,menu=%s", ["봄축제", Jsonb([...])]).

    키는 SQL에 그대로 들어가므로 컬럼명이어야 한다. 호출부는 모두
    `extra="forbid"` 스키마의 `model_dump()`라 필드 집합이 고정이다.
    """
    if not values:
        raise bad_request("VALIDATION_ERROR", "변경할 값이 없습니다.")
    return (",".join(f"{column}=%s" for column in values),
            [jsonb(value) if isinstance(value, dict | list) else value for value in values.values()])


def audit(
    connection: Connection,
    *,
    festival_id: str | None,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    request_id: str,
    before_data: Any = None,
    after_data: Any = None,
) -> None:
    connection.execute(
        """INSERT INTO audit_logs(festival_id,actor_id,action,resource_type,resource_id,before_data,after_data,request_id)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
        (festival_id, actor_id, action, resource_type, resource_id,
         jsonb(before_data) if before_data is not None else None,
         jsonb(after_data) if after_data is not None else None, request_id),
    )


def idempotent(
    connection: Connection,
    *,
    key: str | None,
    scope: str,
    body: Any,
    work: Callable[[], tuple[int, dict]],
) -> tuple[int, dict, bool]:
    if not key:
        raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key 헤더가 필요합니다.")
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{scope}:{key}",))
    previous = one(connection, "SELECT * FROM idempotency_records WHERE scope=%s AND key=%s", (scope, key))
    if previous:
        if previous["request_hash"] != request_hash:
            raise conflict("IDEMPOTENCY_KEY_REUSED", "같은 키에 다른 요청 본문을 사용할 수 없습니다.")
        return previous["response_status"], previous["response_body"], True
    status, response = work()
    connection.execute(
        "INSERT INTO idempotency_records(scope,key,request_hash,response_status,response_body) VALUES(%s,%s,%s,%s,%s)",
        (scope, key, request_hash, status, json.dumps(response, default=str)),
    )
    return status, response, False
