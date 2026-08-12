import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from psycopg import Connection

from ..db import all_rows, audit, database, jsonb, one
from ..errors import bad_request, conflict, forbidden, not_found
from ..http import success
from ..schemas import (AreaIn, AreaPatch, CloneFestivalIn, FacilityIn, FacilityPatch, FestivalIn,
                       FestivalPatch, ProgramIn, ProgramPatch, ProgramSessionIn, ProgramSessionPatch)
from ..security import current_user, festival_access, roles


router = APIRouter()


def expected_version(if_match: str | None, body_version: int | None) -> int:
    if body_version is not None:
        return body_version
    match = re.search(r"\d+", if_match or "")
    if not match:
        raise bad_request("VERSION_REQUIRED", "If-Match 헤더 또는 version 값이 필요합니다.")
    return int(match.group())


def patch_row(
    connection: Connection,
    *,
    table: str,
    resource_id: str,
    festival_id: str,
    values: dict,
    columns: dict[str, str],
    version: int,
    actor_id: str,
    request_id: str,
) -> dict:
    updates, params = [], []
    json_fields = {"supported_languages", "accessibility", "operating_hours"}
    for field, value in values.items():
        if field not in columns:
            continue
        column = columns[field]
        updates.append(f"{column}=%s")
        params.append(jsonb(value) if column in json_fields else value)
    if not updates:
        raise bad_request("VALIDATION_ERROR", "변경할 값이 없습니다.")
    before = one(connection, f"SELECT * FROM {table} WHERE id=%s AND {('id' if table == 'festivals' else 'festival_id')}=%s", (resource_id, festival_id))
    if not before:
        raise not_found()
    params.extend((resource_id, festival_id, version))
    row = one(connection, f"""UPDATE {table} SET {','.join(updates)},version=version+1,updated_at=now()
        WHERE id=%s AND {('id' if table == 'festivals' else 'festival_id')}=%s AND version=%s RETURNING *""", params)
    if not row:
        raise conflict("RESOURCE_VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 최신 값을 다시 조회해 주세요.")
    audit(connection, festival_id=festival_id, actor_id=actor_id, action="UPDATE", resource_type=table.upper(), resource_id=resource_id, before_data=before, after_data=row, request_id=request_id)
    return row


@router.get("/admin/festivals")
def list_festivals(request: Request, user: Annotated[dict, Depends(current_user)], connection: Annotated[Connection, Depends(database)]):
    rows = all_rows(connection, """SELECT id,code,name,description,timezone,starts_at,ends_at,status,default_language,
        supported_languages,version,updated_at FROM festivals WHERE organization_id=%s
        AND (%s OR %s::jsonb ? id::text OR %s::jsonb ? '*') ORDER BY starts_at DESC""",
        (user["organization_id"], user["role"] == "SUPER_ADMIN", jsonb(user["festival_scope"]), jsonb(user["festival_scope"])))
    return success(request, rows)


