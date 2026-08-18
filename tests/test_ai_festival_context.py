def data(response):
    assert response.status_code in (200, 201), f"{response.status_code} {response.text}"
    return response.json()["data"]


def test_visitor_ai_uses_mocked_alan_context_and_reuses_message_storage(client, visitor, connection, monkeypatch):
    from app import ai

    seen = {}

    def fake_answer(question, festival_context):
        seen["question"] = question
        seen["context"] = festival_context
        return "정문 혼잡도가 높아 우회 동선을 이용해 주세요."

    monkeypatch.setattr(ai, "answer_with_festival_context", fake_answer)
    conversation = data(client.post("/api/v1/visitor/ai/conversations", headers=visitor, json={"language": "ko"}))
    answer = data(client.post(
        f"/api/v1/visitor/ai/conversations/{conversation['id']}/messages",
        headers=visitor,
        json={"message": "지금 어디가 혼잡해?"},
    ))

    assert answer["answer"] == "정문 혼잡도가 높아 우회 동선을 이용해 주세요."
    assert answer["safetyStatus"] == "ALLOWED"
    assert seen["question"] == "지금 어디가 혼잡해?"
    assert "congestion" in seen["context"] and "visitor_count" in seen["context"]
    row = connection.execute("SELECT answer,safety_status FROM ai_messages WHERE id=%s", (answer["messageId"],)).fetchone()
    assert row["answer"] == answer["answer"]
    assert row["safety_status"] == "ALLOWED"


def test_visitor_ai_keeps_existing_fallback_when_alan_context_fails(client, visitor, monkeypatch):
    from app import ai

    monkeypatch.setattr(ai, "answer_with_festival_context", lambda question, context: None)
    conversation = data(client.post("/api/v1/visitor/ai/conversations", headers=visitor, json={"language": "ko"}))
    answer = data(client.post(
        f"/api/v1/visitor/ai/conversations/{conversation['id']}/messages",
        headers=visitor,
        json={"message": "근거 없는 질문"},
    ))

    assert answer["safetyStatus"] == "INSUFFICIENT_GROUNDING"
    assert answer["fallback"]["type"] == "HELP_DESK"
