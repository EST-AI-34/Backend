from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from psycopg import Connection

from ..db import all_rows, audit, jsonb, one
from ..deps import Db, IfMatch, Manager, Operator, Scope, SuperAdmin, User
from ..domain import validate_ticket_transition
from ..errors import bad_request, conflict, forbidden, found
from ..esg_export import build_table_artifact
from ..jobs import PURGE_EVERY_TICKS
from ..http import Raw, cursor_params, keyset, paged, success
from ..privacy import CONSENT_ITEMS, RETENTION_POLICY, purge_personal_data, purge_sessions
from .admin_core import created, patch_row
from ..schemas import (AnnouncementDraftIn, AnnouncementIn, AnnouncementPatch, GenericExportIn, MembershipIn,
                       MembershipPatch, PrivacyRequestPatch, PublishAnnouncementIn, SurveyIn, SurveyPatch,
                       KioskCameraPatch, TicketIn, TicketPatch, TicketTransitionIn)
from ..security import hash_password


router = APIRouter()


def publish_announcement_row(connection, request: Request, user: dict, festival_id: str, announcement_id: str,
                             content_version_id: str, body, *, only_draft: bool) -> dict | None:
    """공지에 게시 값을 반영하고 감사 로그를 남긴다. 시작 시각이 미래면 SCHEDULED.

    새로 만들어 바로 게시하는 경로와 초안을 게시하는 경로가 같은 UPDATE를 쓴다.
    only_draft는 초안만 게시하도록 막는다 — 조건에 걸리면 None을 돌려주고 호출부가 처리한다.
    """
    status = "SCHEDULED" if body.starts_at > datetime.now(UTC) else "ACTIVE"
    row = one(connection, f"""UPDATE announcements SET content_version_id=%s,severity=%s,audience=%s,target_area_ids=%s,
        starts_at=%s,ends_at=%s,status=%s,version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s{" AND status='DRAFT'" if only_draft else ""} RETURNING *""",
        (content_version_id, body.severity, jsonb(body.audience), jsonb(body.target_area_ids),
         body.starts_at, body.ends_at, status, announcement_id, festival_id))
    if row:
        audit(connection, festival_id=festival_id, actor_id=str(user["id"]),
              action="PUBLISH_EMERGENCY" if body.severity == "EMERGENCY" else "PUBLISH",
              resource_type="ANNOUNCEMENT", resource_id=str(announcement_id), after_data=row,
              request_id=request.state.request_id)
    return row


@router.get("/admin/festivals/{festival_id}/announcements")
def announcements(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, """SELECT *,CASE WHEN ends_at IS NOT NULL AND ends_at<=now()
        AND status IN('ACTIVE','SCHEDULED') THEN 'EXPIRED' ELSE status END AS effective_status
        FROM announcements WHERE festival_id=%s ORDER BY created_at DESC""", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/announcements", status_code=201)
def create_announcement(festival_id: str, body: AnnouncementIn, request: Request, _: Scope, user: Operator, connection: Db):
    row = one(connection, "INSERT INTO announcements(festival_id,title,created_by) VALUES(%s,%s,%s) RETURNING *", (festival_id, body.title, user["id"]))
    created(connection, request, user, festival_id, "ANNOUNCEMENT", row)
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
    row = publish_announcement_row(connection, request, user, festival_id, str(announcement["id"]), str(version["id"]),
                                   body, only_draft=False)
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
    row = publish_announcement_row(connection, request, user, festival_id, announcement_id, body.content_version_id,
                                   body, only_draft=True)
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "초안 공지만 게시할 수 있습니다.")
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
    rows = all_rows(connection, f"""SELECT * FROM ops_tickets WHERE festival_id=%(festival_id)s AND {VISIBLE_TICKET}
        AND (%(status)s::text IS NULL OR status=%(status)s)
        AND {keyset()}
        ORDER BY created_at DESC,id DESC LIMIT %(limit)s""",
        {"festival_id": festival_id, "role": user["role"], "user_id": user["id"], "status": status,
         **cursor_params(cursor, limit)})
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
    created(connection, request, user, festival_id, "OPS_TICKET", row)
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
    created(connection, request, user, festival_id, "SURVEY", row)
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
    created(connection, request, user, None, "MEMBERSHIP", row, {"email": account["email"], "role": body.role})
    return success(request, row)


