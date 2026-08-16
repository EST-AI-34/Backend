from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from psycopg import Connection

from ..db import all_rows, audit, jsonb, one
from ..deps import Db, IfMatch, Manager, Operator, Scope, SuperAdmin, User
from ..domain import validate_ticket_transition
from ..errors import bad_request, conflict, forbidden, found
from ..esg_export import build_table_artifact
from ..http import Raw, decode_cursor, paged, success
from .admin_core import patch_row
from ..schemas import (AnnouncementDraftIn, AnnouncementIn, AnnouncementPatch, GenericExportIn, MembershipIn,
                       MembershipPatch, PublishAnnouncementIn, SurveyIn, SurveyPatch, TicketIn, TicketPatch,
                       TicketTransitionIn)
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
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="CREATE", resource_type="ANNOUNCEMENT",
          resource_id=str(row["id"]), after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/announcements/publish", status_code=201)
def create_and_publish_announcement(festival_id: str, body: AnnouncementDraftIn, request: Request, _: Scope,
                                    user: Manager, connection: Db):
    """공지 작성부터 게시까지 한 요청·한 트랜잭션.

    화면이 6번의 요청으로 나눠 부르던 흐름을 서버로 옮긴다. 중간 단계가 실패하면 전부
    롤백되므로, 방문객에게 보이지 않는 DRAFT 공지와 고아 콘텐츠 항목이 남지 않는다.
    공지는 현장에서 즉시 나가야 해서 작성자 자가 승인이 허용된 유형이다(감사 로그로 추적).
    """
    announcement = one(connection, "INSERT INTO announcements(festival_id,title,created_by) VALUES(%s,%s,%s) RETURNING *",
        (festival_id, body.title, user["id"]))
    item = one(connection, """INSERT INTO content_items(festival_id,content_type,resource_type,resource_id,slug)
        VALUES(%s,'ANNOUNCEMENT','ANNOUNCEMENT',%s,%s) RETURNING *""",
        (festival_id, announcement["id"], f"announcement-{announcement['id']}"))
    version = one(connection, """INSERT INTO content_versions(content_item_id,author_id,version_no,language,body,status)
        VALUES(%s,%s,1,%s,%s,'APPROVED') RETURNING *""",
        (item["id"], user["id"], "ko", jsonb({"title": body.title, "text": body.body})))
    connection.execute("INSERT INTO content_approvals(content_version_id,reviewer_id,decision,comment) VALUES(%s,%s,'APPROVED',%s)",
        (version["id"], user["id"], "현장 공지 즉시 승인"))
    connection.execute("UPDATE content_items SET published_version_id=%s,lifecycle_status='PUBLISHED',updated_at=now() WHERE id=%s",
        (version["id"], item["id"]))
    status = "SCHEDULED" if body.starts_at > datetime.now(UTC) else "ACTIVE"
    row = one(connection, """UPDATE announcements SET content_version_id=%s,severity=%s,audience=%s,target_area_ids=%s,
        starts_at=%s,ends_at=%s,status=%s,version=version+1,updated_at=now() WHERE id=%s RETURNING *""",
        (version["id"], body.severity, jsonb(body.audience), jsonb(body.target_area_ids),
         body.starts_at, body.ends_at, status, announcement["id"]))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]),
          action="PUBLISH_EMERGENCY" if body.severity == "EMERGENCY" else "PUBLISH",
          resource_type="ANNOUNCEMENT", resource_id=str(announcement["id"]), after_data=row,
          request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/announcements/{announcement_id}")
def announcement(festival_id: str, announcement_id: str, request: Request, _: Scope, connection: Db):
    return success(request, found(one(connection, "SELECT * FROM announcements WHERE id=%s AND festival_id=%s", (announcement_id, festival_id))))


@router.patch("/admin/festivals/{festival_id}/announcements/{announcement_id}")
def update_announcement(festival_id: str, announcement_id: str, body: AnnouncementPatch, request: Request, _: Scope, user: Operator, connection: Db):
    return success(request, patch_row(connection, request, user, "announcements", announcement_id, festival_id, body,
                                      require="status='DRAFT'", conflict_message="초안 상태와 버전을 확인해 주세요."))


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


