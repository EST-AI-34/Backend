from fastapi import APIRouter, Request, Response
from psycopg.errors import UniqueViolation

from .. import ai
from ..context_repository import load_festival_context_rows
from ..db import all_rows, jsonb, one
from ..deps import Db, Visitor
from ..domain import classify_issue, is_safe_question, search_terms
from ..errors import bad_request, conflict, found
from ..http import success
from ..preprocessing import build_festival_context
from ..privacy import CONSENT_ITEMS, RETENTION_POLICY, WITHDRAWABLE, delete_where
from ..schemas import (ComplaintIn, ConsentPatch, ConversationIn, KioskAssistEventIn, MessageIn,
                       PrivacyRequestIn, ReportMessageIn, SurveyResponseIn, VisitorAreaIn)


router = APIRouter()

# VIS-12 구역 판정 유효시간. 지나면 미판정으로 되돌려 재진입 QR 스캔이나 수동 선택을 유도한다.
AREA_VALID_HOURS = 2
# 유효한 구역만 남기는 표현식. 공지 선별과 세션 조회가 같은 기준을 써야 화면과 전달이 어긋나지 않는다.
CURRENT_AREA = f"CASE WHEN area_assigned_at>now()-interval '{AREA_VALID_HOURS} hours' THEN current_area_id END"


def owned_conversation(connection, conversation_id: str, visitor_id) -> None:
    found(one(connection, "SELECT 1 FROM ai_conversations WHERE id=%s AND visitor_session_id=%s", (conversation_id, visitor_id)), "대화를 찾을 수 없습니다.")


def session_area(connection, visitor_id) -> dict:
    return one(connection, f"""SELECT {CURRENT_AREA} AS area_id,area_source,area_assigned_at,
        (SELECT name FROM festival_areas fa WHERE fa.id={CURRENT_AREA}) AS area_name
        FROM visitor_sessions WHERE id=%s""", (visitor_id,))


@router.delete("/visitor-sessions/current", status_code=204)
def end_session(visitor: Visitor, connection: Db) -> Response:
    connection.execute("""UPDATE visitor_sessions SET ended_at=now(),accessibility_preferences='{}',consents='{}',
        current_area_id=NULL,area_source=NULL,area_assigned_at=NULL WHERE id=%s""", (visitor["id"],))
    return Response(status_code=204)


@router.get("/visitor-sessions/current/area")
def current_area(request: Request, visitor: Visitor, connection: Db):
    """VIS-12 현재 구역. 판정하지 못한 상태를 정상으로 보고 전체 대상 콘텐츠로 폴백한다."""
    return success(request, {**session_area(connection, visitor["id"]), "validHours": AREA_VALID_HOURS})


@router.put("/visitor-sessions/current/area")
def set_area(body: VisitorAreaIn, request: Request, visitor: Visitor, connection: Db):
    """진입 QR 지점 또는 방문객의 수동 선택으로 구역을 판정한다. 브라우저 위치정보는 쓰지 않는다."""
    if body.area_id and not one(connection, "SELECT 1 FROM festival_areas WHERE id=%s AND festival_id=%s AND status='ACTIVE'",
                                (body.area_id, visitor["festival_id"])):
        raise bad_request("AREA_SCOPE_MISMATCH", "이 축제의 구역이 아닙니다.")
    connection.execute("""UPDATE visitor_sessions SET current_area_id=%s,area_source=%s,
        area_assigned_at=CASE WHEN %s::uuid IS NULL THEN NULL ELSE now() END WHERE id=%s""",
        (body.area_id, body.source if body.area_id else None, body.area_id, visitor["id"]))
    return success(request, {**session_area(connection, visitor["id"]), "validHours": AREA_VALID_HOURS})


