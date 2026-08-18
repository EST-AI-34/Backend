import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from .errors import bad_request, unprocessable
from .preprocessing import recommendation_exposure_items


# facility_type은 자유 텍스트 컬럼이라 고정된 값 집합이 없다. 안전 관련 키워드가 이름에
# 있으면 이름순보다 먼저 노출한다 — 공개(public.py)·운영자(admin_core.py) 목록 둘 다 이 순서를 쓴다.
# f-string으로 그대로 SQL에 넣는 상수라 컬럼 참조(column)에 사용자 입력이 들어가면 안 된다.
def safety_facility_order(column: str = "facility_type") -> str:
    keywords = ("MEDICAL", "SAFETY", "FIRST_AID", "FIRSTAID", "AED", "EMERGENCY", "SECURITY")
    # 두 호출부 모두 이 문자열을 파라미터 바인딩이 있는 쿼리에 f-string으로 끼워 넣는다.
    # psycopg는 실행 전에 SQL 전체에서 %-플레이스홀더를 찾는데, ILIKE 패턴의 리터럴 %가
    # %M/%S/%F 같은 잘못된 플레이스홀더로 오인돼 "only '%s','%b','%t' are allowed..."로
    # 죽는다(실제 재현됨: /public/.../facilities 500). %%로 이스케이프해 리터럴 %로 남긴다.
    array = ",".join(f"'%%{keyword}%%'" for keyword in keywords)
    return f"CASE WHEN {column} ILIKE ANY(ARRAY[{array}]) THEN 0 ELSE 1 END"


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


# 방문객 셀프 취소 마감. 화면(방문객·운영자)이 "시작 30분 전까지"라고 고지해 왔는데 서버에는
# 검사가 없어서 시작 직전은 물론 시작 뒤에도 취소가 됐다. 고지한 규칙을 여기서 강제한다.
BOOKING_CANCEL_DEADLINE_MINUTES = 30


def validate_booking_cancel_window(starts_at, now=None) -> None:
    now = now or datetime.now(UTC)
    if starts_at - timedelta(minutes=BOOKING_CANCEL_DEADLINE_MINUTES) <= now:
        raise bad_request("CANCEL_WINDOW_CLOSED",
                          f"시작 {BOOKING_CANCEL_DEADLINE_MINUTES}분 전까지만 직접 취소할 수 있습니다. 현장 운영자에게 문의해 주세요.")


def validate_content_review(version: dict, reviewer_id: str, decision: str) -> None:
    if version["status"] != "IN_REVIEW":
        raise bad_request("INVALID_STATE_TRANSITION", "검수 중인 버전만 승인 또는 반려할 수 있습니다.")
    # 공지는 현장에서 즉시 나가야 하므로 작성자 자가 승인을 허용한다(감사 로그로 추적).
    if decision == "APPROVED" and str(version["author_id"]) == reviewer_id and version.get("content_type") != "ANNOUNCEMENT":
        raise unprocessable("AUTHOR_CANNOT_FINAL_APPROVE", "작성자는 자신의 콘텐츠를 최종 승인할 수 없습니다.")


def validate_measurement_review(measurement: dict, evidence_count: int, decision: str) -> None:
    if measurement["status"] not in {"DRAFT", "IN_REVIEW"}:
        raise bad_request("INVALID_STATE_TRANSITION", "승인 대기 실적만 검토할 수 있습니다.")
    requirements = measurement.get("source_requirements") or {}
    if decision == "APPROVED" and (not measurement.get("formula") or not measurement.get("unit") or not requirements):
        raise unprocessable("METRIC_DEFINITION_INCOMPLETE", "산식·단위·출처 요건이 완성된 지표만 승인할 수 있습니다.")
    if decision == "APPROVED" and measurement.get("evidence_required") and evidence_count == 0:
        raise unprocessable("EVIDENCE_REQUIRED", "필수 증빙을 연결해야 합니다.")


# 자격증명·개인식별정보·시스템 내부 정보 요청을 막는다. 공백과 구분자를 제거한 문자열에
# 대고 보므로 "p a s s w o r d", "시스템-프롬프트" 같은 단순 우회는 걸린다.
UNSAFE_TERMS = (
    "비밀번호", "패스워드", "password", "passwd", "credential", "자격증명",
    "apikey", "api키", "accesstoken", "액세스토큰", "refreshtoken", "리프레시토큰",
    "secretkey", "시크릿키", "privatekey", "개인키", "jwt", "환경변수", "envvar",
    "주민등록번호", "주민번호", "여권번호", "운전면허번호", "socialsecurity", "ssn",
    "카드번호", "계좌번호", "cardnumber", "creditcard",
    "시스템프롬프트", "systemprompt", "developermessage", "이전지시무시",
    "ignorepreviousinstructions", "ignoreallprevious", "disregardprevious",
)