# 현장 운영자는 민원과 본인이 맡거나 만든 티켓만 본다. 목록·단건 조회가 같은 조건을 써야 하므로 한 곳에 둔다.
VISIBLE_TICKET = ("(ticket_type='COMPLAINT' OR %(role)s<>'FIELD_OPERATOR' "
                  "OR assignee_id=%(user_id)s OR created_by=%(user_id)s)")


def visible_ticket(connection: Connection, ticket_id: str, festival_id: str, user: dict) -> dict:
    return found(one(connection, f"""SELECT * FROM ops_tickets
        WHERE id=%(ticket_id)s AND festival_id=%(festival_id)s AND {VISIBLE_TICKET}""",
        {"ticket_id": ticket_id, "festival_id": festival_id, "role": user["role"], "user_id": user["id"]}))


@router.get("/admin/festivals/{festival_id}/ops-tickets")
def tickets(festival_id: str, request: Request, _: Scope, user: Operator, connection: Db, status: str | None = None,
            limit: int = Query(100, ge=1, le=200), cursor: str | None = None):
    """티켓 목록.

    축제 기간 내내 쌓이는 목록이라 전량 반환은 응답이 무한정 커진다. 감사 로그와 같은
    (created_at, id) 키셋 커서를 쓴다 — 우선순위 정렬은 페이지 안에서 다시 적용한다.
    """
    after = decode_cursor(cursor)
    rows = all_rows(connection, f"""SELECT * FROM ops_tickets WHERE festival_id=%(festival_id)s AND {VISIBLE_TICKET}
        AND (%(status)s::text IS NULL OR status=%(status)s)
        AND (%(after_at)s::timestamptz IS NULL OR (created_at,id) < (%(after_at)s::timestamptz,%(after_id)s::uuid))
        ORDER BY created_at DESC,id DESC LIMIT %(limit)s""",
        {"festival_id": festival_id, "role": user["role"], "user_id": user["id"], "status": status,
         "after_at": after[0] if after else None, "after_id": after[1] if after else None, "limit": limit + 1})
    rows, page = paged(rows, limit)
    priority_rank = {"EMERGENCY": 1, "HIGH": 2, "NORMAL": 3}
    rows.sort(key=lambda row: (priority_rank.get(row["priority"], 4), row["created_at"]))
    return success(request, rows, page=page)


