from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response

from ..config import settings
from ..db import audit, one
from ..deps import Db, User
from ..errors import AppError, unauthorized
from ..http import success
from ..schemas import LoginIn, PasswordChangeIn, TokenIn
from ..security import (DUMMY_PASSWORD_HASH, access_token, hash_password, hash_token, random_token,
                        verify_password)


router = APIRouter()


def issue_refresh_token(connection, user_id) -> str:
    token = random_token("rt")
    connection.execute("INSERT INTO refresh_tokens(user_id,token_hash,expires_at) VALUES(%s,%s,%s)",
        (user_id, hash_token(token), datetime.now(UTC) + timedelta(days=settings.refresh_token_days)))
    return token


def lock_state(connection, email: str) -> dict | None:
    return one(connection, "SELECT failures,locked_until FROM login_attempts WHERE email=%s", (email,))


def record_failure(connection, email: str) -> None:
    """실패를 세고 한도를 넘으면 잠근다. IP 레이트 리밋만으로는 분산된 자격증명 대입을 못 막는다.

    잠금 창이 지난 행은 먼저 0으로 되돌린다. 안 그러면 failures가 한도 위에 그대로 머물러
    이후 실패 한 번마다 잠금이 새로 걸리는데, 잠긴 동안은 비밀번호 검증 전에 429로 끊기므로
    정상 사용자가 잠금을 풀 방법이 없다 — 공격자가 잠금 시간마다 한 번씩만 틀려도 계정이
    영구히 잠긴다. (같은 UPDATE 안에서는 새 failures 값을 locked_until이 참조할 수 없어
    CASE를 두 번 쓰는 대신 문장을 나눈다.)
    """
    connection.execute("UPDATE login_attempts SET failures=0,locked_until=NULL WHERE email=%s AND locked_until<now()",
                       (email,))
    connection.execute(
        """INSERT INTO login_attempts(email,failures) VALUES(%(email)s,1)
           ON CONFLICT(email) DO UPDATE SET
             failures=login_attempts.failures+1,
             locked_until=CASE WHEN login_attempts.failures+1>=%(max_failures)s
                               THEN now()+make_interval(mins => %(lock_minutes)s) END,
             updated_at=now()""",
        {"email": email, "max_failures": settings.login_max_failures, "lock_minutes": settings.login_lock_minutes},
    )
    # 호출부가 곧바로 401을 던지는데, 그러면 요청 트랜잭션이 통째로 롤백돼 방금 센 실패가
    # 사라진다(= 잠금이 영영 걸리지 않는다). 실패 기록은 여기서 확정한다.
    connection.commit()


@router.post("/auth/login")
def login(body: LoginIn, request: Request, connection: Db):
    email = str(body.email).lower()
    locked = lock_state(connection, email)
    if locked and locked["locked_until"] and locked["locked_until"] > datetime.now(UTC):
        raise AppError(429, "ACCOUNT_LOCKED", "로그인 시도가 많아 잠시 잠겼습니다. 잠시 후 다시 시도해 주세요.", retryable=True)
    row = one(
        connection,
        """SELECT u.*,m.id AS membership_id,m.organization_id,m.role,m.festival_scope
           FROM users u JOIN memberships m ON m.user_id=u.id
           WHERE lower(u.email)=lower(%s) AND u.status='ACTIVE' AND m.status='ACTIVE'
           ORDER BY m.created_at LIMIT 1""",
        (email,),
    )
    # 계정이 없어도 같은 비용의 해시 검증을 돌린다 — 응답 시간으로 가입 여부가 새지 않게.
    if not verify_password(body.password, row["password_hash"] if row else DUMMY_PASSWORD_HASH) or not row:
        record_failure(connection, email)
        raise unauthorized(message="이메일 또는 비밀번호가 올바르지 않습니다.")
    connection.execute("DELETE FROM login_attempts WHERE email=%s", (email,))
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
    token_hash = hash_token(body.refresh_token)
    row = one(
        connection,
        """SELECT rt.id AS refresh_id,u.*,m.id AS membership_id,m.organization_id,m.role,m.festival_scope
           FROM refresh_tokens rt JOIN users u ON u.id=rt.user_id JOIN memberships m ON m.user_id=u.id
           WHERE rt.token_hash=%s AND rt.revoked_at IS NULL AND rt.expires_at>now()
             AND u.status='ACTIVE' AND m.status='ACTIVE' ORDER BY m.created_at LIMIT 1""",
        (token_hash,),
    )
    if not row:
        # 이미 폐기된 토큰이 다시 오면 탈취를 의심한다 — 정상 클라이언트는 회전된 예전 토큰을
        # 다시 쓰지 않는다. 해당 계정의 살아 있는 토큰을 전부 끊어 두 세션 중 하나를 남기지 않는다.
        reused = one(connection, """SELECT user_id FROM refresh_tokens
            WHERE token_hash=%s AND revoked_at IS NOT NULL""", (token_hash,))
        if reused:
            connection.execute("UPDATE refresh_tokens SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                               (reused["user_id"],))
            audit(connection, festival_id=None, actor_id=str(reused["user_id"]), action="REFRESH_TOKEN_REUSE",
                  resource_type="USER", resource_id=str(reused["user_id"]), request_id=request.state.request_id)
            # 아래 401이 요청 트랜잭션을 롤백시킨다. 폐기와 감사 로그를 여기서 확정하지 않으면
            # 탈취 탐지가 아무것도 하지 않은 것과 같아진다.
            connection.commit()
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


@router.post("/me/password")
def change_password(body: PasswordChangeIn, request: Request, user: User, connection: Db):
    """본인 비밀번호 변경.

    운영자 화면은 초기 비밀번호를 발급하고 "로그인한 뒤 변경하라"고 안내해 왔지만
    정작 변경할 방법이 없었다. 변경하면 이 계정의 리프레시 토큰을 전부 폐기해서
    유출된 예전 비밀번호로 이미 열린 세션이 계속 살아 있지 않게 한다.
    """
    row = one(connection, "SELECT password_hash FROM users WHERE id=%s AND status='ACTIVE'", (user["id"],))
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise unauthorized("INVALID_CREDENTIALS", "현재 비밀번호가 올바르지 않습니다.")
    connection.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hash_password(body.new_password), user["id"]))
    connection.execute("UPDATE refresh_tokens SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user["id"],))
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="PASSWORD_CHANGE", resource_type="USER",
          resource_id=str(user["id"]), request_id=request.state.request_id)
    # 리프레시 토큰을 전부 끊었으므로 현재 기기가 계속 쓸 토큰 한 쌍을 새로 내준다.
    return success(request, {"accessToken": access_token(str(user["id"]), str(user["membership_id"])),
                             "refreshToken": issue_refresh_token(connection, user["id"]), "tokenType": "Bearer"})
