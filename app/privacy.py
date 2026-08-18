"""OPS-11 개인정보 동의·파기·열람과 VIS-11 식별자 재발급 판정.

기능 명세서 OPS-11 본문의 '항목별 보유기간 정책표'를 코드의 단일 기준으로 옮긴 것이다.
정책표를 화면과 파기 배치가 함께 읽어서, 안내 문구와 실제 파기 기준이 갈라지지 않게 한다.

파기는 참조 데이터까지 연쇄로 지운다. 자식 테이블 목록을 손으로 적으면 새 테이블이 생길
때마다 빠뜨리므로(예전 purge_expired가 실제로 그랬다) FK 카탈로그를 읽어 아래에서부터
지운다. 보유기간이 더 긴 항목(설문 응답 1년, 업체 매출 1년)은 세션(30일)이 먼저 지워질 때
연결만 끊어 익명 행으로 남긴다 — 연쇄 파기가 더 긴 보유기간을 앞당겨 버리면 안 된다.
"""
import hashlib
import uuid
from typing import Any

from fastapi import Request

from .config import settings
from .db import all_rows, audit, one
from .http import client_ip


# 방문객에게 항목별 수집 근거·보유기간을 그대로 보여 주기 위한 정의.
# withdrawable=False는 서비스 제공에 필수라 철회 대상이 아닌 항목이다.
CONSENT_ITEMS: list[dict[str, Any]] = [
    {"key": "identifier", "label": "방문객 익명 식별자", "featureId": "VIS-11", "withdrawable": False,
     "basis": "예약·쿠폰·포인트의 1인당 한도와 중복 발급을 판정하기 위해 필요합니다.",
     "retention": "축제 종료 후 30일"},
    {"key": "location", "label": "코스·상권 추천 위치", "featureId": "VIS-03·BIZ-03", "withdrawable": True,
     "basis": "현재 위치 주변의 코스와 참여업체를 추천하는 데만 사용합니다.",
     "retention": "추천 생성 즉시 파기(확인자료만 6개월 보관)"},
    {"key": "aiLog", "label": "AI 질의·응답 기록", "featureId": "AI-03", "withdrawable": True,
     "basis": "잘못된 답변 신고와 안전 검수에 사용합니다.",
     "retention": "90일"},
    {"key": "survey", "label": "설문 응답", "featureId": "VIS-10", "withdrawable": False,
     "basis": "익명으로 수집해 만족도 집계와 결과 보고서에 사용합니다.",
     "retention": "축제 종료 후 1년",
     "notice": "설문 응답은 제출 이후 응답자를 식별할 수 없어 열람·삭제 요구 대상에서 제외됩니다."},
]

WITHDRAWABLE = {item["key"] for item in CONSENT_ITEMS if item["withdrawable"]}

# 항목별 보유기간 정책표. 파기 배치가 이 순서대로 돈다 — 보유기간이 긴 항목을 먼저
# 처리해야 짧은 항목의 연쇄 파기가 긴 항목을 앞당겨 지우지 않는다.
RETENTION_POLICY: list[dict[str, str]] = [
    {"key": "AI_LOG", "label": "AI 질의·응답 로그", "featureId": "AI-03", "retention": "90일", "mode": "AUTO"},
    {"key": "SURVEY_RESPONSE", "label": "설문 응답", "featureId": "VIS-10", "retention": "축제 종료 후 1년", "mode": "AUTO"},
    {"key": "BUSINESS_SALES", "label": "업체 매출 데이터", "featureId": "BIZ-04", "retention": "축제 종료 후 1년(동의 철회 시 즉시)", "mode": "AUTO"},
    {"key": "VISITOR_SESSION", "label": "방문객 익명 식별자", "featureId": "VIS-11", "retention": "축제 종료 후 30일", "mode": "AUTO"},
    {"key": "LOCATION_RECORD", "label": "개인위치정보 확인자료", "featureId": "VIS-03·BIZ-03", "retention": "6개월", "mode": "AUTO"},
    {"key": "MERCHANT_ACCOUNT", "label": "상인 계정", "featureId": "BIZ-05", "retention": "비활성화 후 1년", "mode": "AUTO"},
    {"key": "BOOKING_CONTACT", "label": "예약 최소 연락정보", "featureId": "VIS-06", "retention": "해당 회차 종료 후 7일", "mode": "NOT_COLLECTED"},
    {"key": "KIOSK_CAMERA_FRAME", "label": "키오스크 얼굴 검출 프레임", "featureId": "KIOSK-A11Y-01·ESG-G-08", "retention": "기기 내 분석 직후 폐기(서버 미수집)", "mode": "NOT_COLLECTED"},
    {"key": "AUDIT_LOG", "label": "감사 로그", "featureId": "OPS-09", "retention": "2년", "mode": "MANUAL"},
]