@router.get("/visitor/announcements")
def visitor_announcements(request: Request, visitor: Visitor, connection: Db):
    """VIS-07 구역 대상 공지 선별 + OPS-10 세션별 노출 기록.

    공개 목록(`/public/.../announcements`)은 세션이 없어 구역을 알 수 없으므로 전체 공지만
    낼 수 있다. 여기서는 VIS-12 판정 결과로 targetAreaIds를 선별하고, 응답에 실제로 실린
    공지를 세션별로 남겨 운영자가 도달 결과를 확인할 수 있게 한다.

    구역을 판정하지 못한 세션에는 전체 대상 공지만 노출한다. 다만 안전 관련 긴급 공지는
    구역 판정 여부와 무관하게 전달한다(VIS-12 규칙).
    """
    area = session_area(connection, visitor["id"])
    rows = all_rows(connection, """SELECT a.id,a.title,a.severity,a.audience,a.target_area_ids,a.starts_at,a.ends_at,
        cv.body,cv.language,a.updated_at FROM announcements a JOIN content_versions cv ON cv.id=a.content_version_id
        WHERE a.festival_id=%(festival_id)s AND a.status IN ('ACTIVE','SCHEDULED') AND a.starts_at<=now()
          AND (a.ends_at IS NULL OR a.ends_at>now()) AND a.audience ? 'VISITOR' AND cv.status='APPROVED'
          AND (a.target_area_ids='[]'::jsonb OR a.severity='EMERGENCY'
               OR (%(area_id)s::uuid IS NOT NULL AND a.target_area_ids ? %(area_id)s::text))
        ORDER BY CASE a.severity WHEN 'EMERGENCY' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,a.starts_at DESC""",
        {"festival_id": visitor["festival_id"], "area_id": str(area["area_id"]) if area["area_id"] else None})
    for row in rows:
        connection.execute("""INSERT INTO notification_deliveries(festival_id,resource_type,resource_id,visitor_session_id)
            VALUES(%s,'ANNOUNCEMENT',%s,%s) ON CONFLICT DO NOTHING""", (visitor["festival_id"], row["id"], visitor["id"]))
    return success(request, {
        "items": rows, "area": area,
        # 웹 폴링은 화면을 열어 둔 세션에만 닿는다. 이 한계를 방문객 화면이 그대로 고지한다(OPS-10).
        "channel": {"type": "WEB_POLL", "pollSeconds": 30,
                    "limitation": "이 화면을 열어 둔 동안에만 새 공지가 도착합니다. 화면을 닫거나 다른 앱을 쓰는 동안에는 알림이 도달하지 않으므로, 긴급 상황은 현장 방송과 안내 인력 안내를 함께 확인해 주세요."},
    })


@router.post("/visitor/kiosk-assist-events", status_code=204)
def kiosk_assist_event(body: KioskAssistEventIn, visitor: Visitor, connection: Db) -> Response:
    """KIOSK-A11Y-01 익명 효과 지표.

    방문 세션 토큰으로 축제만 확인하고 세션 자체는 저장하지 않는다 — 어떤 세션이 고령으로
    추정됐는지가 남으면 "수집하지 않는다"는 ESG-G-08 규칙이 사실상 깨진다. 남는 것은
    축제·이벤트 종류·모델 버전·시각뿐이라, 지표는 건수 비율로만 계산된다.

    카메라 제안이 꺼진 축제에서도 MANUAL_LARGE_TEXT는 기록한다 — 중지 스위치를 내린 뒤
    수동 전환만으로 접근성 이용이 유지되는지 확인해야 하기 때문이다(ESG-G-08 완료 기준).
    """
    connection.execute("""INSERT INTO kiosk_assist_events(festival_id,event_type,model_version,result)
        VALUES(%s,%s,%s,%s)""",
                       (visitor["festival_id"], body.event_type, body.model_version, body.result))
    return Response(status_code=204)


@router.get("/visitor/privacy")
def privacy_notice(request: Request, visitor: Visitor, connection: Db):
    """OPS-11 항목별 수집 근거·보유기간과 현재 동의 상태."""
    session = one(connection, "SELECT consents FROM visitor_sessions WHERE id=%s", (visitor["id"],))
    return success(request, {"items": CONSENT_ITEMS, "consents": session["consents"], "retentionPolicy": RETENTION_POLICY})


