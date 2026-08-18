"""Alan 오픈 API 연동.

호출부는 실패를 신경 쓰지 않는다. `briefing()`은 실패하면 None을 돌려주고,
호출부는 이미 가지고 있는 규칙 기반 문장을 그대로 쓴다. 외부 AI가 실제로
쓰였는지는 응답의 externalAiUsed로 운영자에게 드러낸다.
"""
import json
import logging
import re
import threading
import time

import httpx

from .config import settings
from .preprocessing import cap_context_size, select_context_for_question


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
# festival_context는 승인 콘텐츠(문서)가 아니라 혼잡·운영 이슈·공지·프로그램·ESG 같은
# 실시간 운영 데이터 스냅샷이다. 문서 인용이 아니라 수치·상태를 있는 그대로 전달해야 한다.
FESTIVAL_CONTEXT_INSTRUCTION = (
    "당신은 지역축제 방문객 안내 도우미입니다. 아래 festival_context에 들어 있는 검증된 운영 "
    "데이터만 사용해 방문객 질문에 자연스러운 한국어로 답하세요.\n"
    "규칙:\n"
    "- festival_context에 있는 사실만 답하고, 수치나 시각을 새로 만들거나 추측하지 마세요.\n"
    "- 여러 시점의 혼잡 데이터가 있으면 가장 최신 값과 추세(trend)를 함께 언급하세요.\n"
    "- 안전/운영 질문에는 해결되지 않은(unresolved) 이슈를 우선 사용하세요.\n"
    "- 일정 질문에는 변경 이력이 있으면 변경된 시각을 사용하세요.\n"
    "- ESG 질문에는 현재값(current)과 목표(target)를 함께 비교해 답하세요.\n"
    "- 시설 질문에는 실제 facilities 목록에 있는 곳만 안내하세요.\n"
    "- 질문에 답할 근거가 festival_context에 없으면 모른다고 말하고 현장 안내데스크 이용을 "
    "권하세요. 개인정보, 원본 DB 행, 내부 식별자는 언급하지 마세요."
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


def answer_with_festival_context(question: str, festival_context: dict) -> str | None:
    """혼잡·운영 이슈·공지·프로그램·ESG 같은 실시간 운영 데이터로 방문객 질문에 답한다.

    grounded_answer()(승인 콘텐츠 검색 결과)와 목적이 다르다 — 이쪽은 "지금 어디가
    혼잡해?"처럼 문서가 아니라 실시간 운영 데이터가 있어야 답할 수 있는 질문을 위한
    것이다. briefing()의 회로 차단기는 일부러 공유하지 않는다 — 방문객 질문은 요청마다
    다르고 관리자 브리핑과 실패 원인을 같은 카운터로 묶을 이유가 없다. ENABLE_EXTERNAL_AI
    조건과 예외 처리 범위, 그리고 ask()가 제공하는 잠금·상태 초기화는 그대로 물려받는다.
    """
    if not settings.external_ai_enabled:
        return None
    try:
        # Alan 질문 API는 GET 쿼리스트링으로 content를 보낸다(ask()/request() 참고) — 이
        # 프로젝트가 쓰는 Alan 프록시(kdt-api-function)는 POST JSON body를 지원하지 않는다
        # (실측: 같은 엔드포인트에 POST하면 404). festival_context 전체(~4.7KB)를 그대로
        # 실으면 URL이 너무 길어져 Alan이 414(URI Too Long)로 거부한다(실제 재현 확인).
        # 그래서 전송 방식을 바꾸는 대신 질문에 맞는 카테고리만 골라 크기를 줄인다.
        narrowed = select_context_for_question(question, festival_context)
        narrowed = cap_context_size(narrowed)
        content = json.dumps(narrowed, ensure_ascii=False, default=str, sort_keys=True)
        return ask_festival_context(question, content)
    # TypeError/AttributeError도 함께 잡는다 — festival_context가 예상한 dict 모양이 아닌
    # 경우(현재 유일한 호출부인 build_festival_context() 결과라면 일어나지 않지만, 이
    # 함수는 공개 헬퍼라 다른 호출부가 생기면 방어가 필요하다) 라우트까지 예외가 새어
    # 나가 500이 되면 안 되고, 다른 실패와 똑같이 조용히 기존 fallback 경로로 넘어가야 한다.
    except (AIUnavailable, httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        logger.warning("외부 AI 축제 컨텍스트 답변 실패, 기존 fallback 경로를 사용합니다: %s", error)
        return None


def ask_festival_context(question: str, context_json: str) -> str:
    return one_sentence(ask(
        f"{FESTIVAL_CONTEXT_INSTRUCTION}\n\n방문객 질문:\n{question}\n\nfestival_context:\n{context_json}"
    ))


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
