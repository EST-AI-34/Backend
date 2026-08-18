import json
from datetime import UTC, datetime
from decimal import Decimal


FESTIVAL_CONTEXT_VERSION = "festival-context-v1"
RECENT_HOURS = 24
CROWD_LEVEL_RANK = {"QUIET": 0, "MODERATE": 1, "BUSY": 2, "FULL": 3}


def recommendation_exposure_items(events: list[dict]) -> list[dict]:
    """Flatten recommendation response snapshots into exposure rows.

    The recommendation event table stores an API response snapshot. Bias checks
    should not care whether an exposure came from `items` or `sponsored_items`;
    this helper normalizes both lists and drops malformed entries.
    """
    exposures: list[dict] = []
    for event in events:
        response = event.get("response_snapshot") or {}
        if not isinstance(response, dict):
            continue
        for group_name in ("items", "sponsored_items"):
            items = response.get(group_name) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                business_id = str(item.get("business_id") or "").strip()
                if not business_id:
                    continue
                exposures.append({
                    "business_id": business_id,
                    "name": item.get("name") or business_id,
                    "category": item.get("category") or "UNKNOWN",
                    "is_sponsored": bool(item.get("is_sponsored") or group_name == "sponsored_items"),
                })
    return exposures


def build_festival_context(rows: dict, now: datetime | None = None) -> dict:
    """Normalize selected DB rows into the small context sent to Alan."""
    now = now or datetime.now(UTC)
    quality: list[dict] = []
    festival = rows.get("festival") or {}
    context = {
        "version": FESTIVAL_CONTEXT_VERSION,
        "generated_at": iso(now),
        "festival": {
            "id": safe_str(festival.get("id")),
            "code": safe_str(festival.get("code")),
            "name": safe_str(festival.get("name")),
            "timezone": safe_str(festival.get("timezone")),
            "status": safe_str(festival.get("status")),
        },
        "congestion": normalize_congestion(
            rows.get("congestion_samples") or rows.get("crowd_snapshots") or [],
            rows.get("congestion_recent") or [], now, quality,
        ),
        "visitor_count": normalize_visitor_counts(rows.get("visitor_count_samples") or [], quality),
        "ops_tickets": normalize_ops_tickets(rows.get("ops_tickets") or [], now, quality),
        "announcements": normalize_announcements(rows.get("announcements") or [], now, quality),
        "esg_measurements": normalize_esg_measurements(rows.get("esg_measurements") or [], now, quality),
        "programs": normalize_programs(rows.get("programs") or [], now, quality),
        "facilities": normalize_facilities(rows.get("facilities") or [], quality),
        "data_quality": quality,
    }
    timestamps = source_timestamps(context)
    context["source_updated_at"] = max(timestamps) if timestamps else None
    return context