@router.patch("/admin/organizations/{organization_id}/memberships/{membership_id}")
def patch_membership(organization_id: str, membership_id: str, body: MembershipPatch, request: Request, user: SuperAdmin, connection: Db):
    same_organization(organization_id, user)
    # 자기 소속의 역할·상태를 스스로 바꾸면 조직에 SUPER_ADMIN이 한 명도 없는 상태로 잠길 수 있다.
    if membership_id == str(user["membership_id"]) and (body.role is not None or body.status is not None):
        raise bad_request("SELF_ROLE_CHANGE_DENIED", "본인 소속의 역할과 상태는 다른 최고 관리자가 변경해야 합니다.")
    before = found(one(connection, "SELECT * FROM memberships WHERE id=%s AND organization_id=%s", (membership_id, organization_id)))
    # deactivated_at은 상인 계정 보유기간(비활성화 후 1년, OPS-11)의 기준점이라 상태와 함께 남긴다.
    row = found(one(connection, """UPDATE memberships SET role=coalesce(%(role)s,role),
        festival_scope=coalesce(%(scope)s,festival_scope),status=coalesce(%(status)s,status),
        deactivated_at=CASE WHEN coalesce(%(status)s,status)='INACTIVE' THEN coalesce(deactivated_at,now()) END
        WHERE id=%(membership_id)s AND organization_id=%(organization_id)s RETURNING *""",
        {"role": body.role, "scope": jsonb(body.festival_scope) if body.festival_scope is not None else None,
         "status": body.status, "membership_id": membership_id, "organization_id": organization_id}))
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="UPDATE", resource_type="MEMBERSHIP",
          resource_id=membership_id, before_data=before, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.delete("/admin/organizations/{organization_id}/memberships/{membership_id}", status_code=204)
def deactivate_membership(organization_id: str, membership_id: str, request: Request, user: SuperAdmin, connection: Db) -> Response:
    same_organization(organization_id, user)
    if membership_id == str(user["membership_id"]):
        raise bad_request("SELF_DEACTIVATION_DENIED", "현재 소속은 비활성화할 수 없습니다.")
    before = found(one(connection, "SELECT * FROM memberships WHERE id=%s AND organization_id=%s", (membership_id, organization_id)))
    connection.execute("UPDATE memberships SET status='INACTIVE',deactivated_at=coalesce(deactivated_at,now()) WHERE id=%s AND organization_id=%s",
                       (membership_id, organization_id))
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
    rows = all_rows(connection, f"""SELECT al.*,u.name AS actor_name,u.email AS actor_email
        FROM audit_logs al LEFT JOIN users u ON u.id=al.actor_id
        WHERE al.festival_id=%(festival_id)s
        AND (%(action)s::text IS NULL OR al.action=%(action)s)
        AND (%(resource_type)s::text IS NULL OR al.resource_type=%(resource_type)s)
        AND {keyset(alias="al")}
        ORDER BY al.created_at DESC,al.id DESC LIMIT %(limit)s""",
        {"festival_id": festival_id, "action": action, "resource_type": resource_type,
         **cursor_params(cursor, limit)})
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


SESSION_DATA_SUMMARY = """SELECT
    (SELECT count(*) FROM bookings WHERE visitor_session_id=%(session_id)s)::int AS bookings,
    (SELECT count(*) FROM coupon_issues WHERE visitor_session_id=%(session_id)s)::int AS coupon_issues,
    (SELECT count(*) FROM reward_events WHERE visitor_session_id=%(session_id)s)::int AS reward_events,
    (SELECT coalesce(sum(points_delta),0)::int FROM point_ledger WHERE visitor_session_id=%(session_id)s) AS points,
    (SELECT count(*) FROM course_plans WHERE visitor_session_id=%(session_id)s)::int AS course_plans,
    (SELECT count(*) FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id
       WHERE c.visitor_session_id=%(session_id)s)::int AS ai_messages"""

# 익명 처리되어 정보주체를 특정할 수 없는 항목. 열람·삭제 요구 대상에서 제외하고 그 사실을 함께 알린다.
PRIVACY_EXCLUDED = ["설문 응답(VIS-10) — 제출 이후 응답자를 특정할 수 없어 보유기간 경과 시 일괄 파기만 적용합니다."]


