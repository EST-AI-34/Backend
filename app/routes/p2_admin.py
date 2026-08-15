import json

from fastapi import APIRouter, Request

from ..config import settings
from ..db import all_rows, audit, jsonb, one
from ..deps import Db, Manager, ManagerOrReviewer, Operator, Scope, User
from ..domain import classify_issue, is_safe_question, mask_sensitive, search_terms, validate_booking_transition
from ..errors import bad_request, conflict, found
from ..http import success
from ..schemas import (BookingStatusIn, BusinessIn, CouponIn, CrowdSnapshotIn, InternalDocumentIn,
                       InternalSearchIn, IssueAnalysisPatch, ReviewIn, RewardActionIn, RewardCampaignIn,
                       StaffAssignmentIn)


router = APIRouter()


def in_festival(connection, table: str, resource_id: str, festival_id: str) -> bool:
    return bool(one(connection, f"SELECT 1 FROM {table} WHERE id=%s AND festival_id=%s", (resource_id, festival_id)))


def insert_coupon(connection, business_id: str, body: CouponIn, created_by) -> dict:
    """운영자 경로와 상인 경로가 같은 쿠폰을 만든다. 접근 권한 검사는 각 라우트에 있다."""
    return one(connection, """INSERT INTO coupons(festival_business_id,name,description,benefit_type,benefit_value,issue_limit,
        per_visitor_limit,valid_from,valid_until,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (business_id, body.name, body.description, body.benefit_type, body.benefit_value, body.issue_limit,
         body.per_visitor_limit, body.starts_at, body.ends_at, created_by))


@router.get("/admin/festivals/{festival_id}/staff-assignments")
def staff_assignments(festival_id: str, request: Request, _: Scope, connection: Db):
    rows = all_rows(connection, """SELECT sa.*,u.name AS staff_name,m.role FROM staff_assignments sa
        JOIN memberships m ON m.id=sa.membership_id JOIN users u ON u.id=m.user_id
        WHERE sa.festival_id=%s ORDER BY sa.starts_at,u.name""", (festival_id,))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/staff-assignments", status_code=201)
def create_staff_assignment(festival_id: str, body: StaffAssignmentIn, request: Request, _: Scope, user: Manager, connection: Db):
    if not one(connection, """SELECT 1 FROM memberships m JOIN festivals f ON f.organization_id=m.organization_id
        JOIN festival_areas a ON a.festival_id=f.id WHERE m.id=%s AND a.id=%s AND f.id=%s AND m.status='ACTIVE'""",
        (body.membership_id, body.area_id, festival_id)):
        raise bad_request("FESTIVAL_SCOPE_MISMATCH", "인력과 구역의 축제 범위를 확인해 주세요.")
    if one(connection, "SELECT 1 FROM staff_assignments WHERE membership_id=%s AND starts_at<%s AND ends_at>%s",
           (body.membership_id, body.ends_at, body.starts_at)):
        raise conflict("SCHEDULE_CONFLICT", "해당 인력의 근무 시간이 겹칩니다.")
    row = one(connection, """INSERT INTO staff_assignments(festival_id,membership_id,area_id,duty_role,task,starts_at,ends_at,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.membership_id, body.area_id, body.duty_role, body.task, body.starts_at, body.ends_at, user["id"]))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="ASSIGN", resource_type="STAFF_ASSIGNMENT",
          resource_id=str(row["id"]), after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/staff-assignments/{assignment_id}/acknowledge")
def acknowledge_assignment(festival_id: str, assignment_id: str, request: Request, _: Scope, user: User, connection: Db):
    row = found(one(connection, """UPDATE staff_assignments SET acknowledged_at=now(),updated_at=now()
        WHERE id=%s AND festival_id=%s AND membership_id=%s RETURNING *""", (assignment_id, festival_id, user["membership_id"])),
        "본인에게 배정된 업무를 찾을 수 없습니다.")
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/crowd-snapshots")
def crowd_snapshots(festival_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, """SELECT cs.*,a.name AS area_name,p.title AS program_title
        FROM crowd_snapshots cs JOIN festival_areas a ON a.id=cs.area_id
        LEFT JOIN program_sessions ps ON ps.id=cs.program_session_id LEFT JOIN programs p ON p.id=ps.program_id
        WHERE cs.festival_id=%s ORDER BY cs.captured_at DESC LIMIT 200""", (festival_id,)))


