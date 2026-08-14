import json
import random
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from psycopg import Connection

from .. import ai
from ..config import settings
from ..db import all_rows, database
from ..domain import recommendation_bias, risk_brief, score_business
from ..errors import bad_request
from ..http import success
from ..security import festival_access
from .public import published_festival


router = APIRouter()

RECOMMENDATION_POLICY = "biz-rec-v1"
# 일정 변경은 "최근에 바뀌었다"가 신호다. 창이 없으면 한 번 고친 세션이 축제 내내 위험으로 남는다.
SCHEDULE_CHANGE_HOURS = 24
# 광고는 일반 추천과 같은 상한을 쓰면 응답이 두 배가 된다. 별도 상한으로 묶는다.
SPONSORED_LIMIT = 3


@router.get("/admin/festivals/{festival_id}/risk-brief")
def admin_risk_brief(festival_id: str, request: Request, _: Annotated[dict, Depends(festival_access)], connection: Annotated[Connection, Depends(database)], include_resolved: bool = False):
    # 임계값 0이면 1건만 있어도 최고 점수라 CRITICAL이 상시화된다. 누적을 봐야 신호가 산다.
    tickets = all_rows(connection, """SELECT CASE WHEN ticket_type='COMPLAINT' THEN 'unresolved_safety_complaints' ELSE 'safety_incidents' END AS type,
        count(*)::int AS value,CASE WHEN ticket_type='COMPLAINT' THEN 3 ELSE 2 END AS threshold,
        max(updated_at) AS source_updated_at FROM ops_tickets
        WHERE festival_id=%s AND priority IN ('HIGH','EMERGENCY') AND (%s OR status NOT IN ('RESOLVED','CLOSED'))
        GROUP BY ticket_type""", (festival_id, include_resolved))
    # 혼잡도는 구역별 최신 유효 스냅샷 중 BUSY/FULL 비율(%)이다.
    crowding = all_rows(connection, """WITH latest AS (SELECT DISTINCT ON (area_id) area_id,crowd_level,captured_at
        FROM crowd_snapshots WHERE festival_id=%s AND expires_at>now() ORDER BY area_id,captured_at DESC)
        SELECT 'crowding' AS type,round(100.0*count(*) FILTER (WHERE crowd_level IN ('BUSY','FULL'))/count(*))::int AS value,
        50 AS threshold,max(captured_at) AS source_updated_at FROM latest HAVING count(*)>0""", (festival_id,))
    staffing = all_rows(connection, """SELECT 'staffing_gap' AS type,count(*)::int AS value,1 AS threshold,max(a.updated_at) AS source_updated_at
        FROM festival_areas a WHERE a.festival_id=%s AND a.status='ACTIVE'
          AND NOT EXISTS(SELECT 1 FROM staff_assignments sa WHERE sa.area_id=a.id AND sa.starts_at<=now() AND sa.ends_at>now())
        HAVING count(*)>0""", (festival_id,))
    schedule = all_rows(connection, """SELECT 'schedule_change' AS type,count(*)::int AS value,0 AS threshold,max(updated_at) AS source_updated_at
        FROM program_sessions WHERE festival_id=%s AND updated_at>created_at+interval '1 minute'
          AND updated_at>now()-make_interval(hours => %s)
        HAVING count(*)>0""", (festival_id, SCHEDULE_CHANGE_HOURS))
    signals = crowding + tickets + staffing + schedule
    brief = risk_brief(signals)
    summary = ai.briefing(ai.RISK_INSTRUCTION, brief["reasons"]) if signals else None
    return success(request, {**brief, "festival_id": festival_id,
                             "summary": summary or brief["summary"],
                             "external_ai_used": summary is not None,
                             "source_updated_at": max((signal["source_updated_at"] for signal in signals), default=None),
                             "include_resolved": include_resolved})