# --- 연쇄 파기 ---------------------------------------------------------------

def _children(connection, table: str) -> list[dict]:
    """table을 참조하는 (자식 테이블, FK 컬럼). 자기참조 FK는 제외한다."""
    return all_rows(connection, """SELECT c.conrelid::regclass::text AS table_name,a.attname AS column_name
        FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
        WHERE c.contype='f' AND c.confrelid=%s::regclass AND c.conrelid<>c.confrelid""", (table,))


def _has_id(connection, table: str) -> bool:
    return bool(one(connection, """SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name='id'""", (table,)))


def delete_rows(connection, table: str, ids: list, path: frozenset[str] = frozenset()) -> int:
    """ids의 행과 이를 참조하는 모든 자식 행을 아래에서부터 지운다.

    path는 이미 지나온 테이블이다 — content_items↔content_versions처럼 서로를 참조하는
    쌍이 있어서 없으면 무한 재귀가 된다.
    """
    if not ids:
        return 0
    for child in _children(connection, table):
        child_table, column = child["table_name"], child["column_name"]
        if child_table in path or child_table == table:
            continue
        if _has_id(connection, child_table):
            child_ids = [row["id"] for row in all_rows(
                connection, f"SELECT id FROM {child_table} WHERE {column}=ANY(%s)", (ids,))]
            delete_rows(connection, child_table, child_ids, path | {table})
        else:
            connection.execute(f"DELETE FROM {child_table} WHERE {column}=ANY(%s)", (ids,))
    return connection.execute(f"DELETE FROM {table} WHERE id=ANY(%s)", (ids,)).rowcount


def delete_where(connection, table: str, where: str, params: tuple = ()) -> int:
    """조건에 맞는 행을 자식까지 연쇄 파기한다. where는 SQL 상수여야 한다(사용자 입력 금지)."""
    ids = [row["id"] for row in all_rows(connection, f"SELECT id FROM {table} WHERE {where}", params)]
    return delete_rows(connection, table, ids)


# 방문 세션보다 보유기간이 긴 항목. 세션 파기가 이들을 끌고 내려가면 안 되므로 연결만 끊는다
# (둘 다 visitor_session_id가 nullable이라 익명 행으로 남아 집계에 계속 쓰인다).
ANONYMIZE_ON_SESSION_PURGE = ("survey_responses", "business_events")


def purge_sessions(connection, where: str, params: tuple = ()) -> int:
    """방문 세션 파기. 더 긴 보유기간 항목의 연결을 먼저 끊고 나머지를 연쇄 파기한다."""
    ids = [row["id"] for row in all_rows(connection, f"SELECT id FROM visitor_sessions WHERE {where}", params)]
    if not ids:
        return 0
    for table in ANONYMIZE_ON_SESSION_PURGE:
        connection.execute(f"UPDATE {table} SET visitor_session_id=NULL WHERE visitor_session_id=ANY(%s)", (ids,))
    return delete_rows(connection, "visitor_sessions", ids)


# --- 파기 배치 ---------------------------------------------------------------

