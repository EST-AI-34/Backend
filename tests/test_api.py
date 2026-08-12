from fastapi.testclient import TestClient
import base64
import hashlib
import hmac
import json
import time

from app.core.config import settings
from app.main import app
from app.repositories.ai_repository import AllenAPIError
from app.services.esg_service import ESGService
from app.services.insights_service import InsightsService


client = TestClient(app)


def admin_headers(role: str = "FESTIVAL_MANAGER", festival_scope: list[str] | None = None) -> dict[str, str]:
    token = _encode_test_jwt(
        payload={
            "sub": "test-admin",
            "role": role,
            "festival_scope": festival_scope if festival_scope is not None else ["EST34-2026", "1"],
        },
    )
    return {"Authorization": f"Bearer {token}"}


def _encode_test_jwt(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "exp": int(time.time()) + 3600,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        **payload,
    }
    header_part = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(settings.JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_b64encode(signature)}"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_public_festival_response_format():
    response = client.get("/api/v1/public/festivals/EST34-2026")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == 1
    assert body["data"]["name"]
    assert body["meta"]["requestId"].startswith("req_")


def test_visitor_ai_message_uses_registered_data(monkeypatch):
    def fake_call_llm(self, prompt, context):
        return {"reply": "등록된 축제 데이터 기준 주요 프로그램을 안내합니다.", "source": "allen"}

    monkeypatch.setattr("app.repositories.ai_repository.AIRepository.call_llm", fake_call_llm)

    response = client.post(
        "/api/v1/visitor/ai/conversations/current/messages",
        json={"message": "오늘 주요 프로그램 알려줘", "language": "ko", "interests": ["program"]},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["answer"]
    assert body["sources"]


def test_esg_briefing_uses_allen_only(monkeypatch):
    captured = {}

    def fake_create_esg_briefing(self, context):
        captured["context"] = context
        return {
            "briefing": "환경 지표와 지역 쿠폰 사용이 확인되며, 혼잡 대응 점검이 필요합니다.",
            "source": "allen",
        }

    monkeypatch.setattr(
        "app.repositories.ai_repository.AIRepository.create_esg_briefing",
        fake_create_esg_briefing,
    )

    response = client.get("/api/v1/esg/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "allen"
    assert body["briefing"] == "환경 지표와 지역 쿠폰 사용이 확인되며, 혼잡 대응 점검이 필요합니다."
    assert body["metrics"]
    assert any("environment_score=" in item for item in captured["context"])
    assert any(item.startswith("metric=") for item in captured["context"])


def test_admin_ai_brief_is_generated_and_saved_without_external_ai(monkeypatch):
    calls = {"count": 0}

    def fake_create_esg_briefing(self, context):
        calls["count"] += 1
        return {
            "briefing": "DB ESG 지표 기준으로 다회용기 운영 개선을 우선 점검해야 합니다.",
            "source": "allen",
        }

    monkeypatch.setattr(
        "app.repositories.ai_repository.AIRepository.create_esg_briefing",
        fake_create_esg_briefing,
    )

    first = client.get("/api/v1/admin/festivals/EST34-2026/ai-brief?focus=esg", headers=admin_headers())
    second = client.get("/api/v1/admin/festivals/EST34-2026/ai-brief?focus=esg", headers=admin_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["count"] == 0
    assert "ESG 개선 속도" in first.json()["data"]["allen_comment"]
    assert second.json()["data"]["allen_comment"] == first.json()["data"]["allen_comment"]


def test_admin_ai_brief_uses_allen_when_external_ai_enabled(monkeypatch):
    original_external_ai = settings.ENABLE_EXTERNAL_AI
    object.__setattr__(settings, "ENABLE_EXTERNAL_AI", True)
    calls = {"count": 0}

    def fake_create_esg_briefing(self, context):
        calls["count"] += 1
        return {
            "briefing": "Allen이 DB ESG 지표를 보고 만든 한줄평입니다.",
            "source": "allen",
        }

    monkeypatch.setattr(
        "app.repositories.ai_repository.AIRepository.create_esg_briefing",
        fake_create_esg_briefing,
    )

    try:
        service = ESGService()
        first = service.get_or_create_admin_ai_brief("EST34-2026", refresh=True)
        second = service.get_or_create_admin_ai_brief("EST34-2026")
    finally:
        object.__setattr__(settings, "ENABLE_EXTERNAL_AI", original_external_ai)

    assert calls["count"] == 1
    assert first.allen_comment == "Allen이 DB ESG 지표를 보고 만든 한줄평입니다."
    assert second.allen_comment == first.allen_comment


def test_admin_ai_brief_falls_back_when_allen_times_out(monkeypatch):
    original_external_ai = settings.ENABLE_EXTERNAL_AI
    object.__setattr__(settings, "ENABLE_EXTERNAL_AI", True)

    def fake_create_esg_briefing(self, context):
        raise AllenAPIError("Allen response read timed out.", status_code=504)

    monkeypatch.setattr(
        "app.repositories.ai_repository.AIRepository.create_esg_briefing",
        fake_create_esg_briefing,
    )

    try:
        brief = ESGService().get_or_create_admin_ai_brief("EST34-2026", refresh=True)
    finally:
        object.__setattr__(settings, "ENABLE_EXTERNAL_AI", original_external_ai)

    assert "ESG 개선 속도" in brief.allen_comment


def test_admin_ai_brief_handles_empty_esg_metrics(monkeypatch):
    monkeypatch.setattr("app.repositories.esg_repository.ESGRepository.list_metrics", lambda self: [])

    brief = ESGService().get_or_create_admin_ai_brief("EMPTY-METRICS", refresh=True)

    assert brief.metric_label == "ESG 운영 지표"
    assert brief.allen_comment


def test_admin_ai_brief_refresh_does_not_duplicate_in_memory_storage():
    service = ESGService()

    service.get_or_create_admin_ai_brief("NO-DUPLICATE", refresh=True)
    service.get_or_create_admin_ai_brief("NO-DUPLICATE", refresh=True)

    assert len(service.repo._briefings) == 1


def test_admin_api_requires_bearer_token():
    response = client.get("/api/v1/admin/festivals/EST34-2026/risk-brief")

    assert response.status_code == 401


def test_admin_api_rejects_wrong_role():
    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers=admin_headers(role="MERCHANT"),
    )

    assert response.status_code == 403


def test_admin_api_rejects_wrong_festival_scope():
    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers=admin_headers(festival_scope=["OTHER-FESTIVAL"]),
    )

    assert response.status_code == 403


def test_admin_api_rejects_expired_token():
    token = _encode_test_jwt(
        {
            "sub": "test-admin",
            "role": "FESTIVAL_MANAGER",
            "festival_scope": ["EST34-2026"],
            "exp": int(time.time()) - 1,
        }
    )

    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_admin_api_rejects_future_nbf():
    token = _encode_test_jwt(
        {
            "sub": "test-admin",
            "role": "FESTIVAL_MANAGER",
            "festival_scope": ["EST34-2026"],
            "nbf": int(time.time()) + 3600,
        }
    )

    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_admin_api_rejects_wrong_issuer_and_audience():
    wrong_issuer = _encode_test_jwt(
        {"sub": "test-admin", "role": "FESTIVAL_MANAGER", "festival_scope": ["EST34-2026"], "iss": "other"}
    )
    wrong_audience = _encode_test_jwt(
        {"sub": "test-admin", "role": "FESTIVAL_MANAGER", "festival_scope": ["EST34-2026"], "aud": "other"}
    )

    issuer_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {wrong_issuer}"},
    )
    audience_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {wrong_audience}"},
    )

    assert issuer_response.status_code == 401
    assert audience_response.status_code == 401