@router.post("/admin/festivals/{festival_id}/ops-tickets", status_code=201)
def create_ticket(festival_id: str, body: TicketIn, request: Request, _: Scope, user: Operator, connection: Db):
    row = one(connection, """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,area_id,priority,assignee_id,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.ticket_type, body.title, body.description, body.area_id, body.priority, body.assignee_id, user["id"]))
    connection.execute("INSERT INTO ops_ticket_events(ticket_id,actor_id,to_status,note) VALUES(%s,%s,'OPEN','티켓 생성')", (row["id"], user["id"]))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="CREATE", resource_type="OPS_TICKET",
          resource_id=str(row["id"]), after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}")
def ticket(festival_id: str, ticket_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    return success(request, visible_ticket(connection, ticket_id, festival_id, user))


@router.patch("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}")
def patch_ticket(festival_id: str, ticket_id: str, body: TicketPatch, request: Request, _: Scope, user: Operator, connection: Db):
    # 현장 운영자 가시성은 patch_row의 축제 범위 검사로는 부족해서 먼저 확인한다.
    visible_ticket(connection, ticket_id, festival_id, user)
    return success(request, patch_row(connection, request, user, "ops_tickets", ticket_id, festival_id, body,
                                      conflict_message="최신 티켓을 다시 조회해 주세요."))


@router.post("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}/transitions")
def transition_ticket(festival_id: str, ticket_id: str, body: TicketTransitionIn, request: Request, _: Scope, user: Operator, connection: Db):
    ticket = visible_ticket(connection, ticket_id, festival_id, user)
    validate_ticket_transition(ticket["status"], body.to_status, body.note)
    if body.to_status == "ASSIGNED" and not ticket["assignee_id"]:
        raise bad_request("ASSIGNEE_REQUIRED", "담당자를 먼저 지정해 주세요.")
    row = one(connection, """UPDATE ops_tickets SET status=%(status)s,version=version+1,updated_at=now(),
        resolved_at=CASE WHEN %(status)s='RESOLVED' THEN now() ELSE resolved_at END,
        closed_at=CASE WHEN %(status)s='CLOSED' THEN now() ELSE closed_at END
        WHERE id=%(ticket_id)s RETURNING *""",
        {"status": body.to_status, "ticket_id": ticket_id})
    connection.execute("""INSERT INTO ops_ticket_events(ticket_id,actor_id,from_status,to_status,note,attachments)
        VALUES(%s,%s,%s,%s,%s,%s)""", (ticket_id, user["id"], ticket["status"], body.to_status, body.note, jsonb(body.attachments)))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="TRANSITION", resource_type="OPS_TICKET",
          resource_id=ticket_id, before_data={"status": ticket["status"]}, after_data={"status": body.to_status}, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/ops-tickets/{ticket_id}/events")
def ticket_events(festival_id: str, ticket_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    visible_ticket(connection, ticket_id, festival_id, user)
    return success(request, all_rows(connection, "SELECT * FROM ops_ticket_events WHERE ticket_id=%s ORDER BY created_at", (ticket_id,)))


@router.get("/admin/festivals/{festival_id}/surveys")
def surveys(festival_id: str, request: Request, _: Scope, connection: Db):
    """설문 목록. 등록·수정 API가 없어 시드로만 만들 수 있던 것을 운영 화면에서 다루게 한다."""
    return success(request, all_rows(connection, """SELECT s.*,
        (SELECT count(*) FROM survey_responses r WHERE r.survey_id=s.id)::int AS response_count,
        coalesce(jsonb_agg(jsonb_build_object('id',q.id,'prompt',q.prompt,'questionType',q.question_type,
          'options',q.options,'required',q.required,'position',q.position) ORDER BY q.position)
          FILTER(WHERE q.id IS NOT NULL),'[]') AS questions
        FROM surveys s LEFT JOIN survey_questions q ON q.survey_id=s.id
        WHERE s.festival_id=%s GROUP BY s.id ORDER BY s.created_at DESC""", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/surveys", status_code=201)
def create_survey(festival_id: str, body: SurveyIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO surveys(festival_id,title,description,starts_at,ends_at,status,prevent_duplicates)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.title, body.description, body.starts_at, body.ends_at, body.status, body.prevent_duplicates))
    for position, question in enumerate(body.questions, 1):
        connection.execute("""INSERT INTO survey_questions(survey_id,prompt,question_type,options,required,position)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (row["id"], question.prompt, question.question_type, jsonb(question.options), question.required, position))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="CREATE", resource_type="SURVEY",
          resource_id=str(row["id"]), after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.patch("/admin/festivals/{festival_id}/surveys/{survey_id}")
def update_survey(festival_id: str, survey_id: str, body: SurveyPatch, request: Request, _: Scope, user: Manager,
                  connection: Db, if_match: IfMatch = None):
    """설문 자체만 수정한다. 응답이 이미 쌓인 문항을 바꾸면 집계가 뒤섞이므로 문항은 건드리지 않는다."""
    return success(request, patch_row(connection, request, user, "surveys", survey_id, festival_id, body, if_match))


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
        option_counts: Raw = Raw()
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
    # 예전에는 ON CONFLICT(email) DO UPDATE SET name=... 이라 이미 있는 이메일이면 입력한
    # 비밀번호가 조용히 버려졌다. 운영자는 새 비밀번호를 발급했다고 믿지만 계정은 예전
    # 비밀번호를 유지한다. 남의 계정 비밀번호를 덮어쓰는 것도 답이 아니라 명시적으로 막는다.
    account = one(connection, """INSERT INTO users(email,password_hash,name) VALUES(%s,%s,%s)
        ON CONFLICT(email) DO NOTHING RETURNING id,email,name""", (str(body.email), hash_password(body.password), body.name))
    if not account:
        raise conflict("EMAIL_ALREADY_REGISTERED",
                       "이미 등록된 이메일입니다. 기존 계정에 소속을 추가하려면 계정 담당자에게 문의해 주세요.")
    row = one(connection, "INSERT INTO memberships(organization_id,user_id,role,festival_scope) VALUES(%s,%s,%s,%s) RETURNING *",
        (organization_id, account["id"], body.role, jsonb(body.festival_scope)))
    row["user"] = account
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="CREATE", resource_type="MEMBERSHIP",
          resource_id=str(row["id"]), after_data={"email": account["email"], "role": body.role}, request_id=request.state.request_id)
    return success(request, row)


