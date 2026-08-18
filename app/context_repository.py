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
        "programs": all_rows(connection, """SELECT p.slug,p.title,p.category,p.status,p.updated_at,
            min(ps.starts_at) FILTER (WHERE ps.starts_at>=now()) AS next_starts_at,
            min(a.name) FILTER (WHERE ps.starts_at>=now()) AS area_name
            FROM programs p LEFT JOIN program_sessions ps ON ps.program_id=p.id
            LEFT JOIN festival_areas a ON a.id=ps.area_id
            WHERE p.festival_id=%s AND p.status IN ('PUBLISHED','UNPUBLISHED')
            GROUP BY p.id ORDER BY next_starts_at NULLS LAST,p.updated_at DESC LIMIT 10""", (festival_id,)),
    }
