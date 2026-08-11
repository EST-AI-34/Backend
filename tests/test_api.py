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
    assert body["data"]["name"] == "2026 그린한강 페스티벌"
    assert body["meta"]["requestId"].startswith("req_")


def test_visitor_ai_message_uses_registered_data():
    response = client.post(
        "/api/v1/visitor/ai/conversations/current/messages",
        json={"message": "오늘 주요 프로그램 알려줘", "language": "ko", "interests": ["program"]},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert "등록된 축제 데이터" in body["answer"]
    assert body["sources"][0]["title"] == "등록된 축제 데이터"