@router.get("/admin/festivals/{festival_id}/privacy/policy")
def privacy_policy(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    """OPS-11 항목별 보유기간 정책표와 동의 항목. 방문객 화면과 같은 정의를 쓴다."""
    last_purge = one(connection, """SELECT created_at,after_data FROM audit_logs
        WHERE action='PURGE' AND resource_type='PERSONAL_DATA' ORDER BY created_at DESC LIMIT 1""")
    return success(request, {"retentionPolicy": RETENTION_POLICY, "consentItems": CONSENT_ITEMS,
                             "purgeSchedule": f"{PURGE_EVERY_TICKS // 3600 or 1}시간마다 자동 실행", "lastPurge": last_purge})


@router.get("/admin/festivals/{festival_id}/privacy/requests")
def privacy_requests(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db, status: str | None = None):
    return success(request, all_rows(connection, """SELECT pr.*,u.name AS handler_name FROM privacy_requests pr
        LEFT JOIN users u ON u.id=pr.handled_by WHERE pr.festival_id=%(festival_id)s
        AND (%(status)s::text IS NULL OR pr.status=%(status)s) ORDER BY pr.created_at DESC LIMIT 200""",
        {"festival_id": festival_id, "status": status}))


@router.post("/admin/festivals/{festival_id}/privacy/requests/{privacy_request_id}/handle")
def handle_privacy_request(festival_id: str, privacy_request_id: str, body: PrivacyRequestPatch, request: Request,
                           _: Scope, user: Manager, connection: Db):
    """열람·삭제 요구 처리.

    삭제를 완료하면 해당 방문 세션의 데이터를 참조 데이터까지 연쇄 파기한다. 요구 자체는
    이력으로 남아야 하므로, 세션을 지우기 전에 요구와의 연결을 끊고 결과 요약만 남긴다.
    """
    before = found(one(connection, "SELECT * FROM privacy_requests WHERE id=%s AND festival_id=%s FOR UPDATE",
                       (privacy_request_id, festival_id)))
    if before["status"] in ("COMPLETED", "REJECTED"):
        raise bad_request("INVALID_STATE_TRANSITION", "이미 종결된 요구입니다.")
    result = None
    if body.status == "COMPLETED":
        if not before["visitor_session_id"]:
            raise bad_request("SUBJECT_NOT_IDENTIFIABLE", "식별자가 없어 대상 데이터를 특정할 수 없습니다.")
        summary = one(connection, SESSION_DATA_SUMMARY, {"session_id": before["visitor_session_id"]})
        result = {"collected": summary, "excluded": PRIVACY_EXCLUDED}
        if before["request_type"] == "DELETE":
            # 요구 자체는 이력으로 남아야 하므로 연결을 먼저 끊는다(privacy_requests도 세션의 자식이다).
            connection.execute("UPDATE privacy_requests SET visitor_session_id=NULL WHERE id=%s", (privacy_request_id,))
            result["deletedRows"] = purge_sessions(connection, "id=%s", (before["visitor_session_id"],))
    row = one(connection, """UPDATE privacy_requests SET status=%s,detail=coalesce(%s,detail),result=%s,
        handled_by=%s,handled_at=now(),updated_at=now() WHERE id=%s RETURNING *""",
        (body.status, body.note, jsonb(result) if result else None, user["id"], privacy_request_id))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.status,
          resource_type="PRIVACY_REQUEST", resource_id=privacy_request_id, before_data=before, after_data=row,
          request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/privacy/purge")
def run_privacy_purge(festival_id: str, request: Request, _: Scope, user: SuperAdmin, connection: Db):
    """정책표에 따른 파기를 즉시 실행한다. 평상시에는 잡 워커가 주기적으로 같은 함수를 돌린다."""
    counts = purge_personal_data(connection)
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="PURGE_MANUAL",
          resource_type="PERSONAL_DATA", resource_id=None, after_data=counts, request_id=request.state.request_id)
    return success(request, {"purged": counts, "policy": RETENTION_POLICY})