@router.post("/admin/festivals/{festival_id}/crowd-snapshots", status_code=201)
def create_crowd_snapshot(festival_id: str, body: CrowdSnapshotIn, request: Request, _: Scope, user: Operator, connection: Db):
    if not in_festival(connection, "festival_areas", body.area_id, festival_id):
        raise bad_request("AREA_SCOPE_MISMATCH", "구역이 같은 축제에 속하지 않습니다.")
    if body.program_session_id and not in_festival(connection, "program_sessions", body.program_session_id, festival_id):
        raise bad_request("FESTIVAL_SCOPE_MISMATCH", "프로그램 회차가 같은 축제에 속하지 않습니다.")
    row = one(connection, """INSERT INTO crowd_snapshots(festival_id,area_id,program_session_id,source_type,crowd_level,
        people_count,estimated_wait_min,captured_at,expires_at,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, body.area_id, body.program_session_id, body.source_type, body.crowd_level, body.people_count, body.estimated_wait_min, body.captured_at, body.expires_at, user["id"]))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/bookings")
def bookings(festival_id: str, request: Request, _: Scope, connection: Db, status: str | None = None):
    rows = all_rows(connection, """SELECT b.id,b.status,b.party_size,b.queue_number,b.called_at,b.created_at,b.updated_at,
        ps.starts_at,ps.ends_at,p.id AS program_id,p.title AS program_title
        FROM bookings b JOIN program_sessions ps ON ps.id=b.program_session_id JOIN programs p ON p.id=ps.program_id
        WHERE b.festival_id=%s AND (%s::text IS NULL OR b.status=%s) ORDER BY ps.starts_at,b.queue_number NULLS FIRST,b.created_at""",
        (festival_id, status, status))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/bookings/{booking_id}/status")
def update_booking_status(festival_id: str, booking_id: str, body: BookingStatusIn, request: Request, _: Scope, user: Operator, connection: Db):
    booking = found(one(connection, "SELECT * FROM bookings WHERE id=%s AND festival_id=%s FOR UPDATE", (booking_id, festival_id)))
    validate_booking_transition(booking["status"], body.status)
    # ops_tickets 전이와 같은 방식이다 — 상태별 타임스탬프는 SQL CASE로 두고 SQL 문자열은 고정한다.
    row = one(connection, """UPDATE bookings SET status=%s,
        called_at=CASE WHEN %s='CALLED' THEN now() ELSE called_at END,
        completed_at=CASE WHEN %s='COMPLETED' THEN now() ELSE completed_at END,
        version=version+1,updated_at=now() WHERE id=%s RETURNING *""",
        (body.status, body.status, body.status, booking_id))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.status, resource_type="BOOKING",
          resource_id=booking_id, before_data=booking, after_data={**row, "note": body.note}, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/businesses")
def businesses(festival_id: str, request: Request, _: Scope, connection: Db, status: str | None = None):
    rows = all_rows(connection, """SELECT fb.*,b.registration_no,b.name,b.address,bo.id AS booth_id,bo.booth_no,bo.area_id
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id LEFT JOIN booths bo ON bo.festival_business_id=fb.id
        WHERE fb.festival_id=%s AND (%s::text IS NULL OR fb.participation_status=%s) ORDER BY b.name""", (festival_id, status, status))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/businesses", status_code=201)
def create_business(festival_id: str, body: BusinessIn, request: Request, _: Scope, user: Manager, connection: Db):
    contact = json.dumps(body.contact, ensure_ascii=False) if body.contact else None
    business = one(connection, """INSERT INTO businesses(organization_id,registration_no,name,contact_encrypted,address)
        VALUES(%s,%s,%s,CASE WHEN %s::text IS NULL THEN NULL ELSE pgp_sym_encrypt(%s,%s) END,%s)
        ON CONFLICT(organization_id,registration_no) DO UPDATE SET name=excluded.name,address=excluded.address,updated_at=now() RETURNING *""",
        (user["organization_id"], body.registration_no, body.name, contact, contact, settings.jwt_secret, jsonb(body.address)))
    row = one(connection, """INSERT INTO festival_businesses(festival_id,business_id,owner_membership_id,category,description,menu,operating_hours,accessibility)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, business["id"], body.owner_membership_id, body.category, body.description, jsonb(body.menu), jsonb(body.operating_hours), jsonb(body.accessibility)))
    if body.area_id and body.booth_no:
        if not in_festival(connection, "festival_areas", body.area_id, festival_id):
            raise bad_request("AREA_SCOPE_MISMATCH", "부스 구역이 같은 축제에 속하지 않습니다.")
        connection.execute("INSERT INTO booths(festival_business_id,area_id,booth_no) VALUES(%s,%s,%s)", (row["id"], body.area_id, body.booth_no))
    return success(request, {**row, "name": business["name"], "registrationNo": business["registration_no"]})


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/review")
def review_business(festival_id: str, business_id: str, body: ReviewIn, request: Request, _: Scope, user: ManagerOrReviewer, connection: Db):
    row = one(connection, """UPDATE festival_businesses SET participation_status=%s,review_comment=%s,approved_by=%s,
        approved_at=CASE WHEN %s='APPROVED' THEN now() ELSE NULL END,version=version+1,updated_at=now()
        WHERE id=%s AND festival_id=%s AND participation_status IN ('SUBMITTED','REJECTED') RETURNING *""",
        (body.decision, body.comment, user["id"], body.decision, business_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "제출 또는 반려 상태의 업체만 검토할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.decision, resource_type="FESTIVAL_BUSINESS",
          resource_id=business_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/businesses/{business_id}/coupons")
def coupons(festival_id: str, business_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, """SELECT c.*,(SELECT count(*) FROM coupon_issues ci WHERE ci.coupon_id=c.id)::int AS issued_count
        FROM coupons c JOIN festival_businesses fb ON fb.id=c.festival_business_id WHERE fb.festival_id=%s AND fb.id=%s ORDER BY c.created_at DESC""",
        (festival_id, business_id)))


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/coupons", status_code=201)
def create_coupon(festival_id: str, business_id: str, body: CouponIn, request: Request, _: Scope, user: Manager, connection: Db):
    if not one(connection, "SELECT 1 FROM festival_businesses WHERE id=%s AND festival_id=%s AND participation_status='APPROVED'", (business_id, festival_id)):
        raise bad_request("BUSINESS_NOT_APPROVED", "승인된 참여업체만 쿠폰을 발행할 수 있습니다.")
    return success(request, insert_coupon(connection, business_id, body, user["id"]))


@router.get("/admin/festivals/{festival_id}/reward-campaigns")
def reward_campaigns(festival_id: str, request: Request, _: Scope, connection: Db):
    """등록한 캠페인과 적립 행동을 다시 볼 수 있어야 운영자가 중복 등록을 피한다."""
    rows = all_rows(connection, """SELECT c.*, coalesce(jsonb_agg(jsonb_build_object(
            'id',a.id,'action_type',a.action_type,'verification_type',a.verification_type,
            'points',a.points,'per_user_limit',a.per_user_limit,'rule',a.rule)
            ORDER BY a.action_type) FILTER (WHERE a.id IS NOT NULL), '[]') AS actions
        FROM reward_campaigns c LEFT JOIN reward_actions a ON a.campaign_id=c.id
        WHERE c.festival_id=%s GROUP BY c.id ORDER BY c.starts_at DESC""", (festival_id,))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/reward-campaigns", status_code=201)
def create_reward_campaign(festival_id: str, body: RewardCampaignIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO reward_campaigns(festival_id,name,starts_at,ends_at,daily_point_limit,created_by)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""", (festival_id, body.name, body.starts_at, body.ends_at, body.daily_point_limit, user["id"]))
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/reward-campaigns/{campaign_id}/actions", status_code=201)
def create_reward_action(festival_id: str, campaign_id: str, body: RewardActionIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = found(one(connection, """INSERT INTO reward_actions(campaign_id,action_type,verification_type,points,per_user_limit,rule)
        SELECT %s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM reward_campaigns WHERE id=%s AND festival_id=%s) RETURNING *""",
        (campaign_id, body.action_type, body.verification_type, body.points, body.per_user_limit, jsonb(body.rule), campaign_id, festival_id)))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/internal-documents")
def internal_documents(festival_id: str, request: Request, _: Scope, user: User, connection: Db):
    """검색과 같은 권한 기준(allowed_roles)으로 목록도 본인이 열람 가능한 문서만 돌려준다."""
    rows = all_rows(connection, """SELECT id,title,document_type,source_url,allowed_roles,status,updated_at
        FROM internal_documents WHERE festival_id=%s AND status='ACTIVE' AND allowed_roles ? %s
        ORDER BY updated_at DESC""", (festival_id, user["role"]))
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/internal-documents", status_code=201)
def create_internal_document(festival_id: str, body: InternalDocumentIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO internal_documents(festival_id,title,document_type,body,source_url,allowed_roles,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id,title,document_type,source_url,allowed_roles,status,created_at""",
        (festival_id, body.title, body.document_type, body.body, body.source_url, jsonb(body.allowed_roles), user["id"]))
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/ai/operations/search")
def search_internal_documents(festival_id: str, body: InternalSearchIn, request: Request, _: Scope, user: User, connection: Db):
    if not is_safe_question(body.question):
        raise bad_request("UNSAFE_QUERY", "민감정보 또는 시스템 정보 요청은 검색할 수 없습니다.")
    patterns = [f"%{term}%" for term in search_terms(body.question)]
    rows = all_rows(connection, """SELECT id,title,document_type,body,source_url,updated_at FROM internal_documents
        WHERE festival_id=%s AND status='ACTIVE' AND allowed_roles ? %s AND body ILIKE ANY(%s)
        ORDER BY updated_at DESC LIMIT 5""", (festival_id, user["role"], patterns)) if patterns else []
    excerpts = [mask_sensitive(row["body"][:500]) for row in rows]
    return success(request, {"answer": "\n\n".join(excerpts) if excerpts else "권한 범위의 운영 문서에서 근거를 찾지 못했습니다.",
                             "sources": [{"documentId": row["id"], "title": row["title"], "sourceUrl": row["source_url"]} for row in rows]})