@router.get("/public/festivals/{festival_code}/business-recommendations")
def business_recommendations(
    festival_code: str,
    request: Request,
    connection: Annotated[Connection, Depends(database)],
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    accessibility_required: bool = False,
):
    if (latitude is None) != (longitude is None):
        raise bad_request("VALIDATION_ERROR", "latitude와 longitude는 함께 입력해야 합니다.")
    festival = published_festival(connection, festival_code)
    # 업체당 부스가 여러 개일 수 있다(booths는 booth_no로만 유일). DISTINCT ON으로 대표 부스 하나만 쓴다.
    rows = all_rows(connection, """SELECT DISTINCT ON (fb.id) fb.id,b.name,fb.category,fb.is_sponsored,fb.esg_participating,
        bo.area_id,a.name AS area_name,a.latitude,a.longitude,
        EXISTS(SELECT 1 FROM coupons c WHERE c.festival_business_id=fb.id AND c.status='ACTIVE'
               AND c.valid_from<=now() AND c.valid_until>now()) AS coupon_available
        FROM festival_businesses fb JOIN businesses b ON b.id=fb.business_id
        LEFT JOIN booths bo ON bo.festival_business_id=fb.id AND bo.status='ACTIVE'
        LEFT JOIN festival_areas a ON a.id=bo.area_id
        WHERE fb.festival_id=%s AND fb.participation_status='APPROVED' AND b.status='ACTIVE'
          AND (%s::text IS NULL OR fb.category=%s)
          AND (NOT %s OR fb.accessibility @> '{"wheelchair": true}')
        ORDER BY fb.id,bo.booth_no""", (festival["id"], category, category, accessibility_required))
    scored = sorted((score_business(row, latitude, longitude, category) for row in rows),
                    key=lambda item: (-item["score"], item["business_id"]))
    result = {
        "festival_id": str(festival["id"]),
        "items": [item for item in scored if not item["is_sponsored"]][:limit],
        "sponsored_items": [item for item in scored if item["is_sponsored"]][:min(limit, SPONSORED_LIMIT)],
        "recommendation_policy_version": RECOMMENDATION_POLICY,
    }
    connection.execute("""INSERT INTO business_recommendation_events(festival_id,request_snapshot,response_snapshot,policy_version)
        VALUES(%s,%s::jsonb,%s::jsonb,%s)""",
        (festival["id"],
         json.dumps({"latitude": latitude, "longitude": longitude, "category": category, "limit": limit,
                     "accessibility_required": accessibility_required}),
         json.dumps(result, ensure_ascii=False, default=str), RECOMMENDATION_POLICY))
    prune_recommendation_events(connection, festival["id"])
    # ponytail: 노출 이력을 남겨야 편향 점검이 성립하므로 이 GET은 캐시하지 않는다.
    return success(request, result)


def prune_recommendation_events(connection: Connection, festival_id) -> None:
    """인증 없는 GET이 행을 계속 쌓으므로 보존 기간이 지난 것은 버린다.

    ponytail: 삽입 경로에 1% 확률로 묻어 크론 없이 굴린다. festival_id로 좁혀
    recommendation_events_window_idx를 타므로 삭제는 짧다. 스케줄러가 생기면 옮긴다.
    """
    if random.random() >= 0.01:
        return
    connection.execute("""DELETE FROM business_recommendation_events
        WHERE festival_id=%s AND created_at<now()-make_interval(days => %s)""",
        (festival_id, settings.recommendation_event_retention_days))


@router.get("/admin/festivals/{festival_id}/recommendation-bias")
def admin_recommendation_bias(
    festival_id: str,
    request: Request,
    _: Annotated[dict, Depends(festival_access)],
    connection: Annotated[Connection, Depends(database)],
    window_days: Annotated[int, Query(ge=1, le=90)] = 7,
    max_business_share: Annotated[float, Query(gt=0, le=1)] = 0.6,
    max_category_share: Annotated[float, Query(gt=0, le=1)] = 0.75,
):
    events = all_rows(connection, """SELECT response_snapshot FROM business_recommendation_events
        WHERE festival_id=%s AND created_at>=now()-make_interval(days => %s) ORDER BY created_at DESC""",
        (festival_id, window_days))
    audit = recommendation_bias(events, max_business_share, max_category_share)
    return success(request, {**audit, "festival_id": festival_id, "window_days": window_days})