def test_admin_api_rejects_bad_signature():
    token = _encode_test_jwt(
        {"sub": "test-admin", "role": "FESTIVAL_MANAGER", "festival_scope": ["EST34-2026"]}
    )
    tampered = f"{token[:-1]}x"

    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {tampered}"},
    )

    assert response.status_code == 401


def test_admin_api_rejects_missing_role_and_scope():
    no_role = _encode_test_jwt({"sub": "test-admin", "festival_scope": ["EST34-2026"]})
    no_scope = _encode_test_jwt({"sub": "test-admin", "role": "FESTIVAL_MANAGER"})

    role_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {no_role}"},
    )
    scope_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers={"Authorization": f"Bearer {no_scope}"},
    )

    assert role_response.status_code == 403
    assert scope_response.status_code == 403


def test_admin_api_applies_role_permissions():
    read_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers=admin_headers(role="FIELD_OPERATOR"),
    )
    write_response = client.post(
        "/api/v1/admin/festivals/EST34-2026/esg/metrics",
        headers=admin_headers(role="FIELD_OPERATOR"),
        json={
            "category": "environment",
            "metric_name": "waste",
            "value": 1,
            "unit": "kg",
            "source": "test",
        },
    )
    super_admin_response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief",
        headers=admin_headers(role="SUPER_ADMIN", festival_scope=["*"]),
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403
    assert super_admin_response.status_code == 200