@router.get("/admin/festivals/{festival_id}/issue-analysis")
def issue_analysis(festival_id: str, request: Request, _: Scope, connection: Db):
    rows = all_rows(connection, """SELECT t.id,t.title,t.description,t.priority,t.status,o.topic,o.sentiment,o.urgent,o.note,o.updated_at
        FROM ops_tickets t LEFT JOIN issue_analysis_overrides o ON o.ticket_id=t.id WHERE t.festival_id=%s ORDER BY t.created_at DESC""", (festival_id,))
    for row in rows:
        inferred = classify_issue(f"{row['title']} {row['description']}", row["priority"])
        topic, sentiment, urgent, note = (row.pop(field) for field in ("topic", "sentiment", "urgent", "note"))
        row["analysis"] = {"topic": topic or inferred["topic"], "sentiment": sentiment or inferred["sentiment"],
                           "urgent": inferred["urgent"] if urgent is None else urgent,
                           "humanReviewed": row["updated_at"] is not None, "note": note}
    return success(request, rows)


@router.patch("/admin/festivals/{festival_id}/issue-analysis/{ticket_id}")
def override_issue_analysis(festival_id: str, ticket_id: str, body: IssueAnalysisPatch, request: Request, _: Scope, user: Operator, connection: Db):
    found(one(connection, "SELECT 1 FROM ops_tickets WHERE id=%s AND festival_id=%s", (ticket_id, festival_id)))
    row = one(connection, """INSERT INTO issue_analysis_overrides(ticket_id,topic,sentiment,urgent,note,updated_by)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(ticket_id) DO UPDATE SET topic=excluded.topic,sentiment=excluded.sentiment,
        urgent=excluded.urgent,note=excluded.note,updated_by=excluded.updated_by,updated_at=now() RETURNING *""",
        (ticket_id, body.topic, body.sentiment, body.urgent, body.note, user["id"]))
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/dashboard")
def dashboard(festival_id: str, request: Request, _: Scope, connection: Db):
    stats = one(connection, """SELECT
        (SELECT count(*) FROM visitor_sessions WHERE festival_id=%s)::int AS visitors,
        (SELECT count(*) FROM bookings WHERE festival_id=%s AND status IN ('CONFIRMED','WAITING','CALLED'))::int AS active_bookings,
        (SELECT count(*) FROM ops_tickets WHERE festival_id=%s AND status NOT IN ('RESOLVED','CLOSED'))::int AS open_tickets,
        (SELECT count(*) FROM festival_businesses WHERE festival_id=%s AND participation_status='APPROVED')::int AS approved_businesses,
        (SELECT count(*) FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id JOIN festival_businesses fb ON fb.id=c.festival_business_id WHERE fb.festival_id=%s)::int AS coupon_issues,
        (SELECT coalesce(sum(pl.points_delta),0)::int FROM point_ledger pl JOIN visitor_sessions vs ON vs.id=pl.visitor_session_id WHERE vs.festival_id=%s) AS points_issued""",
        (festival_id,) * 6)
    crowd = all_rows(connection, """SELECT DISTINCT ON (cs.area_id) cs.area_id,a.name,cs.crowd_level,cs.people_count,
        cs.estimated_wait_min,cs.captured_at,cs.expires_at,(cs.expires_at<=now()) AS stale
        FROM crowd_snapshots cs JOIN festival_areas a ON a.id=cs.area_id WHERE cs.festival_id=%s
        ORDER BY cs.area_id,cs.captured_at DESC""", (festival_id,))
    # AI-05 언어별 이용 로그. 자동 전환 여부·키오스크 여부는 방문객 세션 설정값에 남는다.
    languages = all_rows(connection, """SELECT language,count(*)::int AS sessions,
        count(*) FILTER(WHERE accessibility_preferences->>'languageSource'='AUTO')::int AS auto_switched,
        count(*) FILTER(WHERE accessibility_preferences->>'visitorMode'='kiosk')::int AS kiosk_sessions
        FROM visitor_sessions WHERE festival_id=%s GROUP BY language ORDER BY sessions DESC,language""", (festival_id,))
    return success(request, {"stats": stats, "crowd": crowd, "languages": languages,
                             "updatedAt": max((row["captured_at"] for row in crowd), default=None),
                             "sources": ["visitor_sessions", "bookings", "ops_tickets", "crowd_snapshots", "coupon_issues", "point_ledger"]})