@router.patch("/admin/organizations/{organization_id}/memberships/{membership_id}")
def patch_membership(organization_id: str, membership_id: str, body: MembershipPatch, request: Request, user: SuperAdmin, connection: Db):
    same_organization(organization_id, user)
    # 자기 소속의 역할·상태를 스스로 바꾸면 조직에 SUPER_ADMIN이 한 명도 없는 상태로 잠길 수 있다.
    if membership_id == str(user["membership_id"]) and (body.role is not None or body.status is not None):
        raise bad_request("SELF_ROLE_CHANGE_DENIED", "본인 소속의 역할과 상태는 다른 최고 관리자가 변경해야 합니다.")
    before = found(one(connection, "SELECT * FROM memberships WHERE id=%s AND organization_id=%s", (membership_id, organization_id)))
    row = found(one(connection, """UPDATE memberships SET role=coalesce(%s,role),festival_scope=coalesce(%s,festival_scope),status=coalesce(%s,status)
        WHERE id=%s AND organization_id=%s RETURNING *""",
        (body.role, jsonb(body.festival_scope) if body.festival_scope is not None else None, body.status, membership_id, organization_id)))
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="UPDATE", resource_type="MEMBERSHIP",
          resource_id=membership_id, before_data=before, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.delete("/admin/organizations/{organization_id}/memberships/{membership_id}", status_code=204)
def deactivate_membership(organization_id: str, membership_id: str, request: Request, user: SuperAdmin, connection: Db) -> Response:
    same_organization(organization_id, user)
    if membership_id == str(user["membership_id"]):
        raise bad_request("SELF_DEACTIVATION_DENIED", "현재 소속은 비활성화할 수 없습니다.")
    before = found(one(connection, "SELECT * FROM memberships WHERE id=%s AND organization_id=%s", (membership_id, organization_id)))
    connection.execute("UPDATE memberships SET status='INACTIVE' WHERE id=%s AND organization_id=%s", (membership_id, organization_id))
    # 계정 권한을 끊는 일이 감사 로그에 안 남아서, 누가 누구를 언제 비활성화했는지 추적되지 않았다.
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="DEACTIVATE", resource_type="MEMBERSHIP",
          resource_id=membership_id, before_data=before, after_data={"status": "INACTIVE"},
          request_id=request.state.request_id)
    return Response(status_code=204)


@router.get("/admin/festivals/{festival_id}/audit-logs")
def audit_logs(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db,
               limit: int = Query(20, ge=1, le=100), action: str | None = None,
               resource_type: Annotated[str | None, Query(alias="resourceType")] = None,
               cursor: str | None = None):
    """(created_at, id) 키셋 페이지네이션.

    예전에는 nextCursor=None, hasNext=False가 하드코딩돼 있어 limit 상한(100건) 너머는
    볼 방법이 없었다. 한 건 더 읽어서 다음 페이지 존재 여부를 판단한다.

    행위자는 users를 조인해 이름·이메일까지 준다. actor_id(UUID)만 내려주면 감사 화면이
    "3f2a1b0c…" 같은 값밖에 못 보여줘서 누가 무엇을 했는지 추적이 되지 않는다.
    """
    after = decode_cursor(cursor)
    rows = all_rows(connection, """SELECT al.*,u.name AS actor_name,u.email AS actor_email
        FROM audit_logs al LEFT JOIN users u ON u.id=al.actor_id
        WHERE al.festival_id=%(festival_id)s
        AND (%(action)s::text IS NULL OR al.action=%(action)s)
        AND (%(resource_type)s::text IS NULL OR al.resource_type=%(resource_type)s)
        AND (%(after_at)s::timestamptz IS NULL OR (al.created_at,al.id) < (%(after_at)s::timestamptz,%(after_id)s::uuid))
        ORDER BY al.created_at DESC,al.id DESC LIMIT %(limit)s""",
        {"festival_id": festival_id, "action": action, "resource_type": resource_type,
         "after_at": after[0] if after else None, "after_id": after[1] if after else None, "limit": limit + 1})
    rows, page = paged(rows, limit)
    return success(request, rows, page=page)


