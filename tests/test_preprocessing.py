from datetime import UTC, datetime, timedelta

from app.domain import recommendation_bias
from app.preprocessing import build_festival_context, recommendation_exposure_items


def test_recommendation_exposure_items_flattens_response_groups():
    events = [{
        "response_snapshot": {
            "items": [{"business_id": "1", "name": "Alpha", "category": "FOOD"}],
            "sponsored_items": [{"business_id": "2", "name": "Beta", "category": "CAFE"}],
        },
    }]

    assert recommendation_exposure_items(events) == [
        {"business_id": "1", "name": "Alpha", "category": "FOOD", "is_sponsored": False},
        {"business_id": "2", "name": "Beta", "category": "CAFE", "is_sponsored": True},
    ]


def test_recommendation_exposure_items_drops_malformed_entries():
    events = [
        {"response_snapshot": None},
        {"response_snapshot": {"items": [None, {}, {"business_id": "  "}, {"business_id": 3}]}},
        {"response_snapshot": {"items": "not-a-list"}},
    ]

    assert recommendation_exposure_items(events) == [
        {"business_id": "3", "name": "3", "category": "UNKNOWN", "is_sponsored": False},
    ]


def test_recommendation_bias_uses_normalized_exposures():
    events = [{
        "response_snapshot": {
            "items": [{"business_id": "1", "name": "Alpha", "category": "FOOD"}],
            "sponsored_items": [{"business_id": "2", "name": "Beta", "category": "FOOD"}],
        },
    }]

    audit = recommendation_bias(events, max_business_share=0.6, max_category_share=0.75)

    assert audit["total_exposures"] == 2
    assert audit["sponsored_exposures"] == 1
    assert audit["category_exposures"][0]["category"] == "FOOD"
    assert audit["category_exposures"][0]["is_over_threshold"]


def test_build_festival_context_filters_raw_and_malformed_rows():
    now = datetime(2026, 9, 12, 3, tzinfo=UTC)
    context = build_festival_context({
        "festival": {"id": "festival-1", "code": "EST34", "name": "테스트 축제", "timezone": "Asia/Seoul", "status": "ONGOING"},
        "congestion_samples": [
            {"area_id": "area-1", "area_name": "정문", "crowd_level": "FULL", "people_count": "42",
             "estimated_wait_min": -1, "source_type": "SENSOR", "captured_at": now, "expires_at": now + timedelta(minutes=5),
             "created_by": "operator-id"},
            {"area_id": "area-2", "area_name": "후문", "crowd_level": "BROKEN", "captured_at": "bad-date"},
        ],
        "visitor_count_samples": [{"active_sessions": "7", "created_last_24h": 12, "ended_last_24h": None, "sampled_at": now}],
        "ops_tickets": [{"ticket_type": "INCIDENT", "title": "넘어짐", "description": "개인 연락처 포함 원문",
                         "priority": "HIGH", "status": "OPEN", "area_name": "정문", "updated_at": now}],
        "announcements": [{"title": "우회 안내", "severity": "WARNING", "status": "ACTIVE", "updated_at": now}],
        "esg_measurements": [{"metric_name": "폐기물", "category": "E", "value": "3.5", "unit": "kg",
                              "target": "10", "status": "APPROVED", "measured_at": now - timedelta(days=2),
                              "source_ref": "raw-file"}],
    }, now=now)

    assert context["festival"]["code"] == "EST34"
    assert context["congestion"] == [{
        "area_id": "area-1", "area_name": "정문", "crowd_level": "FULL", "people_count": 42,
        "estimated_wait_min": None, "source_type": "SENSOR",
        "captured_at": "2026-09-12T03:00:00+00:00", "expires_at": "2026-09-12T03:05:00+00:00",
        "trend": "insufficient_data",
    }]
    assert context["visitor_count"]["active_sessions"] == 7
    assert "description" not in context["ops_tickets"][0]
    assert "source_ref" not in context["esg_measurements"][0]
    assert any(issue["source"] == "congestion" for issue in context["data_quality"])
    assert any(issue["source"] == "esg_measurements" and issue["issue"] == "older_than_24h" for issue in context["data_quality"])


