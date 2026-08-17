import re
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..db import all_rows, audit, jsonb, one, set_clause
from ..deps import Db, IfMatch, Manager, Scope, User
from ..domain import safety_facility_order
from ..errors import AppError, bad_request, conflict, forbidden, found
from ..http import success
from ..schemas import (AreaIn, AreaPatch, CloneFestivalIn, FacilityIn, FacilityPatch, FestivalIn,
                       FestivalPatch, ProgramIn, ProgramPatch, ProgramSessionIn, ProgramSessionPatch)


router = APIRouter()

FESTIVAL_INSERT = """INSERT INTO festivals(organization_id,code,name,description,timezone,starts_at,ends_at,default_language,supported_languages)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *"""


def expected_version(if_match: str | None, body_version: int | None) -> int:
    if body_version is not None:
        return body_version
    match = re.search(r"\d+", if_match or "")
    if not match:
        raise bad_request("VERSION_REQUIRED", "If-Match 헤더 또는 version 값이 필요합니다.")
    return int(match.group())


def patch_row(connection, request: Request, user: dict, table: str, resource_id: str, festival_id: str,
              body: BaseModel | dict, if_match: str | None = None, *,
              require: str | None = None, conflict_message: str | None = None) -> dict:
    """축제 범위 안에서 낙관적 잠금으로 한 행을 수정하고 감사 로그를 남긴다.

    body가 Patch 스키마면 version을 빼고 나머지를 변경값으로 쓴다. version이 본문에
    없으면 If-Match 헤더에서 읽는다. 호출부마다 model_dump를 반복하지 않기 위해서다.

    require는 버전 외에 UPDATE가 만족해야 하는 조건(예: "status='DRAFT'")이다. 값이 아니라
    SQL에 그대로 들어가는 상수라 사용자 입력을 넘기면 안 된다.
    """
    values = body if isinstance(body, dict) else body.model_dump(exclude_none=True, exclude={"version"})
    version = expected_version(if_match, getattr(body, "version", None))
    clause, params = set_clause(values)
    scope_column = "id" if table == "festivals" else "festival_id"
    before = found(one(connection, f"SELECT * FROM {table} WHERE id=%s AND {scope_column}=%s", (resource_id, festival_id)))
    row = one(connection, f"""UPDATE {table} SET {clause},version=version+1,updated_at=now()
        WHERE id=%s AND {scope_column}=%s AND version=%s{f' AND {require}' if require else ''} RETURNING *""",
        [*params, resource_id, festival_id, version])
    if not row:
        raise conflict("RESOURCE_VERSION_CONFLICT",
                       conflict_message or "다른 사용자가 먼저 수정했습니다. 최신 값을 다시 조회해 주세요.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="UPDATE", resource_type=table.upper(),
          resource_id=resource_id, before_data=before, after_data=row, request_id=request.state.request_id)
    return row


def created(connection, request: Request, user: dict, festival_id: str | None, resource_type: str, row: dict,
            after_data: Any = None) -> None:
    """CREATE 감사 로그. 생성 라우트가 같은 audit(...) 8줄을 반복하던 자리.

    after_data를 주면 행 전체 대신 그 값만 남긴다(계정 생성처럼 비밀번호 해시가 섞인 행).
    """
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="CREATE",
          resource_type=resource_type, resource_id=str(row["id"]),
          after_data=row if after_data is None else after_data,
          request_id=request.state.request_id)


def in_festival(connection, table: str, resource_id: str, festival_id: str) -> bool:
    """resource_id가 이 축제에 속하는지. 테이블명은 SQL 상수여야 한다(사용자 입력 금지)."""
    return bool(one(connection, f"SELECT 1 FROM {table} WHERE id=%s AND festival_id=%s", (resource_id, festival_id)))


def scoped(connection, table: str, resource_id: str, festival_id: str, message: str = "리소스를 찾을 수 없습니다.") -> None:
    """축제 범위 밖이면 404. 범위 확인만 하고 행은 쓰지 않는 라우트가 쓴다."""
    if not in_festival(connection, table, resource_id, festival_id):
        raise AppError(404, "RESOURCE_NOT_FOUND", message)