# 내보내기 대상 -> (조회 SQL, CSV 컬럼 순서). 여기 없는 resourceType은 400으로 막는다 —
# 예전에는 무엇을 넣든 안내 문구만 담은 빈 잡이 COMPLETED로 기록되고 실제 파일은 없었다.
EXPORT_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "AUDIT_LOG": ("""SELECT al.created_at,al.action,al.resource_type,al.resource_id,al.actor_id,
                            u.name AS actor_name,u.email AS actor_email,al.request_id
                     FROM audit_logs al LEFT JOIN users u ON u.id=al.actor_id
                     WHERE al.festival_id=%s ORDER BY al.created_at DESC LIMIT 10000""",
                  ("created_at", "action", "resource_type", "resource_id", "actor_id",
                   "actor_name", "actor_email", "request_id")),
    "OPS_TICKET": ("""SELECT created_at,ticket_type,title,priority,status,area_id,assignee_id,resolved_at,closed_at
                      FROM ops_tickets WHERE festival_id=%s ORDER BY created_at DESC LIMIT 10000""",
                   ("created_at", "ticket_type", "title", "priority", "status", "area_id", "assignee_id", "resolved_at", "closed_at")),
    "BOOKING": ("""SELECT b.created_at,b.status,b.party_size,b.queue_number,p.title AS program_title,ps.starts_at
                   FROM bookings b JOIN program_sessions ps ON ps.id=b.program_session_id
                   JOIN programs p ON p.id=ps.program_id WHERE b.festival_id=%s ORDER BY b.created_at DESC LIMIT 10000""",
                ("created_at", "status", "party_size", "queue_number", "program_title", "starts_at")),
}


@router.post("/admin/festivals/{festival_id}/exports", status_code=202)
def create_export(festival_id: str, body: GenericExportIn, request: Request, _: Scope, user: Manager, connection: Db):
    """운영 데이터 내보내기. 결과 파일은 `GET /jobs/{jobId}`의 result.artifacts에 담긴다."""
    source = EXPORT_SOURCES.get(body.resource_type)
    if not source:
        raise bad_request("UNSUPPORTED_EXPORT", f"내보낼 수 없는 대상입니다: {body.resource_type}")
    sql, columns = source
    rows = all_rows(connection, sql, (festival_id,))
    artifact = build_table_artifact(rows, columns, body.format, f"{body.resource_type.lower()}-{festival_id[:8]}")
    row = one(connection, """INSERT INTO jobs(festival_id,job_type,resource_type,status,result)
        VALUES(%s,'EXPORT',%s,'COMPLETED',%s) RETURNING *""",
        (festival_id, body.resource_type, jsonb({"format": body.format, "rowCount": len(rows), "artifacts": [artifact]})))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="EXPORT", resource_type=body.resource_type,
          resource_id=str(row["id"]), after_data={"format": body.format, "rowCount": len(rows)}, request_id=request.state.request_id)
    return success(request, {"jobId": row["id"], "status": row["status"], "rowCount": len(rows)})


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, user: User, connection: Db):
    row = found(one(connection, """SELECT j.* FROM jobs j JOIN festivals f ON f.id=j.festival_id
        WHERE j.id=%(job_id)s AND f.organization_id=%(organization_id)s
        AND (%(super_admin)s OR %(scope)s::jsonb ? j.festival_id::text OR %(scope)s::jsonb ? '*')""",
        {"job_id": job_id, "organization_id": user["organization_id"],
         "super_admin": user["role"] == "SUPER_ADMIN", "scope": jsonb(user["festival_scope"])}))
    return success(request, row)