@router.post("/admin/festivals", status_code=201)
def create_festival(body: FestivalIn, request: Request, user: Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER"))], connection: Annotated[Connection, Depends(database)]):
    if user["role"] != "SUPER_ADMIN" and "*" not in user["festival_scope"]:
        raise forbidden("FESTIVAL_SCOPE_DENIED", "새 축제를 만들 권한이 없습니다.")
    row = one(connection, """INSERT INTO festivals(organization_id,code,name,description,timezone,starts_at,ends_at,default_language,supported_languages)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (user["organization_id"], body.code, body.name, body.description, body.timezone, body.starts_at, body.ends_at, body.default_language, jsonb(body.supported_languages)))
    audit(connection, festival_id=str(row["id"]), actor_id=str(user["id"]), action="CREATE", resource_type="FESTIVAL", resource_id=str(row["id"]), after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}")
def get_festival(festival_id: str, request: Request, _: Annotated[dict, Depends(festival_access)], connection: Annotated[Connection, Depends(database)]):
    return success(request, one(connection, "SELECT * FROM festivals WHERE id=%s", (festival_id,)))


@router.patch("/admin/festivals/{festival_id}")
def update_festival(festival_id: str, body: FestivalPatch, request: Request, _: Annotated[dict, Depends(festival_access)], user: Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER"))], connection: Annotated[Connection, Depends(database)], if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    row = patch_row(connection, table="festivals", resource_id=festival_id, festival_id=festival_id,
        values=body.model_dump(exclude_none=True, exclude={"version"}), columns={"name":"name","description":"description","timezone":"timezone","starts_at":"starts_at","ends_at":"ends_at","status":"status","default_language":"default_language","supported_languages":"supported_languages"},
        version=expected_version(if_match, body.version), actor_id=str(user["id"]), request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/areas")
def list_areas(festival_id: str, request: Request, _: Annotated[dict, Depends(festival_access)], connection: Annotated[Connection, Depends(database)]):
    return success(request, all_rows(connection, "SELECT * FROM festival_areas WHERE festival_id=%s ORDER BY name", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/areas", status_code=201)
def create_area(festival_id: str, body: AreaIn, request: Request, _: Annotated[dict, Depends(festival_access)], user: Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER"))], connection: Annotated[Connection, Depends(database)]):
    row = one(connection, "INSERT INTO festival_areas(festival_id,name,area_type,latitude,longitude,status) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *", (festival_id,body.name,body.area_type,body.latitude,body.longitude,body.status))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/areas/{area_id}")
def get_area(festival_id: str, area_id: str, request: Request, _: Annotated[dict, Depends(festival_access)], connection: Annotated[Connection, Depends(database)]):
    row=one(connection,"SELECT * FROM festival_areas WHERE id=%s AND festival_id=%s",(area_id,festival_id))
    if not row: raise not_found()
    return success(request,row)


@router.patch("/admin/festivals/{festival_id}/areas/{area_id}")
def update_area(festival_id:str,area_id:str,body:AreaPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None):
    return success(request,patch_row(connection,table="festival_areas",resource_id=area_id,festival_id=festival_id,values=body.model_dump(exclude_none=True,exclude={"version"}),columns={"name":"name","area_type":"area_type","latitude":"latitude","longitude":"longitude","status":"status"},version=expected_version(if_match,body.version),actor_id=str(user["id"]),request_id=request.state.request_id))


@router.delete("/admin/festivals/{festival_id}/areas/{area_id}",status_code=204)
def archive_area(festival_id:str,area_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None)->Response:
    patch_row(connection,table="festival_areas",resource_id=area_id,festival_id=festival_id,values={"status":"ARCHIVED"},columns={"status":"status"},version=expected_version(if_match,None),actor_id=str(user["id"]),request_id=request.state.request_id);return Response(status_code=204)


@router.get("/admin/festivals/{festival_id}/facilities")
def list_facilities(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):return success(request,all_rows(connection,"SELECT * FROM facilities WHERE festival_id=%s ORDER BY name",(festival_id,)))


@router.post("/admin/festivals/{festival_id}/facilities",status_code=201)
def create_facility(festival_id:str,body:FacilityIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"""INSERT INTO facilities(festival_id,area_id,name,facility_type,accessibility,operating_hours,status)
        SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM festival_areas WHERE id=%s AND festival_id=%s) RETURNING *""",(festival_id,body.area_id,body.name,body.facility_type,jsonb(body.accessibility),jsonb(body.operating_hours),body.status,body.area_id,festival_id))
    if not row:raise bad_request("AREA_SCOPE_MISMATCH","구역이 같은 축제에 속하지 않습니다.")
    return success(request,row)


@router.get("/admin/festivals/{festival_id}/facilities/{facility_id}")
def get_facility(festival_id:str,facility_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"SELECT * FROM facilities WHERE id=%s AND festival_id=%s",(facility_id,festival_id))
    if not row:raise not_found()
    return success(request,row)


@router.patch("/admin/festivals/{festival_id}/facilities/{facility_id}")
def update_facility(festival_id:str,facility_id:str,body:FacilityPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None):
    return success(request,patch_row(connection,table="facilities",resource_id=facility_id,festival_id=festival_id,values=body.model_dump(exclude_none=True,exclude={"version"}),columns={"area_id":"area_id","name":"name","facility_type":"facility_type","accessibility":"accessibility","operating_hours":"operating_hours","status":"status"},version=expected_version(if_match,body.version),actor_id=str(user["id"]),request_id=request.state.request_id))


@router.delete("/admin/festivals/{festival_id}/facilities/{facility_id}",status_code=204)
def archive_facility(festival_id:str,facility_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None)->Response:
    patch_row(connection,table="facilities",resource_id=facility_id,festival_id=festival_id,values={"status":"ARCHIVED"},columns={"status":"status"},version=expected_version(if_match,None),actor_id=str(user["id"]),request_id=request.state.request_id);return Response(status_code=204)


@router.get("/admin/festivals/{festival_id}/programs")
def list_programs(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):return success(request,all_rows(connection,"SELECT * FROM programs WHERE festival_id=%s ORDER BY created_at DESC",(festival_id,)))


@router.post("/admin/festivals/{festival_id}/programs",status_code=201)
def create_program(festival_id:str,body:ProgramIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"INSERT INTO programs(festival_id,slug,title,summary,category,accessibility,status) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",(festival_id,body.slug,body.title,body.summary,body.category,jsonb(body.accessibility),body.status));return success(request,row)


@router.get("/admin/festivals/{festival_id}/programs/{program_id}")
def get_program(festival_id:str,program_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"SELECT * FROM programs WHERE id=%s AND festival_id=%s",(program_id,festival_id))
    if not row:raise not_found()
    return success(request,row)


@router.patch("/admin/festivals/{festival_id}/programs/{program_id}")
def update_program(festival_id:str,program_id:str,body:ProgramPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None):
    return success(request,patch_row(connection,table="programs",resource_id=program_id,festival_id=festival_id,values=body.model_dump(exclude_none=True,exclude={"version"}),columns={"slug":"slug","title":"title","summary":"summary","category":"category","accessibility":"accessibility","status":"status"},version=expected_version(if_match,body.version),actor_id=str(user["id"]),request_id=request.state.request_id))


@router.delete("/admin/festivals/{festival_id}/programs/{program_id}",status_code=204)
def archive_program(festival_id:str,program_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None)->Response:
    patch_row(connection,table="programs",resource_id=program_id,festival_id=festival_id,values={"status":"ARCHIVED"},columns={"status":"status"},version=expected_version(if_match,None),actor_id=str(user["id"]),request_id=request.state.request_id);return Response(status_code=204)


@router.get("/admin/festivals/{festival_id}/programs/{program_id}/sessions")
def list_sessions(festival_id:str,program_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):return success(request,all_rows(connection,"SELECT * FROM program_sessions WHERE festival_id=%s AND program_id=%s ORDER BY starts_at",(festival_id,program_id)))


@router.post("/admin/festivals/{festival_id}/programs/{program_id}/sessions",status_code=201)
def create_session(festival_id:str,program_id:str,body:ProgramSessionIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"""INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity,status)
        SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM programs WHERE id=%s AND festival_id=%s)
        AND EXISTS(SELECT 1 FROM festival_areas WHERE id=%s AND festival_id=%s) RETURNING *""",(festival_id,program_id,body.area_id,body.starts_at,body.ends_at,body.capacity,body.status,program_id,festival_id,body.area_id,festival_id))
    if not row:raise bad_request("FESTIVAL_SCOPE_MISMATCH","프로그램과 구역의 축제 범위를 확인해 주세요.")
    return success(request,row)


@router.patch("/admin/festivals/{festival_id}/program-sessions/{session_id}")
def update_session(festival_id:str,session_id:str,body:ProgramSessionPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None):
    return success(request,patch_row(connection,table="program_sessions",resource_id=session_id,festival_id=festival_id,values=body.model_dump(exclude_none=True,exclude={"version"}),columns={"area_id":"area_id","starts_at":"starts_at","ends_at":"ends_at","capacity":"capacity","status":"status"},version=expected_version(if_match,body.version),actor_id=str(user["id"]),request_id=request.state.request_id))


@router.delete("/admin/festivals/{festival_id}/program-sessions/{session_id}",status_code=204)
def cancel_session(festival_id:str,session_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],if_match:Annotated[str|None,Header(alias="If-Match")]=None)->Response:
    patch_row(connection,table="program_sessions",resource_id=session_id,festival_id=festival_id,values={"status":"CANCELLED"},columns={"status":"status"},version=expected_version(if_match,None),actor_id=str(user["id"]),request_id=request.state.request_id);return Response(status_code=204)


@router.post("/admin/festivals/{festival_id}/clone",status_code=201)
def clone_festival(festival_id:str,body:CloneFestivalIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    if user["role"]!="SUPER_ADMIN" and "*" not in user["festival_scope"]:raise forbidden("FESTIVAL_SCOPE_DENIED","복제 축제를 만들 권한이 없습니다.")
    source=one(connection,"SELECT * FROM festivals WHERE id=%s",(festival_id,))
    row=one(connection,"""INSERT INTO festivals(organization_id,code,name,description,timezone,starts_at,ends_at,default_language,supported_languages)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(user["organization_id"],body.code,body.name,source["description"],source["timezone"],body.starts_at,body.ends_at,source["default_language"],jsonb(source["supported_languages"])))
    connection.execute("""INSERT INTO festival_areas(festival_id,name,area_type,latitude,longitude,status)
        SELECT %s,name,area_type,latitude,longitude,'ACTIVE' FROM festival_areas WHERE festival_id=%s AND status='ACTIVE'""",(row["id"],festival_id))
    audit(connection,festival_id=str(row["id"]),actor_id=str(user["id"]),action="CLONE",resource_type="FESTIVAL",resource_id=str(row["id"]),after_data={"sourceFestivalId":festival_id},request_id=request.state.request_id)
    return success(request,row)
