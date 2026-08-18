from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from psycopg.errors import UniqueViolation

from ..db import all_rows, idempotent, jsonb, one
from ..deps import Db, IdempotencyKey, Visitor
from ..domain import (select_course, supported_language, validate_booking_cancel_window,
                      validate_booking_transition)
from ..errors import bad_request, conflict, found
from ..http import idempotent_success, success
from ..schemas import BookingIn, CoursePlanIn, RewardEventIn, VisitorPreferencesPatch
from ..security import hash_token, random_token
from .public import cached, published_festival


router = APIRouter()


def reserved_seats(connection, session_id) -> int:
    """정원을 차지하고 있는 인원. 입장 완료(COMPLETED)도 자리를 쓴 것이다 —
    빼면 운영자가 입장 처리를 할수록 자리가 비어 보여서 회차 진행 중에 정원 초과 예약이 확정됐다."""
    return one(connection, """SELECT coalesce(sum(party_size),0)::int AS count FROM bookings
        WHERE program_session_id=%s AND status IN ('CONFIRMED','CALLED','COMPLETED')""", (session_id,))["count"]


@router.patch("/visitor-sessions/current")
def update_preferences(body: VisitorPreferencesPatch, request: Request, visitor: Visitor, connection: Db):
    festival = one(connection, "SELECT supported_languages,default_language FROM festivals WHERE id=%s", (visitor["festival_id"],))
    language = supported_language(body.language or visitor["language"], festival["supported_languages"], festival["default_language"])
    row = one(connection, """UPDATE visitor_sessions SET language=%s,accessibility_preferences=coalesce(%s,accessibility_preferences)
        WHERE id=%s RETURNING id,language,accessibility_preferences,expires_at""",
        (language, jsonb(body.accessibility_preferences) if body.accessibility_preferences is not None else None, visitor["id"]))
    return success(request, row)


@router.get("/public/festivals/{festival_code}/businesses")
def public_businesses(festival_code: str, request: Request, response: Response, connection: Db, category: str | None = None):
    festival = published_festival(connection, festival_code)
    # 업체당 부스가 여러 개일 수 있어 그냥 조인하면 같은 업체가 부스 수만큼 중복된다.
    # 목록은 업체 단위이므로 대표 부스(booth_no 오름차순 첫 번째) 하나만 붙인다.
    rows = all_rows(connection, """SELECT DISTINCT ON (fb.id) fb.id,b.name,fb.category,fb.description,fb.menu,
        fb.operating_hours,fb.accessibility,b.address,bo.booth_no,bo.area_id,a.name AS area_name
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id
        LEFT JOIN booths bo ON bo.festival_business_id=fb.id LEFT JOIN festival_areas a ON a.id=bo.area_id
        WHERE fb.festival_id=%(festival_id)s AND fb.participation_status='APPROVED' AND b.status='ACTIVE'
          AND (%(category)s::text IS NULL OR fb.category=%(category)s) ORDER BY fb.id,bo.booth_no""",
        {"festival_id": festival["id"], "category": category})
    rows.sort(key=lambda row: row["name"])
    cached(response)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/coupons")
