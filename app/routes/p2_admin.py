from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from psycopg.errors import UniqueViolation

from ..db import all_rows, audit, jsonb, one, set_clause
from ..deps import Db, IfMatch, Manager, ManagerOrReviewer, Operator, Scope, User
from ..domain import classify_issue, is_safe_question, mask_sensitive, search_terms, validate_booking_transition
from ..errors import bad_request, conflict, found
from ..http import cursor_params, keyset, paged, success
from .admin_core import created, in_festival, patch_row, scoped
from .p2_visitor import promote_waiting
from ..schemas import (BookingStatusIn, BusinessIn, CouponIn, CouponRedeemIn, CrowdSnapshotIn, FestivalBusinessPatch,
                       InternalDocumentIn, InternalDocumentPatch, InternalSearchIn, IssueAnalysisPatch,
                       MerchantInviteIn, ReviewIn, RewardActionIn, RewardCampaignIn, StaffAssignmentIn)
from ..security import hash_token, random_token


router = APIRouter()


def redeem_issue(connection, request: Request, issue: dict, actor_id, festival_id: str) -> dict:
    """발급된 쿠폰을 사용 처리한다.

    운영자 경로(현장 QR 스캔)와 상인 경로가 같은 처리를 한다 — 발급 건을 어떻게 찾고
    누구 것인지 확인하는 부분만 각 라우트에 있다.
    """
    if issue["status"] != "ISSUED" or issue["expired"]:
        raise conflict("INVALID_COUPON_STATUS", "사용 가능 상태의 쿠폰이 아닙니다.")
    try:
        redemption = one(connection, """INSERT INTO coupon_redemptions(coupon_issue_id,festival_business_id,processed_by)
            VALUES(%s,%s,%s) RETURNING *""", (issue["id"], issue["festival_business_id"], actor_id))
    except UniqueViolation as error:
        # 사용 취소된 발급 건은 상태가 ISSUED로 돌아오지만 사용 이력 행은 남아 있다.
        raise conflict("DUPLICATE_ACTION", "이미 사용 처리된 쿠폰입니다.") from error
    connection.execute("UPDATE coupon_issues SET status='REDEEMED' WHERE id=%s", (issue["id"],))
    connection.execute("INSERT INTO business_events(festival_business_id,visitor_session_id,event_type,source) VALUES(%s,%s,'COUPON_REDEEM','COUPON')",
        (issue["festival_business_id"], issue["visitor_session_id"]))
    audit(connection, festival_id=festival_id, actor_id=str(actor_id), action="REDEEM", resource_type="COUPON_ISSUE",
          resource_id=str(issue["id"]), after_data=redemption, request_id=request.state.request_id)
    return redemption


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
    created(connection, request, user, festival_id, "CROWD_SNAPSHOT", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/bookings")
def bookings(festival_id: str, request: Request, _: Scope, connection: Db, status: str | None = None,
             limit: int = Query(100, ge=1, le=200), cursor: str | None = None):
    """예약·대기표 목록. 티켓과 같은 (created_at, id) 키셋 커서로 자른다."""
    rows = all_rows(connection, f"""SELECT b.id,b.status,b.party_size,b.queue_number,b.called_at,b.created_at,b.updated_at,
        ps.starts_at,ps.ends_at,p.id AS program_id,p.title AS program_title
        FROM bookings b JOIN program_sessions ps ON ps.id=b.program_session_id JOIN programs p ON p.id=ps.program_id
        WHERE b.festival_id=%(festival_id)s AND (%(status)s::text IS NULL OR b.status=%(status)s)
        AND {keyset(alias="b")}
        ORDER BY b.created_at DESC,b.id DESC LIMIT %(limit)s""",
        {"festival_id": festival_id, "status": status, **cursor_params(cursor, limit)})
    rows, page = paged(rows, limit)
    rows.sort(key=lambda row: (row["starts_at"], row["queue_number"] is not None, row["queue_number"] or 0, row["created_at"]))
    return success(request, rows, page=page)


@router.post("/admin/festivals/{festival_id}/bookings/{booking_id}/status")
def update_booking_status(festival_id: str, booking_id: str, body: BookingStatusIn, request: Request, _: Scope, user: Operator, connection: Db):
    booking = found(one(connection, "SELECT * FROM bookings WHERE id=%s AND festival_id=%s FOR UPDATE", (booking_id, festival_id)))
    validate_booking_transition(booking["status"], body.status)
    # ops_tickets 전이와 같은 방식이다 — 상태별 타임스탬프는 SQL CASE로 두고 SQL 문자열은 고정한다.
    row = one(connection, """UPDATE bookings SET status=%(status)s,
        called_at=CASE WHEN %(status)s='CALLED' THEN now() ELSE called_at END,
        completed_at=CASE WHEN %(status)s='COMPLETED' THEN now() ELSE completed_at END,
        version=version+1,updated_at=now() WHERE id=%(booking_id)s RETURNING *""",
        {"status": body.status, "booking_id": booking_id})
    # 노쇼로 빠진 자리는 대기가 채워야 한다 — 안 그러면 정원이 남은 채로 회차가 끝난다.
    if body.status == "NO_SHOW":
        promote_waiting(connection, booking["program_session_id"])
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.status, resource_type="BOOKING",
          resource_id=booking_id, before_data=booking, after_data={**row, "note": body.note}, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/businesses")
def businesses(festival_id: str, request: Request, _: Scope, connection: Db, status: str | None = None):
    # 부스가 여러 개인 업체가 중복되지 않도록 대표 부스 하나만 붙인다(공개 목록과 같은 규칙).
    rows = all_rows(connection, """SELECT DISTINCT ON (fb.id) fb.*,b.registration_no,b.name,b.address,
        bo.id AS booth_id,bo.booth_no,bo.area_id
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id LEFT JOIN booths bo ON bo.festival_business_id=fb.id
        WHERE fb.festival_id=%(festival_id)s AND (%(status)s::text IS NULL OR fb.participation_status=%(status)s)
        ORDER BY fb.id,bo.booth_no""", {"festival_id": festival_id, "status": status})
    rows.sort(key=lambda row: row["name"])
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/businesses", status_code=201)
def create_business(festival_id: str, body: BusinessIn, request: Request, _: Scope, user: Manager, connection: Db):
    # 연락처는 저장하지 않는다. JWT 서명 키를 pgp_sym_encrypt 대칭 키로 재사용하고 있었고
    # (키 하나로 토큰 위조와 개인정보 복호화가 동시에 뚫린다), 저장소 어디에도 복호화 코드가
    # 없어 읽지도 못하는 쓰기 전용 데이터였다. 연락은 소유 멤버십 계정으로 한다.
    business = one(connection, """INSERT INTO businesses(organization_id,registration_no,name,address)
        VALUES(%(organization_id)s,%(registration_no)s,%(name)s,%(address)s)
        ON CONFLICT(organization_id,registration_no) DO UPDATE SET name=excluded.name,address=excluded.address,updated_at=now() RETURNING *""",
        {"organization_id": user["organization_id"], "registration_no": body.registration_no, "name": body.name,
         "address": jsonb(body.address)})
    row = one(connection, """INSERT INTO festival_businesses(festival_id,business_id,owner_membership_id,category,description,menu,operating_hours,accessibility)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (festival_id, business["id"], body.owner_membership_id, body.category, body.description, jsonb(body.menu), jsonb(body.operating_hours), jsonb(body.accessibility)))
    if body.area_id and body.booth_no:
        if not in_festival(connection, "festival_areas", body.area_id, festival_id):
            raise bad_request("AREA_SCOPE_MISMATCH", "부스 구역이 같은 축제에 속하지 않습니다.")
        connection.execute("INSERT INTO booths(festival_business_id,area_id,booth_no) VALUES(%s,%s,%s)", (row["id"], body.area_id, body.booth_no))
    created(connection, request, user, festival_id, "FESTIVAL_BUSINESS", row)
    return success(request, {**row, "name": business["name"], "registrationNo": business["registration_no"]})


@router.patch("/admin/festivals/{festival_id}/businesses/{business_id}")
def update_festival_business(festival_id: str, business_id: str, body: FestivalBusinessPatch, request: Request,
                             _: Scope, user: Manager, connection: Db, if_match: IfMatch = None):
    """운영자가 참여업체 속성을 고친다.

    광고 노출(is_sponsored)과 ESG 참여(esg_participating)는 방문객 추천 점수와 광고 분리에
    쓰이는 값인데 설정할 API가 없어 DB를 직접 고치는 수밖에 없었다.
    """
    return success(request, patch_row(connection, request, user, "festival_businesses", business_id, festival_id,
                                      body, if_match))


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/review")
def review_business(festival_id: str, business_id: str, body: ReviewIn, request: Request, _: Scope, user: ManagerOrReviewer, connection: Db):
    row = one(connection, """UPDATE festival_businesses SET participation_status=%(decision)s,review_comment=%(comment)s,
        approved_by=%(reviewer)s,approved_at=CASE WHEN %(decision)s='APPROVED' THEN now() ELSE NULL END,
        version=version+1,updated_at=now()
        WHERE id=%(business_id)s AND festival_id=%(festival_id)s
          AND participation_status IN ('SUBMITTED','REJECTED') RETURNING *""",
        {"decision": body.decision, "comment": body.comment, "reviewer": user["id"],
         "business_id": business_id, "festival_id": festival_id})
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "제출 또는 반려 상태의 업체만 검토할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.decision, resource_type="FESTIVAL_BUSINESS",
          resource_id=business_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


# BIZ-05 초대 링크 만료. 기획에서 72시간으로 확정했다.
INVITATION_HOURS = 72


@router.get("/admin/festivals/{festival_id}/businesses/{business_id}/invitations")
def merchant_invitations(festival_id: str, business_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    """업체에 발급한 상인 계정 초대와 현재 연결된 계정."""
    scoped(connection, "festival_businesses", business_id, festival_id)
    rows = all_rows(connection, """SELECT mi.id,mi.email,mi.status,mi.expires_at,mi.accepted_at,mi.created_at,
        (mi.status='PENDING' AND mi.expires_at<=now()) AS expired,u.name AS accepted_name
        FROM merchant_invitations mi LEFT JOIN memberships m ON m.id=mi.membership_id LEFT JOIN users u ON u.id=m.user_id
        WHERE mi.festival_business_id=%s ORDER BY mi.created_at DESC""", (business_id,))
    owner = one(connection, """SELECT m.id AS membership_id,m.status,u.name,u.email FROM festival_businesses fb
        JOIN memberships m ON m.id=fb.owner_membership_id JOIN users u ON u.id=m.user_id WHERE fb.id=%s""", (business_id,))
    return success(request, {"invitations": rows, "owner": owner})


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/invitations", status_code=201)
def create_merchant_invitation(festival_id: str, business_id: str, body: MerchantInviteIn, request: Request,
                               _: Scope, user: Manager, connection: Db):
    """상인 계정 초대 발급.

    계정은 이 링크로만 만들어진다(자율 가입 없음). 사업자 증빙은 BIZ-01 업체 승인 절차에서
    이미 확인하므로 여기서 다시 검증하지 않는다. 토큰 원문은 응답으로 한 번만 나가고
    서버에는 해시만 남는다 — 유출된 DB로 초대를 수락할 수 없게.
    """
    scoped(connection, "festival_businesses", business_id, festival_id, "참여업체를 찾을 수 없습니다.")
    token = random_token("mi")
    row = one(connection, """INSERT INTO merchant_invitations(festival_business_id,email,token_hash,invited_by,expires_at)
        VALUES(%s,%s,%s,%s,now()+make_interval(hours => %s)) RETURNING id,email,status,expires_at,created_at""",
        (business_id, str(body.email).lower(), hash_token(token), user["id"], INVITATION_HOURS))
    # 초대받는 사람의 표시 이름은 수락 시점에 계정이 없을 때만 쓰이므로 초대 행에 두지 않고 링크에 싣는다.
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="INVITE", resource_type="MERCHANT_ACCOUNT",
          resource_id=str(row["id"]), after_data={"email": row["email"], "businessId": business_id},
          request_id=request.state.request_id)
    return success(request, {**row, "inviteToken": token, "name": body.name, "expiresInHours": INVITATION_HOURS})


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/invitations/{invitation_id}/revoke")
def revoke_merchant_invitation(festival_id: str, business_id: str, invitation_id: str, request: Request,
                               _: Scope, user: Manager, connection: Db):
    row = one(connection, """UPDATE merchant_invitations mi SET status='REVOKED' FROM festival_businesses fb
        WHERE mi.id=%s AND mi.festival_business_id=fb.id AND fb.id=%s AND fb.festival_id=%s AND mi.status='PENDING'
        RETURNING mi.id,mi.email,mi.status""", (invitation_id, business_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "대기 중인 초대만 회수할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="REVOKE", resource_type="MERCHANT_ACCOUNT",
          resource_id=invitation_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.delete("/admin/festivals/{festival_id}/businesses/{business_id}/merchant", status_code=204)
def deactivate_business_merchant(festival_id: str, business_id: str, request: Request, _: Scope, user: Manager,
                                 connection: Db) -> Response:
    """업체와 연결된 상인 계정을 비활성화한다(축제 종료 후 정리).

    계정을 지우지 않고 비활성화만 한다 — 보유기간(비활성화 후 1년)이 지나면 OPS-11 파기
    배치가 개인정보를 지운다. 업체 연결도 끊어 이후 본인 확인이 성립하지 않게 한다.
    """
    business = found(one(connection, """SELECT owner_membership_id FROM festival_businesses
        WHERE id=%s AND festival_id=%s""", (business_id, festival_id)))
    if not business["owner_membership_id"]:
        raise bad_request("MERCHANT_NOT_LINKED", "이 업체에 연결된 상인 계정이 없습니다.")
    connection.execute("""UPDATE memberships SET status='INACTIVE',deactivated_at=coalesce(deactivated_at,now())
        WHERE id=%s AND role='MERCHANT'""", (business["owner_membership_id"],))
    connection.execute("UPDATE festival_businesses SET owner_membership_id=NULL,updated_at=now() WHERE id=%s", (business_id,))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="DEACTIVATE", resource_type="MERCHANT_ACCOUNT",
          resource_id=str(business["owner_membership_id"]), after_data={"businessId": business_id},
          request_id=request.state.request_id)
    return Response(status_code=204)


# BIZ-04 소규모 표본 보호. 표본 업체가 이보다 적으면 비교 통계에서 개별 업체 실적이 역산된다.
MIN_COMPARISON_SAMPLE = 5


@router.get("/admin/festivals/{festival_id}/business-performance")
def business_performance(festival_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    """BIZ-04 운영자용 업체별 전환 지표와 전체 참여 성과.

    매출은 수집 동의(sales_consent)가 있는 업체만 집계·표시한다. 비교 통계는 표본이
    MIN_COMPARISON_SAMPLE 미만이면 개별 업체 실적이 역산되므로 내려주지 않는다.
    """
    # 이벤트와 쿠폰을 한 쿼리에서 조인하면 곱집합이 된다 — 노출 1건이 발급 쿠폰 수만큼
    # 불어나 전환율과 매출이 통째로 틀렸다. 서로 무관한 집계라 각각 서브쿼리로 센다.
    rows = all_rows(connection, """SELECT fb.id,b.name,fb.category,fb.is_sponsored,fb.esg_participating,fb.sales_consent,
        coalesce(e.impressions,0)::int AS impressions,coalesce(e.visits,0)::int AS visits,
        coalesce(k.coupons_issued,0)::int AS coupons_issued,coalesce(k.coupons_redeemed,0)::int AS coupons_redeemed,
        CASE WHEN fb.sales_consent THEN coalesce(e.sales_amount,0) END AS sales_amount
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id
        LEFT JOIN LATERAL (SELECT count(*) FILTER(WHERE be.event_type='IMPRESSION') AS impressions,
                                  count(*) FILTER(WHERE be.event_type='VISIT') AS visits,
                                  coalesce(sum(be.sales_amount),0) AS sales_amount
                           FROM business_events be WHERE be.festival_business_id=fb.id) e ON true
        LEFT JOIN LATERAL (SELECT count(ci.id) AS coupons_issued,
                                  count(cr.id) FILTER(WHERE cr.status='REDEEMED') AS coupons_redeemed
                           FROM coupons c JOIN coupon_issues ci ON ci.coupon_id=c.id
                           LEFT JOIN coupon_redemptions cr ON cr.coupon_issue_id=ci.id
                           WHERE c.festival_business_id=fb.id) k ON true
        WHERE fb.festival_id=%s AND fb.participation_status='APPROVED'
        ORDER BY b.name""", (festival_id,))
    for row in rows:
        row["redemption_rate"] = round(row["coupons_redeemed"] / row["coupons_issued"] * 100, 1) if row["coupons_issued"] else None
        row["visit_rate"] = round(row["visits"] / row["impressions"] * 100, 1) if row["impressions"] else None
    totals = {key: sum(row[key] for row in rows) for key in ("impressions", "visits", "coupons_issued", "coupons_redeemed")}
    totals["businesses"] = len(rows)
    totals["salesConsented"] = sum(1 for row in rows if row["sales_consent"])
    comparison = None
    if len(rows) >= MIN_COMPARISON_SAMPLE:
        rates = sorted(row["redemption_rate"] for row in rows if row["redemption_rate"] is not None)
        comparison = {
            "averageRedemptionRate": round(sum(rates) / len(rates), 1) if rates else None,
            "medianRedemptionRate": rates[len(rates) // 2] if rates else None,
            "averageCouponsIssued": round(totals["coupons_issued"] / len(rows), 1),
        }
    return success(request, {
        "items": rows, "totals": totals, "comparison": comparison,
        "comparisonSuppressed": comparison is None,
        "minComparisonSample": MIN_COMPARISON_SAMPLE,
        "salesNotice": "매출은 수집 동의를 받은 업체만 집계합니다.",
    })


@router.get("/admin/festivals/{festival_id}/businesses/{business_id}/coupons")
def coupons(festival_id: str, business_id: str, request: Request, _: Scope, connection: Db):
    return success(request, all_rows(connection, """SELECT c.*,(SELECT count(*) FROM coupon_issues ci WHERE ci.coupon_id=c.id)::int AS issued_count
        FROM coupons c JOIN festival_businesses fb ON fb.id=c.festival_business_id WHERE fb.festival_id=%s AND fb.id=%s ORDER BY c.created_at DESC""",
        (festival_id, business_id)))


@router.post("/admin/festivals/{festival_id}/businesses/{business_id}/coupons", status_code=201)
def create_coupon(festival_id: str, business_id: str, body: CouponIn, request: Request, _: Scope, user: Manager, connection: Db):
    if not one(connection, "SELECT 1 FROM festival_businesses WHERE id=%s AND festival_id=%s AND participation_status='APPROVED'", (business_id, festival_id)):
        raise bad_request("BUSINESS_NOT_APPROVED", "승인된 참여업체만 쿠폰을 발행할 수 있습니다.")
    row = insert_coupon(connection, business_id, body, user["id"])
    created(connection, request, user, festival_id, "COUPON", row)
    return success(request, row)


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


@router.post("/admin/festivals/{festival_id}/coupon-redemptions")
def redeem_coupon_on_site(festival_id: str, body: CouponRedeemIn, request: Request, _: Scope, user: Operator, connection: Db):
    """현장 운영자가 방문객 QR(사용 토큰)을 읽어 쿠폰을 사용 처리한다.

    상인용 경로(/merchant/coupon-issues/{issue_id}/redeem)는 업체 소유자로 범위가 묶여 있어
    운영자가 대신 처리할 수 없다. 여기서는 축제 범위로만 제한하고, 스캔한 토큰 하나로 발급
    건을 찾는다 — QR에 발급 ID까지 담지 않아도 되도록.
    """
    issue = one(connection, """SELECT ci.id,ci.status,ci.visitor_session_id,(ci.expires_at<=now()) AS expired,
        c.festival_business_id,c.name FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id
        JOIN festival_businesses fb ON fb.id=c.festival_business_id
        WHERE ci.issue_token_hash=%s AND fb.festival_id=%s FOR UPDATE OF ci""",
        (hash_token(body.issue_token), festival_id))
    if not issue:
        raise bad_request("INVALID_COUPON_TOKEN", "이 축제에서 발급된 쿠폰을 찾을 수 없습니다.")
    redemption = redeem_issue(connection, request, issue, user["id"], festival_id)
    return success(request, {**redemption, "couponName": issue["name"]})


@router.post("/admin/festivals/{festival_id}/reward-campaigns", status_code=201)
def create_reward_campaign(festival_id: str, body: RewardCampaignIn, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """INSERT INTO reward_campaigns(festival_id,name,starts_at,ends_at,daily_point_limit,created_by)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""", (festival_id, body.name, body.starts_at, body.ends_at, body.daily_point_limit, user["id"]))
    created(connection, request, user, festival_id, "REWARD_CAMPAIGN", row)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/reward-campaigns/{campaign_id}/actions", status_code=201)
def create_reward_action(festival_id: str, campaign_id: str, body: RewardActionIn, request: Request, _: Scope, user: Manager, connection: Db):
    # QR·현장 확인 리워드는 인증 값이 있어야 검증이 성립한다. rule.verificationKeys가 비어 있으면
    # 서버가 어떤 값이든 통과시켜서, 방문객이 현장에 가지 않고도 포인트를 받을 수 있었다.
    if body.verification_type != "SELF" and not (body.rule or {}).get("verificationKeys"):
        raise bad_request("VERIFICATION_KEYS_REQUIRED",
                          "SELF가 아닌 인증 방식은 rule.verificationKeys에 인증 값을 1개 이상 등록해야 합니다.")
    row = found(one(connection, """INSERT INTO reward_actions(campaign_id,action_type,verification_type,points,per_user_limit,rule)
        SELECT %s,%s,%s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM reward_campaigns WHERE id=%s AND festival_id=%s) RETURNING *""",
        (campaign_id, body.action_type, body.verification_type, body.points, body.per_user_limit, jsonb(body.rule), campaign_id, festival_id)))
    created(connection, request, user, festival_id, "REWARD_ACTION", row)
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
    created(connection, request, user, festival_id, "INTERNAL_DOCUMENT", row)
    return success(request, row)


@router.patch("/admin/festivals/{festival_id}/internal-documents/{document_id}")
def update_internal_document(festival_id: str, document_id: str, body: InternalDocumentPatch, request: Request,
                             _: Scope, user: Manager, connection: Db):
    """운영 문서 수정. 등록·조회·검색만 있어서 오타 하나도 고칠 수 없었다."""
    values = body.model_dump(exclude_none=True)
    if not values:
        raise bad_request("VALIDATION_ERROR", "변경할 값이 없습니다.")
    if "allowed_roles" in values:
        values["allowed_roles"] = jsonb(values["allowed_roles"])
    before = found(one(connection, "SELECT * FROM internal_documents WHERE id=%s AND festival_id=%s AND status='ACTIVE'", (document_id, festival_id)))
    clause, params = set_clause(values)
    row = found(one(connection, f"""UPDATE internal_documents SET {clause},updated_at=now()
        WHERE id=%s AND festival_id=%s AND status='ACTIVE'
        RETURNING id,title,document_type,source_url,allowed_roles,status,updated_at""", [*params, document_id, festival_id]))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="UPDATE", resource_type="INTERNAL_DOCUMENT",
          resource_id=document_id, before_data=before, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.delete("/admin/festivals/{festival_id}/internal-documents/{document_id}", status_code=204)
def archive_internal_document(festival_id: str, document_id: str, request: Request, _: Scope, user: Manager, connection: Db) -> Response:
    """보관 처리. 감사 대상 문서라 실제로 지우지 않고 status만 ARCHIVED로 바꾼다(검색 대상에서 빠진다)."""
    row = found(one(connection, """UPDATE internal_documents SET status='ARCHIVED',updated_at=now()
        WHERE id=%s AND festival_id=%s AND status='ACTIVE' RETURNING id""", (document_id, festival_id)))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="ARCHIVE", resource_type="INTERNAL_DOCUMENT",
          resource_id=str(row["id"]), request_id=request.state.request_id)
    return Response(status_code=204)


@router.post("/admin/festivals/{festival_id}/ai/operations/search")
def search_internal_documents(festival_id: str, body: InternalSearchIn, request: Request, _: Scope, user: User, connection: Db):
    if not is_safe_question(body.question):
        raise bad_request("UNSAFE_QUERY", "민감정보 또는 시스템 정보 요청은 검색할 수 없습니다.")
    patterns = [f"%{term}%" for term in search_terms(body.question)]
    # internal_documents_body_idx(gin_trgm_ops)가 ILIKE ANY를 받는다.
    rows = all_rows(connection, """SELECT id,title,document_type,body,source_url,updated_at FROM internal_documents
        WHERE festival_id=%(festival_id)s AND status='ACTIVE' AND allowed_roles ? %(role)s AND body ILIKE ANY(%(patterns)s)
        ORDER BY (SELECT count(*) FROM unnest(%(patterns)s::text[]) pattern WHERE body ILIKE pattern) DESC,
                 updated_at DESC LIMIT 5""",
        {"festival_id": festival_id, "role": user["role"], "patterns": patterns}) if patterns else []
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
    scoped(connection, "ops_tickets", ticket_id, festival_id)
    row = one(connection, """INSERT INTO issue_analysis_overrides(ticket_id,topic,sentiment,urgent,note,updated_by)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(ticket_id) DO UPDATE SET topic=excluded.topic,sentiment=excluded.sentiment,
        urgent=excluded.urgent,note=excluded.note,updated_by=excluded.updated_by,updated_at=now() RETURNING *""",
        (ticket_id, body.topic, body.sentiment, body.urgent, body.note, user["id"]))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="UPDATE",
          resource_type="ISSUE_ANALYSIS", resource_id=ticket_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/dashboard")
def dashboard(
    festival_id: str,
    request: Request,
    _: Scope,
    connection: Db,
    area_id: Annotated[str | None, Query(alias="areaId")] = None,
    time_from: Annotated[datetime | None, Query(alias="timeFrom")] = None,
    time_to: Annotated[datetime | None, Query(alias="timeTo")] = None,
):
    # 구역(area) 필터는 해당 지표가 구역과 실제로 연결된 경우에만 적용한다 — 방문 세션·포인트
    # 적립은 구역 없이 축제 전체 단위라 areaId를 줘도 그대로 전체 값을 낸다.
    # 같은 값이 쿼리 안에서 여러 번 쓰이므로 이름 파라미터를 쓴다(위치 인자로는 30개가 된다).
    filters = {"festival_id": festival_id, "area_id": area_id, "time_from": time_from, "time_to": time_to}
    stats = one(connection, """SELECT
        (SELECT count(*) FROM visitor_sessions WHERE festival_id=%(festival_id)s
           AND (%(time_from)s::timestamptz IS NULL OR created_at>=%(time_from)s)
           AND (%(time_to)s::timestamptz IS NULL OR created_at<=%(time_to)s))::int AS visitors,
        (SELECT count(*) FROM bookings b JOIN program_sessions ps ON ps.id=b.program_session_id
           WHERE b.festival_id=%(festival_id)s AND b.status IN ('CONFIRMED','WAITING','CALLED')
           AND (%(area_id)s::uuid IS NULL OR ps.area_id=%(area_id)s)
           AND (%(time_from)s::timestamptz IS NULL OR b.created_at>=%(time_from)s)
           AND (%(time_to)s::timestamptz IS NULL OR b.created_at<=%(time_to)s))::int AS active_bookings,
        (SELECT count(*) FROM ops_tickets WHERE festival_id=%(festival_id)s AND status NOT IN ('RESOLVED','CLOSED')
           AND (%(area_id)s::uuid IS NULL OR area_id=%(area_id)s)
           AND (%(time_from)s::timestamptz IS NULL OR created_at>=%(time_from)s)
           AND (%(time_to)s::timestamptz IS NULL OR created_at<=%(time_to)s))::int AS open_tickets,
        (SELECT count(DISTINCT fb.id) FROM festival_businesses fb LEFT JOIN booths bo ON bo.festival_business_id=fb.id
           WHERE fb.festival_id=%(festival_id)s AND fb.participation_status='APPROVED'
           AND (%(area_id)s::uuid IS NULL OR bo.area_id=%(area_id)s))::int AS approved_businesses,
        (SELECT count(*) FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id JOIN festival_businesses fb ON fb.id=c.festival_business_id
           WHERE fb.festival_id=%(festival_id)s
           AND (%(time_from)s::timestamptz IS NULL OR ci.issued_at>=%(time_from)s)
           AND (%(time_to)s::timestamptz IS NULL OR ci.issued_at<=%(time_to)s))::int AS coupon_issues,
        (SELECT coalesce(sum(pl.points_delta),0)::int FROM point_ledger pl JOIN visitor_sessions vs ON vs.id=pl.visitor_session_id
           WHERE vs.festival_id=%(festival_id)s
           AND (%(time_from)s::timestamptz IS NULL OR pl.created_at>=%(time_from)s)
           AND (%(time_to)s::timestamptz IS NULL OR pl.created_at<=%(time_to)s)) AS points_issued""", filters)
    crowd = all_rows(connection, """SELECT DISTINCT ON (cs.area_id) cs.area_id,a.name,cs.crowd_level,cs.people_count,
        cs.estimated_wait_min,cs.captured_at,cs.expires_at,(cs.expires_at<=now()) AS stale
        FROM crowd_snapshots cs JOIN festival_areas a ON a.id=cs.area_id WHERE cs.festival_id=%(festival_id)s
        AND (%(area_id)s::uuid IS NULL OR cs.area_id=%(area_id)s)
        AND (%(time_from)s::timestamptz IS NULL OR cs.captured_at>=%(time_from)s)
        AND (%(time_to)s::timestamptz IS NULL OR cs.captured_at<=%(time_to)s)
        ORDER BY cs.area_id,cs.captured_at DESC""", filters)
    # AI-05 언어별 이용 로그. 자동 전환 여부·키오스크 여부는 방문객 세션 설정값에 남는다.
    languages = all_rows(connection, """SELECT language,count(*)::int AS sessions,
        count(*) FILTER(WHERE accessibility_preferences->>'languageSource'='AUTO')::int AS auto_switched,
        count(*) FILTER(WHERE accessibility_preferences->>'visitorMode'='kiosk')::int AS kiosk_sessions
        FROM visitor_sessions WHERE festival_id=%(festival_id)s
        AND (%(time_from)s::timestamptz IS NULL OR created_at>=%(time_from)s)
        AND (%(time_to)s::timestamptz IS NULL OR created_at<=%(time_to)s)
        GROUP BY language ORDER BY sessions DESC,language""", filters)
    return success(request, {"stats": stats, "crowd": crowd, "languages": languages,
                             "updatedAt": max((row["captured_at"] for row in crowd), default=None),
                             "sources": ["visitor_sessions", "bookings", "ops_tickets", "crowd_snapshots", "coupon_issues", "point_ledger"],
                             "filters": {"areaId": area_id, "timeFrom": time_from, "timeTo": time_to}})
