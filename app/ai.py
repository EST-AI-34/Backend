"""Alan 오픈 API 연동.

호출부는 실패를 신경 쓰지 않는다. `briefing()`은 실패하면 None을 돌려주고,
호출부는 이미 가지고 있는 규칙 기반 문장을 그대로 쓴다. 외부 AI가 실제로
쓰였는지는 응답의 externalAiUsed로 운영자에게 드러낸다.
"""
import logging
import re
import threading
import time

import httpx

from .config import settings


logger = logging.getLogger(__name__)

# 키를 채우지 않은 배포를 인증 실패가 아니라 설정 누락으로 구분한다.
PLACEHOLDER_KEYS = {"", "your_alan_api_key_here", "changeme", "replace_me"}

RISK_INSTRUCTION = (
    "아래 검증된 축제 운영 위험 정보만 사용해 운영자용 한국어 요약을 정확히 한 문장으로 쓰세요. "
    "점수, 이름, 연락처, 개인정보, 확인되지 않은 원인을 새로 만들지 마세요."
)
ESG_INSTRUCTION = (
    "아래 검증된 ESG 정보만 사용해 운영자 대시보드용 한국어 브리핑을 정확히 한 문장으로 쓰세요. "
    "가장 중요한 상태와 필요한 조치 하나만 언급하고, 새로운 수치를 만들거나 계산하지 마세요."
)
VISITOR_INSTRUCTION = (
    "방문객의 질문에 아래 승인된 축제 정보만 사용해 친절하고 간결한 한국어로 답하세요. "
    "정보에 없는 사실은 추측하지 말고, 웹이나 이전 대화의 정보는 사용하지 마세요."
)


class AIUnavailable(RuntimeError):
    pass


# 회로 차단기. briefing()은 DB 커넥션을 쥔 요청 스레드 안에서 동기로 돈다(풀 max_size=10).
# Alan이 죽으면 대시보드 요청마다 타임아웃 + 재시도만큼 커넥션이 묶여 풀이 마른다.
# 연속 실패가 쌓이면 한동안 아예 부르지 않고 규칙 기반 문장으로 넘어간다.
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 60
_breaker = {"failures": 0, "open_until": 0.0}
# Alan 상태는 client_id 단위인데 현재 배포는 할당받은 키 하나를 공유한다. reset과 질문을
# 한 임계 구역으로 묶어 요청 사이 문맥을 지운다.
# ponytail: 프로세스 잠금은 현재 1-worker 배포용이다. 여러 replica 전에 공급자의 세션별 키가 필요하다.
_alan_lock = threading.Lock()


def reset_breaker() -> None:
    """차단 상태를 지운다. 프로세스 전역 상태라 테스트가 서로 간섭하지 않게 필요하다."""
    _breaker.update(failures=0, open_until=0.0)


def briefing(instruction: str, context: list[str]) -> str | None:
    """한 문장 브리핑. 비활성·미설정·오류·타임아웃·회로 차단이면 None."""
    if not settings.external_ai_enabled:
        return None
    if time.monotonic() < _breaker["open_until"]:
        return None
    try:
        answer = one_sentence(ask(prompt(instruction, context)))
    # ValueError는 response.json()이 JSON이 아닌 본문(게이트웨이 HTML 등)을 만났을 때다.
    except (AIUnavailable, httpx.HTTPError, ValueError) as error:
        _breaker["failures"] += 1
        if _breaker["failures"] >= BREAKER_THRESHOLD:
            _breaker["open_until"] = time.monotonic() + BREAKER_COOLDOWN_SECONDS
            _breaker["failures"] = 0
            logger.warning("외부 AI 연속 실패로 %s초 동안 호출을 건너뜁니다.", BREAKER_COOLDOWN_SECONDS)
        logger.warning("외부 AI 브리핑 실패, 규칙 기반 문장을 사용합니다: %s", error)
        return None
    _breaker["failures"] = 0
    return answer


def grounded_answer(question: str, sources: list[dict]) -> str | None:
    """승인 콘텐츠가 있을 때만 Alan으로 방문객용 답변을 다듬는다."""
    if not sources:
        return None
    context = []
    for source in sources:
        body = source["body"]
        context.append(" | ".join(filter(None, (
            body.get("title"), body.get("summary"), body.get("description"), body.get("text"),
        ))))
    return briefing(f"{VISITOR_INSTRUCTION}\n\n방문객 질문: {question}", context)


def ask(content: str) -> str:
    """Alan 상태를 앞뒤로 지우고 질문 한 건을 보낸다. 실패 시 AIUnavailable."""
    if settings.alan_client_id.strip() in PLACEHOLDER_KEYS:
        raise AIUnavailable("ALAN_CLIENT_ID가 설정되지 않았습니다.")
    with _alan_lock:
        reset_state()
        try:
            data = request({"content": content, "client_id": settings.alan_client_id})
        finally:
            try:
                reset_state()
            except AIUnavailable as error:
                # 다음 요청은 사전 reset이 성공해야 질문을 보내므로 현재 응답까지 버릴 이유는 없다.
                logger.warning("Alan 응답 후 상태 초기화 실패: %s", error)
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise AIUnavailable("Alan이 빈 답변을 반환했습니다.")
    return answer.strip()


def reset_state() -> None:
    """공유 client_id의 이전 대화 상태를 제거한다. 상태 없음(404)은 정상이다."""
    url = settings.alan_question_url.rsplit("/question", 1)[0] + "/reset-state"
    try:
        with httpx.Client(timeout=timeout()) as client:
            response = client.request("DELETE", url, json={"client_id": settings.alan_client_id})
        if response.status_code == 404:
            return
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise AIUnavailable(f"Alan 대화 상태 초기화에 실패했습니다: {error}") from error


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
    attempts = max(1, settings.alan_max_retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout()) as client:
                response = client.get(settings.alan_question_url, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AIUnavailable("Alan이 객체가 아닌 JSON을 반환했습니다.")
            return data
        except httpx.HTTPStatusError as error:
            detail = f"Alan이 오류 상태를 반환했습니다: {error.response.status_code} {error.response.text[:200]}"
            # 4xx는 키·요청 문제라 다시 보내도 같다. 5xx만 재시도한다.
            if error.response.status_code < 500:
                raise AIUnavailable(detail) from error
            backoff(attempt, attempts, detail, error)
        except httpx.HTTPError as error:
            backoff(attempt, attempts, str(error), error)
    raise AIUnavailable("Alan 요청이 실패했습니다.")


def backoff(attempt: int, attempts: int, detail: str, error: Exception) -> None:
    """마지막 시도면 AIUnavailable, 아니면 잠깐 쉬고 호출부 루프로 돌아간다."""
    logger.warning("Alan 요청 실패 %s/%s: %s", attempt, attempts, detail)
    if attempt >= attempts:
        raise AIUnavailable(f"Alan 요청이 {attempts}회 모두 실패했습니다: {detail}") from error
    time.sleep(min(0.5 * attempt, 2.0))


def timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=settings.alan_connect_timeout, read=settings.alan_read_timeout,
                         write=settings.alan_connect_timeout, pool=settings.alan_connect_timeout)
