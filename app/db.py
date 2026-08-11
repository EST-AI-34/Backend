import hashlib
import json
from collections.abc import Callable, Generator
from typing import Any

from psycopg import Connection
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings
from .errors import AppError, conflict


pool = ConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row},
)


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda data: json.dumps(data, default=str, ensure_ascii=False))


def database() -> Generator[Connection, None, None]:
    with pool.connection() as connection:
        yield connection


def one(connection: Connection, sql: str, params: tuple | list = ()) -> dict | None:
    return connection.execute(sql, params).fetchone()


def all_rows(connection: Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return connection.execute(sql, params).fetchall()


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
        (festival_id, actor_id, action, resource_type, resource_id, json.dumps(before_data, default=str) if before_data is not None else None,
         json.dumps(after_data, default=str) if after_data is not None else None, request_id),
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


def translate_db_error(error: Exception) -> AppError:
    if isinstance(error, UniqueViolation):
        return conflict("DUPLICATE_ACTION", "이미 존재하는 값입니다.")
    if isinstance(error, ForeignKeyViolation):
        return AppError(422, "REFERENCE_CONSTRAINT", "연결된 리소스를 확인해 주세요.")
    raise error
