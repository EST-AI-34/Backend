"""잡 워커와 만료 데이터 정리.

둘 다 요청 경로 밖에서 도는 코드라 API 테스트에 잡히지 않는데, 실패하면 조용히
데이터가 쌓이거나 잡이 무한 재시도된다.
"""
from app import jobs


def test_purge_cascades_to_every_visitor_session_child(client, connection):
    """OPS-11: 보유기간이 지난 세션은 참조 데이터까지 연쇄 파기된다.

    자식 테이블 목록을 손으로 적으면 새 테이블이 생길 때 빠뜨리므로 FK 카탈로그를 읽는다.
    다만 보유기간이 더 긴 항목(설문 응답 1년)은 연쇄 파기가 앞당겨 지우면 안 되고,
    세션 연결만 끊겨 익명 행으로 남아야 한다.
    """
    referencing = {row["table_name"] for row in connection.execute("""
        SELECT c.conrelid::regclass::text AS table_name FROM pg_constraint c
        WHERE c.contype='f' AND c.confrelid='visitor_sessions'::regclass""").fetchall()}
    assert {"survey_responses", "reward_events", "course_plans", "ai_message_reports"} <= referencing

    session = connection.execute("""INSERT INTO visitor_sessions(festival_id,anonymous_token_hash,expires_at)
        SELECT id,'purge-test-hash',now()-interval '400 days' FROM festivals WHERE code='EST34-2026'
        RETURNING id""").fetchone()
    survey = connection.execute("SELECT id FROM surveys LIMIT 1").fetchone()
    response = connection.execute("INSERT INTO survey_responses(survey_id,visitor_session_id) VALUES(%s,%s) RETURNING id",
                                  (survey["id"], session["id"])).fetchone()
    plan = connection.execute("""INSERT INTO course_plans(visitor_session_id,input_preferences,expected_duration_min)
        VALUES(%s,'{}',60) RETURNING id""", (session["id"],)).fetchone()
    try:
        jobs.purge_expired()
        assert connection.execute("SELECT 1 FROM visitor_sessions WHERE id=%s", (session["id"],)).fetchone() is None
        assert connection.execute("SELECT 1 FROM course_plans WHERE id=%s", (plan["id"],)).fetchone() is None
        kept = connection.execute("SELECT visitor_session_id FROM survey_responses WHERE id=%s", (response["id"],)).fetchone()
        assert kept and kept["visitor_session_id"] is None
    finally:
        connection.execute("DELETE FROM survey_responses WHERE id=%s", (response["id"],))
        connection.execute("DELETE FROM course_plans WHERE id=%s", (plan["id"],))
        connection.execute("DELETE FROM visitor_sessions WHERE id=%s", (session["id"],))


def test_purge_deletes_expired_session_without_references(client, connection):
    session = connection.execute("""INSERT INTO visitor_sessions(festival_id,anonymous_token_hash,expires_at)
        SELECT id,'purge-test-orphan',now()-interval '400 days' FROM festivals WHERE code='EST34-2026'
        RETURNING id""").fetchone()
    jobs.purge_expired()
    assert connection.execute("SELECT 1 FROM visitor_sessions WHERE id=%s", (session["id"],)).fetchone() is None


def test_database_error_still_counts_as_a_job_attempt(client, connection, monkeypatch):
    """세이브포인트가 없으면 핸들러의 DB 오류가 fail_job의 UPDATE까지 물고 늘어져
    전부 롤백된다 — attempts가 오르지 않아 워커가 같은 잡을 영원히 다시 집는다."""
    job = connection.execute("""INSERT INTO jobs(festival_id,job_type,resource_type,resource_id)
        SELECT id,'GENERATE_ESG_REPORT','ESG_REPORT',NULL FROM festivals WHERE code='EST34-2026'
        RETURNING id""").fetchone()

    def broken(connection, job):
        connection.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setitem(jobs.JOB_HANDLERS, "GENERATE_ESG_REPORT", (broken, True))
    try:
        assert jobs.process_one_job() is True
        row = connection.execute("SELECT status,attempts,error FROM jobs WHERE id=%s", (job["id"],)).fetchone()
        assert row["attempts"] == 1 and row["status"] == "PENDING" and row["error"]
    finally:
        connection.execute("DELETE FROM jobs WHERE id=%s", (job["id"],))


def test_unknown_job_type_fails_immediately(client, connection):
    job = connection.execute("""INSERT INTO jobs(festival_id,job_type,resource_type)
        SELECT id,'NOT_A_JOB','ESG_REPORT' FROM festivals WHERE code='EST34-2026' RETURNING id""").fetchone()
    try:
        assert jobs.process_one_job() is True
        row = connection.execute("SELECT status,attempts FROM jobs WHERE id=%s", (job["id"],)).fetchone()
        assert row["status"] == "FAILED" and row["attempts"] == 1
    finally:
        connection.execute("DELETE FROM jobs WHERE id=%s", (job["id"],))
