"""myAlan(앨런) LLM 연동.

호출부는 실패를 신경 쓰지 않는다. `briefing()`은 실패하면 None을 돌려주고,
호출부는 이미 가지고 있는 규칙 기반 문장을 그대로 쓴다. 외부 AI가 실제로
쓰였는지는 응답의 externalAiUsed로 운영자에게 드러낸다.
"""
import logging
import re
import time

import httpx

from .config import settings


logger = logging.getLogger(__name__)

# 키를 채우지 않은 배포를 인증 실패가 아니라 설정 누락으로 구분한다.
PLACEHOLDER_KEYS = {"", "your_allen_api_key_here", "changeme", "replace_me"}

RISK_INSTRUCTION = (
    "아래 검증된 축제 운영 위험 정보만 사용해 운영자용 한국어 요약을 정확히 한 문장으로 쓰세요. "
    "점수, 이름, 연락처, 개인정보, 확인되지 않은 원인을 새로 만들지 마세요."
)
ESG_INSTRUCTION = (
    "아래 검증된 ESG 정보만 사용해 운영자 대시보드용 한국어 브리핑을 정확히 한 문장으로 쓰세요. "
    "가장 중요한 상태와 필요한 조치 하나만 언급하고, 새로운 수치를 만들거나 계산하지 마세요."
)

_token: str | None = None
_token_expires_at = 0.0


class AIUnavailable(RuntimeError):
    pass


def briefing(instruction: str, context: list[str]) -> str | None:
    """한 문장 브리핑. 비활성·미설정·오류·타임아웃이면 None."""
    if not settings.external_ai_enabled:
        return None
    try:
        return one_sentence(complete(instruction, context))
    except (AIUnavailable, httpx.HTTPError) as error:
        logger.warning("외부 AI 브리핑 실패, 규칙 기반 문장을 사용합니다: %s", error)
        return None


def complete(instruction: str, context: list[str]) -> str:
    """앨런 채널을 열고 답변 한 건을 받는다. 실패 시 AIUnavailable."""
    require_config()
    channel = channel_id()
    messages_path = f"{settings.allen_channels_path.rstrip('/')}/{channel}/messages"
    data = request("POST", messages_path, json={
        "channel_id": channel,
        "persona_id": settings.allen_persona_id,
        "content": prompt(instruction, context),
        "options": {"file_ids": []},
    })
    reply = extract_reply(data)
    if not reply:
        reply = extract_reply(poll(messages_path))
    if not reply:
        raise AIUnavailable("앨런이 빈 답변을 반환했습니다.")
    return reply.strip()


def prompt(instruction: str, context: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in context)
    return ("당신은 지역축제 운영 보조입니다. 백엔드가 제공한 검증된 정보만 사용하고 "
            "통계·일정·혼잡도·예약·민원·ESG 값을 지어내지 마세요.\n\n"
            f"{instruction}\n\n검증된 정보:\n{lines}")


def one_sentence(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"\[(?:출처|source)\d*\]\([^)]+\)", "", compact, flags=re.IGNORECASE)
    compact = compact.strip(" -*#")
    # 숫자 사이의 소수점은 문장 끝으로 보지 않는다.
    end = re.search(r"(?<!\d)[.!?。](?!\d)", compact)
    return compact[: end.end()].strip() if end else compact[:220].strip()


def extract_reply(data: dict) -> str | None:
    if isinstance(data.get("content"), str) and data["content"].strip():
        return data["content"]
    message = data.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str) and message["content"].strip():
        return message["content"]
    for item in reversed(data.get("messages") or []):
        if isinstance(item, dict) and item.get("userRole") != "user" and isinstance(item.get("content"), str) and item["content"].strip():
            return item["content"]
    return None


def channel_id() -> str:
    data = request("POST", settings.allen_channels_path,
                   json={"persona_id": settings.allen_persona_id, "temporary": True})
    channel = data.get("inserted_id") or data.get("_id") or data.get("channel_id")
    if not isinstance(channel, str) or not channel.strip():
        raise AIUnavailable("앨런이 채널 ID를 반환하지 않았습니다.")
    return channel.strip()


