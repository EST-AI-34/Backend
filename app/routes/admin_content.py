from fastapi import APIRouter, Request
from psycopg import Connection

from ..db import all_rows, audit, jsonb, one
from ..deps import Db, Manager, ManagerOrReviewer, Operator, Scope
from ..domain import validate_content_review
from ..errors import bad_request, found, unprocessable
from ..http import success
from .admin_core import created, scoped
from ..schemas import AIDecisionIn, ContentItemIn, ContentVersionIn, PublishContentIn, ReviewIn


router = APIRouter()

VERSIONS_SQL = """SELECT cv.*,coalesce(jsonb_agg(jsonb_build_object('reviewerId',ca.reviewer_id,
    'decision',ca.decision,'comment',ca.comment,'decidedAt',ca.decided_at)) FILTER(WHERE ca.id IS NOT NULL),'[]') reviews
    FROM content_versions cv LEFT JOIN content_approvals ca ON ca.content_version_id=cv.id
    WHERE cv.content_item_id=ANY(%s::uuid[]) GROUP BY cv.id ORDER BY cv.version_no DESC"""


def versions_by_item(connection: Connection, item_ids: list) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {str(item_id): [] for item_id in item_ids}
    if item_ids:
        for version in all_rows(connection, VERSIONS_SQL, ([str(item_id) for item_id in item_ids],)):
            grouped[str(version["content_item_id"])].append(version)
    return grouped


@router.get("/admin/festivals/{festival_id}/content-items")
def items(festival_id: str, request: Request, _: Scope, connection: Db):
    rows = all_rows(connection, """SELECT ci.*,cv.version_no,cv.language,cv.status AS published_version_status
        FROM content_items ci LEFT JOIN content_versions cv ON cv.id=ci.published_version_id
        WHERE ci.festival_id=%s ORDER BY ci.updated_at DESC""", (festival_id,))
    grouped = versions_by_item(connection, [row["id"] for row in rows])
    for row in rows:
        row["versions"] = grouped[str(row["id"])]
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/content-items", status_code=201)
def create_item(festival_id: str, body: ContentItemIn, request: Request, _: Scope, user: Manager, connection: Db):
    if bool(body.resource_type) != bool(body.resource_id):
        raise bad_request("VALIDATION_ERROR", "resourceType과 resourceId는 함께 입력해야 합니다.")
    if body.resource_type == "PROGRAM" and not one(connection, "SELECT 1 FROM programs WHERE id=%s AND festival_id=%s", (body.resource_id, festival_id)):
        raise bad_request("FESTIVAL_SCOPE_MISMATCH", "프로그램이 같은 축제에 속하지 않습니다.")
    row = one(connection, "INSERT INTO content_items(festival_id,content_type,resource_type,resource_id,slug) VALUES(%s,%s,%s,%s,%s) RETURNING *",
        (festival_id, body.content_type, body.resource_type, body.resource_id, body.slug))
    created(connection, request, user, festival_id, "CONTENT_ITEM", row)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/content-items/{item_id}")
def item_detail(festival_id: str, item_id: str, request: Request, _: Scope, connection: Db):
    item = found(one(connection, "SELECT * FROM content_items WHERE id=%s AND festival_id=%s", (item_id, festival_id)))
    item["versions"] = versions_by_item(connection, [item_id])[str(item_id)]
    return success(request, item)


@router.post("/admin/festivals/{festival_id}/content-items/{item_id}/versions", status_code=201)
def create_version(festival_id: str, item_id: str, body: ContentVersionIn, request: Request, _: Scope, user: Operator, connection: Db):
    scoped(connection, "content_items", item_id, festival_id)
    row = one(connection, """INSERT INTO content_versions(content_item_id,author_id,version_no,language,body,change_note)
        SELECT %s,%s,coalesce(max(version_no),0)+1,%s,%s,%s FROM content_versions
        WHERE content_item_id=%s AND language=%s RETURNING *""",
        (item_id, user["id"], body.language, jsonb(body.body), body.change_note, item_id, body.language))
    created(connection, request, user, festival_id, "CONTENT_VERSION", row)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/content-versions/{version_id}/submit")
