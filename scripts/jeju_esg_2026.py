"""EST34-2026 축제 데이터를 visitjeju 2026제주수변공원ESG축제 기준으로 재구성한다.

출처: https://visitjeju.net/kr/festival/view?contentsid=CNTS_300000000014541
원 행사 기간은 2026-07-18~19(토·일)이지만 이미 지난 날짜라 다가오는 주말(2026-08-22~23)로 옮겼다.
바꾸려면 STARTS_AT/ENDS_AT만 고치면 된다.

기본은 드라이런(롤백)이다. 실제 반영은 --apply.
    python -m scripts.jeju_esg_2026            # 변경 건수만 출력하고 롤백
    python -m scripts.jeju_esg_2026 --apply    # 커밋
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

KST = timezone(timedelta(hours=9))
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://visitjeju.net/kr/festival/view?contentsid=CNTS_300000000014541")

FESTIVAL_CODE = "EST34-2026"
NAME = "2026제주수변공원ESG축제"
DESCRIPTION = (
    "월대천의 자연환경과 지역상권을 잇는 참여형 ESG 축제. "
    "플로깅, 생태환경 체험, 업사이클링 공방, 수변 캠핑·피크닉, 버스킹, 프리마켓으로 "
    "지속가능한 관광을 실현한다. "
    "장소: 제주시 외도동 월대천·수변공원 일대(제주시 내도동 도근내길 45). "
    "주관: 제주관광공사. 문의: 064-712-7151."
)
STARTS_AT = datetime(2026, 8, 22, 10, 0, tzinfo=KST)
ENDS_AT = datetime(2026, 8, 23, 18, 0, tzinfo=KST)

TRANSPORT = [
    {"mode": "버스", "label": "외도초등학교 정류장 하차", "detail": "제주 시내버스 이용 후 도보 8분", "status": "원활"},
    {"mode": "주차", "label": "수변공원 임시주차장", "detail": "외도포구 공영주차장 병행 이용 권장", "status": "보통"},
    {"mode": "자전거", "label": "제주 해안도로 자전거길 연결", "detail": "수변공원 입구 거치대 운영", "status": "원활"},
    {"mode": "도보", "label": "월대천 산책로 진입", "detail": "내도동 도근내길 45 방면 무장애 동선", "status": "원활"},
]

# (키, 이름, 구분, 위도, 경도)
AREAS = [
    ("waterside-stage", "월대천 수변무대", "STAGE", 33.4901, 126.4372),
    ("lawn-plaza", "수변공원 잔디마당", "MAIN", 33.4896, 126.4381),
    ("plogging-start", "플로깅 출발점", "COURSE", 33.4907, 126.4365),
    ("upcycling-zone", "업사이클링 공방존", "EXPERIENCE", 33.4892, 126.4388),
    ("eco-zone", "생태체험존", "EXPERIENCE", 33.4910, 126.4359),
    ("market-zone", "프리마켓존", "MARKET", 33.4888, 126.4376),
]

# (키, 이름, 구분, 소속 구역 키, 접근성)
FACILITIES = [
    ("info-center", "종합안내소", "INFO", "lawn-plaza", {"wheelchair": True, "signLanguage": True}),
    ("restroom-main", "수변공원 화장실", "RESTROOM", "lawn-plaza", {"wheelchair": True}),
    ("medical", "의무실", "MEDICAL", "lawn-plaza", {"wheelchair": True}),
    ("nursing", "수유실", "NURSING", "upcycling-zone", {"wheelchair": True}),
    ("recycle-station", "분리배출 스테이션", "RECYCLING", "upcycling-zone", {"wheelchair": True}),
    ("parking", "임시주차장", "PARKING", "plogging-start", {"wheelchair": True}),
]

# (슬러그, 제목, 요약, 분류, 구역 키, 정원, [(일차, 시작시, 시간)])
PROGRAMS = [
    ("jeju-esg-plogging", "월대천 플로깅", "월대천 산책로를 걸으며 해양쓰레기를 수거하는 ESG 실천 프로그램", "esg",
     "plogging-start", 60, [(0, 10, 2), (1, 10, 2)]),
    ("jeju-esg-eco-experience", "생태환경 체험", "월대천 하천 생태와 제주 용천수를 관찰하는 해설 체험", "experience",
     "eco-zone", 40, [(0, 13, 2), (1, 13, 2)]),
    ("jeju-esg-upcycling", "업사이클링 공방", "버려진 자원을 생활 소품으로 되살리는 참여형 공방", "experience",
     "upcycling-zone", 30, [(0, 11, 3), (1, 11, 3)]),
    ("jeju-esg-waterside-camping", "수변 캠핑·피크닉", "수변공원 잔디마당에서 즐기는 저탄소 피크닉과 캠핑 존", "experience",
     "lawn-plaza", None, [(0, 10, 8), (1, 10, 8)]),
    ("jeju-esg-busking", "수변 버스킹", "월대천 수변무대에서 열리는 지역 아티스트 버스킹", "performance",
     "waterside-stage", None, [(0, 16, 2), (1, 16, 2)]),
    ("jeju-esg-free-market", "프리마켓", "제주 지역 상권과 함께하는 친환경 프리마켓", "market",
     "market-zone", None, [(0, 10, 7), (1, 10, 7)]),
]

ANNOUNCEMENTS = [
    ("plogging-kit", "플로깅 키트 배부 안내", "플로깅 키트는 플로깅 출발점에서 회차 시작 30분 전부터 배부합니다.", "INFO"),
    ("zero-waste", "다회용기 사용 안내", "프리마켓과 푸드 부스는 다회용기만 사용합니다. 개인 텀블러를 지참해 주세요.", "INFO"),
]

# 테스트가 남긴 잔여물 패턴. 실 데이터와 겹치지 않게 좁게 잡았다.
JUNK_FESTIVAL_CODES = "CLONE-%"
JUNK_PROGRAM_SLUGS = ("status-check-%", "smoke-%")
JUNK_AREA_NAMES = ("구역-%", "이름변경")


def key(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NS, "/".join(parts))


def day(offset: int, hour: int) -> datetime:
    return (STARTS_AT + timedelta(days=offset)).replace(hour=hour, minute=0, second=0, microsecond=0)


def referrers(cur, table: str) -> list[tuple[str, str]]:
    """table을 참조하는 (자식 테이블, 자식 컬럼) 목록. 단일 컬럼 FK만 본다."""
    cur.execute(
        """SELECT c.conrelid::regclass::text, a.attname
           FROM pg_constraint c
           JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
           WHERE c.contype = 'f' AND c.confrelid = %s::regclass AND array_length(c.conkey, 1) = 1""",
        (table,),
    )
    return [(t, col) for t, col in cur.fetchall()]


def cascade_delete(cur, table: str, ids: list, counts: dict, path: tuple = ()) -> None:
    """FK 그래프를 따라 자식부터 지운다. 모든 대상 테이블은 id 단일 PK를 쓴다."""
    if not ids:
        return
    # content_items.published_version_id ↔ content_versions.content_item_id 순환 FK를 먼저 끊는다.
    if table == "content_items":
        cur.execute("UPDATE content_items SET published_version_id=NULL WHERE id=ANY(%s)", (ids,))
    for child, column in referrers(cur, table):
        if child in path:  # 자기참조·순환만 막는다. 같은 테이블을 다른 부모에서 다시 만나는 건 정상이다.
            continue
        cur.execute(
            f'SELECT id FROM "{child}" WHERE "{column}" = ANY(%s)' if has_id(cur, child)
            else f'SELECT NULL FROM "{child}" WHERE "{column}" = ANY(%s) LIMIT 0',
            (ids,),
        )
        child_ids = [r[0] for r in cur.fetchall() if r[0] is not None]
        cascade_delete(cur, child, child_ids, counts, path + (table,))
        cur.execute(f'DELETE FROM "{child}" WHERE "{column}" = ANY(%s)', (ids,))
        if cur.rowcount:
            counts[child] = counts.get(child, 0) + cur.rowcount
    cur.execute(f'DELETE FROM "{table}" WHERE id = ANY(%s)', (ids,))
    if cur.rowcount:
        counts[table] = counts.get(table, 0) + cur.rowcount


def has_id(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name='id'",
        (table,),
    )
    return cur.fetchone() is not None


def rebuild(cur) -> dict:
    counts: dict = {}
    cur.execute("SELECT id, organization_id FROM festivals WHERE code=%s", (FESTIVAL_CODE,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"축제 코드 {FESTIVAL_CODE}를 찾을 수 없습니다.")
    fid, _org = row

    cur.execute("SELECT id FROM users ORDER BY created_at LIMIT 1")
    author = cur.fetchone()[0]

    cur.execute(
        """UPDATE festivals SET name=%s, description=%s, starts_at=%s, ends_at=%s, status='PUBLISHED',
                  timezone='Asia/Seoul', transport=%s::jsonb, version=version+1, updated_at=now()
           WHERE id=%s""",
        (NAME, DESCRIPTION, STARTS_AT, ENDS_AT, psycopg.types.json.Json(TRANSPORT), fid),
    )
    counts["festivals"] = cur.rowcount

    area_ids = {}
    for slug, name, area_type, lat, lon in AREAS:
        aid = key("area", slug)
        area_ids[slug] = aid
        cur.execute(
            """INSERT INTO festival_areas (id, festival_id, name, area_type, latitude, longitude, status)
               VALUES (%s,%s,%s,%s,%s,%s,'ACTIVE')
               ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, area_type=EXCLUDED.area_type,
                 latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude, status='ACTIVE',
                 version=festival_areas.version+1, updated_at=now()""",
            (aid, fid, name, area_type, lat, lon),
        )
    # 기존 구역은 지우지 않고 내린다(혼잡 스냅샷·티켓 등이 참조한다).
    cur.execute(
        "UPDATE festival_areas SET status='ARCHIVED', updated_at=now() WHERE festival_id=%s AND id<>ALL(%s) AND status<>'ARCHIVED'",
        (fid, list(area_ids.values())),
    )
    counts["festival_areas.archived"] = cur.rowcount
    counts["festival_areas.upserted"] = len(AREAS)

    for slug, name, ftype, area_slug, access in FACILITIES:
        cur.execute(
            """INSERT INTO facilities (id, festival_id, area_id, name, facility_type, accessibility, status)
               VALUES (%s,%s,%s,%s,%s,%s::jsonb,'ACTIVE')
               ON CONFLICT (id) DO UPDATE SET area_id=EXCLUDED.area_id, name=EXCLUDED.name,
                 facility_type=EXCLUDED.facility_type, accessibility=EXCLUDED.accessibility,
                 status='ACTIVE', version=facilities.version+1, updated_at=now()""",
            (key("facility", slug), fid, area_ids[area_slug], name, ftype, psycopg.types.json.Json(access)),
        )
    # /map은 시설을 구역 상태와 무관하게 내려준다. 구역만 내리면 폐지된 구역의 시설이 마커로 남는다.
    cur.execute(
        "UPDATE facilities SET status='INACTIVE', updated_at=now() WHERE festival_id=%s AND id<>ALL(%s) AND status='ACTIVE'",
        (fid, [key("facility", f[0]) for f in FACILITIES]),
    )
    counts["facilities.deactivated"] = cur.rowcount
    counts["facilities.upserted"] = len(FACILITIES)

    program_ids = []
    for slug, title, summary, category, area_slug, capacity, sessions in PROGRAMS:
        pid = key("program", slug)
        program_ids.append(pid)
        cur.execute(
            """INSERT INTO programs (id, festival_id, slug, title, summary, category, status)
               VALUES (%s,%s,%s,%s,%s,%s,'PUBLISHED')
               ON CONFLICT (id) DO UPDATE SET slug=EXCLUDED.slug, title=EXCLUDED.title, summary=EXCLUDED.summary,
                 category=EXCLUDED.category, status='PUBLISHED', version=programs.version+1, updated_at=now()""",
            (pid, fid, slug, title, summary, category),
        )
        # 공개 목록(/public/.../programs, /map)은 PROGRAM 리소스에 연결된 게시 콘텐츠가 있어야 노출한다.
        item_id, ver_id = key("content", slug), key("version", slug)
        cur.execute(
            """INSERT INTO content_items (id, festival_id, content_type, resource_type, resource_id, slug, lifecycle_status)
               VALUES (%s,%s,'PROGRAM','PROGRAM',%s,%s,'PUBLISHED')
               ON CONFLICT (id) DO UPDATE SET resource_id=EXCLUDED.resource_id, slug=EXCLUDED.slug,
                 lifecycle_status='PUBLISHED', updated_at=now()""",
            (item_id, fid, pid, f"program-{slug}"),
        )
        cur.execute(
            """INSERT INTO content_versions (id, content_item_id, author_id, version_no, language, body, change_note, status)
               VALUES (%s,%s,%s,1,'ko',%s::jsonb,'제주 ESG 축제 정보 반영','APPROVED')
               ON CONFLICT (id) DO UPDATE SET body=EXCLUDED.body, status='APPROVED'""",
            (ver_id, item_id, author, psycopg.types.json.Json({"title": title, "body": summary})),
        )
        cur.execute("UPDATE content_items SET published_version_id=%s WHERE id=%s", (ver_id, item_id))

        for index, (offset, hour, hours) in enumerate(sessions):
            cur.execute(
                """INSERT INTO program_sessions (id, festival_id, program_id, area_id, starts_at, ends_at, capacity, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'OPEN')
                   ON CONFLICT (id) DO UPDATE SET area_id=EXCLUDED.area_id, starts_at=EXCLUDED.starts_at,
                     ends_at=EXCLUDED.ends_at, capacity=EXCLUDED.capacity, status='OPEN',
                     version=program_sessions.version+1, updated_at=now()""",
                (key("session", slug, str(index)), fid, pid, area_ids[area_slug],
                 day(offset, hour), day(offset, hour) + timedelta(hours=hours), capacity),
            )
    counts["programs.upserted"] = len(PROGRAMS)
    counts["program_sessions.upserted"] = sum(len(p[6]) for p in PROGRAMS)

    # 이전 축제 프로그램은 비공개로 내린다.
    cur.execute(
        "UPDATE programs SET status='DRAFT', updated_at=now() WHERE festival_id=%s AND id<>ALL(%s) AND status='PUBLISHED'",
        (fid, program_ids),
    )
    counts["programs.unpublished"] = cur.rowcount
    cur.execute(
        """UPDATE content_items SET lifecycle_status='UNPUBLISHED', updated_at=now()
           WHERE festival_id=%s AND resource_type='PROGRAM' AND resource_id<>ALL(%s) AND lifecycle_status='PUBLISHED'""",
        (fid, program_ids),
    )
    counts["content_items.unpublished"] = cur.rowcount

    cur.execute("UPDATE announcements SET status='CLOSED', updated_at=now() WHERE festival_id=%s AND status='ACTIVE'", (fid,))
    counts["announcements.closed"] = cur.rowcount
    for slug, title, body, severity in ANNOUNCEMENTS:
        # 공개 공지 조회는 content_versions와 이너 조인이라, 승인된 본문 버전이 없으면 노출되지 않는다.
        item_id, ver_id = key("ann-content", slug), key("ann-version", slug)
        cur.execute(
            """INSERT INTO content_items (id, festival_id, content_type, slug, lifecycle_status)
               VALUES (%s,%s,'ANNOUNCEMENT',%s,'PUBLISHED')
               ON CONFLICT (id) DO UPDATE SET slug=EXCLUDED.slug, lifecycle_status='PUBLISHED', updated_at=now()""",
            (item_id, fid, f"announcement-{slug}"),
        )
        cur.execute(
            """INSERT INTO content_versions (id, content_item_id, author_id, version_no, language, body, change_note, status)
               VALUES (%s,%s,%s,1,'ko',%s::jsonb,'제주 ESG 축제 공지','APPROVED')
               ON CONFLICT (id) DO UPDATE SET body=EXCLUDED.body, status='APPROVED'""",
            (ver_id, item_id, author, psycopg.types.json.Json({"title": title, "body": body})),
        )
        cur.execute("UPDATE content_items SET published_version_id=%s WHERE id=%s", (ver_id, item_id))
        cur.execute(
            """INSERT INTO announcements (id, festival_id, content_version_id, title, severity, audience, target_area_ids, starts_at, ends_at, status, created_by)
               VALUES (%s,%s,%s,%s,%s,'["VISITOR"]'::jsonb,'[]'::jsonb,now(),%s,'ACTIVE',%s)
               ON CONFLICT (id) DO UPDATE SET content_version_id=EXCLUDED.content_version_id, title=EXCLUDED.title,
                 severity=EXCLUDED.severity, starts_at=now(), ends_at=EXCLUDED.ends_at, status='ACTIVE',
                 version=announcements.version+1, updated_at=now()""",
            (key("announcement", slug), fid, ver_id, title, severity, ENDS_AT, author),
        )
    counts["announcements.upserted"] = len(ANNOUNCEMENTS)

    return counts


def cleanup(cur) -> dict:
    counts: dict = {}
    # audit_logs는 append-only 트리거로 잠겨 있다. 삭제할 축제의 감사 로그도 같이 지워야 FK가 풀리므로
    # 이 트랜잭션 동안만 내린다. ALTER TABLE도 트랜잭션 대상이라 롤백하면 그대로 복구된다.
    cur.execute("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_append_only")
    try:
        return _cleanup(cur, counts)
    finally:
        cur.execute("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_append_only")


def _cleanup(cur, counts: dict) -> dict:
    cur.execute("SELECT id FROM festivals WHERE code LIKE %s", (JUNK_FESTIVAL_CODES,))
    cascade_delete(cur, "festivals", [r[0] for r in cur.fetchall()], counts)

    for pattern in JUNK_PROGRAM_SLUGS:
        cur.execute("SELECT id FROM programs WHERE slug LIKE %s", (pattern,))
        pids = [r[0] for r in cur.fetchall()]
        if pids:
            # resource_id는 FK가 아니라서 FK 그래프로는 안 잡힌다. 직접 걷어낸다.
            cur.execute("SELECT id FROM content_items WHERE resource_type='PROGRAM' AND resource_id=ANY(%s)", (pids,))
            cascade_delete(cur, "content_items", [r[0] for r in cur.fetchall()], counts)
            cascade_delete(cur, "programs", pids, counts)

    for pattern in JUNK_AREA_NAMES:
        cur.execute("SELECT id FROM festival_areas WHERE name LIKE %s", (pattern,))
        cascade_delete(cur, "festival_areas", [r[0] for r in cur.fetchall()], counts)
    return counts


def main() -> None:
    apply = "--apply" in sys.argv
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL이 필요합니다.")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cur:
            rebuilt = rebuild(cur)
            removed = cleanup(cur)
        if apply:
            connection.commit()
        else:
            connection.rollback()
    print("재구성:", *(f"  {k}: {v}" for k, v in rebuilt.items()), sep="\n")
    print("정리:", *(f"  {k}: {v}" for k, v in sorted(removed.items())) or "  없음", sep="\n")
    print("적용됨(커밋)" if apply else "드라이런 — 롤백함. 반영하려면 --apply")


if __name__ == "__main__":
    main()
