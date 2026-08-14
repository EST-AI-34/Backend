"""API 테스트용 DB 픽스처.

DATABASE_URL이 가리키는 DB에 마이그레이션과 데모 시드를 한 번 적용한다.
DB가 없으면 테스트를 건너뛴다(도메인 테스트는 DB 없이도 돈다).
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def database_ready() -> bool:
    from app.config import settings

    try:
        with psycopg.connect(settings.database_url, connect_timeout=3):
            return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def client():
    if not database_ready():
        pytest.skip("DATABASE_URL로 접속할 수 있는 PostgreSQL이 필요합니다 (docker compose up -d).")
    # 스크립트를 파일 경로로 돌리면 sys.path에 scripts/만 들어가 app을 못 찾는다.
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for script in ("scripts/migrate.py", "scripts/seed.py"):
        subprocess.run([sys.executable, script], cwd=ROOT, env=env, check=True, capture_output=True)

    from app.db import pool
    from app.main import app

    pool.open(wait=True)
    with TestClient(app) as test_client:
        yield test_client
    pool.close()


@pytest.fixture(scope="session")
def connection(client):
    """테스트가 직접 만드는 데이터는 즉시 커밋되어야 API 요청에서 보인다."""
    from app.config import settings

    with psycopg.connect(settings.database_url, row_factory=psycopg.rows.dict_row, autocommit=True) as connection:
        yield connection


@pytest.fixture(scope="session")
def festival(connection):
    return connection.execute("SELECT id,code FROM festivals WHERE code='EST34-2026'").fetchone()


def token_for(client, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "ChangeMe123!"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["accessToken"]


@pytest.fixture(scope="session")
def manager(client):
    return {"Authorization": f"Bearer {token_for(client, 'manager@example.com')}"}


@pytest.fixture(scope="session")
def reviewer(client):
    return {"Authorization": f"Bearer {token_for(client, 'reviewer@example.com')}"}


@pytest.fixture(scope="session")
def operator(client):
    return {"Authorization": f"Bearer {token_for(client, 'operator@example.com')}"}


@pytest.fixture
def visitor(client, festival):
    """축제마다 새 익명 방문 세션을 연다."""
    response = client.post(f"/api/v1/public/festivals/{festival['code']}/visitor-sessions",
                           json={"language": "ko", "consents": {"privacy": True}})
    assert response.status_code in (200, 201), response.text
    return {"Authorization": f"Bearer {response.json()['data']['sessionToken']}"}


@pytest.fixture
def unique():
    return lambda prefix: f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def session_id(connection, festival):
    """예약 가능한 회차를 매번 새로 만든다(정원 넉넉히)."""
    program = connection.execute("SELECT id FROM programs WHERE festival_id=%s LIMIT 1", (festival["id"],)).fetchone()
    area = connection.execute("SELECT id FROM festival_areas WHERE festival_id=%s LIMIT 1", (festival["id"],)).fetchone()
    row = connection.execute("""INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity)
        VALUES(%s,%s,%s,now()+interval '1 hour',now()+interval '2 hours',50) RETURNING id""",
        (festival["id"], program["id"], area["id"])).fetchone()
    return str(row["id"])
