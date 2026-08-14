from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from psycopg import Connection

from ..config import settings
from ..db import all_rows, jsonb, one
from ..deps import Db
from ..domain import supported_language
from ..errors import found
from ..http import success
from ..schemas import VisitorSessionIn
from ..security import hash_token, random_token


router = APIRouter()


def published_festival(connection: Connection, code: str) -> dict:
    return found(one(
        connection,
        """SELECT id,code,name,description,timezone,starts_at,ends_at,status,default_language,
                  supported_languages,visitor_menus,updated_at FROM festivals
           WHERE code=%s AND status IN ('PUBLISHED','ONGOING','ENDED')""",
        (code,),
    ), "게시된 축제를 찾을 수 없습니다.")


def cached(response: Response, seconds: int = 60) -> None:
    response.headers["Cache-Control"] = f"public, max-age={seconds}, stale-while-revalidate={seconds}"


def visitor_language(festival: dict, requested: str | None, request: Request) -> str:
    return supported_language(requested or request.headers.get("Accept-Language"), festival["supported_languages"], festival["default_language"])


@router.get("/public/festivals/{festival_code}")
def festival_home(festival_code: str, request: Request, response: Response, connection: Db):
    result = published_festival(connection, festival_code)
    cached(response, 120)
    return success(request, result)


@router.get("/public/festivals/{festival_code}/programs")
def programs(
    festival_code: str,
    request: Request,
    response: Response,
    connection: Db,
    selected_date: Annotated[date | None, Query(alias="date")] = None,
    area_id: Annotated[str | None, Query(alias="areaId")] = None,
    category: str | None = None,
    status: str = "OPEN",
    language: str | None = None,
):
    festival = published_festival(connection, festival_code)
    language = visitor_language(festival, language, request)
    values: list = [festival["id"], language, festival["default_language"]]
    clauses = ["p.festival_id=%s", "p.status='PUBLISHED'", "ci.lifecycle_status='PUBLISHED'", "cv.language IN (%s,%s)"]
    for clause, value in (("p.category=%s", category), ("ps.area_id=%s", area_id), ("ps.status=%s", status),
                          ("(ps.starts_at AT TIME ZONE f.timezone)::date=%s", selected_date)):
        if value:
            clauses.append(clause)
            values.append(value)
    rows = all_rows(
        connection,
        f"""SELECT p.id,p.slug,p.title,p.summary,p.category,p.accessibility,p.updated_at,cv.language,
                    ci.updated_at AS published_at,
                    jsonb_agg(DISTINCT jsonb_build_object('id',ps.id,'startsAt',ps.starts_at,'endsAt',ps.ends_at,
                      'capacity',ps.capacity,'status',ps.status,'area',jsonb_build_object('id',a.id,'name',a.name))) AS sessions
             FROM programs p JOIN festivals f ON f.id=p.festival_id JOIN program_sessions ps ON ps.program_id=p.id
             JOIN festival_areas a ON a.id=ps.area_id
             JOIN content_items ci ON ci.festival_id=p.festival_id AND ci.resource_type='PROGRAM' AND ci.resource_id=p.id
             JOIN content_versions cv ON cv.id=ci.published_version_id
             WHERE {' AND '.join(clauses)} GROUP BY p.id,cv.language,ci.updated_at ORDER BY min(ps.starts_at),p.title""",
        values,
    )
    cached(response)
    return success(request, rows, page={"nextCursor": None, "hasNext": False, "limit": len(rows)})


@router.get("/public/festivals/{festival_code}/programs/{program_slug}")
def program_detail(festival_code: str, program_slug: str, request: Request, response: Response, connection: Db, language: str | None = None):
    festival = published_festival(connection, festival_code)
    language = visitor_language(festival, language, request)
    row = found(one(
        connection,
        """SELECT p.id,p.slug,p.title,p.summary,p.category,p.accessibility,p.updated_at,cv.language,cv.body,
                  ci.updated_at AS published_at,
                  coalesce(jsonb_agg(jsonb_build_object('id',ps.id,'startsAt',ps.starts_at,'endsAt',ps.ends_at,
                    'capacity',ps.capacity,'status',ps.status,'area',jsonb_build_object('id',a.id,'name',a.name))
                    ORDER BY ps.starts_at) FILTER(WHERE ps.id IS NOT NULL),'[]') AS sessions
           FROM programs p JOIN content_items ci ON ci.festival_id=p.festival_id AND ci.resource_type='PROGRAM'
             AND ci.resource_id=p.id AND ci.lifecycle_status='PUBLISHED'
           JOIN content_versions cv ON cv.id=ci.published_version_id AND cv.language IN (%s,%s)
           LEFT JOIN program_sessions ps ON ps.program_id=p.id LEFT JOIN festival_areas a ON a.id=ps.area_id
           WHERE p.festival_id=%s AND p.slug=%s AND p.status='PUBLISHED'
           GROUP BY p.id,cv.id,ci.updated_at ORDER BY (cv.language=%s) DESC LIMIT 1""",
        (language, festival["default_language"], festival["id"], program_slug, language),
    ), "게시된 프로그램을 찾을 수 없습니다.")
    cached(response)
    return success(request, row)


@router.get("/public/festivals/{festival_code}/areas")
def areas(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, "SELECT id,name,area_type,latitude,longitude,status,updated_at FROM festival_areas WHERE festival_id=%s AND status='ACTIVE' ORDER BY name", (festival["id"],))
    cached(response)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/facilities")
