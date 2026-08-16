import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import Connection

from .config import settings
from .db import database, one
from .errors import forbidden, unauthorized


bearer = HTTPBearer(auto_error=False)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def random_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


# 존재하지 않는 계정에 대고도 같은 비용의 해시 검증을 한 번 돌리기 위한 더미 해시.
# 없으면 "계정 없음"은 즉시 401, "비밀번호 틀림"은 scrypt 시간만큼 늦게 401이라
# 응답 시간만 재도 가입된 이메일인지 알 수 있다.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


def access_token(user_id: str, membership_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": user_id, "type": "access", "membershipId": membership_id, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes), "iss": "festival-dx"},
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    connection: Annotated[Connection, Depends(database)],
) -> dict:
    if not credentials:
        raise unauthorized()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"], issuer="festival-dx")
    except jwt.ExpiredSignatureError as error:
        raise unauthorized("TOKEN_EXPIRED", "운영자 토큰이 만료되었습니다.") from error
    except jwt.PyJWTError as error:
        raise unauthorized(message="유효하지 않은 운영자 토큰입니다.") from error
    if payload.get("type") != "access":
        raise unauthorized()
    user = one(
        connection,
        """SELECT u.id,u.email,u.name,m.id AS membership_id,m.organization_id,m.role,m.festival_scope
           FROM users u JOIN memberships m ON m.user_id=u.id
           WHERE u.id=%s AND m.id=%s AND u.status='ACTIVE' AND m.status='ACTIVE'""",
        (payload.get("sub"), payload.get("membershipId")),
    )
    if not user:
        raise unauthorized()
    return user


def roles(*allowed: str):
    def check(user: Annotated[dict, Depends(current_user)]) -> dict:
        if user["role"] not in allowed:
            raise forbidden()
        return user
    return check


def festival_access(
    festival_id: Annotated[str, Path()],
    user: Annotated[dict, Depends(current_user)],
    connection: Annotated[Connection, Depends(database)],
) -> dict:
    festival = one(connection, "SELECT id,organization_id FROM festivals WHERE id=%s", (festival_id,))
    scope = user.get("festival_scope") or []
    if not festival or str(festival["organization_id"]) != str(user["organization_id"]) or not (user["role"] == "SUPER_ADMIN" or "*" in scope or festival_id in scope):
        raise forbidden("FESTIVAL_SCOPE_DENIED", "축제 접근 범위가 아닙니다.")
    return festival


def current_visitor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    connection: Annotated[Connection, Depends(database)],
) -> dict:
    if not credentials or not credentials.credentials.startswith("vs_"):
        raise unauthorized()
    visitor = one(
        connection,
        """SELECT id,festival_id,language,accessibility_preferences FROM visitor_sessions
           WHERE anonymous_token_hash=%s AND ended_at IS NULL AND expires_at>now()""",
        (hash_token(credentials.credentials),),
    )
    if not visitor:
        raise unauthorized("TOKEN_EXPIRED", "방문 세션이 만료되었거나 유효하지 않습니다.")
    return visitor