def archive(connection, request: Request, user: dict, table: str, resource_id: str, festival_id: str,
            if_match: str | None, status: str = "ARCHIVED") -> Response:
    patch_row(connection, request, user, table, resource_id, festival_id, {"status": status}, if_match)
    return Response(status_code=204)


@router.get("/admin/festivals")
def list_festivals(request: Request, user: User, connection: Db):
    rows = all_rows(connection, """SELECT id,code,name,description,timezone,starts_at,ends_at,status,default_language,
        supported_languages,version,updated_at FROM festivals WHERE organization_id=%(organization_id)s
        AND (%(super_admin)s OR %(scope)s::jsonb ? id::text OR %(scope)s::jsonb ? '*') ORDER BY starts_at DESC""",
        {"organization_id": user["organization_id"], "super_admin": user["role"] == "SUPER_ADMIN",
         "scope": jsonb(user["festival_scope"])})
    return success(request, rows)


@router.post("/admin/festivals", status_code=201)
def create_festival(body: FestivalIn, request: Request, user: Manager, connection: Db):
    if user["role"] != "SUPER_ADMIN" and "*" not in user["festival_scope"]:
        raise forbidden("FESTIVAL_SCOPE_DENIED", "새 축제를 만들 권한이 없습니다.")
    row = one(connection, FESTIVAL_INSERT,
        (user["organization_id"], body.code, body.name, body.description, body.timezone, body.starts_at, body.ends_at, body.default_language, jsonb(body.supported_languages)))
    created(connection, request, user, str(row["id"]), "FESTIVAL", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}")
def get_festival(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, one(connection, "SELECT * FROM festivals WHERE id=%s", (festival_id,)))