# 개인정보로 취급하는 패턴. mask_sensitive와 위험 질문 판정이 같은 규칙을 쓴다.
SENSITIVE_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[이메일 마스킹]"),
    # 주민등록번호: 생년월일 6자리 + 성별코드(1-4,5-8) + 6자리
    (re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)"), "[주민등록번호 마스킹]"),
    # 카드번호: 13~16자리(4자리 묶음 구분자 허용)
    (re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)"), "[카드번호 마스킹]"),
    # 휴대폰
    (re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)"), "[연락처 마스킹]"),
    # 유선전화: 02 또는 03x~06x 지역번호
    (re.compile(r"(?<!\d)(?:02|0[3-6]\d)[- ]?\d{3,4}[- ]?\d{4}(?!\d)"), "[연락처 마스킹]"),
)


def is_safe_question(message: str) -> bool:
    """차단 대상이면 False.

    예전 구현은 키워드 6개를 원문에 그대로 대조해서 대소문자·띄어쓰기만 바꿔도 통과했다.
    지금은 영문 소문자화 + 공백/구분자 제거 후 비교하고, 개인정보 패턴이 질문 본문에
    직접 들어 있는 경우도 막는다.
    """
    normalized = re.sub(r"[\s\-_.·]+", "", message.lower())
    if any(term in normalized for term in UNSAFE_TERMS):
        return False
    return not any(pattern.search(message) for pattern, _ in SENSITIVE_PATTERNS)


# 한국어 조사. 검색이 토큰 통째로 ILIKE라 "화장실이"가 본문의 "화장실은"과 안 맞았다.
# 긴 것부터 떼어낸다("에서는"을 "는"보다 먼저 봐야 한다).
JOSA = ("에서는", "에게는", "으로는", "이라는", "에서", "에게", "한테", "으로", "이나", "까지",
        "부터", "보다", "라도", "이라", "은", "는", "이", "가", "을", "를", "에", "와", "과",
        "도", "만", "의", "로")

# 방문객이 실제로 쓰는 구어체를 승인 콘텐츠의 표현으로 잇는다. 범용 형태소 분석기보다
# 축제 안내에서 자주 실패한 표현만 명시하는 편이 결과와 운영 범위를 예측하기 쉽다.
QUERY_ALIASES = {
    "밥": ("먹거리", "음식"),
    "먹어": ("먹거리", "음식"),
    "먹을": ("먹거리", "음식"),
    "차 가져": ("주차", "자가용"),
    "자동차": ("주차", "자가용"),
    "몇 시": ("운영 시간",),
    "몇시": ("운영 시간",),
    "언제 열": ("운영 시간",),
    "돈 내": ("입장료", "무료"),
    "무료야": ("입장료", "무료"),
    "행사": ("프로그램", "체험"),
    "애완": ("반려동물",),
    "멍멍이": ("반려동물", "강아지"),
    "비 오": ("우천", "비"),
    "비오": ("우천", "비"),
    "더워": ("폭염", "그늘막", "식수대"),
    "다쳤": ("응급", "의료"),
}


def without_josa(term: str) -> str:
    """조사를 뗀 어간. 뗄 게 없거나 남는 글자가 1자면 원본 그대로."""
    for josa in JOSA:
        if term.endswith(josa) and len(term) - len(josa) >= 2:
            return term[: -len(josa)]
    return term


def search_terms(text: str) -> list[str]:
    terms = [term for term in re.split(r"[^\w가-힣]+", text.lower()) if len(term) >= 2][:8]
    # 어간을 원본과 함께 넘긴다(OR 검색이라 원본이 맞던 문서는 계속 맞는다).
    variants = [variant for term in terms for variant in (term, without_josa(term))]
    lowered = text.lower()
    variants.extend(alias for phrase, aliases in QUERY_ALIASES.items() if phrase in lowered for alias in aliases)
    return list(dict.fromkeys(variants))


def supported_language(requested: str | None, supported: list[str], default: str) -> str:
    language = (requested or default).lower().split("-")[0]
    return language if language in supported else default


