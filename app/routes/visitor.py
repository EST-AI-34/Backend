from fastapi import APIRouter, Request, Response
from psycopg.errors import UniqueViolation

from ..db import all_rows, jsonb, one
from ..deps import Db, Visitor
from ..domain import is_safe_question, search_terms
from ..errors import bad_request, conflict, found
from ..http import success
from ..schemas import ComplaintIn, ConversationIn, MessageIn, ReportMessageIn, SurveyResponseIn


router = APIRouter()


def owned_conversation(connection, conversation_id: str, visitor_id) -> None:
    found(one(connection, "SELECT 1 FROM ai_conversations WHERE id=%s AND visitor_session_id=%s", (conversation_id, visitor_id)), "대화를 찾을 수 없습니다.")


@router.delete("/visitor-sessions/current", status_code=204)
def end_session(visitor: Visitor, connection: Db) -> Response:
    connection.execute("UPDATE visitor_sessions SET ended_at=now(),accessibility_preferences='{}',consents='{}' WHERE id=%s", (visitor["id"],))
    return Response(status_code=204)


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
    row = one(connection, """INSERT INTO ops_tickets(festival_id,ticket_type,title,description)
        VALUES(%s,'COMPLAINT',%s,%s) RETURNING id,status,created_at""", (visitor["festival_id"], title, body.description))
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
        row = one(connection, """INSERT INTO ai_messages(conversation_id,question,answer,safety_status,fallback)
            VALUES(%s,%s,%s,'BLOCKED',%s) RETURNING *""",
            (conversation_id, body.message, "보안 또는 개인정보와 관련된 요청에는 답변할 수 없습니다.", jsonb(fallback)))
        return success(request, {"messageId": row["id"], "answer": row["answer"], "safetyStatus": "BLOCKED", "sources": [], "fallback": fallback})

    patterns = [f"%{term}%" for term in search_terms(body.message)]
    sources = all_rows(connection, """SELECT cv.id AS content_version_id,cv.body,cv.language,ci.content_type,ci.resource_type,
        ci.slug,ci.updated_at,f.code AS festival_code FROM content_items ci
        JOIN content_versions cv ON cv.id=ci.published_version_id JOIN festivals f ON f.id=ci.festival_id
        WHERE ci.festival_id=%s AND ci.lifecycle_status='PUBLISHED' AND cv.status='APPROVED'
          AND cv.body::text ILIKE ANY(%s) ORDER BY ci.updated_at DESC LIMIT 3""", (visitor["festival_id"], patterns)) if patterns else []
    allowed = bool(sources)
    excerpts = [source["body"].get("summary") or source["body"].get("description") or source["body"].get("title") for source in sources]
    answer = "\n\n".join(filter(None, excerpts)) if allowed else "승인된 축제 정보에서 충분한 근거를 찾지 못했습니다."
    fallback = None if allowed else {"type": "HELP_DESK", "message": "현장 안내데스크 또는 공식 연락처를 이용해 주세요."}
    row = one(connection, """INSERT INTO ai_messages(conversation_id,question,answer,safety_status,freshness_at,fallback)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conversation_id, body.message, answer, "ALLOWED" if allowed else "INSUFFICIENT_GROUNDING",
         sources[0]["updated_at"] if sources else None, jsonb(fallback) if fallback else None))
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
                             "freshnessAt": row["freshness_at"], "sources": response_sources, "fallback": fallback})


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
