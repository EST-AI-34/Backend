from datetime import UTC, datetime
from decimal import Decimal


FESTIVAL_CONTEXT_VERSION = "festival-context-v1"
RECENT_HOURS = 24


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
        "congestion": normalize_congestion(rows.get("congestion_samples") or rows.get("crowd_snapshots") or [], now, quality),
        "visitor_count": normalize_visitor_counts(rows.get("visitor_count_samples") or [], quality),
        "ops_tickets": normalize_ops_tickets(rows.get("ops_tickets") or [], now, quality),
        "announcements": normalize_announcements(rows.get("announcements") or [], now, quality),
        "esg_measurements": normalize_esg_measurements(rows.get("esg_measurements") or [], now, quality),
        "programs": normalize_programs(rows.get("programs") or [], now, quality),
        "data_quality": quality,
    }
    timestamps = source_timestamps(context)
    context["source_updated_at"] = max(timestamps) if timestamps else None
    return context


def normalize_congestion(samples: list[dict], now: datetime, quality: list[dict]) -> list[dict]:
    items = []
    for sample in samples[:20]:
        captured_at = as_datetime(sample.get("captured_at"))
        expires_at = as_datetime(sample.get("expires_at"))
        if not captured_at or (expires_at and expires_at <= now):
            quality.append({"source": "congestion", "issue": "stale_or_malformed_sample"})
            continue
        items.append({
            "area_id": safe_str(sample.get("area_id")),
            "area_name": safe_str(sample.get("area_name")),
            "crowd_level": enum_value(sample.get("crowd_level"), {"QUIET", "MODERATE", "BUSY", "FULL"}, "UNKNOWN"),
            "people_count": safe_int(sample.get("people_count")),
            "estimated_wait_min": safe_int(sample.get("estimated_wait_min")),
            "source_type": safe_str(sample.get("source_type")),
            "captured_at": iso(captured_at),
            "expires_at": iso(expires_at),
        })
    if not items:
        quality.append({"source": "congestion", "issue": "empty_result"})
    return items


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
    items = []
    for row in rows[:10]:
        updated_at = as_datetime(row.get("updated_at"))
        if updated_at and stale(updated_at, now):
            quality.append({"source": "programs", "issue": "older_than_24h", "title": safe_str(row.get("title"))})
        items.append({
            "slug": safe_str(row.get("slug")),
            "title": safe_str(row.get("title"))[:120],
            "category": safe_str(row.get("category")),
            "status": safe_str(row.get("status")),
            "next_starts_at": iso(as_datetime(row.get("next_starts_at"))),
            "area_name": safe_str(row.get("area_name")),
        })
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
