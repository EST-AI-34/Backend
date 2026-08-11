from fastapi.testclient import TestClient

from app.main import app


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
