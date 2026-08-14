"""앨런(Alan) 오픈 API 연동.

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


class AIUnavailable(RuntimeError):
    pass


def briefing(instruction: str, context: list[str]) -> str | None:
    """한 문장 브리핑. 비활성·미설정·오류·타임아웃이면 None."""
    if not settings.external_ai_enabled:
        return None
    try:
        return one_sentence(ask(prompt(instruction, context)))
    # ValueError는 response.json()이 JSON이 아닌 본문(게이트웨이 HTML 등)을 만났을 때다.
    except (AIUnavailable, httpx.HTTPError, ValueError) as error:
        logger.warning("외부 AI 브리핑 실패, 규칙 기반 문장을 사용합니다: %s", error)
        return None


def ask(content: str) -> str:
    """앨런에 질문 한 건을 보내고 답변을 받는다. 실패 시 AIUnavailable."""
    if settings.allen_client_id.strip() in PLACEHOLDER_KEYS:
        raise AIUnavailable("ALLEN_CLIENT_ID가 설정되지 않았습니다.")
    data = request({"content": content, "client_id": settings.allen_client_id})
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise AIUnavailable("앨런이 빈 답변을 반환했습니다.")
    return answer.strip()


def prompt(instruction: str, context: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in context)
    return ("당신은 지역축제 운영 보조입니다. 아래 검증된 정보만 사용하고 "
            "통계·일정·혼잡도·예약·민원·ESG 값을 지어내지 마세요. "
            "웹을 검색하지 말고 출처를 붙이지 마세요.\n\n"
            f"{instruction}\n\n검증된 정보:\n{lines}")


def one_sentence(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"\[(?:출처|source)\d*\]\([^)]+\)", "", compact, flags=re.IGNORECASE)
    compact = compact.replace("**", "").replace("##", "").strip(" -*#\"'")
    # 숫자 사이의 소수점은 문장 끝으로 보지 않는다.
    end = re.search(r"(?<!\d)[.!?。](?!\d)", compact)
    return (compact[: end.end()] if end else compact[:220]).strip(" \"'")


def request(params: dict) -> dict:
    attempts = max(1, settings.allen_max_retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout()) as client:
                response = client.get(settings.allen_question_url, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AIUnavailable("앨런이 객체가 아닌 JSON을 반환했습니다.")
            return data
        except httpx.HTTPStatusError as error:
            detail = f"앨런이 오류 상태를 반환했습니다: {error.response.status_code} {error.response.text[:200]}"
            # 4xx는 키·요청 문제라 다시 보내도 같다. 5xx만 재시도한다.
            if error.response.status_code < 500:
                raise AIUnavailable(detail) from error
            backoff(attempt, attempts, detail, error)
        except httpx.HTTPError as error:
            backoff(attempt, attempts, str(error), error)
    raise AIUnavailable("앨런 요청이 실패했습니다.")


def backoff(attempt: int, attempts: int, detail: str, error: Exception) -> None:
    """마지막 시도면 AIUnavailable, 아니면 잠깐 쉬고 호출부 루프로 돌아간다."""
    logger.warning("앨런 요청 실패 %s/%s: %s", attempt, attempts, detail)
    if attempt >= attempts:
        raise AIUnavailable(f"앨런 요청이 {attempts}회 모두 실패했습니다: {detail}") from error
    time.sleep(min(0.5 * attempt, 2.0))


def timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=settings.allen_connect_timeout, read=settings.allen_read_timeout,
                         write=settings.allen_connect_timeout, pool=settings.allen_connect_timeout)
