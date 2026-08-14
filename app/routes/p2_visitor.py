import json
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from psycopg.errors import UniqueViolation

from ..config import settings
from ..db import all_rows, idempotent, jsonb, one
from ..deps import Db, IdempotencyKey, Visitor
from ..domain import select_course, supported_language, validate_booking_transition
from ..errors import bad_request, conflict, found
from ..http import idempotent_success, success
from ..schemas import BookingIn, CoursePlanIn, RewardEventIn, VisitorPreferencesPatch
from ..security import hash_token, random_token
from .public import cached, published_festival


router = APIRouter()


def reserved_seats(connection, session_id) -> int:
    return one(connection, """SELECT coalesce(sum(party_size),0)::int AS count FROM bookings
        WHERE program_session_id=%s AND status IN ('CONFIRMED','CALLED')""", (session_id,))["count"]


@router.patch("/visitor-sessions/current")
def update_preferences(body: VisitorPreferencesPatch, request: Request, visitor: Visitor, connection: Db):
    festival = one(connection, "SELECT supported_languages,default_language FROM festivals WHERE id=%s", (visitor["festival_id"],))
    language = supported_language(body.language or visitor["language"], festival["supported_languages"], festival["default_language"])
    row = one(connection, """UPDATE visitor_sessions SET language=%s,accessibility_preferences=coalesce(%s,accessibility_preferences)
        WHERE id=%s RETURNING id,language,accessibility_preferences,expires_at""",
        (language, jsonb(body.accessibility_preferences) if body.accessibility_preferences is not None else None, visitor["id"]))
    return success(request, row)


@router.get("/public/festivals/{festival_code}/crowd")
def public_crowd(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT DISTINCT ON (cs.area_id,coalesce(cs.program_session_id,'00000000-0000-0000-0000-000000000000'::uuid))
        cs.area_id,a.name AS area_name,cs.program_session_id,cs.crowd_level,cs.estimated_wait_min,cs.captured_at,
        cs.expires_at,(cs.expires_at<=now()) AS stale
        FROM crowd_snapshots cs JOIN festival_areas a ON a.id=cs.area_id WHERE cs.festival_id=%s
        ORDER BY cs.area_id,coalesce(cs.program_session_id,'00000000-0000-0000-0000-000000000000'::uuid),cs.captured_at DESC""", (festival["id"],))
    cached(response, 15)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/businesses")
def public_businesses(festival_code: str, request: Request, response: Response, connection: Db, category: str | None = None):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT fb.id,b.name,fb.category,fb.description,fb.menu,fb.operating_hours,fb.accessibility,
        b.address,bo.booth_no,bo.area_id,a.name AS area_name FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id
        LEFT JOIN booths bo ON bo.festival_business_id=fb.id LEFT JOIN festival_areas a ON a.id=bo.area_id
        WHERE fb.festival_id=%s AND fb.participation_status='APPROVED' AND b.status='ACTIVE'
          AND (%s::text IS NULL OR fb.category=%s) ORDER BY b.name""", (festival["id"], category, category))
    cached(response)
    return success(request, rows)


@router.get("/public/festivals/{festival_code}/coupons")
def public_coupons(festival_code: str, request: Request, response: Response, connection: Db):
    festival = published_festival(connection, festival_code)
    rows = all_rows(connection, """SELECT c.id,c.name,c.description,c.benefit_type,c.benefit_value,c.valid_from,c.valid_until,
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
        contact = json.dumps(body.contact, ensure_ascii=False) if body.contact else None
        try:
            row = one(connection, """INSERT INTO bookings(festival_id,visitor_session_id,program_session_id,status,party_size,queue_number,contact_encrypted)
                VALUES(%s,%s,%s,%s,%s,%s,CASE WHEN %s::text IS NULL THEN NULL ELSE pgp_sym_encrypt(%s,%s) END)
                RETURNING id,status,party_size,queue_number,created_at""",
                (visitor["festival_id"], visitor["id"], session_id, "CONFIRMED" if confirmed else "WAITING", body.party_size, queue_number, contact, contact, settings.jwt_secret))
        except UniqueViolation as error:
            raise conflict("DUPLICATE_ACTION", "같은 회차의 예약 또는 대기표가 이미 있습니다.") from error
        return 201, {**row, "programTitle": session["title"], "startsAt": session["starts_at"]}
    return idempotent_success(request, response, idempotent(connection, key=idempotency_key, scope=f"booking:{visitor['id']}:{session_id}", body=body.model_dump(), work=work))


@router.delete("/visitor/bookings/{booking_id}", status_code=204)
def cancel_booking(booking_id: str, visitor: Visitor, connection: Db) -> Response:
    booking = found(one(connection, "SELECT * FROM bookings WHERE id=%s AND visitor_session_id=%s FOR UPDATE", (booking_id, visitor["id"])))
    validate_booking_transition(booking["status"], "CANCELLED")
    connection.execute("UPDATE bookings SET status='CANCELLED',cancelled_at=now(),version=version+1,updated_at=now() WHERE id=%s", (booking_id,))
    if booking["status"] == "CONFIRMED":
        session = one(connection, "SELECT capacity FROM program_sessions WHERE id=%s FOR UPDATE", (booking["program_session_id"],))
        waiting = one(connection, "SELECT * FROM bookings WHERE program_session_id=%s AND status='WAITING' ORDER BY queue_number FOR UPDATE SKIP LOCKED LIMIT 1", (booking["program_session_id"],))
        if waiting and (session["capacity"] is None or reserved_seats(connection, booking["program_session_id"]) + waiting["party_size"] <= session["capacity"]):
            connection.execute("UPDATE bookings SET status='CONFIRMED',queue_number=NULL,version=version+1,updated_at=now() WHERE id=%s", (waiting["id"],))
    return Response(status_code=204)


@router.post("/visitor/course-plans", status_code=201)
def create_course_plan(body: CoursePlanIn, request: Request, visitor: Visitor, connection: Db):
    values: list = [visitor["festival_id"], body.starts_at or datetime.now(UTC), body.excluded_program_ids]
    clauses = ["ps.festival_id=%s", "ps.status='OPEN'", "p.status='PUBLISHED'", "ps.starts_at>=%s", "NOT (p.id=ANY(%s::uuid[]))"]
    for clause, value in (("p.category=ANY(%s)", body.interests), ("ps.area_id=%s", body.area_id)):
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
    rows = all_rows(connection, """SELECT ci.id,CASE WHEN ci.expires_at<=now() AND ci.status='ISSUED' THEN 'EXPIRED' ELSE ci.status END AS status,
        ci.issued_at,ci.expires_at,c.name,c.description,c.benefit_type,c.benefit_value,b.name AS business_name
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
        today_points = one(connection, "SELECT coalesce(sum(points_delta),0)::int AS points FROM point_ledger WHERE visitor_session_id=%s AND created_at::date=CURRENT_DATE", (visitor["id"],))["points"]
        if today_points + action["points"] > action["daily_point_limit"]:
            raise conflict("DAILY_POINT_LIMIT_EXCEEDED", "일일 포인트 한도를 초과했습니다.")
        try:
            event = one(connection, """INSERT INTO reward_events(reward_action_id,visitor_session_id,verification_key,evidence)
                VALUES(%s,%s,%s,%s) RETURNING *""", (body.reward_action_id, visitor["id"], body.verification_key, jsonb(body.evidence)))
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