def select_course(sessions: list[dict], duration_min: int, starts_at=None) -> list[dict]:
    """겹치지 않는 회차를 요청한 소요 시간 안에서 고른다.

    starts_at을 생략하면 예전에는 deadline이 None이 되어 duration_min이 통째로 무시됐다
    (60분을 요청해도 후보 50개가 전부 코스에 들어갔다). 기준 시각이 없으면 첫 회차의
    시작 시각을 기준으로 삼는다.
    """
    if not sessions:
        return []
    cursor = starts_at or min(session["starts_at"] for session in sessions)
    deadline = cursor + timedelta(minutes=duration_min)
    selected: list[dict] = []
    used_programs: set = set()
    for session in sessions:
        if session["starts_at"] < cursor or session["ends_at"] > deadline:
            continue
        # 같은 프로그램의 다른 회차를 두 번 넣으면 코스가 아니라 중복 안내가 된다.
        program_id = session.get("program_id")
        if program_id is not None and program_id in used_programs:
            continue
        selected.append(session)
        used_programs.add(program_id)
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
    """운영 문서 발췌에서 개인정보를 가린다.

    순서가 중요하다 — 주민등록번호(13자리)를 카드번호 규칙보다 먼저 잡아야
    "[카드번호 마스킹]"으로 잘못 표시되지 않는다. SENSITIVE_PATTERNS가 그 순서다.
    """
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


RISK_ACTIONS = {
    "crowding": "혼잡 구역에 안전 인력을 추가하고 우회 동선을 안내해 주세요.",
    "safety_incidents": "진행 중인 안전 사고를 우선 처리해 주세요.",
    "unresolved_safety_complaints": "미해결 안전 민원을 처리한 뒤 위험도를 낮춰 주세요.",
    "staffing_gap": "예비 인력을 해당 구역에 재배치해 주세요.",
    "schedule_change": "변경된 일정을 현장 담당자와 확인한 뒤 방문객 공지를 게시해 주세요.",
    "abnormal_crowd_surge": "급증 구역에 즉시 안전 인력을 배치하고 우회·대기 안내를 방문객에게 보내 주세요.",
}

# BUSY/FULL 비율은 "지금 얼마나 찼는가"만 본다. 짧은 시간에 급격히 찬 것(비정상 급증)은
# 놓친다 — 절대 비율이 임계값 밑이어도 짧은 시간에 여러 단계 뛰면 그 자체로 위험 신호다.
ABNORMAL_SURGE_TYPE = "abnormal_crowd_surge"


# 신호 종류별 (임계값 초과 점수, 이하 점수). schedule_change는 발생 자체가 신호라 같은 값을 준다.
RISK_POINTS = {
    "safety_incidents": (35, 15),
    "unresolved_safety_complaints": (30, 15),
    "staffing_gap": (25, 10),
    "schedule_change": (20, 20),
    ABNORMAL_SURGE_TYPE: (40, 20),
}


def risk_points(signal: dict) -> int:
    """crowding은 혼잡 구역 비율(0-100), abnormal_crowd_surge는 급증 구역 수, 나머지는 건수 기준이다."""
    value, threshold = float(signal["value"]), float(signal.get("threshold") or 0)
    # crowding만 3단계다 — 90% 이상은 임계값과 무관하게 최고점.
    if signal["type"] == "crowding":
        return 45 if value >= 90 else 30 if value >= threshold else 10
    over, under = RISK_POINTS.get(signal["type"], (10, 10))
    return over if value > threshold else under


def risk_alerts(signals: list[dict]) -> list[str]:
    """즉시 통보가 필요한 신호만 별도로 뽑는다. BUSY/FULL 비율 임계값 초과는 evidence/reasons로
    충분히 보이지만, 비정상 급증은 조용히 묻히면 안 되는 신호라 alerts로 분리한다."""
    return [
        f"{signal.get('area_name') or signal.get('area_id') or '구역 미상'} 구역: "
        f"{signal.get('window_minutes', 10)}분 내 혼잡도가 {int(signal['value'])}단계 급증했습니다."
        for signal in signals if signal["type"] == ABNORMAL_SURGE_TYPE
    ]


def risk_brief(signals: list[dict]) -> dict:
    """검증된 운영 신호만으로 위험도를 계산한다. 신호가 없으면 추정하지 않는다."""
    if not signals:
        return {
            "risk_level": "INSUFFICIENT_DATA", "risk_score": 0, "evidence": [], "alerts": [],
            "summary": "위험도를 판단할 만한 운영 데이터가 없습니다.",
            "reasons": ["혼잡·민원·일정·인력 신호가 수집되지 않았습니다."],
            "recommended_actions": ["현장 보고와 운영 기록을 갱신한 뒤 다시 확인해 주세요."],
            "operator_notes": ["규칙 기반 결과이며, 공지 전 현장 확인이 필요합니다."],
            "policy_version": "risk-v1",
        }
    score = min(100, sum(risk_points(signal) for signal in signals))
    level = "CRITICAL" if score >= 75 else "WARNING" if score >= 40 else "NORMAL"
    types = {signal["type"] for signal in signals}
    return {
        "risk_level": level, "risk_score": score, "evidence": signals, "alerts": risk_alerts(signals),
        "summary": f"검증된 신호 {', '.join(sorted(types))} 기준 위험도는 {level}(점수 {score})입니다.",
        "reasons": [f"{signal['type']} 값 {signal['value']}을(를) 임계값 {signal.get('threshold')}과(와) 비교했습니다." for signal in signals],
        "recommended_actions": [RISK_ACTIONS[name] for name in sorted(types) if name in RISK_ACTIONS] or ["운영 신호를 계속 관찰해 주세요."],
        "operator_notes": ["규칙 기반 결과이며, 공지 전 현장 확인이 필요합니다."],
        "policy_version": "risk-v1",
    }


