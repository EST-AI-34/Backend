"""PATCH·아카이브 경로 검증.

공통 SET 절 생성기(set_clause)를 쓰는 엔드포인트들이라 한 곳이 깨지면 전부 깨진다.
"""
import pytest

from app.db import set_clause
from app.errors import AppError

from conftest import headers_for


def data(response):
    assert response.status_code in (200, 201), f"{response.status_code} {response.text}"
    return response.json()["data"]


def test_set_clause_marks_json_values_and_rejects_empty():
    clause, params = set_clause({"name": "봄축제", "supported_languages": ["ko", "en"], "capacity": 10})
    assert clause == "name=%s,supported_languages=%s,capacity=%s"
    assert params[0] == "봄축제" and params[2] == 10
    assert params[1].obj == ["ko", "en"]  # dict/list는 Jsonb로 감싼다
    with pytest.raises(AppError) as error:
        set_clause({})
    assert error.value.status == 400


def test_patch_area_bumps_version_and_rejects_stale_version(client, festival, manager, unique):
    base = f"/api/v1/admin/festivals/{festival['id']}/areas"
    area = data(client.post(base, headers=manager, json={"name": unique("구역"), "areaType": "STAGE"}))

    updated = data(client.patch(f"{base}/{area['id']}", headers=manager,
                                json={"name": "이름변경", "latitude": 37.5, "version": area["version"]}))
    assert (updated["name"], float(updated["latitude"]), updated["version"]) == ("이름변경", 37.5, area["version"] + 1)

    stale = client.patch(f"{base}/{area['id']}", headers=manager, json={"name": "재변경", "version": area["version"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "RESOURCE_VERSION_CONFLICT"

    empty = client.patch(f"{base}/{area['id']}", headers=manager, json={"version": updated["version"]})
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "VALIDATION_ERROR"

    # If-Match 헤더만으로도 버전을 읽고, DELETE는 ARCHIVED로 남긴다.
    assert client.delete(f"{base}/{area['id']}", headers={**manager, "If-Match": f'W/"{updated["version"]}"'}).status_code == 204
    assert data(client.get(f"{base}/{area['id']}", headers=manager))["status"] == "ARCHIVED"


def test_patch_facility_writes_json_columns(client, festival, manager, unique):
    area = data(client.post(f"/api/v1/admin/festivals/{festival['id']}/areas", headers=manager,
                            json={"name": unique("구역"), "areaType": "STAGE"}))
    base = f"/api/v1/admin/festivals/{festival['id']}/facilities"
    facility = data(client.post(base, headers=manager, json={"areaId": area["id"], "name": unique("화장실"), "facilityType": "TOILET"}))
    updated = data(client.patch(f"{base}/{facility['id']}", headers=manager,
                                json={"accessibility": {"wheelchair": True}, "operatingHours": {"open": "09:00"}, "version": facility["version"]}))
    assert updated["accessibility"] == {"wheelchair": True} and updated["operatingHours"] == {"open": "09:00"}


def test_patch_announcement_requires_draft_and_stores_lists(client, festival, manager, unique):
    base = f"/api/v1/admin/festivals/{festival['id']}/announcements"
    announcement = data(client.post(base, headers=manager, json={"title": unique("공지")}))
    updated = data(client.patch(f"{base}/{announcement['id']}", headers=manager,
                                json={"title": "제목변경", "severity": "WARNING", "audience": ["VISITOR"], "version": announcement["version"]}))
    assert (updated["title"], updated["severity"], updated["audience"]) == ("제목변경", "WARNING", ["VISITOR"])

    stale = client.patch(f"{base}/{announcement['id']}", headers=manager, json={"title": "재변경", "version": announcement["version"]})
    assert stale.status_code == 409


def test_merchant_patch_resubmits_business(client, connection, festival, manager, unique):
    """시드 업체를 건드리면 뒤 테스트의 승인 상태가 깨지므로 전용 업체를 만든다."""
    merchant = headers_for(client, "merchant@example.com")
    membership = connection.execute("SELECT m.id FROM memberships m JOIN users u ON u.id=m.user_id WHERE u.email='merchant@example.com'").fetchone()
    business = data(client.post(f"/api/v1/admin/festivals/{festival['id']}/businesses", headers=manager, json={
        "registrationNo": unique("reg"), "name": "테스트상회", "category": "FOOD", "ownerMembershipId": str(membership["id"]),
    }))
    updated = data(client.patch(f"/api/v1/merchant/businesses/{business['id']}", headers=merchant,
                                json={"name": "상호변경", "menu": [{"name": "국밥", "price": 9000}], "version": business["version"]}))
    assert updated["participationStatus"] == "SUBMITTED"
    assert updated["menu"] == [{"name": "국밥", "price": 9000}]
    assert updated["version"] == business["version"] + 1
    assert connection.execute("SELECT name FROM businesses WHERE id=%s", (business["businessId"],)).fetchone()["name"] == "상호변경"

    nothing = client.patch(f"/api/v1/merchant/businesses/{business['id']}", headers=merchant, json={"version": updated["version"]})
    assert nothing.status_code == 400 and nothing.json()["error"]["code"] == "VALIDATION_ERROR"