@router.get("/admin/festivals/{festival_id}/visitor-identity")
def visitor_identity(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    """VIS-11 식별자 재발급과 한도 우회 의심 패턴.

    같은 기기 버킷에서 식별자가 두 번 이상 발급되면 저장소 초기화·기기 변경으로 1인당
    한도가 초기화됐을 수 있다. 발급 횟수와 그 세션들의 쿠폰·리워드·예약 건수를 함께 보여
    운영자가 부정 패턴을 판단할 수 있게 한다.
    """
    rows = all_rows(connection, """WITH buckets AS (
          SELECT device_key,array_agg(visitor_session_id) AS session_ids,count(*)::int AS session_count,
                 min(created_at) AS first_at,max(created_at) AS last_at
          FROM visitor_identity_events WHERE festival_id=%s GROUP BY device_key HAVING count(*)>1
        )
        SELECT left(b.device_key,8) AS device_key,b.session_count,b.first_at,b.last_at,
          (SELECT count(*) FROM coupon_issues ci WHERE ci.visitor_session_id=ANY(b.session_ids))::int AS coupon_issues,
          (SELECT count(*) FROM reward_events re WHERE re.visitor_session_id=ANY(b.session_ids))::int AS reward_events,
          (SELECT count(*) FROM bookings bk WHERE bk.visitor_session_id=ANY(b.session_ids))::int AS bookings
        FROM buckets b ORDER BY b.session_count DESC,b.last_at DESC LIMIT 100""", (festival_id,))
    totals = one(connection, """SELECT count(*)::int AS issuances,
        count(*) FILTER(WHERE event_type='REISSUED')::int AS reissues,
        count(DISTINCT device_key)::int AS devices FROM visitor_identity_events WHERE festival_id=%s""", (festival_id,))
    return success(request, {"totals": totals, "suspects": rows})


@router.get("/admin/festivals/{festival_id}/notification-deliveries")
def notification_deliveries(festival_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    """OPS-10 발송 이력과 세션별 노출 확인 결과.

    웹 폴링이 유일한 채널이라 '도달'은 해당 화면을 열어 둔 세션의 폴링 응답에 실렸는지로만
    확인된다. 백그라운드·종료 세션은 도달 보장 범위 밖이므로 노출 세션 수만 사실대로 센다.
    """
    announcements = all_rows(connection, """SELECT a.id,a.title,a.severity,a.target_area_ids,a.starts_at,a.status,
        count(nd.id)::int AS delivered_sessions,min(nd.delivered_at) AS first_delivered_at,max(nd.delivered_at) AS last_delivered_at,
        round(extract(epoch FROM min(nd.delivered_at)-a.starts_at))::int AS first_delivery_lag_seconds
        FROM announcements a LEFT JOIN notification_deliveries nd
          ON nd.resource_type='ANNOUNCEMENT' AND nd.resource_id=a.id
        WHERE a.festival_id=%s AND a.status<>'DRAFT' GROUP BY a.id ORDER BY a.starts_at DESC NULLS LAST LIMIT 100""",
        (festival_id,))
    calls = one(connection, """SELECT count(*) FILTER(WHERE b.status='CALLED')::int AS called,
        count(nd.id)::int AS delivered,
        round(avg(extract(epoch FROM nd.delivered_at-b.called_at)))::int AS avg_lag_seconds
        FROM bookings b LEFT JOIN notification_deliveries nd
          ON nd.resource_type='BOOKING_CALL' AND nd.resource_id=b.id
        WHERE b.festival_id=%s AND b.called_at IS NOT NULL""", (festival_id,))
    return success(request, {
        "announcements": announcements, "bookingCalls": calls,
        "channel": {"type": "WEB_POLL", "announcementPollSeconds": 30, "bookingPollSeconds": 10,
                    "limitation": "웹 폴링은 화면이 열려 있는 세션에만 도달합니다. 백그라운드·종료 세션은 도달 보장 범위에서 제외되므로 긴급 상황은 현장 방송 등 오프라인 수단을 병행해야 합니다."},
    })


# ESG-G-08 이용자 대상 공개 안내. 화면 문구가 아니라 처리 원칙 자체이므로 API가 단일 기준으로 낸다.
KIOSK_CAMERA_NOTICE = {
    "purpose": "키오스크 화면의 글씨 크기를 제안하기 위해서만 얼굴을 일시적으로 감지해 연령대를 추정합니다. 신원 확인이 아닙니다.",
    "choice": "카메라 사용은 선택입니다. 거절하거나 카메라가 없어도 모든 기능을 그대로 이용할 수 있고, 큰 글씨·음성 안내는 언제든 버튼으로 켤 수 있습니다.",
    "processingLocation": "추정은 키오스크 기기 안에서만 수행됩니다.",
    "retention": "영상·얼굴 이미지·특징값·추정 연령은 저장하지 않고 분석 직후 폐기하며 서버로 전송하지 않습니다.",
    "prohibitedUse": "추정 결과를 가격·입장·자격·추천 우선순위·서비스 이용 제한에 사용하지 않습니다.",
}


def kiosk_camera_state(connection, festival_id: str) -> dict:
    row = found(one(connection, "SELECT kiosk_camera_enabled,kiosk_camera_stop_reason FROM festivals WHERE id=%s", (festival_id,)))
    return {"enabled": row["kiosk_camera_enabled"], "stopReason": row["kiosk_camera_stop_reason"], "notice": KIOSK_CAMERA_NOTICE}


@router.get("/admin/festivals/{festival_id}/kiosk-camera")
def kiosk_camera(festival_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    """ESG-G-08 카메라·AI 투명성 화면: 공개 안내, 중지 스위치 상태, 익명 효과 지표.

    지표는 kiosk_assist_events 건수만으로 계산한다 — 방문객 세션과 잇지 않으므로 개별
    이용자가 어떤 추정을 받았는지는 조회할 수 없다. 연령대 판정 결과도 익명 범주와
    시각·모델 버전만 남기며 영상·얼굴 특징값·추정 나이는 저장하지 않는다.
    """
    counts = {row["event_type"]: row["count"] for row in all_rows(connection,
        """SELECT event_type,count(*)::int AS count FROM kiosk_assist_events
           WHERE festival_id=%s GROUP BY event_type""", (festival_id,))}
    models = all_rows(connection, """SELECT coalesce(model_version,'(미기록)') AS model_version,count(*)::int AS count,
        max(created_at) AS last_seen_at FROM kiosk_assist_events WHERE festival_id=%s
        GROUP BY 1 ORDER BY count DESC""", (festival_id,))
    estimate_result_counts = {row["result"]: row["count"] for row in all_rows(connection,
        """SELECT result,count(*)::int AS count FROM kiosk_assist_events
           WHERE festival_id=%s AND event_type='ESTIMATE_RESULT'
           GROUP BY result ORDER BY result""", (festival_id,))}
    estimate_result_log = all_rows(connection, """SELECT result,
        coalesce(model_version,'(미기록)') AS model_version,created_at
        FROM kiosk_assist_events
        WHERE festival_id=%s AND event_type='ESTIMATE_RESULT'
        ORDER BY created_at DESC LIMIT 100""", (festival_id,))
    granted = counts.get("CONSENT_GRANTED", 0)
    suggested = counts.get("SUGGESTED", 0)
    accepted = counts.get("ACCEPTED", 0)
    return success(request, {
        **kiosk_camera_state(connection, festival_id),
        "counts": counts,
        "models": models,
        "estimateResults": {"counts": estimate_result_counts, "recent": estimate_result_log},
        # 분모가 0이면 비율을 만들지 않는다. 0%로 내리면 "한 번도 안 썼다"가 "다 실패했다"로 읽힌다.
        "rates": {
            "consentAcceptRate": _rate(granted, counts.get("CONSENT_SHOWN", 0)),
            "estimateFailureRate": _rate(counts.get("ESTIMATE_FAILED", 0), granted),
            "suggestionAcceptRate": _rate(accepted, suggested),
            "manualLargeTextCount": counts.get("MANUAL_LARGE_TEXT", 0),
            "taskCompletedCount": counts.get("TASK_COMPLETED", 0),
        },
    })


def _rate(part: int, total: int) -> float | None:
    return round(part / total, 3) if total else None


@router.patch("/admin/festivals/{festival_id}/kiosk-camera")
def update_kiosk_camera(festival_id: str, body: KioskCameraPatch, request: Request, _: Scope, user: Manager, connection: Db):
    """카메라 제안 켜기·중지. 편향·오탐이 확인되면 여기서 내리고 수동 접근성 모드만 남긴다.

    중지 사유를 감사 로그에 남긴다 — 정기 점검 결과가 기록으로 남지 않으면 ESG-G-08의
    '감시·중지 장치'가 스위치 하나로 끝나 버린다.
    """
    if not body.enabled and not (body.stop_reason or "").strip():
        raise bad_request("STOP_REASON_REQUIRED", "카메라 제안을 중지할 때는 사유를 입력해 주세요.")
    before = kiosk_camera_state(connection, festival_id)
    connection.execute("UPDATE festivals SET kiosk_camera_enabled=%s,kiosk_camera_stop_reason=%s WHERE id=%s",
                       (body.enabled, None if body.enabled else body.stop_reason.strip(), festival_id))
    after = kiosk_camera_state(connection, festival_id)
    audit(connection, festival_id=festival_id, actor_id=user["id"], action="KIOSK_CAMERA_TOGGLE",
          resource_type="FESTIVALS", resource_id=festival_id, request_id=request.state.request_id,
          before_data={"enabled": before["enabled"], "stopReason": before["stopReason"]},
          after_data={"enabled": after["enabled"], "stopReason": after["stopReason"]})
    return success(request, after)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, user: User, connection: Db):
    row = found(one(connection, """SELECT j.* FROM jobs j JOIN festivals f ON f.id=j.festival_id
        WHERE j.id=%(job_id)s AND f.organization_id=%(organization_id)s
        AND (%(super_admin)s OR %(scope)s::jsonb ? j.festival_id::text OR %(scope)s::jsonb ? '*')""",
        {"job_id": job_id, "organization_id": user["organization_id"],
         "super_admin": user["role"] == "SUPER_ADMIN", "scope": jsonb(user["festival_scope"])}))
    return success(request, row)