def submit_version(festival_id: str, version_id: str, request: Request, _: Scope, user: Operator, connection: Db):
    row = one(connection, """UPDATE content_versions cv SET status='IN_REVIEW' FROM content_items ci
        WHERE cv.id=%s AND cv.content_item_id=ci.id AND ci.festival_id=%s AND cv.status='DRAFT' RETURNING cv.*""", (version_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "초안 버전만 검수를 요청할 수 있습니다.")
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="SUBMIT_REVIEW",
          resource_type="CONTENT_VERSION", resource_id=version_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/content-versions/{version_id}/reviews")
def review_version(festival_id: str, version_id: str, body: ReviewIn, request: Request, _: Scope, user: ManagerOrReviewer, connection: Db):
    version = found(one(connection, """SELECT cv.*,ci.content_type FROM content_versions cv JOIN content_items ci ON ci.id=cv.content_item_id
        WHERE cv.id=%s AND ci.festival_id=%s""", (version_id, festival_id)))
    validate_content_review(version, str(user["id"]), body.decision)
    connection.execute("INSERT INTO content_approvals(content_version_id,reviewer_id,decision,comment) VALUES(%s,%s,%s,%s)",
        (version_id, user["id"], body.decision, body.comment))
    row = one(connection, "UPDATE content_versions SET status=%s WHERE id=%s RETURNING *", (body.decision, version_id))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action=body.decision, resource_type="CONTENT_VERSION",
          resource_id=version_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/content-items/{item_id}/publish")
def publish_item(festival_id: str, item_id: str, body: PublishContentIn, request: Request, _: Scope, user: Manager, connection: Db):
    target = found(one(connection, """SELECT ci.*,cv.status AS version_status,cv.content_item_id FROM content_items ci
        JOIN content_versions cv ON cv.id=%s WHERE ci.id=%s AND ci.festival_id=%s""", (body.version_id, item_id, festival_id)))
    if str(target["content_item_id"]) != item_id or target["version_status"] != "APPROVED":
        raise unprocessable("CONTENT_NOT_APPROVED", "이 항목의 승인된 버전만 게시할 수 있습니다.")
    row = one(connection, "UPDATE content_items SET published_version_id=%s,lifecycle_status='PUBLISHED',updated_at=now() WHERE id=%s RETURNING *", (body.version_id, item_id))
    if row["resource_type"] == "PROGRAM":
        connection.execute("UPDATE programs SET status='PUBLISHED',updated_at=now(),version=version+1 WHERE id=%s AND festival_id=%s", (row["resource_id"], festival_id))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="PUBLISH", resource_type="CONTENT_ITEM",
          resource_id=item_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.post("/admin/festivals/{festival_id}/content-items/{item_id}/unpublish")
def unpublish_item(festival_id: str, item_id: str, request: Request, _: Scope, user: Manager, connection: Db):
    row = one(connection, """UPDATE content_items SET lifecycle_status='UNPUBLISHED',updated_at=now()
        WHERE id=%s AND festival_id=%s AND lifecycle_status='PUBLISHED' RETURNING *""", (item_id, festival_id))
    if not row:
        raise bad_request("INVALID_STATE_TRANSITION", "게시 중인 콘텐츠만 종료할 수 있습니다.")
    if row["resource_type"] == "PROGRAM":
        connection.execute("UPDATE programs SET status='UNPUBLISHED',updated_at=now(),version=version+1 WHERE id=%s", (row["resource_id"],))
    audit(connection, festival_id=festival_id, actor_id=str(user["id"]), action="UNPUBLISH", resource_type="CONTENT_ITEM",
          resource_id=item_id, after_data=row, request_id=request.state.request_id)
    return success(request, row)


@router.get("/admin/festivals/{festival_id}/ai/reviews")
def ai_reviews(festival_id: str, request: Request, _: Scope, user: ManagerOrReviewer, connection: Db, status: str = "OPEN"):
    rows = all_rows(connection, """SELECT r.*,m.question,m.answer,m.safety_status,m.model_version FROM ai_message_reports r
        JOIN ai_messages m ON m.id=r.message_id JOIN ai_conversations c ON c.id=m.conversation_id
        WHERE c.festival_id=%(festival_id)s AND (%(status)s::text IS NULL OR r.status=%(status)s)
        ORDER BY r.created_at""", {"festival_id": festival_id, "status": status})
    return success(request, rows)


@router.post("/admin/festivals/{festival_id}/ai/reviews/{review_id}/decision")
def ai_decision(festival_id: str, review_id: str, body: AIDecisionIn, request: Request, _: Scope, user: ManagerOrReviewer, connection: Db):
    row = found(one(connection, """UPDATE ai_message_reports r SET status='CLOSED',decision=%s,reviewer_id=%s,reviewed_at=now()
        FROM ai_messages m,ai_conversations c WHERE r.id=%s AND r.message_id=m.id AND m.conversation_id=c.id
        AND c.festival_id=%s AND r.status='OPEN' RETURNING r.*""", (body.decision, user["id"], review_id, festival_id)))
    return success(request, row)
