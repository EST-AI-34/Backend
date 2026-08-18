from datetime import UTC, datetime, timedelta


def data(response):
    assert response.status_code in (200, 201), f"{response.status_code} {response.text}"
    return response.json()["data"]


def ask(client, visitor, message, monkeypatch):
    """질문 하나를 보내고, ai.answer_with_festival_context에 실제로 전달된 festival_context를
    가로채 돌려준다. Allen 자체는 호출하지 않는다(외부 네트워크 호출 없음)."""
    from app import ai

    seen = {}

    def fake_answer(question, festival_context):
        seen["question"] = question
        seen["context"] = festival_context
        return "테스트 응답"

    monkeypatch.setattr(ai, "answer_with_festival_context", fake_answer)
    conversation = data(client.post("/api/v1/visitor/ai/conversations", headers=visitor, json={"language": "ko"}))
    data(client.post(f"/api/v1/visitor/ai/conversations/{conversation['id']}/messages",
                     headers=visitor, json={"message": message}))
    return seen["context"]


def make_area(connection, festival, name: str, unique):
    area_name = f"{name}-{unique('area')}"
    area_id = connection.execute(
        "INSERT INTO festival_areas(festival_id,name,area_type) VALUES(%s,%s,'ZONE') RETURNING id",
        (festival["id"], area_name),
    ).fetchone()["id"]
    return area_id, area_name


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


def manager_id(connection):
    return connection.execute("SELECT id FROM users WHERE email='manager@example.com'").fetchone()["id"]


def test_congestion_question_context_has_latest_level_and_rapid_trend(client, visitor, connection, festival, unique, monkeypatch):
    """Q1 "지금 어디가 제일 혼잡해?" / Q2 "A구역 지금 괜찮아?" 용 컨텍스트."""
    area_id, area_name = make_area(connection, festival, "A구역", unique)
    now = datetime.now(UTC)
    for minutes_ago, level, count in ((30, "MODERATE", 250), (20, "BUSY", 520), (10, "BUSY", 780), (0, "FULL", 950)):
        connection.execute(
            """INSERT INTO crowd_snapshots(festival_id,area_id,source_type,crowd_level,people_count,captured_at,expires_at)
               VALUES(%s,%s,'SENSOR',%s,%s,%s,%s)""",
            (festival["id"], area_id, level, count, now - timedelta(minutes=minutes_ago), now + timedelta(hours=1)),
        )

    context = ask(client, visitor, "지금 어디가 제일 혼잡해?", monkeypatch)

    entry = next(item for item in context["congestion"] if item["area_name"] == area_name)
    assert entry["crowd_level"] == "FULL"
    assert entry["people_count"] == 950
    assert entry["trend"] == "rapidly_increasing"


def test_safety_question_context_has_unresolved_high_priority_ticket(client, visitor, connection, festival, unique, monkeypatch):
    """Q3 "현재 안전 문제 있어?" 용 컨텍스트 — HIGH/OPEN만 전달, RESOLVED는 제외."""
    title = f"안전 이슈-{unique('ticket')}"
    resolved_title = f"해결된 이슈-{unique('ticket')}"
    connection.execute(
        """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,priority,status,created_by)
           VALUES(%s,'INCIDENT',%s,'테스트용 안전 이슈','HIGH','OPEN',%s)""",
        (festival["id"], title, manager_id(connection)),
    )
    connection.execute(
        """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,priority,status,created_by)
           VALUES(%s,'COMPLAINT',%s,'이미 처리됨','LOW','RESOLVED',%s)""",
        (festival["id"], resolved_title, manager_id(connection)),
    )

    context = ask(client, visitor, "현재 안전 문제 있어?", monkeypatch)

    titles = [item["title"] for item in context["ops_tickets"]]
    assert title in titles
    assert resolved_title not in titles
    entry = next(item for item in context["ops_tickets"] if item["title"] == title)
    assert entry["priority"] == "HIGH"
    assert entry["status"] == "OPEN"