@router.patch("/visitor/privacy/consents")
def update_consents(body: ConsentPatch, request: Request, visitor: Visitor, connection: Db):
    """항목별 동의·철회. 필수 항목은 철회 대상이 아니고, 철회는 즉시 해당 데이터에 반영된다."""
    unknown = set(body.consents) - {item["key"] for item in CONSENT_ITEMS}
    if unknown:
        raise bad_request("UNKNOWN_CONSENT_ITEM", f"정의되지 않은 수집 항목입니다: {', '.join(sorted(unknown))}")
    locked = {key for key, granted in body.consents.items() if not granted and key not in WITHDRAWABLE}
    if locked:
        raise bad_request("CONSENT_REQUIRED", "서비스 제공에 필요한 항목은 철회할 수 없습니다. 이용을 중단하려면 방문 세션을 종료해 주세요.")
    row = one(connection, "UPDATE visitor_sessions SET consents=consents||%s WHERE id=%s RETURNING consents",
              (jsonb(body.consents), visitor["id"]))
    purged = {}
    if body.consents.get("aiLog") is False:
        # 철회가 저장만 되고 이미 쌓인 기록이 남으면 철회가 아니다. 이 세션의 대화를 연쇄 파기한다.
        purged["aiLog"] = delete_where(connection, "ai_conversations", "visitor_session_id=%s", (visitor["id"],))
    return success(request, {"consents": row["consents"], "purged": purged})


@router.get("/visitor/privacy/requests")
def my_privacy_requests(request: Request, visitor: Visitor, connection: Db):
    return success(request, all_rows(connection, """SELECT id,request_type,status,detail,result,created_at,handled_at
        FROM privacy_requests WHERE visitor_session_id=%s ORDER BY created_at DESC""", (visitor["id"],)))


@router.post("/visitor/privacy/requests", status_code=201)
def create_privacy_request(body: PrivacyRequestIn, request: Request, visitor: Visitor, connection: Db):
    """열람·삭제 요구 접수.

    로그인 수단이 없으므로 본인확인은 요청에 실린 VIS-11 식별자(방문 세션 토큰)로 갈음한다.
    익명 설문 응답은 제출 이후 응답자를 특정할 수 없어 대상에서 제외된다(수집 화면에 사전 고지).
    """
    if one(connection, """SELECT 1 FROM privacy_requests WHERE visitor_session_id=%s AND request_type=%s
        AND status IN ('RECEIVED','IN_PROGRESS')""", (visitor["id"], body.request_type)):
        raise conflict("DUPLICATE_ACTION", "같은 유형의 요구가 이미 처리 중입니다.")
    row = one(connection, """INSERT INTO privacy_requests(festival_id,visitor_session_id,request_type,detail)
        VALUES(%s,%s,%s,%s) RETURNING id,request_type,status,detail,created_at""",
        (visitor["festival_id"], visitor["id"], body.request_type, body.detail))
    return success(request, {**row, "excluded": ["설문 응답(익명 처리되어 응답자를 특정할 수 없습니다)"]})


@router.post("/visitor/surveys/{survey_id}/responses", status_code=201)
def submit_survey(survey_id: str, body: SurveyResponseIn, request: Request, visitor: Visitor, connection: Db):
    survey = found(one(connection, """SELECT * FROM surveys WHERE id=%s AND festival_id=%s AND status='ACTIVE'
        AND (starts_at IS NULL OR starts_at<=now()) AND (ends_at IS NULL OR ends_at>now())""", (survey_id, visitor["festival_id"])),
        "참여 가능한 설문을 찾을 수 없습니다.")
    questions = all_rows(connection, "SELECT id,required FROM survey_questions WHERE survey_id=%s", (survey_id,))
    allowed = {str(question["id"]) for question in questions}
    submitted = {answer.question_id for answer in body.answers}
    if not submitted <= allowed:
        raise bad_request("INVALID_QUESTION", "설문에 속하지 않은 질문이 포함되어 있습니다.")
    if any(question["required"] and str(question["id"]) not in submitted for question in questions):
        raise bad_request("REQUIRED_ANSWER_MISSING", "필수 질문에 답변해 주세요.")
    try:
        row = one(connection, "INSERT INTO survey_responses(survey_id,visitor_session_id) VALUES(%s,%s) RETURNING id,created_at",
            (survey_id, visitor["id"] if survey["prevent_duplicates"] else None))
        for answer in body.answers:
            connection.execute("INSERT INTO survey_answers(response_id,question_id,value) VALUES(%s,%s,%s)", (row["id"], answer.question_id, jsonb(answer.value)))
        return success(request, row)
    except UniqueViolation as error:
        raise conflict("DUPLICATE_ACTION", "이미 이 설문에 응답했습니다.") from error