def distance_meters(lat1, lon1, lat2, lon2) -> int | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    hav = math.sin(math.radians(float(lat2) - float(lat1)) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(float(lon2) - float(lon1)) / 2) ** 2
    return round(6371000 * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav)))


def score_business(business: dict, latitude=None, longitude=None, category: str | None = None) -> dict:
    score, reasons = 0.25, ["영업 중인 승인 업체입니다."]
    if category and business["category"] == category:
        score += 0.25
        reasons.append("요청한 업종과 일치합니다.")
    if business.get("coupon_available"):
        score += 0.15
        reasons.append("사용 가능한 쿠폰이 있습니다.")
    if business.get("esg_participating"):
        score += 0.10
        reasons.append("ESG·지역상생 프로그램 참여 업체입니다.")
    distance = distance_meters(latitude, longitude, business.get("latitude"), business.get("longitude"))
    if distance is not None and distance < 1000:
        score += 0.25 * (1 - distance / 1000)
        reasons.append(f"현재 위치에서 약 {distance}m 거리입니다.")
    return {
        "business_id": str(business["id"]), "name": business["name"], "category": business["category"],
        "score": round(min(score, 1.0), 2), "reasons": reasons,
        "is_sponsored": bool(business.get("is_sponsored")), "distance_meters": distance,
        "area_id": str(business["area_id"]) if business.get("area_id") else None,
        "area_name": business.get("area_name"),
    }


def recommendation_bias(events: list[dict], max_business_share: float = 0.6, max_category_share: float = 0.75) -> dict:
    """추천 노출이 특정 업체·업종에 쏠렸는지 점검한다. 광고 노출도 함께 집계한다."""
    businesses: Counter[str] = Counter()
    sponsored: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    labels: dict[str, dict] = {}
    # 추천 편향 전처리 회귀 방지: response_snapshot이 dict가 아니거나(방어적 스키마 변화),
    # item이 dict가 아니거나 business_id가 공백뿐인 경우까지 recommendation_exposure_items가
    # 한곳에서 걸러준다. 여기서 다시 인라인으로 파싱하면 그 방어가 새는 경로가 생긴다.
    for item in recommendation_exposure_items(events):
        business_id = item["business_id"]
        businesses[business_id] += 1
        categories[str(item["category"])] += 1
        labels[business_id] = {"name": item["name"], "category": item["category"]}
        if item["is_sponsored"]:
            sponsored[business_id] += 1
    total = sum(businesses.values())
    share = (lambda count: round(count / total, 4)) if total else (lambda count: 0.0)
    business_rows = [
        {"business_id": business_id, **labels[business_id], "total_exposures": count,
         "sponsored_exposures": sponsored[business_id], "exposure_share": share(count),
         "is_over_threshold": share(count) > max_business_share}
        for business_id, count in businesses.most_common()
    ]
    category_rows = [
        {"category": name, "total_exposures": count, "exposure_share": share(count),
         "is_over_threshold": share(count) > max_category_share}
        for name, count in categories.most_common()
    ]
    over = [row for row in business_rows + category_rows if row["is_over_threshold"]]
    if not total:
        status, summary, actions = "INSUFFICIENT_DATA", "편향을 판단할 추천 노출 기록이 없습니다.", ["추천 트래픽이 쌓인 뒤 다시 점검해 주세요."]
    elif over:
        status, summary, actions = "WARNING", "일부 업체 또는 업종의 노출이 임계값을 넘었습니다.", ["임계값을 넘은 대상의 노출 사유를 확인하고 필요하면 노출 순환 정책을 조정해 주세요."]
    else:
        status, summary, actions = "PASS", "임계값을 넘는 노출 쏠림이 없습니다.", ["주간 편향 점검을 계속 유지해 주세요."]
    return {
        "status": status, "summary": summary, "checked_event_count": len(events),
        "total_exposures": total, "sponsored_exposures": sum(sponsored.values()),
        "business_exposures": business_rows, "category_exposures": category_rows,
        "thresholds": {"max_business_exposure_share": max_business_share, "max_category_exposure_share": max_category_share},
        "recommended_actions": actions,
    }
