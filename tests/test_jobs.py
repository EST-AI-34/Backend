"""잡 워커와 만료 데이터 정리.

둘 다 요청 경로 밖에서 도는 코드라 API 테스트에 잡히지 않는데, 실패하면 조용히
데이터가 쌓이거나 잡이 무한 재시도된다.
"""
from app import jobs


def test_purge_guards_every_visitor_session_reference(client, connection):
    """자식 테이블 목록을 손으로 적으면 새 테이블이 생길 때 빠뜨린다.

    실제로 survey_responses·reward_events·course_plans·ai_message_reports가 빠져 있어
    FK 위반으로 정리 트랜잭션 전체가 롤백되고 있었다. 카탈로그에서 읽는지 확인한다.
    """
    referencing = {row["table_name"] for row in connection.execute("""
        SELECT c.conrelid::regclass::text AS table_name FROM pg_constraint c
        WHERE c.contype='f' AND c.confrelid='visitor_sessions'::regclass""").fetchall()}
    assert {"survey_responses", "reward_events", "course_plans", "ai_message_reports"} <= referencing

    # 참조가 남은 만료 세션은 지우지 않고 넘어간다(FK 위반으로 죽지 않는다).
    session = connection.execute("""INSERT INTO visitor_sessions(festival_id,anonymous_token_hash,expires_at)
        SELECT id,'purge-test-hash',now()-interval '400 days' FROM festivals WHERE code='EST34-2026'
        RETURNING id""").fetchone()
    survey = connection.execute("SELECT id FROM surveys LIMIT 1").fetchone()
    connection.execute("INSERT INTO survey_responses(survey_id,visitor_session_id) VALUES(%s,%s)",
                       (survey["id"], session["id"]))
    try:
        jobs.purge_expired()
        assert connection.execute("SELECT 1 FROM visitor_sessions WHERE id=%s", (session["id"],)).fetchone()
    finally:
        connection.execute("DELETE FROM survey_responses WHERE visitor_session_id=%s", (session["id"],))
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