@router.post("/visitor/complaints", status_code=201)
def submit_complaint(body: ComplaintIn, request: Request, visitor: Visitor, connection: Db):
    # ponytail: 분류는 제목 앞에 붙여 운영 화면의 기존 자동 분류 규칙에 태운다. 별도 컬럼은 필요해지면 추가.
    title = f"[{body.category}] {body.title}" if body.category else body.title
    # 예전에는 priority를 지정하지 않아 전부 NORMAL로 들어갔다. 위험 브리프는 HIGH·EMERGENCY만
    # 집계하므로, 방문객이 올린 안전 민원이 운영자 위험도에 절대 반영되지 않았다.
    # 티켓 화면이 이미 쓰는 분류 규칙을 그대로 태워 안전·긴급 신호는 HIGH로 올린다.
    analysis = classify_issue(f"{title} {body.description}")
    priority = "HIGH" if analysis["urgent"] else "NORMAL"
    row = one(connection, """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,priority)
        VALUES(%s,'COMPLAINT',%s,%s,%s) RETURNING id,status,priority,created_at""",
        (visitor["festival_id"], title, body.description, priority))
    return success(request, row)


@router.post("/visitor/ai/conversations", status_code=201)
def start_conversation(body: ConversationIn, request: Request, visitor: Visitor, connection: Db):
    if body.festival_code:
        festival = one(connection, "SELECT id FROM festivals WHERE code=%s", (body.festival_code,))
        if not festival or str(festival["id"]) != str(visitor["festival_id"]):
            raise bad_request("FESTIVAL_SESSION_MISMATCH", "방문 세션과 축제가 일치하지 않습니다.")
    row = one(connection, "INSERT INTO ai_conversations(festival_id,visitor_session_id,language) VALUES(%s,%s,%s) RETURNING id,language,created_at",
        (visitor["festival_id"], visitor["id"], body.language))
    return success(request, row)


