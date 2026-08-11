from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.security import hash_password


def main() -> None:
    password_hash = hash_password("ChangeMe123!")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        organization = connection.execute("SELECT * FROM organizations WHERE name='EST34 Demo Organization' LIMIT 1").fetchone()
        if not organization:
            organization = connection.execute("INSERT INTO organizations(name) VALUES('EST34 Demo Organization') RETURNING *").fetchone()
        accounts = [
            ("admin@example.com", "최고 관리자", "SUPER_ADMIN"),
            ("manager@example.com", "축제 담당자", "FESTIVAL_MANAGER"),
            ("reviewer@example.com", "검토 담당자", "REVIEWER"),
            ("operator@example.com", "현장 운영자", "FIELD_OPERATOR"),
        ]
        users = {}
        for email, name, role in accounts:
            user = connection.execute("""INSERT INTO users(email,password_hash,name) VALUES(%s,%s,%s)
                ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,name=excluded.name RETURNING *""", (email,password_hash,name)).fetchone()
            connection.execute("""INSERT INTO memberships(organization_id,user_id,role,festival_scope) VALUES(%s,%s,%s,%s)
                ON CONFLICT(organization_id,user_id) DO UPDATE SET role=excluded.role,festival_scope=excluded.festival_scope,status='ACTIVE'""", (organization["id"],user["id"],role,Jsonb(["*"])))
            users[role]=user
        festival = connection.execute("""INSERT INTO festivals(organization_id,code,name,description,starts_at,ends_at,status)
            VALUES(%s,'EST34-2026','2026 지역문화축제','AI·ESG 기반 지역축제 DX 데모','2026-09-12T00:00:00Z','2026-09-14T12:00:00Z','PUBLISHED')
            ON CONFLICT(code) DO UPDATE SET name=excluded.name,status='PUBLISHED',updated_at=now() RETURNING *""", (organization["id"],)).fetchone()
        area = connection.execute("SELECT * FROM festival_areas WHERE festival_id=%s AND name='메인 광장'",(festival["id"],)).fetchone()
        if not area:
            area=connection.execute("INSERT INTO festival_areas(festival_id,name,area_type,latitude,longitude) VALUES(%s,'메인 광장','MAIN',37.5665,126.9780) RETURNING *",(festival["id"],)).fetchone()
        connection.execute("""INSERT INTO facilities(festival_id,area_id,name,facility_type,accessibility,operating_hours)
            SELECT %s,%s,'가족 수유실','NURSING_ROOM','{"wheelchair":true}','{"daily":"09:00-20:00"}'
            WHERE NOT EXISTS(SELECT 1 FROM facilities WHERE festival_id=%s AND name='가족 수유실')""",(festival["id"],area["id"],festival["id"]))
        program=connection.execute("""INSERT INTO programs(festival_id,slug,title,summary,category,status)
            VALUES(%s,'family-craft','가족 공예 체험','아이와 함께 지역 공예를 체험합니다.','experience','PUBLISHED')
            ON CONFLICT(festival_id,slug) DO UPDATE SET title=excluded.title,status='PUBLISHED' RETURNING *""",(festival["id"],)).fetchone()
        if not connection.execute("SELECT 1 FROM program_sessions WHERE program_id=%s",(program["id"],)).fetchone():
            connection.execute("""INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity)
                VALUES(%s,%s,%s,'2026-09-12T05:00:00Z','2026-09-12T06:00:00Z',30)""",(festival["id"],program["id"],area["id"]))
        item=connection.execute("SELECT * FROM content_items WHERE festival_id=%s AND slug='family-craft'",(festival["id"],)).fetchone()
        if not item:item=connection.execute("INSERT INTO content_items(festival_id,content_type,resource_type,resource_id,slug) VALUES(%s,'PROGRAM','PROGRAM',%s,'family-craft') RETURNING *",(festival["id"],program["id"])).fetchone()
        version=connection.execute("SELECT * FROM content_versions WHERE content_item_id=%s AND language='ko' ORDER BY version_no DESC LIMIT 1",(item["id"],)).fetchone()
        if not version:
            version=connection.execute("""INSERT INTO content_versions(content_item_id,author_id,version_no,language,body,status)
                VALUES(%s,%s,1,'ko',%s,'APPROVED') RETURNING *""",(item["id"],users["FESTIVAL_MANAGER"]["id"],Jsonb({"title":"가족 공예 체험","summary":"아이와 함께 참여할 수 있으며 가족 수유실이 메인 광장에 있습니다."}))).fetchone()
            connection.execute("INSERT INTO content_approvals(content_version_id,reviewer_id,decision,comment) VALUES(%s,%s,'APPROVED','데모 승인')",(version["id"],users["REVIEWER"]["id"]))
        connection.execute("UPDATE content_items SET lifecycle_status='PUBLISHED',published_version_id=%s,updated_at=now() WHERE id=%s",(version["id"],item["id"]))
        survey=connection.execute("SELECT * FROM surveys WHERE festival_id=%s AND title='방문객 만족도'",(festival["id"],)).fetchone()
        if not survey:
            survey=connection.execute("INSERT INTO surveys(festival_id,title,description,status) VALUES(%s,'방문객 만족도','민감정보는 입력하지 마세요.','ACTIVE') RETURNING *",(festival["id"],)).fetchone()
            connection.execute("""INSERT INTO survey_questions(survey_id,prompt,question_type,required,position)
                VALUES(%s,'축제에 얼마나 만족하셨나요?','RATING',true,1),(%s,'개선 의견을 알려주세요.','TEXT',false,2)""",(survey["id"],survey["id"]))
        tickets = [
            ("COMPLAINT", "메인 광장 그늘막 추가 요청", "대기 구역의 그늘 공간이 부족하다는 민원이 접수되었습니다.", "HIGH", "IN_PROGRESS"),
            ("INCIDENT", "체험존 미끄럼 사고", "현장 조치와 안전 표지 설치를 완료했습니다.", "HIGH", "RESOLVED"),
            ("COMPLAINT", "다회용기 반납 위치 안내", "반납 스테이션 안내 표지 보강이 필요합니다.", "NORMAL", "ASSIGNED"),
        ]
        for ticket_type, title, description, priority, status in tickets:
            ticket = connection.execute("SELECT id FROM ops_tickets WHERE festival_id=%s AND title=%s", (festival["id"], title)).fetchone()
            if not ticket:
                ticket = connection.execute("""INSERT INTO ops_tickets(festival_id,ticket_type,title,description,area_id,priority,assignee_id,status,created_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (festival["id"],ticket_type,title,description,area["id"],priority,users["FIELD_OPERATOR"]["id"],status,users["FESTIVAL_MANAGER"]["id"])).fetchone()
                for event_status in ("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED")[:("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED").index(status)+1]:
                    connection.execute("INSERT INTO ops_ticket_events(ticket_id,actor_id,to_status,note) VALUES(%s,%s,%s,'데모 시드')", (ticket["id"],users["FESTIVAL_MANAGER"]["id"],event_status))
        metrics = [
            ("E", "다회용기 반납량", "반납 로그 합계", "개", 500, "REUSABLE_CUP_RETURN", 320),
            ("S", "접근성 서비스 이용", "접근성 기능 이용 로그 합계", "건", 500, "ACCESSIBILITY_USAGE", 412),
            ("G", "운영 데이터 승인율", "승인 데이터 비율", "%", 100, "APPROVAL_LOG", 83),
        ]
        for category, name, formula, unit, target, source_type, value in metrics:
            metric = connection.execute("SELECT id FROM esg_metrics WHERE festival_id=%s AND name=%s", (festival["id"], name)).fetchone()
            if not metric:
                metric = connection.execute("INSERT INTO esg_metrics(festival_id,name,category,created_by) VALUES(%s,%s,%s,%s) RETURNING id", (festival["id"],name,category,users["FESTIVAL_MANAGER"]["id"])).fetchone()
            metric_version = connection.execute("SELECT id FROM esg_metric_versions WHERE metric_id=%s ORDER BY version_no DESC LIMIT 1", (metric["id"],)).fetchone()
            if not metric_version:
                metric_version = connection.execute("""INSERT INTO esg_metric_versions(metric_id,version_no,formula,unit,target,source_requirements,evidence_required,created_by)
                    VALUES(%s,1,%s,%s,%s,%s,false,%s) RETURNING id""", (metric["id"],formula,unit,target,Jsonb({"type":source_type}),users["FESTIVAL_MANAGER"]["id"])).fetchone()
            measurement = connection.execute("SELECT id FROM esg_measurements WHERE metric_version_id=%s AND dedupe_key='seed-2026'", (metric_version["id"],)).fetchone()
            if not measurement:
                measurement = connection.execute("""INSERT INTO esg_measurements(festival_id,metric_version_id,value,source_type,source_ref,dedupe_key,measured_at,status,created_by)
                    VALUES(%s,%s,%s,%s,'데모 운영 로그','seed-2026','2026-09-13T03:00:00Z','APPROVED',%s) RETURNING id""", (festival["id"],metric_version["id"],value,source_type,users["FESTIVAL_MANAGER"]["id"])).fetchone()
                connection.execute("INSERT INTO esg_reviews(measurement_id,reviewer_id,decision,comment) VALUES(%s,%s,'APPROVED','데모 시드 승인')", (measurement["id"],users["REVIEWER"]["id"]))
    print("seeded demo data")
    print("accounts: admin/manager/reviewer/operator @example.com, password: ChangeMe123!")


if __name__ == "__main__":
    main()