def test_schedule_questions_context_has_start_time_and_reschedule_flag(client, visitor, connection, festival, unique, monkeypatch):
    """Q4 "퍼레이드 몇 시야?" / Q5 "변경된 일정 있어?" 용 컨텍스트."""
    area_id, area_name = make_area(connection, festival, "메인 무대", unique)
    slug = unique("parade")
    program_id = connection.execute(
        "INSERT INTO programs(festival_id,slug,title,category,status) VALUES(%s,%s,'메인 퍼레이드','PARADE','PUBLISHED') RETURNING id",
        (festival["id"], slug),
    ).fetchone()["id"]
    now = datetime.now(UTC)
    original_start = now.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=1)
    changed_start = original_start + timedelta(minutes=30)
    connection.execute(
        """INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,created_at,updated_at)
           VALUES(%s,%s,%s,%s,%s,now()-interval '1 day',now())""",
        (festival["id"], program_id, area_id, changed_start, changed_start + timedelta(hours=1)),
    )

    context = ask(client, visitor, "퍼레이드 몇 시야?", monkeypatch)

    entry = next(item for item in context["programs"] if item["slug"] == slug)
    assert entry["starts_at"] == changed_start.astimezone(UTC).isoformat()
    assert entry["rescheduled"] is True


def test_announcement_question_context_has_latest_notice(client, visitor, connection, festival, unique, monkeypatch):
    """Q6 "공지사항 알려줘" 용 컨텍스트."""
    title = f"우회 동선 안내-{unique('notice')}"
    connection.execute(
        """INSERT INTO announcements(festival_id,title,severity,status,starts_at,created_by)
           VALUES(%s,%s,'WARNING','ACTIVE',now(),%s)""",
        (festival["id"], title, manager_id(connection)),
    )

    context = ask(client, visitor, "공지사항 알려줘", monkeypatch)

    entry = next(item for item in context["announcements"] if item["title"] == title)
    assert entry["severity"] == "WARNING"
    assert entry["status"] == "ACTIVE"


def test_esg_questions_context_has_current_and_target(client, visitor, connection, festival, unique, monkeypatch):
    """Q7 "다회용기 사용률 어때?" / Q8 "ESG 목표 잘 달성하고 있어?" 용 컨텍스트."""
    metric_name = f"다회용기 사용률-{unique('metric')}"
    user = manager_id(connection)
    metric_id = connection.execute(
        "INSERT INTO esg_metrics(festival_id,name,category,created_by) VALUES(%s,%s,'E',%s) RETURNING id",
        (festival["id"], metric_name, user),
    ).fetchone()["id"]
    version_id = connection.execute(
        """INSERT INTO esg_metric_versions(metric_id,version_no,formula,unit,target,source_requirements,created_by)
           VALUES(%s,1,'reuse/total*100','%%',80,'{}'::jsonb,%s) RETURNING id""",
        (metric_id, user),
    ).fetchone()["id"]
    connection.execute(
        """INSERT INTO esg_measurements(festival_id,metric_version_id,value,source_type,dedupe_key,measured_at,status,created_by)
           VALUES(%s,%s,61,'MANUAL',%s,now(),'APPROVED',%s)""",
        (festival["id"], version_id, unique("dedupe"), user),
    )

    context = ask(client, visitor, "다회용기 사용률 어때?", monkeypatch)

    entry = next(item for item in context["esg_measurements"] if item["metric_name"] == metric_name)
    assert entry["value"] == 61
    assert entry["target"] == 80
    assert entry["status"] == "APPROVED"


def test_facility_question_context_has_restroom(client, visitor, connection, festival, unique, monkeypatch):
    """Q9 "화장실 어디 있어?" 용 컨텍스트."""
    area_id, area_name = make_area(connection, festival, "B구역", unique)
    name = f"화장실-{unique('facility')}"
    connection.execute(
        "INSERT INTO facilities(festival_id,area_id,name,facility_type) VALUES(%s,%s,%s,'RESTROOM')",
        (festival["id"], area_id, name),
    )

    context = ask(client, visitor, "화장실 어디 있어?", monkeypatch)

    entry = next(item for item in context["facilities"] if item["name"] == name)
    assert entry["facility_type"] == "RESTROOM"
    assert entry["area_name"] == area_name