@router.post("/visitor/ai/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: MessageIn, request: Request, visitor: Visitor, connection: Db):
    owned_conversation(connection, conversation_id, visitor["id"])
    if not is_safe_question(body.message):
        fallback = {"type": "HELP_DESK"}
        row = one(connection, """INSERT INTO ai_messages(conversation_id,question,answer,safety_status,fallback,context)
            VALUES(%s,%s,%s,'BLOCKED',%s,%s) RETURNING *""",
            (conversation_id, body.message, "보안 또는 개인정보와 관련된 요청에는 답변할 수 없습니다.",
             jsonb(fallback), jsonb(body.context)))
        return success(request, {"messageId": row["id"], "answer": row["answer"], "safetyStatus": "BLOCKED",
                                 "sources": [], "fallback": fallback, "externalAiUsed": False})

    patterns = [f"%{term}%" for term in search_terms(body.message)]
    # 최신순으로 뽑던 걸 맞은 검색어 개수순으로 바꿨다. "아이 잃어버렸어요"가 분실물 안내 대신
    # "아이"만 걸린 프로그램 문서를 물어왔다. 동점이면 제목이 걸린 문서, 그다음 최신순.
    # 시드는 한 트랜잭션이라 updated_at이 전부 같다. slug까지 넣어야 순서가 매번 같다.
    sources = all_rows(connection, """SELECT content_version_id,body,language,content_type,resource_type,slug,updated_at,festival_code
        FROM (SELECT cv.id AS content_version_id,cv.body,cv.language,ci.content_type,ci.resource_type,
                ci.slug,ci.updated_at,f.code AS festival_code,
                coalesce(cv.body->>'title','') AS title,
                coalesce(cv.body->>'title','') || ' ' || coalesce(cv.body->>'summary','') || ' ' ||
                coalesce(cv.body->>'description','') || ' ' || coalesce(cv.body->>'text','') AS haystack
              FROM content_items ci
              JOIN content_versions cv ON cv.id=ci.published_version_id JOIN festivals f ON f.id=ci.festival_id
              WHERE ci.festival_id=%(festival_id)s AND ci.lifecycle_status='PUBLISHED' AND cv.status='APPROVED') candidates
        WHERE haystack ILIKE ANY(%(patterns)s)
        ORDER BY (SELECT count(*) FROM unnest(%(patterns)s::text[]) pattern WHERE haystack ILIKE pattern) DESC,
                 (SELECT count(*) FROM unnest(%(patterns)s::text[]) pattern WHERE title ILIKE pattern) DESC,
                 updated_at DESC, slug LIMIT 3""",
        {"festival_id": visitor["festival_id"], "patterns": patterns}) if patterns else []
    allowed = bool(sources)
    excerpts = [source["body"].get("summary") or source["body"].get("description") or source["body"].get("title") for source in sources]

    # 혼잡·운영 이슈·공지·프로그램·ESG처럼 승인 콘텐츠(문서)가 아니라 실시간 운영 데이터가
    # 있어야 답할 수 있는 질문("지금 어디가 혼잡해?" 등)은 아래 콘텐츠 검색만으로는 답이
    # 안 나온다. festival_context 기반 답변을 먼저 시도하고, 거기서 답을 못 만들면(비활성·
    # 실패·근거 부족) 기존 grounded_answer(승인 콘텐츠) 경로로 넘어간다 — 한 요청에서 Alan을
    # 두 번 부르지 않는다. ENABLE_EXTERNAL_AI 확인은 briefing()과 같은 자리(ai.py 함수 내부)에
    # 둔다 — 호출부마다 따로 검사하면 조건이 흩어진다.
    festival_context = build_festival_context(load_festival_context_rows(connection, visitor["festival_id"]))
    generated = ai.answer_with_festival_context(body.message, festival_context)
    freshness_at = festival_context["source_updated_at"]
    if not generated and allowed:
        generated = ai.grounded_answer(body.message, sources)
        freshness_at = sources[0]["updated_at"]

    if generated:
        answer = generated
        allowed = True
        fallback = None
    else:
        answer = "\n\n".join(filter(None, excerpts)) if allowed else "승인된 축제 정보에서 충분한 근거를 찾지 못했습니다."
        fallback = None if allowed else {"type": "HELP_DESK", "message": "현장 안내데스크 또는 공식 연락처를 이용해 주세요."}
        freshness_at = sources[0]["updated_at"] if sources else None

    row = one(connection, """INSERT INTO ai_messages(conversation_id,question,answer,safety_status,freshness_at,fallback,context)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conversation_id, body.message, answer, "ALLOWED" if allowed else "INSUFFICIENT_GROUNDING",
         freshness_at, jsonb(fallback) if fallback else None, jsonb(body.context)))
    response_sources = []
    for rank, source in enumerate(sources, 1):
        connection.execute("INSERT INTO ai_message_sources(message_id,content_version_id,rank) VALUES(%s,%s,%s)", (row["id"], source["content_version_id"], rank))
        response_sources.append({
            "contentVersionId": source["content_version_id"],
            "title": source["body"].get("title") or source["slug"],
            "resourceType": source["content_type"],
            "resourceUrl": f"/public/festivals/{source['festival_code']}/programs/{source['slug']}" if source["resource_type"] == "PROGRAM" else f"/public/festivals/{source['festival_code']}",
            "rank": rank,
        })
    return success(request, {"messageId": row["id"], "answer": row["answer"], "safetyStatus": row["safety_status"],
                             "freshnessAt": row["freshness_at"], "sources": response_sources, "fallback": fallback,
                             "externalAiUsed": generated is not None})


@router.get("/visitor/ai/conversations/{conversation_id}/messages")
def message_history(conversation_id: str, request: Request, visitor: Visitor, connection: Db):
    owned_conversation(connection, conversation_id, visitor["id"])
    rows = all_rows(connection, """SELECT m.id,m.question,m.answer,m.safety_status,m.freshness_at,m.fallback,m.created_at,
        coalesce(jsonb_agg(jsonb_build_object('contentVersionId',s.content_version_id,'rank',s.rank) ORDER BY s.rank)
          FILTER(WHERE s.content_version_id IS NOT NULL),'[]') AS sources FROM ai_messages m
        LEFT JOIN ai_message_sources s ON s.message_id=m.id WHERE m.conversation_id=%s GROUP BY m.id ORDER BY m.created_at""", (conversation_id,))
    return success(request, rows)


@router.post("/visitor/ai/messages/{message_id}/reports", status_code=201)
def report_message(message_id: str, body: ReportMessageIn, request: Request, visitor: Visitor, connection: Db):
    found(one(connection, """SELECT m.id FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id
        WHERE m.id=%s AND c.visitor_session_id=%s""", (message_id, visitor["id"])), "메시지를 찾을 수 없습니다.")
    row = one(connection, """INSERT INTO ai_message_reports(message_id,visitor_session_id,reason,detail)
        VALUES(%s,%s,%s,%s) RETURNING id,status,created_at""", (message_id, visitor["id"], body.reason, body.detail))
    return success(request, row)