def test_readiness_check():
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_admin_risk_brief_rule_based_warning():
    response = client.get(
        "/api/v1/admin/festivals/EST34-2026/risk-brief?refresh=true",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["festival_id"] == "EST34-2026"
    assert body["risk_level"] in {"warning", "critical"}
    assert body["risk_score"] >= 40
    assert body["evidence"]


def test_admin_risk_level_boundaries():
    service = InsightsService()

    assert service._risk_level(39) == "normal"
    assert service._risk_level(40) == "warning"
    assert service._risk_level(74) == "warning"
    assert service._risk_level(75) == "critical"


def test_admin_risk_brief_handles_insufficient_data(monkeypatch):
    monkeypatch.setattr(
        "app.repositories.insights_repository.InsightsRepository.list_risk_signals",
        lambda self, festival_id, include_resolved=False: [],
    )

    response = client.get(
        "/api/v1/admin/festivals/UNKNOWN/risk-brief?refresh=true",
        headers=admin_headers(festival_scope=["UNKNOWN"]),
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["risk_level"] == "insufficient_data"
    assert body["risk_score"] == 0
    assert body["evidence"] == []


def test_admin_risk_brief_allen_fallback(monkeypatch):
    original_external_ai = settings.ENABLE_EXTERNAL_AI
    object.__setattr__(settings, "ENABLE_EXTERNAL_AI", True)

    def fake_create_risk_briefing(self, context):
        raise AllenAPIError("Allen timeout", status_code=504)

    monkeypatch.setattr(
        "app.repositories.ai_repository.AIRepository.create_risk_briefing",
        fake_create_risk_briefing,
    )

    try:
        response = client.get(
            "/api/v1/admin/festivals/EST34-2026/risk-brief?refresh=true",
            headers=admin_headers(),
        )
    finally:
        object.__setattr__(settings, "ENABLE_EXTERNAL_AI", original_external_ai)

    assert response.status_code == 200
    assert response.json()["data"]["fallback_used"] is True


def test_business_recommendations_filter_distance_and_sponsorship(monkeypatch):
    monkeypatch.setattr(
        "app.repositories.insights_repository.InsightsRepository.list_business_candidates",
        lambda self, festival_id: [
            {
                "id": "101",
                "festival_id": festival_id,
                "name": "DB Local Restaurant",
                "category": "restaurant",
                "location_id": "area-1",
                "latitude": 37.5260,
                "longitude": 126.9350,
                "coupon_available": True,
                "operating_status": "open",
                "is_sponsored": False,
                "accessible": True,
                "esg_participating": True,
                "description": "DB row",
            },
            {
                "id": "102",
                "festival_id": festival_id,
                "name": "Sponsored Cafe",
                "category": "cafe",
                "location_id": "area-2",
                "latitude": 37.5270,
                "longitude": 126.9340,
                "coupon_available": True,
                "operating_status": "open",
                "is_sponsored": True,
                "accessible": True,
                "esg_participating": False,
                "description": "DB row",
            },
        ],
    )

    response = client.get(
        "/api/v1/visitor/festivals/EST34-2026/business-recommendations"
        "?latitude=37.5260&longitude=126.9350&limit=10"
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["items"][0]["business_id"] == "BIZ-101"
    assert body["items"][0]["distance_meters"] == 0
    assert body["sponsored_items"][0]["business_id"] == "BIZ-102"


def test_business_recommendations_empty_db_candidates_do_not_use_fixture(monkeypatch):
    monkeypatch.setattr(
        "app.repositories.insights_repository.InsightsRepository.list_business_candidates",
        lambda self, festival_id: [],
    )

    response = client.get("/api/v1/visitor/festivals/EST34-2026/business-recommendations")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["items"] == []
    assert body["sponsored_items"] == []


def test_business_recommendations_reject_invalid_filters():
    partial = client.get("/api/v1/visitor/festivals/EST34-2026/business-recommendations?latitude=37")
    bad_latitude = client.get(
        "/api/v1/visitor/festivals/EST34-2026/business-recommendations?latitude=91&longitude=126"
    )
    bad_category = client.get(
        "/api/v1/visitor/festivals/EST34-2026/business-recommendations?category=unknown"
    )
    bad_limit = client.get("/api/v1/visitor/festivals/EST34-2026/business-recommendations?limit=0")

    assert partial.status_code == 422
    assert bad_latitude.status_code == 422
    assert bad_category.status_code == 422
    assert bad_limit.status_code == 422