def normalize_congestion(samples: list[dict], recent_samples: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    trend_by_area = congestion_trend_by_area(recent_samples)
    items = []
    for sample in samples[:20]:
        captured_at = as_datetime(sample.get("captured_at"))
        expires_at = as_datetime(sample.get("expires_at"))
        if not captured_at or (expires_at and expires_at <= now):
            quality.append({"source": "congestion", "issue": "stale_or_malformed_sample"})
            continue
        area_id = safe_str(sample.get("area_id"))
        items.append({
            "area_id": area_id,
            "area_name": safe_str(sample.get("area_name")),
            "crowd_level": enum_value(sample.get("crowd_level"), {"QUIET", "MODERATE", "BUSY", "FULL"}, "UNKNOWN"),
            "people_count": safe_int(sample.get("people_count")),
            "estimated_wait_min": safe_int(sample.get("estimated_wait_min")),
            "source_type": safe_str(sample.get("source_type")),
            "captured_at": iso(captured_at),
            "expires_at": iso(expires_at),
            # 최신 스냅샷 한 건만으로는 "지금 원래 이 정도"인지 "방금 급증"인지 구분할 수
            # 없다. 같은 구역의 최근 스냅샷들을 비교해 방문객 질문("괜찮아?")에 답할 수 있는
            # 최소한의 추세를 덧붙인다.
            "trend": trend_by_area.get(area_id, "insufficient_data"),
        })
    if not items:
        quality.append({"source": "congestion", "issue": "empty_result"})
    return items


def congestion_trend_by_area(recent_samples: list[dict]) -> dict[str, str]:
    by_area: dict[str, list[dict]] = {}
    for sample in recent_samples:
        area_id = safe_str(sample.get("area_id"))
        captured_at = as_datetime(sample.get("captured_at"))
        if not area_id or not captured_at:
            continue
        by_area.setdefault(area_id, []).append({
            "captured_at": captured_at,
            "people_count": safe_int(sample.get("people_count")),
            "crowd_level": enum_value(sample.get("crowd_level"), {"QUIET", "MODERATE", "BUSY", "FULL"}, "UNKNOWN"),
        })
    trends: dict[str, str] = {}
    for area_id, points in by_area.items():
        points.sort(key=lambda point: point["captured_at"])
        trends[area_id] = trend_from_points(points)
    return trends


def trend_from_points(points: list[dict]) -> str:
    if len(points) < 2:
        return "insufficient_data"
    first, last = points[0], points[-1]
    if first["people_count"] is not None and last["people_count"] is not None and first["people_count"] > 0:
        change = (last["people_count"] - first["people_count"]) / first["people_count"]
        if change >= 0.5:
            return "rapidly_increasing"
        if change >= 0.15:
            return "increasing"
        if change <= -0.15:
            return "decreasing"
        return "stable"
    first_rank = CROWD_LEVEL_RANK.get(first["crowd_level"])
    last_rank = CROWD_LEVEL_RANK.get(last["crowd_level"])
    if first_rank is None or last_rank is None:
        return "insufficient_data"
    if last_rank - first_rank >= 2:
        return "rapidly_increasing"
    if last_rank > first_rank:
        return "increasing"
    if last_rank < first_rank:
        return "decreasing"
    return "stable"


def normalize_visitor_counts(samples: list[dict], quality: list[dict]) -> dict:
    sample = samples[0] if samples else {}
    result = {
        "active_sessions": safe_int(sample.get("active_sessions"), 0),
        "created_last_24h": safe_int(sample.get("created_last_24h"), 0),
        "ended_last_24h": safe_int(sample.get("ended_last_24h"), 0),
        "sampled_at": iso(as_datetime(sample.get("sampled_at"))),
    }
    if not samples:
        quality.append({"source": "visitor_count", "issue": "empty_result"})
    return result


def normalize_ops_tickets(rows: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    items = []
    for row in rows[:20]:
        updated_at = as_datetime(row.get("updated_at")) or as_datetime(row.get("created_at"))
        if not updated_at:
            quality.append({"source": "ops_tickets", "issue": "malformed_timestamp"})
            continue
        if stale(updated_at, now):
            quality.append({"source": "ops_tickets", "issue": "older_than_24h", "title": safe_str(row.get("title"))})
        items.append({
            "ticket_type": enum_value(row.get("ticket_type"), {"COMPLAINT", "INCIDENT"}, "UNKNOWN"),
            "title": safe_str(row.get("title"))[:120],
            "priority": enum_value(row.get("priority"), {"LOW", "NORMAL", "HIGH", "EMERGENCY"}, "UNKNOWN"),
            "status": enum_value(row.get("status"), {"OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED"}, "UNKNOWN"),
            "area_name": safe_str(row.get("area_name")),
            "updated_at": iso(updated_at),
        })
    if not items:
        quality.append({"source": "ops_tickets", "issue": "empty_result"})
    return items


def normalize_announcements(rows: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    items = []
    for row in rows[:10]:
        updated_at = as_datetime(row.get("updated_at")) or as_datetime(row.get("starts_at"))
        if not updated_at:
            quality.append({"source": "announcements", "issue": "malformed_timestamp"})
            continue
        status = enum_value(row.get("status"), {"DRAFT", "SCHEDULED", "ACTIVE", "CLOSED"}, "UNKNOWN")
        if status != "ACTIVE" and stale(updated_at, now):
            quality.append({"source": "announcements", "issue": "old_non_active_announcement", "title": safe_str(row.get("title"))})
        items.append({
            "title": safe_str(row.get("title"))[:120],
            "severity": enum_value(row.get("severity"), {"INFO", "WARNING", "EMERGENCY"}, "UNKNOWN"),
            "status": status,
            "starts_at": iso(as_datetime(row.get("starts_at"))),
            "ends_at": iso(as_datetime(row.get("ends_at"))),
            "updated_at": iso(updated_at),
        })
    if not items:
        quality.append({"source": "announcements", "issue": "empty_result"})
    return items


def normalize_esg_measurements(rows: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    items = []
    for row in rows[:20]:
        measured_at = as_datetime(row.get("measured_at"))
        if not measured_at:
            quality.append({"source": "esg_measurements", "issue": "malformed_timestamp"})
            continue
        if stale(measured_at, now):
            quality.append({"source": "esg_measurements", "issue": "older_than_24h", "metric": safe_str(row.get("metric_name"))})
        items.append({
            "metric_name": safe_str(row.get("metric_name")),
            "category": enum_value(row.get("category"), {"E", "S", "G"}, "UNKNOWN"),
            "value": safe_number(row.get("value")),
            "unit": safe_str(row.get("unit")),
            "target": safe_number(row.get("target")),
            "status": enum_value(row.get("status"), {"DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED"}, "UNKNOWN"),
            "measured_at": iso(measured_at),
        })
    if not items:
        quality.append({"source": "esg_measurements", "issue": "empty_result"})
    return items


def normalize_programs(rows: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    """회차(program_sessions) 단위 일정. "몇 시야?"에는 실제 시작 시각이, "일정 바뀌었어?"에는
    rescheduled 플래그가 있어야 답할 수 있다 — 프로그램 단위 요약만으로는 둘 다 안 된다."""
    items = []
    for row in rows[:15]:
        starts_at = as_datetime(row.get("starts_at"))
        if not starts_at:
            quality.append({"source": "programs", "issue": "malformed_timestamp", "title": safe_str(row.get("title"))})
            continue
        items.append({
            "slug": safe_str(row.get("slug")),
            "title": safe_str(row.get("title"))[:120],
            "category": safe_str(row.get("category")),
            "area_name": safe_str(row.get("area_name")),
            "starts_at": iso(starts_at),
            "ends_at": iso(as_datetime(row.get("ends_at"))),
            # 운영자 위험 브리프(schedule_change 신호)와 같은 기준: 등록 뒤 1분 넘게 지나
            # 수정됐으면 변경된 일정으로 본다.
            "rescheduled": bool(row.get("rescheduled")),
        })
    if not items:
        quality.append({"source": "programs", "issue": "empty_result"})
    return items


def normalize_facilities(rows: list[dict], quality: list[dict]) -> list[dict]:
    items = []
    for row in rows[:30]:
        name = safe_str(row.get("name"))
        if not name:
            continue
        items.append({
            "name": name,
            "facility_type": safe_str(row.get("facility_type")),
            "area_name": safe_str(row.get("area_name")),
        })
    if not items:
        quality.append({"source": "facilities", "issue": "empty_result"})
    return items


def source_timestamps(value) -> list[str]:
    if isinstance(value, dict):
        return [found for item in value.values() for found in source_timestamps(item)]
    if isinstance(value, list):
        return [found for item in value for found in source_timestamps(item)]
    if isinstance(value, str) and value.endswith("+00:00"):
        return [value]
    return []


def as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def iso(value: datetime | None) -> str | None:
    if not value:
        return None
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def stale(value: datetime, now: datetime) -> bool:
    return (now - value.astimezone(UTC)).total_seconds() > RECENT_HOURS * 3600


def safe_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def safe_int(value, default=None) -> int | None:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def safe_number(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enum_value(value, allowed: set[str], default: str) -> str:
    text = safe_str(value)
    return text if text in allowed else default


# Alan 질문 API는 GET 쿼리스트링으로 content를 보낸다(app/ai.py의 request()). festival_context
# 전체(카테고리 6개, ~4.7KB)를 그대로 실으면 URL이 길어져 Alan이 414(URI Too Long)로 거부한다
# (실제 재현 확인). 근본 대응은 질문 의도에 맞는 카테고리만 골라 보내는 것이다 — LLM을 한 번
# 더 불러 의도를 분류하지 않고 키워드 규칙으로 충분히 가른다.
CONTEXT_CATEGORY_KEYWORDS = {
    "congestion": ("혼잡", "붐비", "북적", "사람 많", "괜찮"),
    "ops_tickets": ("안전", "위험", "사고", "문제", "이슈"),
    "programs": ("퍼레이드", "공연", "프로그램", "일정", "몇 시", "시간", "변경"),
    # "알려줘"는 거의 모든 질문에 붙는 범용 어미라 넣지 않는다 — 넣으면 다른 카테고리
    # 질문에도 announcements가 항상 딸려 붙어 크기 축소 효과가 옅어진다.
    "announcements": ("공지", "안내사항"),
    "esg_measurements": ("esg", "다회용기", "재사용", "재활용", "대중교통", "목표"),
    "facilities": ("화장실", "시설", "안내소", "의무실", "휴게"),
}
# 매칭되는 키워드가 하나도 없을 때 쓰는 최소 핵심 카테고리 — 안전·혼잡·공지는 대부분의
# 방문객 질문에 공통으로 유용하고, 나머지(ESG·시설·프로그램)보다 우선순위가 높다.
SAFE_CORE_CATEGORIES = ("congestion", "ops_tickets", "announcements")
CONTEXT_LIST_KEYS = ("congestion", "ops_tickets", "announcements", "esg_measurements", "programs", "facilities")

# GET URL 길이 상한에 맞춘 안전 마진. instruction·질문 문자열까지 포함해 URL 인코딩되므로
# festival_context 자체는 이보다 더 작게 유지해야 한다.
MAX_ALAN_CONTEXT_CHARS = 2000


def select_context_for_question(question: str, context: dict) -> dict:
    """질문과 관련된 카테고리만 채우고 나머지는 빈 리스트로 비운 festival_context를 만든다.

    키(key) 자체는 항상 유지한다 — Alan에게 주는 스키마가 질문마다 흔들리지 않게 하기
    위해서다. 매칭되는 카테고리가 없으면 SAFE_CORE_CATEGORIES로 대체한다.
    """
    normalized = (question or "").lower()
    selected = {
        category for category, keywords in CONTEXT_CATEGORY_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    }
    if not selected:
        selected = set(SAFE_CORE_CATEGORIES)

    narrowed = dict(context)
    for key in CONTEXT_LIST_KEYS:
        narrowed[key] = context.get(key, []) if key in selected else []
    return narrowed


def cap_context_size(context: dict, max_chars: int = MAX_ALAN_CONTEXT_CHARS) -> dict:
    """선택된 카테고리를 담아도 너무 크면 각 리스트를 앞에서부터 남기고 뒤를 줄인다.

    각 카테고리 리스트는 DB 조회 단계(context_repository.py)에서 이미 최신·우선순위
    순으로 정렬돼 나오므로, 앞쪽만 남기는 것 자체가 "가장 중요한 항목 우선"이다.
    문자열을 중간에서 자르지 않는다 — 항목 단위로만 줄여 JSON이 항상 유효하게 유지된다.
    리스트를 전부 비워도 여전히 넘치면(메타 필드 자체가 큰 경우) 더 줄일 게 없으므로
    그 상태로 반환한다 — 어느 경우든 마지막으로 만든 상태를 항상 크기 검사한 뒤 돌려준다.
    """
    capped = dict(context)
    limit = max((len(capped.get(key) or []) for key in CONTEXT_LIST_KEYS), default=0)
    while True:
        content = json.dumps(capped, ensure_ascii=False, default=str, sort_keys=True)
        if len(content) <= max_chars or limit <= 0:
            return capped
        limit -= 1
        for key in CONTEXT_LIST_KEYS:
            values = capped.get(key) or []
            if len(values) > limit:
                capped[key] = values[:limit]
