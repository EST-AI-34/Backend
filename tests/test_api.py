from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.repositories.ai_repository import AllenAPIError
from app.services.esg_service import ESGService


client = TestClient(app)


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

    first = client.get("/api/v1/admin/festivals/EST34-2026/ai-brief?focus=esg")
    second = client.get("/api/v1/admin/festivals/EST34-2026/ai-brief?focus=esg")

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
