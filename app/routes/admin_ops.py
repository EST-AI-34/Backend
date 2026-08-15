from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from psycopg import Connection

from ..db import all_rows, audit, jsonb, one, set_clause
from ..deps import Db, Manager, Operator, Scope, SuperAdmin, User
from ..domain import validate_ticket_transition
from ..errors import bad_request, conflict, forbidden, found
from ..http import success
from ..schemas import (AnnouncementIn, AnnouncementPatch, GenericExportIn, MembershipIn, MembershipPatch,
                       PublishAnnouncementIn, TicketIn, TicketPatch, TicketTransitionIn)
from ..security import hash_password


router = APIRouter()


@router.get("/admin/festivals/{festival_id}/announcements")
def announcements(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, """SELECT *,CASE WHEN ends_at IS NOT NULL AND ends_at<=now()
        AND status IN('ACTIVE','SCHEDULED') THEN 'EXPIRED' ELSE status END AS effective_status
        FROM announcements WHERE festival_id=%s ORDER BY created_at DESC""", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/announcements", status_code=201)
def create_announcement(festival_id: str, body: AnnouncementIn, request: Request, _: Scope, user: Operator, connection: Db):
    row = one(connection, "INSERT INTO announcements(festival_id,title,created_by) VALUES(%s,%s,%s) RETURNING *", (festival_id, body.title, user["id"]))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/announcements/{announcement_id}")
def announcement(festival_id: str, announcement_id: str, request: Request, _: Scope, connection: Db):
    return success(request, found(one(connection, "SELECT * FROM announcements WHERE id=%s AND festival_id=%s", (announcement_id, festival_id))))


@router.patch("/admin/festivals/{festival_id}/announcements/{announcement_id}")
def update_announcement(festival_id: str, announcement_id: str, body: AnnouncementPatch, request: Request, _: Scope, user: Operator, connection: Db):
    clause, params = set_clause(body.model_dump(exclude_none=True, exclude={"version"}))
    row = one(connection, f"""UPDATE announcements SET {clause},version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s AND version=%s AND status='DRAFT' RETURNING *""",
        [*params, announcement_id, festival_id, body.version])
    if not row:
        raise conflict("RESOURCE_VERSION_CONFLICT", "초안 상태와 버전을 확인해 주세요.")
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/announcements/{announcement_id}/publish")
def publish_announcement(festival_id: str, announcement_id: str, body: PublishAnnouncementIn, request: Request, _: Scope, user: Manager, connection: Db):
    if body.ends_at and body.starts_at >= body.ends_at:
        raise bad_request("VALIDATION_ERROR", "endsAt은 startsAt 이후여야 합니다.")
    if not one(connection, """SELECT cv.id FROM content_versions cv JOIN content_items ci ON ci.id=cv.content_item_id
        WHERE cv.id=%s AND ci.festival_id=%s AND cv.status='APPROVED'""", (body.content_version_id, festival_id)):
        raise bad_request("CONTENT_NOT_APPROVED", "승인된 공지 콘텐츠만 게시할 수 있습니다.")
    status = "SCHEDULED" if body.starts_at > datetime.now(UTC) else "ACTIVE"
    row = one(connection, """UPDATE announcements SET content_version_id=%s,severity=%s,audience=%s,target_area_ids=%s,
        starts_at=%s,ends_at=%s,status=%s,version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s AND status='DRAFT' RETURNING *""",
        (body.content_version_id, body.severity, jsonb(body.audience), jsonb(body.target_area_ids), body.starts_at, body.ends_at, status, announcement_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "초안 공지만 게시할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]),
          action="PUBLISH_EMERGENCY" if body.severity == "EMERGENCY" else "PUBLISH",
          resource_type="ANNOUNCEMENT", resource_id=announcement_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/announcements/{announcement_id}/close")
def close_announcement(festival_id: str, announcement_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """UPDATE announcements SET status='CLOSED',ends_at=least(coalesce(ends_at,now()),now()),version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s AND status IN('ACTIVE','SCHEDULED') RETURNING *""", (announcement_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "게시 중인 공지만 종료할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="CLOSE", resource_type="ANNOUNCEMENT",
          resource_id=announcement_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


def visible_ticket(connection: Connection, ticket_id: str, festival_id: str, user: dict) -> dict:
    return found(one(connection, """SELECT * FROM ops_tickets WHERE id=%s AND festival_id=%s
        AND (ticket_type='COMPLAINT' OR %s<>'FIELD_OPERATOR' OR assignee_id=%s OR created_by=%s)""",
        (ticket_id, festival_id, user["role"], user["id"], user["id"])))


@router.get("/admin/festivals/{festival_id}/ops-tickets")
def tickets(festival_id: str, request: Request, _: Scope, user: Operator, connection: Db, status: str | None = None):
    rows = all_rows(connection, """SELECT * FROM ops_tickets WHERE festival_id=%s
        AND (ticket_type='COMPLAINT' OR %s<>'FIELD_OPERATOR' OR assignee_id=%s OR created_by=%s)
        AND (%s::text IS NULL OR status=%s) ORDER BY CASE priority WHEN 'EMERGENCY' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END,created_at""",
        (festival_id, user["role"], user["id"], user["id"], status, status))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/ops-tickets", status_code=201)
def create_ticket(festival_id: str, body: TicketIn, request: Request, _: Scope, user: Operator, connection: Db):
    row = one(connection, """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,area_id,priority,assignee_id,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.ticket_type, body.title, body.description, body.area_id, body.priority, body.assignee_id, user["id"]))
    connection.execute("INSERT INTO ops_ticket_events(ticket_id,actor_id,to_status,note) VALUES(%s,%s,'OPEN','티켓 생성')", (row["id"], user["id"]))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}")
def ticket(festival_id: str, ticket_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    return success(request, visible_ticket(connection, ticket_id, festival_id, user))


@router.patch("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}")
def patch_ticket(festival_id: str, ticket_id: str, body: TicketPatch, request: Request, _: Scope, user: Operator, connection: Db):
    visible_ticket(connection, ticket_id, festival_id, user)
    row = one(connection, """UPDATE ops_tickets SET assignee_id=coalesce(%s,assignee_id),priority=coalesce(%s,priority),version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s AND version=%s RETURNING *""", (body.assignee_id, body.priority, ticket_id, festival_id, body.version))
    if not row:
        raise conflict("RESOURCE_VERSION_CONFLICT", "최신 티켓을 다시 조회해 주세요.")
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}/transitions")
def transition_ticket(festival_id: str, ticket_id: str, body: TicketTransitionIn, request: Request, _: Scope, user: Operator, connection: Db):
    ticket = visible_ticket(connection, ticket_id, festival_id, user)
    validate_ticket_transition(ticket["status"], body.to_status, body.note)
    if body.to_status == "ASSIGNED" and not ticket["assignee_id"]:
        raise bad_request("ASSIGNEE_REQUIRED", "담당자를 먼저 지정해 주세요.")
    row = one(connection, """UPDATE ops_tickets SET status=%s,version=version+1,updated_at=now(),
        resolved_at=CASE WHEN %s='RESOLVED' THEN now() ELSE resolved_at END,
        closed_at=CASE WHEN %s='CLOSED' THEN now() ELSE closed_at END WHERE id=%s RETURNING *""",
        (body.to_status, body.to_status, body.to_status, ticket_id))
    connection.execute("""INSERT INTO ops_ticket_events(ticket_id,actor_id,from_status,to_status,note,attachments)
        VALUES(%s,%s,%s,%s,%s,%s)""", (ticket_id, user["id"], ticket["status"], body.to_status, body.note, jsonb(body.attachments)))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="TRANSITION", resource_type="OPS_TICKET",
          resource_id=ticket_id, before_data={"status": ticket["status"]}, after_data={"status": body.to_status}, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}/events")
def ticket_events(festival_id: str, ticket_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    visible_ticket(connection, ticket_id, festival_id, user)
    return success(request, all_rows(connection, "SELECT * FROM ops_ticket_events WHERE ticket_id=%s ORDER BY created_at", (ticket_id,)))


@router.get("/admin/festivals/{festival_id}/surveys/{survey_id}/summary")
def survey_summary(festival_id: str, survey_id: str, request: Request, _: Scope, connection: Db):
    """방문객 제출·중복방지·익명 저장은 있었지만 운영자가 결과를 모아 볼 API가 없었다.
    개별 응답(visitor_session_id 등)은 절대 내보내지 않고 문항별 집계만 돌려준다."""
    survey = found(one(connection, "SELECT id,title,prevent_duplicates FROM surveys WHERE id=%s AND festival_id=%s", (survey_id, festival_id)))
    response_count = one(connection, "SELECT count(*)::int AS count FROM survey_responses WHERE survey_id=%s", (survey_id,))["count"]
    questions = all_rows(connection, "SELECT id,prompt,question_type,position FROM survey_questions WHERE survey_id=%s ORDER BY position", (survey_id,))
    answers = all_rows(connection, """SELECT sa.question_id,sa.value FROM survey_answers sa
        JOIN survey_responses sr ON sr.id=sa.response_id WHERE sr.survey_id=%s""", (survey_id,))
    answers_by_question: dict[str, list] = {}
    for answer in answers:
        answers_by_question.setdefault(str(answer["question_id"]), []).append(answer["value"])

    def summarize(question: dict) -> dict:
        values = answers_by_question.get(str(question["id"]), [])
        average_rating = None
        if question["question_type"] == "RATING":
            numeric = [float(value) for value in values if isinstance(value, int | float)]
            average_rating = round(sum(numeric) / len(numeric), 2) if numeric else None
        option_counts: dict[str, int] = {}
        if question["question_type"] in ("SINGLE_CHOICE", "MULTIPLE_CHOICE"):
            for value in values:
                for option in (value if isinstance(value, list) else [value]):
                    if isinstance(option, str):
                        option_counts[option] = option_counts.get(option, 0) + 1
        return {"question_id": question["id"], "prompt": question["prompt"], "question_type": question["question_type"],
                "response_count": len(values), "average_rating": average_rating, "option_counts": option_counts}

    return success(request, {
        "survey_id": survey_id, "title": survey["title"], "response_count": response_count,
        "anonymous": True, "duplicate_prevention": survey["prevent_duplicates"],
        "questions": [summarize(question) for question in questions],
    })


def same_organization(organization_id: str, user: dict) -> None:
    if organization_id != str(user["organization_id"]):
        raise forbidden()


@router.get("/admin/organizations/{organization_id}/memberships")
def memberships(organization_id: str, request: Request, user: SuperAdmin, connection: Db):
    same_organization(organization_id, user)
    return success(request, all_rows(connection, """SELECT m.id,m.user_id,u.email,u.name,m.role,m.festival_scope,m.status,m.created_at
        FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organization_id=%s ORDER BY m.created_at""", (organization_id,)))


@router.post("/admin/organizations/{organization_id}/memberships", status_code=201)
def create_membership(organization_id: str, body: MembershipIn, request: Request, user: SuperAdmin, connection: Db):
    same_organization(organization_id, user)
    account = one(connection, """INSERT INTO users(email,password_hash,name) VALUES(%s,%s,%s)
        ON CONFLICT(email) DO UPDATE SET name=excluded.name RETURNING id,email,name""", (str(body.email), hash_password(body.password), body.name))
    row = one(connection, "INSERT INTO memberships(organization_id,user_id,role,festival_scope) VALUES(%s,%s,%s,%s) RETURNING *",
        (organization_id, account["id"], body.role, jsonb(body.festival_scope)))
    row["user"] = account
    return success(request, row)


@router.patch("/admin/organizations/{organization_id}/memberships/{membership_id}")
def patch_membership(organization_id: str, membership_id: str, body: MembershipPatch, request: Request, user: SuperAdmin, connection: Db):
    same_organization(organization_id, user)
    row = found(one(connection, """UPDATE memberships SET role=coalesce(%s,role),festival_scope=coalesce(%s,festival_scope),status=coalesce(%s,status)
        WHERE id=%s AND organization_id=%s RETURNING *""",
        (body.role, jsonb(body.festival_scope) if body.festival_scope is not None else None, body.status, membership_id, organization_id)))
    return success(request, row)


@router.delete("/admin/organizations/{organization_id}/memberships/{membership_id}", status_code=204)
def deactivate_membership(organization_id: str, membership_id: str, user: SuperAdmin, connection: Db) -> Response:
    same_organization(organization_id, user)
    if membership_id == str(user["membership_id"]):
        raise bad_request("SELF_DEACTIVATION_DENIED", "현재 소속은 비활성화할 수 없습니다.")
    connection.execute("UPDATE memberships SET status='INACTIVE' WHERE id=%s AND organization_id=%s", (membership_id, organization_id))
    return Response(status_code=204)


@router.get("/admin/festivals/{festival_id}/audit-logs")
def audit_logs(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db,
               limit: int = Query(20, ge=1, le=100), action: str | None = None,
               resource_type: Annotated[str | None, Query(alias="resourceType")] = None):
    rows = all_rows(connection, """SELECT * FROM audit_logs WHERE festival_id=%s AND (%s::text IS NULL OR action=%s)
        AND (%s::text IS NULL OR resource_type=%s) ORDER BY created_at DESC LIMIT %s""",
        (festival_id, action, action, resource_type, resource_type, limit))
    return success(request, rows, page={"nextCursor": None, "hasNext": False, "limit": limit})


@router.post("/admin/festivals/{festival_id}/exports", status_code=202)
def create_export(festival_id: str, body: GenericExportIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO jobs(festival_id,job_type,resource_type,status,result)
        VALUES(%s,'EXPORT',%s,'COMPLETED',%s) RETURNING *""",
        (festival_id, body.resource_type, jsonb({"format": body.format, "message": "내보내기 작업이 기록되었습니다."})))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="EXPORT", resource_type=body.resource_type,
          resource_id=str(row["id"]), after_data={"format": body.format}, request_id=request.state.request_id)
    return success(request, {"jobId": row["id"], "status": row["status"]})


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, user: User, connection: Db):
    row = found(one(connection, """SELECT j.* FROM jobs j JOIN festivals f ON f.id=j.festival_id WHERE j.id=%s AND f.organization_id=%s
        AND (%s OR %s::jsonb ? j.festival_id::text OR %s::jsonb ? '*')""",
        (job_id, user["organization_id"], user["role"] == "SUPER_ADMIN", jsonb(user["festival_scope"]), jsonb(user["festival_scope"]))))
    return success(request, row)
