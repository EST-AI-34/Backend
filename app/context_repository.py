from .db import all_rows, one


def load_festival_context_rows(connection, festival_id: str) -> dict:
    """Load only the DB columns allowed to become Alan context."""
    return {
        "festival": one(connection, """SELECT id,code,name,timezone,status,starts_at,ends_at
            FROM festivals WHERE id=%s""", (festival_id,)),
        "congestion_samples": all_rows(connection, """SELECT DISTINCT ON (cs.area_id) cs.area_id,a.name AS area_name,
            cs.source_type,cs.crowd_level,cs.people_count,cs.estimated_wait_min,cs.captured_at,cs.expires_at
            FROM crowd_snapshots cs JOIN festival_areas a ON a.id=cs.area_id
            WHERE cs.festival_id=%s ORDER BY cs.area_id,cs.captured_at DESC LIMIT 20""", (festival_id,)),
        # 추세 판정용. 구역별 최신 한 건(위 congestion_samples)만으로는 "방금 급증"인지
        # "원래 이 정도"인지 구분할 수 없다.
        "congestion_recent": all_rows(connection, """SELECT cs.area_id,cs.crowd_level,cs.people_count,cs.captured_at
            FROM crowd_snapshots cs WHERE cs.festival_id=%s AND cs.captured_at>now()-interval '2 hours'
            ORDER BY cs.area_id,cs.captured_at""", (festival_id,)),
        "visitor_count_samples": [one(connection, """SELECT
            count(*) FILTER (WHERE ended_at IS NULL AND expires_at>now())::int AS active_sessions,
            count(*) FILTER (WHERE created_at>=now()-interval '24 hours')::int AS created_last_24h,
            count(*) FILTER (WHERE ended_at>=now()-interval '24 hours')::int AS ended_last_24h,
            now() AS sampled_at
            FROM visitor_sessions WHERE festival_id=%s""", (festival_id,))],
        "ops_tickets": all_rows(connection, """SELECT t.ticket_type,t.title,t.priority,t.status,a.name AS area_name,
            t.created_at,t.updated_at FROM ops_tickets t LEFT JOIN festival_areas a ON a.id=t.area_id
            WHERE t.festival_id=%s AND t.status NOT IN ('RESOLVED','CLOSED')
            ORDER BY CASE t.priority WHEN 'EMERGENCY' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END,
                     t.updated_at DESC LIMIT 20""", (festival_id,)),
        "announcements": all_rows(connection, """SELECT a.title,a.severity,a.status,a.starts_at,a.ends_at,a.updated_at
            FROM announcements a WHERE a.festival_id=%s
              AND a.status IN ('ACTIVE','SCHEDULED')
              AND (a.ends_at IS NULL OR a.ends_at>now()-interval '24 hours')
            ORDER BY CASE a.severity WHEN 'EMERGENCY' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,
                     a.starts_at DESC NULLS LAST LIMIT 10""", (festival_id,)),
        "esg_measurements": all_rows(connection, """SELECT m.name AS metric_name,m.category,em.value,v.unit,v.target,
            em.status,em.measured_at FROM esg_measurements em
            JOIN esg_metric_versions v ON v.id=em.metric_version_id
            JOIN esg_metrics m ON m.id=v.metric_id
            WHERE em.festival_id=%s AND em.status='APPROVED'
            ORDER BY em.measured_at DESC LIMIT 20""", (festival_id,)),
        # 회차(program_sessions) 단위로 내려서 "퍼레이드 몇 시야?"에 실제 시작 시각을,
        # "일정 바뀌었어?"에 변경 여부를 답할 수 있게 한다. 프로그램 단위 요약만으로는
        # 어느 것도 답할 수 없다(association 없이는 시각이 없다).
        "programs": all_rows(connection, """SELECT p.slug,p.title,p.category,a.name AS area_name,
            ps.starts_at,ps.ends_at,ps.created_at,ps.updated_at,
            (ps.updated_at>ps.created_at+interval '1 minute') AS rescheduled
            FROM programs p JOIN program_sessions ps ON ps.program_id=p.id
            LEFT JOIN festival_areas a ON a.id=ps.area_id
            WHERE p.festival_id=%s AND p.status IN ('PUBLISHED','UNPUBLISHED')
              AND ps.starts_at>=now()-interval '2 hours'
            ORDER BY ps.starts_at LIMIT 15""", (festival_id,)),
        "facilities": all_rows(connection, """SELECT f.name,f.facility_type,a.name AS area_name
            FROM facilities f JOIN festival_areas a ON a.id=f.area_id
            WHERE f.festival_id=%s AND f.status='ACTIVE'
            ORDER BY f.facility_type,f.name LIMIT 30""", (festival_id,)),
    }