def test_congestion_trend_detects_rapid_increase_and_stability():
    """A구역은 급격히 증가, B구역은 안정 — '지금 A구역 괜찮아?' 같은 질문에 답할 근거."""
    now = datetime(2026, 9, 12, 12, 40, tzinfo=UTC)
    context = build_festival_context({
        "festival": {"id": "festival-1", "code": "EST34"},
        "congestion_samples": [
            {"area_id": "area-a", "area_name": "A구역", "crowd_level": "FULL", "people_count": 950,
             "source_type": "SENSOR", "captured_at": now, "expires_at": now + timedelta(hours=1)},
            {"area_id": "area-b", "area_name": "B구역", "crowd_level": "MODERATE", "people_count": 200,
             "source_type": "SENSOR", "captured_at": now, "expires_at": now + timedelta(hours=1)},
        ],
        "congestion_recent": [
            {"area_id": "area-a", "crowd_level": "MODERATE", "people_count": 250, "captured_at": now - timedelta(minutes=30)},
            {"area_id": "area-a", "crowd_level": "BUSY", "people_count": 520, "captured_at": now - timedelta(minutes=20)},
            {"area_id": "area-a", "crowd_level": "BUSY", "people_count": 780, "captured_at": now - timedelta(minutes=10)},
            {"area_id": "area-a", "crowd_level": "FULL", "people_count": 950, "captured_at": now},
            {"area_id": "area-b", "crowd_level": "MODERATE", "people_count": 180, "captured_at": now - timedelta(minutes=30)},
            {"area_id": "area-b", "crowd_level": "MODERATE", "people_count": 190, "captured_at": now - timedelta(minutes=20)},
            {"area_id": "area-b", "crowd_level": "MODERATE", "people_count": 185, "captured_at": now - timedelta(minutes=10)},
            {"area_id": "area-b", "crowd_level": "MODERATE", "people_count": 200, "captured_at": now},
        ],
    }, now=now)

    by_area = {item["area_id"]: item for item in context["congestion"]}
    assert by_area["area-a"]["trend"] == "rapidly_increasing"
    assert by_area["area-a"]["people_count"] == 950
    assert by_area["area-b"]["trend"] == "stable"


def test_programs_flag_rescheduled_sessions():
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    context = build_festival_context({
        "festival": {"id": "festival-1"},
        "programs": [
            {"slug": "parade", "title": "메인 퍼레이드", "category": "PARADE", "area_name": "A구역",
             "starts_at": now + timedelta(hours=6, minutes=30), "ends_at": now + timedelta(hours=7),
             "created_at": now - timedelta(days=2), "updated_at": now - timedelta(minutes=5), "rescheduled": True},
            {"slug": "food-showcase", "title": "로컬 푸드쇼", "category": "FOOD", "area_name": "B구역",
             "starts_at": now + timedelta(hours=2), "ends_at": now + timedelta(hours=3),
             "created_at": now - timedelta(days=2), "updated_at": now - timedelta(days=2), "rescheduled": False},
        ],
    }, now=now)

    parade = next(item for item in context["programs"] if item["slug"] == "parade")
    assert parade["rescheduled"] is True
    assert parade["starts_at"] == "2026-09-12T18:30:00+00:00"
    food = next(item for item in context["programs"] if item["slug"] == "food-showcase")
    assert food["rescheduled"] is False


def test_facilities_are_normalized_and_empty_result_flagged():
    context = build_festival_context({
        "festival": {"id": "festival-1"},
        "facilities": [{"name": "A구역 화장실", "facility_type": "RESTROOM", "area_name": "A구역"}],
    }, now=datetime(2026, 9, 12, tzinfo=UTC))
    assert context["facilities"] == [{"name": "A구역 화장실", "facility_type": "RESTROOM", "area_name": "A구역"}]

    empty_context = build_festival_context({"festival": {}}, now=datetime(2026, 9, 12, tzinfo=UTC))
    assert empty_context["facilities"] == []
    assert any(issue["source"] == "facilities" for issue in empty_context["data_quality"])


def test_build_festival_context_handles_empty_results():
    context = build_festival_context({"festival": {}}, now=datetime(2026, 9, 12, tzinfo=UTC))

    assert context["congestion"] == []
    assert context["ops_tickets"] == []
    assert context["visitor_count"]["active_sessions"] == 0
    assert {issue["source"] for issue in context["data_quality"]} >= {
        "congestion", "visitor_count", "ops_tickets", "announcements", "esg_measurements", "facilities",
    }