def poll(messages_path: str) -> dict:
    for _ in range(settings.allen_poll_attempts):
        time.sleep(settings.allen_poll_seconds)
        data = request("GET", messages_path)
        if extract_reply(data):
            return data
    raise AIUnavailable("앨런 답변이 시간 안에 오지 않았습니다.")


def require_config() -> None:
    mode = settings.allen_auth_mode.strip().lower()
    if mode == "bearer" and settings.allen_api_key.strip() in PLACEHOLDER_KEYS:
        raise AIUnavailable("ALLEN_API_KEY가 설정되지 않았습니다.")
    if mode == "implicit" and settings.allen_client_id.strip() in PLACEHOLDER_KEYS:
        raise AIUnavailable("ALLEN_AUTH_MODE=implicit에는 ALLEN_CLIENT_ID가 필요합니다.")
    if mode not in {"bearer", "implicit"}:
        raise AIUnavailable(f"지원하지 않는 ALLEN_AUTH_MODE입니다: {settings.allen_auth_mode}")


def timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=settings.allen_connect_timeout, read=settings.allen_read_timeout,
                         write=settings.allen_connect_timeout, pool=settings.allen_connect_timeout)


def request(method: str, path: str, **kwargs) -> dict:
    url = f"{settings.allen_base_url.rstrip('/')}/{path.lstrip('/')}"
    attempts = max(1, settings.allen_max_retries + 1)
    refreshed = False
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout()) as client:
                response = client.request(method, url, headers={"Authorization": f"Bearer {auth_token()}", "Content-Type": "application/json"}, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AIUnavailable("앨런이 객체가 아닌 JSON을 반환했습니다.")
            return data
        except httpx.HTTPStatusError as error:
            # 만료된 implicit 토큰은 한 번만 재발급한다.
            if error.response.status_code == 401 and settings.allen_auth_mode.strip().lower() == "implicit" and not refreshed:
                clear_token()
                refreshed = True
                continue
            raise AIUnavailable(f"앨런이 오류 상태를 반환했습니다: {error.response.status_code} {error.response.text[:200]}") from error
        except (httpx.TimeoutException, httpx.HTTPError) as error:
            logger.warning("앨런 요청 실패 %s/%s: %s", attempt, attempts, error)
            if attempt >= attempts:
                raise AIUnavailable(f"앨런 요청이 {attempts}회 모두 실패했습니다: {error}") from error
            time.sleep(min(0.5 * attempt, 2.0))
    raise AIUnavailable("앨런 요청이 실패했습니다.")


def auth_token() -> str:
    if settings.allen_auth_mode.strip().lower() == "bearer":
        return settings.allen_api_key
    return implicit_token()


def implicit_token() -> str:
    global _token, _token_expires_at
    if _token and time.monotonic() < _token_expires_at:
        return _token
    base = settings.allen_auth_base_url.rstrip("/")
    client_id = settings.allen_client_id.strip()
    try:
        with httpx.Client(timeout=timeout()) as client:
            client.post(f"{base}/device-info", json={"device_id": client_id, "platform": settings.allen_device_platform, "version": settings.allen_device_version}).raise_for_status()
            response = client.post(f"{base}/oauth2/token", data={"client_id": client_id, "grant_type": "implicit_grant"})
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as error:
        raise AIUnavailable(f"앨런 implicit 토큰 발급에 실패했습니다: {error}") from error
    token = data.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise AIUnavailable("앨런이 access_token을 반환하지 않았습니다.")
    try:
        ttl = float(data.get("expires_in"))
    except (TypeError, ValueError):
        ttl = 900.0
    _token, _token_expires_at = token.strip(), time.monotonic() + max(30.0, ttl - 30.0)
    return _token


def clear_token() -> None:
    global _token, _token_expires_at
    _token, _token_expires_at = None, 0.0
