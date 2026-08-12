from typing import Annotated

from fastapi import APIRouter, Depends, Request
from psycopg import Connection

from ..db import all_rows, audit, database, jsonb, one
from ..errors import bad_request, conflict, forbidden
from ..http import success
from ..schemas import BusinessEventIn, BusinessPatch, CouponIn, CouponRedeemIn, CouponReverseIn
from ..security import hash_token, roles


router = APIRouter()


def owned_business(connection: Connection, business_id: str, user: dict, *, approved: bool = False) -> dict:
    row = one(connection, """SELECT fb.*,b.name,b.registration_no FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id
        JOIN festivals f ON f.id=fb.festival_id WHERE fb.id=%s AND fb.owner_membership_id=%s AND f.organization_id=%s""",
        (business_id, user["membership_id"], user["organization_id"]))
    if not row:
        raise forbidden("BUSINESS_SCOPE_DENIED", "본인 업체만 접근할 수 있습니다.")
    if approved and row["participation_status"] != "APPROVED":
        raise bad_request("BUSINESS_NOT_APPROVED", "승인된 참여업체만 사용할 수 있습니다.")
    return row


@router.get("/merchant/businesses")
def businesses(request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    rows = all_rows(connection, """SELECT fb.*,b.name,b.registration_no,b.address,bo.booth_no,bo.area_id
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id LEFT JOIN booths bo ON bo.festival_business_id=fb.id
        WHERE fb.owner_membership_id=%s ORDER BY fb.updated_at DESC""", (user["membership_id"],))
    return success(request, rows)


@router.patch("/merchant/businesses/{business_id}")
def update_business(business_id: str, body: BusinessPatch, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    before = owned_business(connection, business_id, user)
    if before["participation_status"] not in {"DRAFT", "SUBMITTED", "REJECTED", "APPROVED"}:
        raise bad_request("INVALID_STATE_TRANSITION", "수정 가능한 업체 상태가 아닙니다.")
    values = body.model_dump(exclude_none=True, exclude={"name", "version"})
    columns = {"category": "category", "description": "description", "menu": "menu", "operating_hours": "operating_hours", "accessibility": "accessibility"}
    updates, params = [], []
    for field, value in values.items():
        updates.append(f"{columns[field]}=%s")
        params.append(jsonb(value) if field in {"menu", "operating_hours", "accessibility"} else value)
    if body.name is not None:
        connection.execute("UPDATE businesses SET name=%s,updated_at=now() WHERE id=%s", (body.name, before["business_id"]))
    if not updates and body.name is None:
        raise bad_request("VALIDATION_ERROR", "변경할 값이 없습니다.")
    updates.extend(["participation_status='SUBMITTED'", "review_comment=NULL", "version=version+1", "updated_at=now()"])
    params.extend((business_id, body.version))
    row = one(connection, f"UPDATE festival_businesses SET {','.join(updates)} WHERE id=%s AND version=%s RETURNING *", params)
    if not row:
        raise conflict("RESOURCE_VERSION_CONFLICT", "업체 정보가 이미 변경되었습니다.")
    audit(connection, festival_id=str(row["festival_id"]), actor_id=str(user["id"]), action="SUBMIT", resource_type="FESTIVAL_BUSINESS", resource_id=business_id, before_data=before, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/merchant/businesses/{business_id}/coupons", status_code=201)
def create_coupon(business_id: str, body: CouponIn, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    owned_business(connection, business_id, user, approved=True)
    row = one(connection, """INSERT INTO coupons(festival_business_id,name,description,benefit_type,benefit_value,issue_limit,
        per_visitor_limit,valid_from,valid_until,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (business_id, body.name, body.description, body.benefit_type, body.benefit_value, body.issue_limit, body.per_visitor_limit, body.starts_at, body.ends_at, user["id"]))
    return success(request, row)


@router.post("/merchant/coupon-issues/{issue_id}/redeem")
def redeem_coupon(issue_id: str, body: CouponRedeemIn, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    issue = one(connection, """SELECT ci.*,c.festival_business_id,c.name FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id
        JOIN festival_businesses fb ON fb.id=c.festival_business_id WHERE ci.id=%s AND fb.owner_membership_id=%s FOR UPDATE OF ci""", (issue_id, user["membership_id"]))
    if not issue:
        raise forbidden("BUSINESS_SCOPE_DENIED", "본인 업체의 쿠폰만 처리할 수 있습니다.")
    if issue["issue_token_hash"] != hash_token(body.issue_token):
        raise bad_request("INVALID_COUPON_TOKEN", "쿠폰 토큰이 일치하지 않습니다.")
    if issue["status"] != "ISSUED" or issue["expires_at"] <= one(connection, "SELECT now() AS now")["now"]:
        raise conflict("INVALID_COUPON_STATUS", "사용 가능 상태의 쿠폰이 아닙니다.")
    redemption = one(connection, """INSERT INTO coupon_redemptions(coupon_issue_id,festival_business_id,processed_by)
        VALUES(%s,%s,%s) RETURNING *""", (issue_id, issue["festival_business_id"], user["id"]))
    connection.execute("UPDATE coupon_issues SET status='REDEEMED' WHERE id=%s", (issue_id,))
    connection.execute("INSERT INTO business_events(festival_business_id,visitor_session_id,event_type,source) VALUES(%s,%s,'COUPON_REDEEM','COUPON')", (issue["festival_business_id"], issue["visitor_session_id"]))
    return success(request, redemption)


@router.post("/merchant/coupon-redemptions/{redemption_id}/reverse")
def reverse_coupon(redemption_id: str, body: CouponReverseIn, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    redemption = one(connection, """SELECT cr.* FROM coupon_redemptions cr JOIN festival_businesses fb ON fb.id=cr.festival_business_id
        WHERE cr.id=%s AND fb.owner_membership_id=%s FOR UPDATE OF cr""", (redemption_id, user["membership_id"]))
    if not redemption:
        raise forbidden("BUSINESS_SCOPE_DENIED", "본인 업체의 쿠폰 사용만 취소할 수 있습니다.")
    if redemption["status"] != "REDEEMED":
        raise conflict("INVALID_COUPON_STATUS", "이미 취소된 사용 내역입니다.")
    row = one(connection, "UPDATE coupon_redemptions SET status='REVERSED',reversed_at=now(),reversal_reason=%s WHERE id=%s RETURNING *", (body.reason, redemption_id))
    connection.execute("UPDATE coupon_issues SET status=CASE WHEN expires_at>now() THEN 'ISSUED' ELSE 'EXPIRED' END WHERE id=%s", (redemption["coupon_issue_id"],))
    audit(connection, festival_id=None, actor_id=str(user["id"]), action="REVERSE", resource_type="COUPON_REDEMPTION", resource_id=redemption_id, before_data=redemption, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/merchant/businesses/{business_id}/events", status_code=201)
def record_business_event(business_id: str, body: BusinessEventIn, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    owned_business(connection, business_id, user, approved=True)
    if body.event_type == "SALE" and body.sales_amount is None:
        raise bad_request("VALIDATION_ERROR", "매출 이벤트에는 금액이 필요합니다.")
    row = one(connection, "INSERT INTO business_events(festival_business_id,event_type,sales_amount,source) VALUES(%s,%s,%s,%s) RETURNING *", (business_id, body.event_type, body.sales_amount, body.source))
    return success(request, row)


@router.get("/merchant/businesses/{business_id}/performance")
def performance(business_id: str, request: Request, user: Annotated[dict, Depends(roles("MERCHANT"))], connection: Annotated[Connection, Depends(database)]):
    owned_business(connection, business_id, user)
    metrics = all_rows(connection, """SELECT event_type,count(*)::int AS count,coalesce(sum(sales_amount),0) AS sales_amount
        FROM business_events WHERE festival_business_id=%s GROUP BY event_type ORDER BY event_type""", (business_id,))
    coupons = one(connection, """SELECT count(ci.id)::int AS issued,count(cr.id) FILTER(WHERE cr.status='REDEEMED')::int AS redeemed
        FROM coupons c LEFT JOIN coupon_issues ci ON ci.coupon_id=c.id LEFT JOIN coupon_redemptions cr ON cr.coupon_issue_id=ci.id
        WHERE c.festival_business_id=%s""", (business_id,))
    return success(request, {"events": metrics, "coupons": coupons})
