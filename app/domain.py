import re
from datetime import timedelta

from .errors import bad_request, unprocessable


TICKET_TRANSITIONS = {
    "OPEN": ["ASSIGNED"],
    "ASSIGNED": ["IN_PROGRESS"],
    "IN_PROGRESS": ["RESOLVED"],
    "RESOLVED": ["CLOSED", "IN_PROGRESS"],
    "CLOSED": [],
}

BOOKING_TRANSITIONS = {
    "WAITING": {"CALLED", "CANCELLED"},
    "CALLED": {"COMPLETED", "NO_SHOW", "CANCELLED"},
    "CONFIRMED": {"COMPLETED", "NO_SHOW", "CANCELLED"},
    "CANCELLED": set(),
    "NO_SHOW": set(),
    "COMPLETED": set(),
}


def validate_ticket_transition(current: str, target: str, note: str | None = None) -> None:
    if target not in TICKET_TRANSITIONS.get(current, []):
        raise bad_request("INVALID_STATE_TRANSITION", f"{current}에서 {target}(으)로 전이할 수 없습니다.")
    if target == "CLOSED" and not (note or "").strip():
        raise bad_request("CLOSE_REASON_REQUIRED", "완료 사유가 필요합니다.")
    if current == "RESOLVED" and target == "IN_PROGRESS" and not (note or "").strip():
        raise bad_request("REOPEN_REASON_REQUIRED", "재처리 사유가 필요합니다.")


def validate_booking_transition(current: str, target: str) -> None:
    if target not in BOOKING_TRANSITIONS.get(current, set()):
        raise bad_request("INVALID_STATE_TRANSITION", f"{current}에서 {target}(으)로 전이할 수 없습니다.")


def validate_content_review(version: dict, reviewer_id: str, decision: str) -> None:
    if version["status"] != "IN_REVIEW":
        raise bad_request("INVALID_STATE_TRANSITION", "검수 중인 버전만 승인 또는 반려할 수 있습니다.")
    if decision == "APPROVED" and str(version["author_id"]) == reviewer_id:
        raise unprocessable("AUTHOR_CANNOT_FINAL_APPROVE", "작성자는 자신의 콘텐츠를 최종 승인할 수 없습니다.")


def validate_measurement_review(measurement: dict, evidence_count: int, decision: str) -> None:
    if measurement["status"] not in {"DRAFT", "IN_REVIEW"}:
        raise bad_request("INVALID_STATE_TRANSITION", "승인 대기 실적만 검토할 수 있습니다.")
    requirements = measurement.get("source_requirements") or {}
    if decision == "APPROVED" and (not measurement.get("formula") or not measurement.get("unit") or not requirements):
        raise unprocessable("METRIC_DEFINITION_INCOMPLETE", "산식·단위·출처 요건이 완성된 지표만 승인할 수 있습니다.")
    if decision == "APPROVED" and measurement.get("evidence_required") and evidence_count == 0:
        raise unprocessable("EVIDENCE_REQUIRED", "필수 증빙을 연결해야 합니다.")


def is_safe_question(message: str) -> bool:
    lowered = message.lower()
    return not any(term in lowered for term in ("비밀번호", "password", "주민등록번호", "social security", "시스템 프롬프트", "system prompt"))


def search_terms(text: str) -> list[str]:
    return list(dict.fromkeys(term for term in re.split(r"[^\w가-힣]+", text.lower()) if len(term) >= 2))[:8]


def supported_language(requested: str | None, supported: list[str], default: str) -> str:
    language = (requested or default).lower().split("-")[0]
    return language if language in supported else default


def select_course(sessions: list[dict], duration_min: int, starts_at=None) -> list[dict]:
    selected: list[dict] = []
    cursor = starts_at
    deadline = starts_at + timedelta(minutes=duration_min) if starts_at else None
    for session in sessions:
        if cursor and session["starts_at"] < cursor:
            continue
        if deadline and session["ends_at"] > deadline:
            continue
        selected.append(session)
        cursor = session["ends_at"]
    return selected


def classify_issue(text: str, priority: str = "NORMAL") -> dict:
    lowered = text.lower()
    topics = {
        "SAFETY": ("사고", "위험", "다침", "미끄", "화재", "응급"),
        "CROWD": ("혼잡", "대기", "줄", "붐비"),
        "FACILITY": ("화장실", "시설", "수유", "주차", "그늘"),
        "GUIDANCE": ("안내", "표지", "길", "위치"),
    }
    topic = next((name for name, terms in topics.items() if any(term in lowered for term in terms)), "OTHER")
    negative = any(term in lowered for term in ("불편", "부족", "고장", "사고", "위험", "불만"))
    urgent = priority == "EMERGENCY" or topic == "SAFETY"
    return {"topic": topic, "sentiment": "NEGATIVE" if negative else "NEUTRAL", "urgent": urgent}


def mask_sensitive(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일 마스킹]", text)
    return re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[연락처 마스킹]", text)