def facilities(festival_code: str, request: Request, response: Response, connection: Db, type_: Annotated[str | None, Query(alias="type")] = None):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT f.id,f.name,f.facility_type,f.accessibility,f.operating_hours,f.status,f.updated_at,
        jsonb_build_object('id',a.id,'name',a.name,'latitude',a.latitude,'longitude',a.longitude) AS area
        FROM facilities f JOIN festival_areas a ON a.id=f.area_id WHERE f.festival_id=%s AND f.status='ACTIVE'
        AND (%s::text IS NULL OR f.facility_type=%s) ORDER BY f.name""", (festival["id"], type_, type_))
    cached(response)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/map")
def festival_map(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    areas_data = all_rows(connection, "SELECT id,name,area_type,latitude,longitude,status FROM festival_areas WHERE festival_id=%s AND status='ACTIVE'", (festival["id"],))
    facilities_data = all_rows(connection, "SELECT id,area_id,name,facility_type,accessibility,operating_hours,status FROM facilities WHERE festival_id=%s AND status='ACTIVE'", (festival["id"],))
    programs_data = all_rows(connection, """SELECT DISTINCT p.id,p.slug,p.title,ps.area_id FROM programs p JOIN program_sessions ps ON ps.program_id=p.id
        JOIN content_items ci ON ci.resource_type='PROGRAM' AND ci.resource_id=p.id AND ci.lifecycle_status='PUBLISHED'
        WHERE p.festival_id=%s AND p.status='PUBLISHED' AND ps.status NOT IN ('CANCELLED','ENDED')""", (festival["id"],))
    cached(response)
    return success(request, {"festivalTimezone": festival["timezone"], "areas": areas_data, "facilities": facilities_data, "programs": programs_data})


@router.get("/public/festivals/{festival_code}/announcements")
def announcements(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT a.id,a.title,a.severity,a.audience,a.target_area_ids,a.starts_at,a.ends_at,
        CASE WHEN a.ends_at IS NOT NULL AND a.ends_at<=now() THEN 'EXPIRED' ELSE 'ACTIVE' END AS status,
        cv.body,cv.language,a.updated_at FROM announcements a JOIN content_versions cv ON cv.id=a.content_version_id
        WHERE a.festival_id=%s AND a.status IN ('ACTIVE','SCHEDULED') AND a.starts_at<=now()
          AND (a.ends_at IS NULL OR a.ends_at>now()) AND a.audience ? 'VISITOR' AND cv.status='APPROVED'
        ORDER BY CASE a.severity WHEN 'EMERGENCY' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,a.starts_at DESC""", (festival["id"],))
    cached(response, 15)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/announcements/{announcement_id}")
def announcement(festival_code: str, announcement_id: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    row = found(one(connection, """SELECT a.id,a.title,a.severity,a.audience,a.target_area_ids,a.starts_at,a.ends_at,cv.body,cv.language,a.updated_at
        FROM announcements a JOIN content_versions cv ON cv.id=a.content_version_id WHERE a.id=%s AND a.festival_id=%s
          AND a.status IN ('ACTIVE','SCHEDULED') AND a.starts_at<=now() AND (a.ends_at IS NULL OR a.ends_at>now())
          AND a.audience ? 'VISITOR' AND cv.status='APPROVED'""", (announcement_id, festival["id"])), "노출 중인 공지를 찾을 수 없습니다.")
    cached(response, 15)
    return success(request, row)


@router.post("/public/festivals/{festival_code}/visitor-sessions", status_code=201)
def create_visitor_session(festival_code: str, body: VisitorSessionIn, request: Request, connection: Db):
    festival = published_festival(connection, festival_code)
    token = random_token("vs")
    expires_at = datetime.now(UTC) + timedelta(hours=settings.visitor_session_hours)
    language = visitor_language(festival, body.language, request)
    row = one(connection, """INSERT INTO visitor_sessions(festival_id,anonymous_token_hash,language,accessibility_preferences,consents,expires_at)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""", (festival["id"], hash_token(token), language, jsonb(body.accessibility_preferences), jsonb(body.consents), expires_at))
    return success(request, {"id": row["id"], "sessionToken": token, "expiresAt": expires_at, "language": language,
                             "accessibilityPreferences": body.accessibility_preferences,
                             "festival": {"code": festival["code"], "timezone": festival["timezone"], "supportedLanguages": festival["supported_languages"]}})


@router.get("/public/festivals/{festival_code}/surveys")
def surveys(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT s.id,s.title,s.description,s.starts_at,s.ends_at,
        coalesce(jsonb_agg(jsonb_build_object('id',q.id,'prompt',q.prompt,'type',q.question_type,'options',q.options,
          'required',q.required,'position',q.position) ORDER BY q.position) FILTER(WHERE q.id IS NOT NULL),'[]') AS questions
        FROM surveys s LEFT JOIN survey_questions q ON q.survey_id=s.id WHERE s.festival_id=%s AND s.status='ACTIVE'
          AND (s.starts_at IS NULL OR s.starts_at<=now()) AND (s.ends_at IS NULL OR s.ends_at>now())
        GROUP BY s.id ORDER BY s.created_at""", (festival["id"],))
    cached(response, 30)
    return success(request, rows)