def purge_personal_data(connection) -> dict[str, int]:
    """정책표에 따라 보유기간이 지난 개인정보를 파기하고 항목별 건수를 돌려준다."""
    counts: dict[str, int] = {}

    counts["AI_LOG"] = delete_where(connection, "ai_conversations", "created_at<now()-interval '90 days'")

    counts["SURVEY_RESPONSE"] = delete_where(connection, "survey_responses", """
        EXISTS(SELECT 1 FROM surveys s JOIN festivals f ON f.id=s.festival_id
               WHERE s.id=survey_responses.survey_id AND f.ends_at<now()-interval '365 days')""")

    # 동의를 철회한 업체의 매출은 보유기간과 무관하게 즉시 파기한다.
    counts["BUSINESS_SALES"] = connection.execute("""DELETE FROM business_events be
        WHERE be.event_type='SALE' AND EXISTS(SELECT 1 FROM festival_businesses fb JOIN festivals f ON f.id=fb.festival_id
          WHERE fb.id=be.festival_business_id AND (NOT fb.sales_consent OR f.ends_at<now()-interval '365 days'))""").rowcount

    counts["VISITOR_SESSION"] = purge_sessions(connection, """EXISTS(SELECT 1 FROM festivals f
        WHERE f.id=visitor_sessions.festival_id AND f.ends_at<now()-interval '30 days')""")

    counts["LOCATION_RECORD"] = connection.execute(
        "DELETE FROM business_recommendation_events WHERE created_at<now()-make_interval(days => %s)",
        (settings.recommendation_event_retention_days,)).rowcount

    # 상인 계정은 지우면 업체 연결·감사 기록의 참조가 끊긴다. 개인정보(이메일·이름)만 지우고
    # 로그인 불가 상태로 굳힌다 — 파기 목적은 달성하면서 이력은 추적 가능하게 남는다.
    counts["MERCHANT_ACCOUNT"] = connection.execute("""UPDATE users u
        SET email='purged-'||u.id||'@invalid',name='(파기된 계정)',password_hash='',status='PURGED'
        WHERE u.status<>'PURGED' AND EXISTS(SELECT 1 FROM memberships m WHERE m.user_id=u.id
          AND m.role='MERCHANT' AND m.status='INACTIVE' AND m.deactivated_at<now()-interval '365 days')
          AND NOT EXISTS(SELECT 1 FROM memberships m WHERE m.user_id=u.id AND m.status='ACTIVE')""").rowcount

    if any(counts.values()):
        audit(connection, festival_id=None, actor_id=None, action="PURGE", resource_type="PERSONAL_DATA",
              resource_id=None, request_id=f"job_{uuid.uuid4()}", after_data=counts)
    return counts


# --- VIS-11 식별자 재발급 ------------------------------------------------------

def device_key(request: Request) -> str:
    """기기 버킷 해시.

    저장소를 비우거나 기기를 바꾸면 익명 식별자가 새로 발급되고 1인당 한도가 초기화된다.
    이를 감지하려면 식별자 밖에 남는 신호가 필요한데, 지문 수집은 하지 않기로 했으므로
    요청 헤더에서 이미 드러나는 값(User-Agent + 접속 IP)만 서명 키로 해시해 버킷으로 쓴다.
    원문은 저장하지 않고, 축제별 발급 횟수를 세는 용도로만 남는다.

    ponytail: UA+IP 버킷이라 공용 와이파이나 TRUST_PROXY_HEADERS가 꺼진 프록시 배포에서는
    서로 다른 방문객이 한 버킷에 묶여 재발급으로 잡힌다(거짓 양성). 그래서 이 신호는 차단이
    아니라 운영자 검토용으로만 쓴다 — 자동 차단이 필요해지면 현장 확인 기반 인증(QR 스팟
    재확인 등)을 더해야 하고, 브라우저 지문 수집으로 정확도를 올리는 방향은 쓰지 않는다.
    """
    raw = f"{request.headers.get('User-Agent', '')}|{client_ip(request)}"
    return hashlib.sha256(f"{settings.jwt_secret}|{raw}".encode()).hexdigest()[:32]


def record_identity(connection, festival_id, session_id, request: Request) -> dict:
    """세션 발급을 기기 버킷 단위로 기록한다. 같은 버킷의 두 번째부터는 재발급으로 본다."""
    key = device_key(request)
    prior = one(connection, """SELECT count(*)::int AS count FROM visitor_identity_events
        WHERE festival_id=%s AND device_key=%s""", (festival_id, key))["count"]
    event_type = "REISSUED" if prior else "ISSUED"
    connection.execute("""INSERT INTO visitor_identity_events(festival_id,visitor_session_id,device_key,event_type,prior_session_count)
        VALUES(%s,%s,%s,%s,%s)""", (festival_id, session_id, key, event_type, prior))
    return {"eventType": event_type, "priorSessionCount": prior}