@router.patch("/admin/festivals/{festival_id}")
def update_festival(festival_id: str, body: FestivalPatch, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    return success(request, patch_row(connection, request, user, "festivals", festival_id, festival_id, body, if_match))


@router.get("/admin/festivals/{festival_id}/areas")
def list_areas(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, "SELECT * FROM festival_areas WHERE festival_id=%s ORDER BY name", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/areas", status_code=201)
def create_area(festival_id: str, body: AreaIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO festival_areas(festival_id,name,area_type,description,latitude,longitude,status)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.name, body.area_type, body.description, body.latitude, body.longitude, body.status))
    created(connection, request, user, festival_id, "FESTIVAL_AREAS", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/areas/{area_id}")
def get_area(festival_id: str, area_id: str, request: Request, _: Scope, connection: Db):
    return success(request, found(one(connection, "SELECT * FROM festival_areas WHERE id=%s AND festival_id=%s", (area_id, festival_id))))


@router.patch("/admin/festivals/{festival_id}/areas/{area_id}")
def update_area(festival_id: str, area_id: str, body: AreaPatch, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    return success(request, patch_row(connection, request, user, "festival_areas", area_id, festival_id, body, if_match))


@router.delete("/admin/festivals/{festival_id}/areas/{area_id}", status_code=204)
def archive_area(festival_id: str, area_id: str, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None) -> Response:
    return archive(connection, request, user, "festival_areas", area_id, festival_id, if_match)


@router.get("/admin/festivals/{festival_id}/facilities")
def list_facilities(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection,
        f"SELECT * FROM facilities WHERE festival_id=%s ORDER BY {safety_facility_order()},name", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/facilities", status_code=201)
def create_facility(festival_id: str, body: FacilityIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO facilities(festival_id,area_id,name,facility_type,accessibility,operating_hours,status)
        SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM festival_areas WHERE id=%s AND festival_id=%s) RETURNING *""",
        (festival_id, body.area_id, body.name, body.facility_type, jsonb(body.accessibility), jsonb(body.operating_hours), body.status, body.area_id, festival_id))
    if not row:
        raise bad_request("AREA_SCOPE_MISMATCH", "구역이 같은 축제에 속하지 않습니다.")
    created(connection, request, user, festival_id, "FACILITIES", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/facilities/{facility_id}")
def get_facility(festival_id: str, facility_id: str, request: Request, _: Scope, connection: Db):
    return success(request, found(one(connection, "SELECT * FROM facilities WHERE id=%s AND festival_id=%s", (facility_id, festival_id))))


@router.patch("/admin/festivals/{festival_id}/facilities/{facility_id}")
def update_facility(festival_id: str, facility_id: str, body: FacilityPatch, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    return success(request, patch_row(connection, request, user, "facilities", facility_id, festival_id, body, if_match))


@router.delete("/admin/festivals/{festival_id}/facilities/{facility_id}", status_code=204)
def archive_facility(festival_id: str, facility_id: str, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None) -> Response:
    return archive(connection, request, user, "facilities", facility_id, festival_id, if_match)


@router.get("/admin/festivals/{festival_id}/programs")
def list_programs(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, "SELECT * FROM programs WHERE festival_id=%s ORDER BY created_at DESC", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/programs", status_code=201)
def create_program(festival_id: str, body: ProgramIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, "INSERT INTO programs(festival_id,slug,title,summary,category,accessibility,status) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (festival_id, body.slug, body.title, body.summary, body.category, jsonb(body.accessibility), body.status))
    created(connection, request, user, festival_id, "PROGRAMS", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/programs/{program_id}")
def get_program(festival_id: str, program_id: str, request: Request, _: Scope, connection: Db):
    return success(request, found(one(connection, "SELECT * FROM programs WHERE id=%s AND festival_id=%s", (program_id, festival_id))))


@router.patch("/admin/festivals/{festival_id}/programs/{program_id}")
def update_program(festival_id: str, program_id: str, body: ProgramPatch, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    return success(request, patch_row(connection, request, user, "programs", program_id, festival_id, body, if_match))


@router.delete("/admin/festivals/{festival_id}/programs/{program_id}", status_code=204)
def archive_program(festival_id: str, program_id: str, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None) -> Response:
    return archive(connection, request, user, "programs", program_id, festival_id, if_match)


@router.get("/admin/festivals/{festival_id}/programs/{program_id}/sessions")
def list_sessions(festival_id: str, program_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, "SELECT * FROM program_sessions WHERE festival_id=%s AND program_id=%s ORDER BY starts_at", (festival_id, program_id)))


@router.post("/admin/festivals/{festival_id}/programs/{program_id}/sessions", status_code=201)
def create_session(festival_id: str, program_id: str, body: ProgramSessionIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity,status)
        SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM programs WHERE id=%s AND festival_id=%s)
        AND EXISTS(SELECT 1 FROM festival_areas WHERE id=%s AND festival_id=%s) RETURNING *""",
        (festival_id, program_id, body.area_id, body.starts_at, body.ends_at, body.capacity, body.status, program_id, festival_id, body.area_id, festival_id))
    if not row:
        raise bad_request("FESTIVAL_SCOPE_MISMATCH", "프로그램과 구역의 축제 범위를 확인해 주세요.")
    created(connection, request, user, festival_id, "PROGRAM_SESSIONS", row)
    return success(request, row)


@router.patch("/admin/festivals/{festival_id}/program-sessions/{session_id}")
def update_session(festival_id: str, session_id: str, body: ProgramSessionPatch, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    return success(request, patch_row(connection, request, user, "program_sessions", session_id, festival_id, body, if_match))


@router.delete("/admin/festivals/{festival_id}/program-sessions/{session_id}", status_code=204)
def cancel_session(festival_id: str, session_id: str, request: Request, _: Scope, user: Manager, connection: Db, if_match: IfMatch = None) -> Response:
    return archive(connection, request, user, "program_sessions", session_id, festival_id, if_match, status="CANCELLED")


@router.post("/admin/festivals/{festival_id}/clone", status_code=201)
def clone_festival(festival_id: str, body: CloneFestivalIn, request: Request, _: Scope, user: Manager, connection: Db):
    if user["role"] != "SUPER_ADMIN" and "*" not in user["festival_scope"]:
        raise forbidden("FESTIVAL_SCOPE_DENIED", "복제 축제를 만들 권한이 없습니다.")
    source = one(connection, "SELECT * FROM festivals WHERE id=%s", (festival_id,))
    row = one(connection, FESTIVAL_INSERT,
        (user["organization_id"], body.code, body.name, source["description"], source["timezone"], body.starts_at, body.ends_at, source["default_language"], jsonb(source["supported_languages"])))
    # 예전에는 구역만 복사해서 사실상 "구역 복사"였다. 시설·프로그램·회차까지 옮겨야
    # 다음 회차 축제를 처음부터 다시 입력하지 않는다. 회차 시각은 두 축제의 시작 시각
    # 차이만큼 통째로 민다 — 상대적 일정(첫날 10시 등)이 그대로 유지된다.
    #
    # 프로그램은 DRAFT로 복사한다. 게시는 콘텐츠 검수·승인을 다시 거쳐야 하고,
    # 복사본에는 아직 승인된 콘텐츠 버전이 없다(게시 상태로 두면 공개 목록이 깨진다).
    shift = body.starts_at - source["starts_at"]
    connection.execute("""INSERT INTO festival_areas(festival_id,name,area_type,description,latitude,longitude,status)
        SELECT %s,name,area_type,description,latitude,longitude,'ACTIVE' FROM festival_areas
        WHERE festival_id=%s AND status='ACTIVE'""", (row["id"], festival_id))
    # 새 구역은 이름으로 원본과 짝짓는다(같은 축제 안에서 구역 이름은 운영상 유일하다).
    connection.execute("""INSERT INTO facilities(festival_id,area_id,name,facility_type,accessibility,operating_hours,status)
        SELECT %s,new_area.id,f.name,f.facility_type,f.accessibility,f.operating_hours,'ACTIVE'
        FROM facilities f JOIN festival_areas old_area ON old_area.id=f.area_id
        JOIN festival_areas new_area ON new_area.festival_id=%s AND new_area.name=old_area.name
        WHERE f.festival_id=%s AND f.status='ACTIVE'""", (row["id"], row["id"], festival_id))
    connection.execute("""INSERT INTO programs(festival_id,slug,title,summary,category,accessibility,status)
        SELECT %s,slug,title,summary,category,accessibility,'DRAFT' FROM programs
        WHERE festival_id=%s AND status<>'ARCHIVED'""", (row["id"], festival_id))
    connection.execute("""INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity,status)
        SELECT %s,new_program.id,new_area.id,ps.starts_at+%s,ps.ends_at+%s,ps.capacity,'OPEN'
        FROM program_sessions ps JOIN programs old_program ON old_program.id=ps.program_id
        JOIN festival_areas old_area ON old_area.id=ps.area_id
        JOIN programs new_program ON new_program.festival_id=%s AND new_program.slug=old_program.slug
        JOIN festival_areas new_area ON new_area.festival_id=%s AND new_area.name=old_area.name
        WHERE ps.festival_id=%s AND ps.status<>'CANCELLED'""",
        (row["id"], shift, shift, row["id"], row["id"], festival_id))
    copied = one(connection, """SELECT
        (SELECT count(*)::int FROM festival_areas WHERE festival_id=%s) AS areas,
        (SELECT count(*)::int FROM facilities WHERE festival_id=%s) AS facilities,
        (SELECT count(*)::int FROM programs WHERE festival_id=%s) AS programs,
        (SELECT count(*)::int FROM program_sessions WHERE festival_id=%s) AS sessions""",
        (row["id"], row["id"], row["id"], row["id"]))
    audit(connection, festival_id=str(row["id"]), actor_id=str(user["id"]), action="CLONE", resource_type="FESTIVAL",
          resource_id=str(row["id"]), after_data={"sourceFestivalId": festival_id, "copied": copied}, request_id=request.state.request_id)
    return success(request, {**row, "copied": copied})
