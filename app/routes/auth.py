from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response

from ..config import settings
from ..db import audit, one
from ..deps import Db, User
from ..errors import unauthorized
from ..http import success
from ..schemas import LoginIn, TokenIn
from ..security import access_token, hash_token, random_token, verify_password


router = APIRouter()


def issue_refresh_token(connection, user_id) -> str:
    token = random_token("rt")
    connection.execute("INSERT INTO refresh_tokens(user_id,token_hash,expires_at) VALUES(%s,%s,%s)",
        (user_id, hash_token(token), datetime.now(UTC) + timedelta(days=settings.refresh_token_days)))
    return token


@router.post("/auth/login")
def login(body: LoginIn, request: Request, connection: Db):
    row = one(
        connection,
        """SELECT u.*,m.id AS membership_id,m.organization_id,m.role,m.festival_scope
           FROM users u JOIN memberships m ON m.user_id=u.id
           WHERE lower(u.email)=lower(%s) AND u.status='ACTIVE' AND m.status='ACTIVE'
           ORDER BY m.created_at LIMIT 1""",
        (str(body.email),),
    )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise unauthorized(message="이메일 또는 비밀번호가 올바르지 않습니다.")
    refresh = issue_refresh_token(connection, row["id"])
    audit(connection, festival_id=None, actor_id=str(row["id"]), action="LOGIN", resource_type="USER", resource_id=str(row["id"]), request_id=request.state.request_id)
    return success(request, {
        "accessToken": access_token(str(row["id"]), str(row["membership_id"])),
        "refreshToken": refresh,
        "tokenType": "Bearer",
        "user": {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]},
    })


@router.post("/auth/refresh")
def refresh(body: TokenIn, request: Request, connection: Db):
    row = one(
        connection,
        """SELECT rt.id AS refresh_id,u.*,m.id AS membership_id,m.organization_id,m.role,m.festival_scope
           FROM refresh_tokens rt JOIN users u ON u.id=rt.user_id JOIN memberships m ON m.user_id=u.id
           WHERE rt.token_hash=%s AND rt.revoked_at IS NULL AND rt.expires_at>now()
             AND u.status='ACTIVE' AND m.status='ACTIVE' ORDER BY m.created_at LIMIT 1""",
        (hash_token(body.refresh_token),),
    )
    if not row:
        raise unauthorized("TOKEN_EXPIRED", "리프레시 토큰이 만료되었거나 폐기되었습니다.")
    connection.execute("UPDATE refresh_tokens SET revoked_at=now() WHERE id=%s", (row["refresh_id"],))
    return success(request, {"accessToken": access_token(str(row["id"]), str(row["membership_id"])),
                             "refreshToken": issue_refresh_token(connection, row["id"]), "tokenType": "Bearer"})


@router.post("/auth/logout", status_code=204)
def logout(body: TokenIn, connection: Db) -> Response:
    connection.execute("UPDATE refresh_tokens SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL", (hash_token(body.refresh_token),))
    return Response(status_code=204)


@router.get("/me")
def me(request: Request, user: User):
    return success(request, {"id": user["id"], "email": user["email"], "name": user["name"],
                             "organizationId": user["organization_id"], "role": user["role"], "festivalScope": user["festival_scope"]})
