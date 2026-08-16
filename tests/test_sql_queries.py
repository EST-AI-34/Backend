import re
from pathlib import Path

from app.routes.admin_content import versions_by_item


# 캐스트 없는 파라미터를 IS NULL과 비교하면 Postgres가 타입을 정하지 못한다.
# 위치 인자(%s)와 이름 인자(%(name)s) 둘 다 막는다.
UNTYPED_NULL_CHECK = re.compile(r"%(\([a-z_]+\))?s IS NULL")


def test_nullable_sql_parameters_have_explicit_types():
    routes = Path("app/routes")
    assert not [path for path in routes.glob("*.py") if UNTYPED_NULL_CHECK.search(path.read_text())]


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, sql, params=()):
        self.calls += 1
        self.params = params
        return self

    def fetchall(self):
        return self.rows


def test_versions_group_by_item_in_one_query():
    connection = FakeConnection([
        {"id": "v1", "content_item_id": "a", "version_no": 2},
        {"id": "v2", "content_item_id": "a", "version_no": 1},
    ])
    grouped = versions_by_item(connection, ["a", "b"])
    assert connection.calls == 1
    assert connection.params == (["a", "b"],)
    assert [version["id"] for version in grouped["a"]] == ["v1", "v2"]
    assert grouped["b"] == []
    assert versions_by_item(FakeConnection([]), []) == {}
