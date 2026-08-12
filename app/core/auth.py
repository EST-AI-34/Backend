from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings


security = HTTPBearer(auto_error=False)
PLACEHOLDER_SECRETS = {"", "replace-with-at-least-32-random-characters", "changeme", "replace_me"}
ADMIN_ROLES = {"SUPER_ADMIN", "FESTIVAL_MANAGER", "FIELD_OPERATOR", "REVIEWER"}


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    role: str
    festival_scope: list[str]


def require_admin(
    festival_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AdminPrincipal:
    return require_admin_roles(ADMIN_ROLES)(festival_id, credentials)


def require_admin_roles(allowed_roles: set[str]):
    def dependency(
        festival_id: str | None = None,
        credentials: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> AdminPrincipal:
        return _require_admin(allowed_roles, festival_id, credentials)

    return dependency


def _require_admin(
    allowed_roles: set[str],
    festival_id: str | None,
    credentials: HTTPAuthorizationCredentials | None,
) -> AdminPrincipal:
    _validate_auth_settings()
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication is required.",
        )
    try:
        payload = _decode_hs256_jwt(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        ) from exc

    role = str(payload.get("role") or "")
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role is not allowed.",
        )

    scope = _festival_scope(payload)
    if festival_id is not None and "*" not in scope and str(festival_id) not in scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role is not allowed for this festival.",
        )

    return AdminPrincipal(
        subject=str(payload.get("sub") or ""),
        role=role,
        festival_scope=scope,
    )


def _festival_scope(payload: dict[str, Any]) -> list[str]:
    value = payload.get("festival_scope", [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _decode_hs256_jwt(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three parts.")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(settings.JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64decode(parts[2])
    if not hmac.compare_digest(expected, actual):
        raise ValueError("JWT signature mismatch.")
    header = json.loads(_b64decode(parts[0]))
    if header.get("alg") != "HS256":
        raise ValueError("Unsupported JWT algorithm.")
    payload = json.loads(_b64decode(parts[1]))
    if not isinstance(payload, dict):
        raise ValueError("JWT payload must be an object.")
    _validate_claims(payload)
    return payload


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _validate_auth_settings() -> None:
    if settings.ENVIRONMENT.lower() != "development" and settings.JWT_SECRET.strip() in PLACEHOLDER_SECRETS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin authentication is not configured.",
        )


def _validate_claims(payload: dict[str, Any]) -> None:
    now = int(time.time())
    exp = _int_claim(payload, "exp")
    if exp is None or exp <= now:
        raise ValueError("JWT is expired or missing exp.")
    nbf = _int_claim(payload, "nbf")
    if nbf is not None and nbf > now:
        raise ValueError("JWT is not active yet.")
    if payload.get("iss") != settings.JWT_ISSUER:
        raise ValueError("JWT issuer mismatch.")
    audience = payload.get("aud")
    valid_audience = audience == settings.JWT_AUDIENCE or (
        isinstance(audience, list) and settings.JWT_AUDIENCE in audience
    )
    if not valid_audience:
        raise ValueError("JWT audience mismatch.")


def _int_claim(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"JWT {name} must be numeric.") from exc