def public_coupons(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT c.id,c.name,c.description,c.benefit_type,c.benefit_value,c.valid_from,c.valid_until,
        c.per_visitor_limit,
        c.issue_limit-(SELECT count(*) FROM coupon_issues ci WHERE ci.coupon_id=c.id) AS remaining,b.name AS business_name
        FROM coupons c JOIN festival_businesses fb ON fb.id=c.festival_business_id JOIN businesses b ON b.id=fb.business_id
        WHERE fb.festival_id=%s AND fb.participation_status='APPROVED' AND c.status='ACTIVE'
          AND c.valid_from<=now() AND c.valid_until>now() ORDER BY c.valid_until,c.name""", (festival["id"],))
    cached(response, 30)
    return success(request, rows)


@router.get("/visitor/bookings")
def my_bookings(request: Request, visitor: Visitor, connection: Db):
    rows = all_rows(connection, """SELECT b.id,b.status,b.party_size,b.queue_number,b.called_at,b.created_at,b.updated_at,
        ps.starts_at,ps.ends_at,p.title AS program_title,p.slug AS program_slug,a.name AS area_name
        FROM bookings b JOIN program_sessions ps ON ps.id=b.program_session_id JOIN programs p ON p.id=ps.program_id
        JOIN festival_areas a ON a.id=ps.area_id WHERE b.visitor_session_id=%s ORDER BY ps.starts_at""", (visitor["id"],))
    # OPS-10: 호출은 이 폴링 응답에 실릴 때 비로소 방문객에게 닿는다. 도달 결과를 운영자가
    # 확인할 수 있도록 응답에 실제로 실린 호출을 세션별로 남긴다.
    for row in rows:
        if row["status"] == "CALLED":
            connection.execute("""INSERT INTO notification_deliveries(festival_id,resource_type,resource_id,visitor_session_id)
                VALUES(%s,'BOOKING_CALL',%s,%s) ON CONFLICT DO NOTHING""", (visitor["festival_id"], row["id"], visitor["id"]))
    return success(request, rows)


@router.post("/visitor/program-sessions/{session_id}/bookings", status_code=201)
def create_booking(session_id: str, body: BookingIn, request: Request, response: Response, visitor: Visitor,
                   connection: Db, idempotency_key: IdempotencyKey = None):
    def work():
        session = found(one(connection, """SELECT ps.*,p.title FROM program_sessions ps JOIN programs p ON p.id=ps.program_id
            WHERE ps.id=%s AND ps.festival_id=%s AND ps.status='OPEN' AND ps.ends_at>now() FOR UPDATE OF ps""",
            (session_id, visitor["festival_id"])), "예약 가능한 프로그램 회차를 찾을 수 없습니다.")
        confirmed = session["capacity"] is None or reserved_seats(connection, session_id) + body.party_size <= session["capacity"]
        queue_number = None if confirmed else one(connection, "SELECT coalesce(max(queue_number),0)+1 AS next FROM bookings WHERE program_session_id=%s", (session_id,))["next"]
        # contact는 더 이상 저장하지 않는다. JWT 서명 키를 pgp_sym_encrypt 키로 재사용하고 있었고
        # (키 하나가 유출되면 토큰 위조와 개인정보 복호화가 같이 뚫린다), 복호화하는 코드가 저장소
        # 어디에도 없어 읽을 수도 없는 쓰기 전용 데이터였다. 호출도 대기표 화면으로 하므로 필요 없다.
        try:
            row = one(connection, """INSERT INTO bookings(festival_id,visitor_session_id,program_session_id,status,party_size,queue_number)
                VALUES(%(festival_id)s,%(visitor_id)s,%(session_id)s,%(status)s,%(party_size)s,%(queue_number)s)
                RETURNING id,status,party_size,queue_number,created_at""",
                {"festival_id": visitor["festival_id"], "visitor_id": visitor["id"], "session_id": session_id,
                 "status": "CONFIRMED" if confirmed else "WAITING", "party_size": body.party_size,
                 "queue_number": queue_number})
        except UniqueViolation as error:
            raise conflict("DUPLICATE_ACTION", "같은 회차의 예약 또는 대기표가 이미 있습니다.") from error
        return 201, {**row, "programTitle": session["title"], "startsAt": session["starts_at"]}
    return idempotent_success(request, response, idempotent(connection, key=idempotency_key, scope=f"booking:{visitor['id']}:{session_id}", body=body.model_dump(), work=work))


@router.delete("/visitor/bookings/{booking_id}", status_code=204)
def cancel_booking(booking_id: str, visitor: Visitor, connection: Db) -> Response:
    booking = found(one(connection, """SELECT b.*,ps.starts_at FROM bookings b
        JOIN program_sessions ps ON ps.id=b.program_session_id
        WHERE b.id=%s AND b.visitor_session_id=%s FOR UPDATE OF b""", (booking_id, visitor["id"])))
    validate_booking_transition(booking["status"], "CANCELLED")
    validate_booking_cancel_window(booking["starts_at"])
    connection.execute("UPDATE bookings SET status='CANCELLED',cancelled_at=now(),version=version+1,updated_at=now() WHERE id=%s", (booking_id,))
    # 자리를 쓰고 있던 예약이 빠졌을 때만 대기를 올린다(CALLED도 자리를 차지한다).
    if booking["status"] in ("CONFIRMED", "CALLED"):
        promote_waiting(connection, booking["program_session_id"])
    return Response(status_code=204)


def promote_waiting(connection, session_id) -> None:
    """빈 자리만큼 대기를 순번대로 확정한다.

    예전에는 선두 한 건만 봤다 — 5명이 취소해도 한 건만 올라갔고, 선두가 인원 때문에 못
    들어가면 뒤에 맞는 대기가 있어도 자리가 비어 있는 채로 남았다.
    인원이 안 맞는 대기는 건너뛰되 순번은 그대로 두어 다음 취소 때 다시 후보가 된다.
    """
    session = one(connection, "SELECT capacity FROM program_sessions WHERE id=%s FOR UPDATE", (session_id,))
    waiting = all_rows(connection, """SELECT id,party_size FROM bookings WHERE program_session_id=%s AND status='WAITING'
        ORDER BY queue_number FOR UPDATE SKIP LOCKED""", (session_id,))
    taken = reserved_seats(connection, session_id)
    for booking in waiting:
        if session["capacity"] is not None and taken + booking["party_size"] > session["capacity"]:
            continue
        connection.execute("UPDATE bookings SET status='CONFIRMED',queue_number=NULL,version=version+1,updated_at=now() WHERE id=%s",
                           (booking["id"],))
        taken += booking["party_size"]


@router.post("/visitor/course-plans", status_code=201)
def create_course_plan(body: CoursePlanIn, request: Request, visitor: Visitor, connection: Db):
    # OPS-11: 위치 항목 동의를 철회한 세션에는 위치 기반 좁히기를 적용하지 않는다.
    # 철회가 저장만 되고 서버가 계속 위치를 쓰면 철회한 것이 아니다.
    consents = one(connection, "SELECT consents FROM visitor_sessions WHERE id=%s", (visitor["id"],))["consents"]
    if consents.get("location") is False:
        body = body.model_copy(update={"area_id": None})
    values: list = [visitor["festival_id"], body.starts_at or datetime.now(UTC), body.excluded_program_ids]
    clauses = ["ps.festival_id=%s", "ps.status='OPEN'", "p.status='PUBLISHED'", "ps.starts_at>=%s", "NOT (p.id=ANY(%s::uuid[]))"]
    # accessibility는 받아서 input_preferences에 적어 두기만 하고 후보 선정에는 쓰이지 않았다.
    # 휠체어 접근이 필요하다고 답한 방문객에게 접근 불가 프로그램을 추천하면 안 된다.
    required_accessibility = {key: True for key, value in body.accessibility.items() if value is True}
    for clause, value in (("p.category=ANY(%s)", body.interests), ("ps.area_id=%s", body.area_id),
                          ("p.accessibility @> %s", jsonb(required_accessibility) if required_accessibility else None)):
        if value:
            clauses.append(clause)
            values.append(value)
    sessions = all_rows(connection, f"""SELECT ps.id,ps.starts_at,ps.ends_at,p.id AS program_id,p.title,p.category,a.name AS area_name
        FROM program_sessions ps JOIN programs p ON p.id=ps.program_id JOIN festival_areas a ON a.id=ps.area_id
        WHERE {' AND '.join(clauses)} ORDER BY ps.starts_at LIMIT 50""", values)
    selected = found(select_course(sessions, body.duration_min, body.starts_at), "조건에 맞는 운영 중 프로그램을 찾을 수 없습니다.")
    plan = one(connection, "INSERT INTO course_plans(visitor_session_id,input_preferences,expected_duration_min) VALUES(%s,%s,%s) RETURNING *",
        (visitor["id"], jsonb(body.model_dump()), body.duration_min))
    items = []
    for sequence, session in enumerate(selected, 1):
        item = one(connection, """INSERT INTO course_items(course_plan_id,program_session_id,sequence_no,recommendation_reason)
            VALUES(%s,%s,%s,%s) RETURNING *""", (plan["id"], session["id"], sequence, f"{session['category']} 관심사와 운영 시간을 반영했습니다."))
        items.append({**item, "program": session})
    return success(request, {**plan, "items": items})


@router.get("/visitor/coupons")
def my_coupons(request: Request, visitor: Visitor, connection: Db):
    # coupon_id를 함께 준다 — 없으면 화면이 "이미 발급받았는지"를 업체명·쿠폰명 문자열로
    # 짐작해야 해서, 방문객당 한도가 2장 이상인 쿠폰의 두 번째 발급이 잠겼다.
    rows = all_rows(connection, """SELECT ci.id,CASE WHEN ci.expires_at<=now() AND ci.status='ISSUED' THEN 'EXPIRED' ELSE ci.status END AS status,
        ci.issued_at,ci.expires_at,ci.coupon_id,c.name,c.description,c.benefit_type,c.benefit_value,b.name AS business_name
        FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id JOIN festival_businesses fb ON fb.id=c.festival_business_id
        JOIN businesses b ON b.id=fb.business_id WHERE ci.visitor_session_id=%s ORDER BY ci.issued_at DESC""", (visitor["id"],))
    return success(request, rows)


@router.post("/visitor/coupons/{coupon_id}/issues", status_code=201)
def issue_coupon(coupon_id: str, request: Request, response: Response, visitor: Visitor, connection: Db, idempotency_key: IdempotencyKey = None):
    def work():
        coupon = found(one(connection, """SELECT c.*,fb.festival_id,b.name AS business_name FROM coupons c
            JOIN festival_businesses fb ON fb.id=c.festival_business_id JOIN businesses b ON b.id=fb.business_id
            WHERE c.id=%s AND fb.festival_id=%s AND fb.participation_status='APPROVED' AND c.status='ACTIVE'
              AND c.valid_from<=now() AND c.valid_until>now() FOR UPDATE OF c""", (coupon_id, visitor["festival_id"])),
            "발급 가능한 쿠폰을 찾을 수 없습니다.")
        counts = one(connection, """SELECT count(*)::int AS total,
            count(*) FILTER(WHERE visitor_session_id=%s)::int AS mine FROM coupon_issues WHERE coupon_id=%s""", (visitor["id"], coupon_id))
        if counts["total"] >= coupon["issue_limit"]:
            raise conflict("CAPACITY_EXCEEDED", "쿠폰이 모두 발급되었습니다.")
        if counts["mine"] >= coupon["per_visitor_limit"]:
            raise conflict("ACTION_LIMIT_EXCEEDED", "방문객별 쿠폰 발급 한도를 초과했습니다.")
        token = random_token("cp")
        try:
            row = one(connection, """INSERT INTO coupon_issues(coupon_id,visitor_session_id,issue_token_hash,expires_at)
                VALUES(%s,%s,%s,%s) RETURNING id,status,issued_at,expires_at""", (coupon_id, visitor["id"], hash_token(token), coupon["valid_until"]))
        except UniqueViolation as error:
            raise conflict("DUPLICATE_ACTION", "이미 발급받은 쿠폰입니다.") from error
        connection.execute("INSERT INTO business_events(festival_business_id,visitor_session_id,event_type,source) VALUES(%s,%s,'COUPON_ISSUE','COUPON')",
            (coupon["festival_business_id"], visitor["id"]))
        return 201, {**row, "issueToken": token, "couponName": coupon["name"], "businessName": coupon["business_name"]}
    return idempotent_success(request, response, idempotent(connection, key=idempotency_key, scope=f"coupon:{visitor['id']}:{coupon_id}", body={}, work=work))


@router.post("/visitor/coupon-issues/{issue_id}/token")
def rotate_issue_token(issue_id: str, request: Request, visitor: Visitor, connection: Db):
    """쿠폰 사용 토큰 재발급.

    서버에는 해시만 남아서 발급 응답을 놓치면(기기 교체, 저장소 삭제) QR을 다시 만들 수 없고,
    쿠폰은 이미 발급돼 재발급도 막혀 있어 방문객이 영영 쓸 수 없는 상태가 됐다.
    새 토큰을 발급하고 해시를 교체한다 — 예전 토큰은 그 즉시 무효가 되므로 잃어버린
    QR 사진이 남의 손에 있어도 쓰이지 않는다.
    """
    issue = found(one(connection, """SELECT ci.id,ci.status,(ci.expires_at<=now()) AS expired,c.name
        FROM coupon_issues ci JOIN coupons c ON c.id=ci.coupon_id
        WHERE ci.id=%s AND ci.visitor_session_id=%s FOR UPDATE OF ci""", (issue_id, visitor["id"])),
        "발급받은 쿠폰을 찾을 수 없습니다.")
    if issue["status"] != "ISSUED" or issue["expired"]:
        raise conflict("INVALID_COUPON_STATUS", "사용 가능 상태의 쿠폰만 재발급할 수 있습니다.")
    token = random_token("cp")
    row = one(connection, """UPDATE coupon_issues SET issue_token_hash=%s WHERE id=%s
        RETURNING id,status,issued_at,expires_at""", (hash_token(token), issue_id))
    return success(request, {**row, "issueToken": token, "couponName": issue["name"]})


@router.get("/visitor/reward-actions")
def reward_actions(request: Request, visitor: Visitor, connection: Db):
    rows = all_rows(connection, """SELECT a.id,a.action_type,a.verification_type,a.points,a.per_user_limit,a.rule,
        count(e.id)::int AS earned_count FROM reward_actions a JOIN reward_campaigns c ON c.id=a.campaign_id
        LEFT JOIN reward_events e ON e.reward_action_id=a.id AND e.visitor_session_id=%s
        WHERE c.festival_id=%s AND c.status='ACTIVE' AND c.starts_at<=now() AND c.ends_at>now()
        GROUP BY a.id ORDER BY a.action_type""", (visitor["id"], visitor["festival_id"]))
    # rule에는 인증 키가 들어 있어 그대로 내려주지 않고 표시에 필요한 이름·위치만 추린다.
    return success(request, [{
        "id": row["id"], "action_type": row["action_type"], "points": row["points"],
        "verification_type": row["verification_type"],
        "name": (row["rule"] or {}).get("name", row["action_type"]),
        "location": (row["rule"] or {}).get("location", ""),
        "completed": row["earned_count"] >= row["per_user_limit"],
    } for row in rows])


@router.post("/visitor/reward-events", status_code=201)
def create_reward_event(body: RewardEventIn, request: Request, response: Response, visitor: Visitor, connection: Db, idempotency_key: IdempotencyKey = None):
    def work():
        action = found(one(connection, """SELECT a.*,c.festival_id,c.daily_point_limit FROM reward_actions a JOIN reward_campaigns c ON c.id=a.campaign_id
            WHERE a.id=%s AND c.festival_id=%s AND c.status='ACTIVE' AND c.starts_at<=now() AND c.ends_at>now() FOR UPDATE OF c""",
            (body.reward_action_id, visitor["festival_id"])), "참여 가능한 리워드 행동을 찾을 수 없습니다.")
        count = one(connection, "SELECT count(*)::int AS count FROM reward_events WHERE reward_action_id=%s AND visitor_session_id=%s",
            (body.reward_action_id, visitor["id"]))["count"]
        if count >= action["per_user_limit"]:
            raise conflict("ACTION_LIMIT_EXCEEDED", "행동별 참여 한도를 초과했습니다.")
        allowed_keys = (action["rule"] or {}).get("verificationKeys")
        if allowed_keys and body.verification_key not in allowed_keys:
            raise bad_request("INVALID_VERIFICATION", "유효하지 않은 행동 인증 값입니다.")
        # daily_point_limit은 캠페인별 설정인데 예전에는 point_ledger 전체 합계와 비교해서
        # 캠페인 A에서 쌓은 포인트가 캠페인 B의 한도를 잡아먹었다. 같은 캠페인 적립분만 센다.
        today_points = one(connection, """SELECT coalesce(sum(pl.points_delta),0)::int AS points FROM point_ledger pl
            JOIN reward_events re ON re.id=pl.reward_event_id JOIN reward_actions ra ON ra.id=re.reward_action_id
            WHERE pl.visitor_session_id=%s AND ra.campaign_id=%s AND pl.created_at::date=CURRENT_DATE""",
            (visitor["id"], action["campaign_id"]))["points"]
        if today_points + action["points"] > action["daily_point_limit"]:
            raise conflict("DAILY_POINT_LIMIT_EXCEEDED", "일일 포인트 한도를 초과했습니다.")
        try:
            # occurred_at은 스키마로 받기만 하고 버려지고 있었다 — 현장 인증 시각과 서버 도달
            # 시각이 다를 수 있으므로 준 값을 그대로 남긴다(없으면 컬럼 기본값 now()).
            event = one(connection, """INSERT INTO reward_events(reward_action_id,visitor_session_id,verification_key,evidence,occurred_at)
                VALUES(%s,%s,%s,%s,coalesce(%s,now())) RETURNING *""",
                (body.reward_action_id, visitor["id"], body.verification_key, jsonb(body.evidence), body.occurred_at))
        except UniqueViolation as error:
            raise conflict("DUPLICATE_ACTION", "이미 인증된 행동입니다.") from error
        ledger = one(connection, "INSERT INTO point_ledger(visitor_session_id,reward_event_id,points_delta,reason) VALUES(%s,%s,%s,%s) RETURNING *",
            (visitor["id"], event["id"], action["points"], action["action_type"]))
        return 201, {"event": event, "points": ledger["points_delta"]}
    return idempotent_success(request, response, idempotent(connection, key=idempotency_key, scope=f"reward:{visitor['id']}:{body.reward_action_id}", body=body.model_dump(), work=work))


@router.get("/visitor/points")
def points(request: Request, visitor: Visitor, connection: Db):
    ledger = all_rows(connection, "SELECT id,points_delta,reason,created_at FROM point_ledger WHERE visitor_session_id=%s ORDER BY created_at DESC", (visitor["id"],))
    return success(request, {"balance": sum(row["points_delta"] for row in ledger), "ledger": ledger})
