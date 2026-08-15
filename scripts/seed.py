import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.db import one
from app.security import hash_password


TICKET_FLOW = ("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED")


def main() -> None:
    password_hash = hash_password("ChangeMe123!")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        organization = (one(connection, "SELECT * FROM organizations WHERE name='EST34 Demo Organization' LIMIT 1")
                        or one(connection, "INSERT INTO organizations(name) VALUES('EST34 Demo Organization') RETURNING *"))
        accounts = [
            ("admin@example.com", "최고 관리자", "SUPER_ADMIN"),
            ("manager@example.com", "축제 담당자", "FESTIVAL_MANAGER"),
            ("reviewer@example.com", "검토 담당자", "REVIEWER"),
            ("operator@example.com", "현장 운영자", "FIELD_OPERATOR"),
            ("merchant@example.com", "참여 상인", "MERCHANT"),
        ]
        users = {}
        memberships = {}
        for email, name, role in accounts:
            user = one(connection, """INSERT INTO users(email,password_hash,name) VALUES(%s,%s,%s)
                ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,name=excluded.name RETURNING *""", (email,password_hash,name))
            connection.execute("""INSERT INTO memberships(organization_id,user_id,role,festival_scope) VALUES(%s,%s,%s,%s)
                ON CONFLICT(organization_id,user_id) DO UPDATE SET role=excluded.role,festival_scope=excluded.festival_scope,status='ACTIVE'""", (organization["id"],user["id"],role,Jsonb(["*"])))
            users[role]=user
            memberships[role]=one(connection, "SELECT * FROM memberships WHERE organization_id=%s AND user_id=%s",(organization["id"],user["id"]))
        festival = one(connection, """INSERT INTO festivals(organization_id,code,name,description,starts_at,ends_at,status,supported_languages)
            VALUES(%s,'EST34-2026','2026 지역문화축제','AI·ESG 기반 지역축제 DX 데모','2026-09-12T00:00:00Z','2026-09-14T12:00:00Z','PUBLISHED','["ko","en","zh","ja"]')
            ON CONFLICT(code) DO UPDATE SET name=excluded.name,status='PUBLISHED',
                supported_languages=excluded.supported_languages,updated_at=now() RETURNING *""", (organization["id"],))
        area = (one(connection, "SELECT * FROM festival_areas WHERE festival_id=%s AND name='메인 광장'",(festival["id"],))
                or one(connection, "INSERT INTO festival_areas(festival_id,name,area_type,latitude,longitude) VALUES(%s,'메인 광장','MAIN',37.5665,126.9780) RETURNING *",(festival["id"],)))
        connection.execute("""INSERT INTO facilities(festival_id,area_id,name,facility_type,accessibility,operating_hours)
            SELECT %s,%s,'가족 수유실','NURSING_ROOM','{"wheelchair":true}','{"daily":"09:00-20:00"}'
            WHERE NOT EXISTS(SELECT 1 FROM facilities WHERE festival_id=%s AND name='가족 수유실')""",(festival["id"],area["id"],festival["id"]))
        program=one(connection, """INSERT INTO programs(festival_id,slug,title,summary,category,status)
            VALUES(%s,'family-craft','가족 공예 체험','아이와 함께 지역 공예를 체험합니다.','experience','PUBLISHED')
            ON CONFLICT(festival_id,slug) DO UPDATE SET title=excluded.title,status='PUBLISHED' RETURNING *""",(festival["id"],))
        if not one(connection, "SELECT 1 FROM program_sessions WHERE program_id=%s",(program["id"],)):
            connection.execute("""INSERT INTO program_sessions(festival_id,program_id,area_id,starts_at,ends_at,capacity)
                VALUES(%s,%s,%s,'2026-09-12T05:00:00Z','2026-09-12T06:00:00Z',30)""",(festival["id"],program["id"],area["id"]))
        item=(one(connection, "SELECT * FROM content_items WHERE festival_id=%s AND slug='family-craft'",(festival["id"],))
              or one(connection, "INSERT INTO content_items(festival_id,content_type,resource_type,resource_id,slug) VALUES(%s,'PROGRAM','PROGRAM',%s,'family-craft') RETURNING *",(festival["id"],program["id"])))
        version=one(connection, "SELECT * FROM content_versions WHERE content_item_id=%s AND language='ko' ORDER BY version_no DESC LIMIT 1",(item["id"],))
        if not version:
            version=one(connection, """INSERT INTO content_versions(content_item_id,author_id,version_no,language,body,status)
                VALUES(%s,%s,1,'ko',%s,'APPROVED') RETURNING *""",(item["id"],users["FESTIVAL_MANAGER"]["id"],Jsonb({"title":"가족 공예 체험","summary":"아이와 함께 참여할 수 있으며 가족 수유실이 메인 광장에 있습니다."})))
            connection.execute("INSERT INTO content_approvals(content_version_id,reviewer_id,decision,comment) VALUES(%s,%s,'APPROVED','데모 승인')",(version["id"],users["REVIEWER"]["id"]))
        connection.execute("UPDATE content_items SET lifecycle_status='PUBLISHED',published_version_id=%s,updated_at=now() WHERE id=%s",(version["id"],item["id"]))
        survey=one(connection, "SELECT * FROM surveys WHERE festival_id=%s AND title='방문객 만족도'",(festival["id"],))
        if not survey:
            survey=one(connection, "INSERT INTO surveys(festival_id,title,description,status) VALUES(%s,'방문객 만족도','민감정보는 입력하지 마세요.','ACTIVE') RETURNING *",(festival["id"],))
            connection.execute("""INSERT INTO survey_questions(survey_id,prompt,question_type,required,position)
                VALUES(%s,'축제에 얼마나 만족하셨나요?','RATING',true,1),(%s,'개선 의견을 알려주세요.','TEXT',false,2)""",(survey["id"],survey["id"]))
        tickets = [
            ("COMPLAINT", "메인 광장 그늘막 추가 요청", "대기 구역의 그늘 공간이 부족하다는 민원이 접수되었습니다.", "HIGH", "IN_PROGRESS"),
            ("INCIDENT", "체험존 미끄럼 사고", "현장 조치와 안전 표지 설치를 완료했습니다.", "HIGH", "RESOLVED"),
            ("COMPLAINT", "다회용기 반납 위치 안내", "반납 스테이션 안내 표지 보강이 필요합니다.", "NORMAL", "ASSIGNED"),
        ]
        for ticket_type, title, description, priority, status in tickets:
            if one(connection, "SELECT id FROM ops_tickets WHERE festival_id=%s AND title=%s", (festival["id"], title)):
                continue
            ticket = one(connection, """INSERT INTO ops_tickets(festival_id,ticket_type,title,description,area_id,priority,assignee_id,status,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (festival["id"],ticket_type,title,description,area["id"],priority,users["FIELD_OPERATOR"]["id"],status,users["FESTIVAL_MANAGER"]["id"]))
            for event_status in TICKET_FLOW[:TICKET_FLOW.index(status)+1]:
                connection.execute("INSERT INTO ops_ticket_events(ticket_id,actor_id,to_status,note) VALUES(%s,%s,%s,'데모 시드')", (ticket["id"],users["FESTIVAL_MANAGER"]["id"],event_status))
        metrics = [
            ("E", "다회용기 반납량", "반납 로그 합계", "개", 500, "REUSABLE_CUP_RETURN", 320),
            ("S", "접근성 서비스 이용", "접근성 기능 이용 로그 합계", "건", 500, "ACCESSIBILITY_USAGE", 412),
            ("G", "운영 데이터 승인율", "승인 데이터 비율", "%", 100, "APPROVAL_LOG", 83),
        ]
        for category, name, formula, unit, target, source_type, value in metrics:
            metric = (one(connection, "SELECT id FROM esg_metrics WHERE festival_id=%s AND name=%s", (festival["id"], name))
                      or one(connection, "INSERT INTO esg_metrics(festival_id,name,category,created_by) VALUES(%s,%s,%s,%s) RETURNING id", (festival["id"],name,category,users["FESTIVAL_MANAGER"]["id"])))
            metric_version = (one(connection, "SELECT id FROM esg_metric_versions WHERE metric_id=%s ORDER BY version_no DESC LIMIT 1", (metric["id"],))
                              or one(connection, """INSERT INTO esg_metric_versions(metric_id,version_no,formula,unit,target,source_requirements,evidence_required,created_by)
                                  VALUES(%s,1,%s,%s,%s,%s,false,%s) RETURNING id""", (metric["id"],formula,unit,target,Jsonb({"type":source_type}),users["FESTIVAL_MANAGER"]["id"])))
            if not one(connection, "SELECT id FROM esg_measurements WHERE metric_version_id=%s AND dedupe_key='seed-2026'", (metric_version["id"],)):
                measurement = one(connection, """INSERT INTO esg_measurements(festival_id,metric_version_id,value,source_type,source_ref,dedupe_key,measured_at,status,created_by)
                    VALUES(%s,%s,%s,%s,'데모 운영 로그','seed-2026','2026-09-13T03:00:00Z','APPROVED',%s) RETURNING id""", (festival["id"],metric_version["id"],value,source_type,users["FESTIVAL_MANAGER"]["id"]))
                connection.execute("INSERT INTO esg_reviews(measurement_id,reviewer_id,decision,comment) VALUES(%s,%s,'APPROVED','데모 시드 승인')", (measurement["id"],users["REVIEWER"]["id"]))
        business=one(connection, """INSERT INTO businesses(organization_id,registration_no,name,address)
            VALUES(%s,'EST34-DEMO-MERCHANT','제주 로컬 카페',%s)
            ON CONFLICT(organization_id,registration_no) DO UPDATE SET name=excluded.name,address=excluded.address,updated_at=now() RETURNING *""",
            (organization["id"],Jsonb({"road":"제주시 축제로 34"})))
        festival_business=(one(connection, "SELECT * FROM festival_businesses WHERE festival_id=%s AND business_id=%s",(festival["id"],business["id"]))
            or one(connection, """INSERT INTO festival_businesses(festival_id,business_id,owner_membership_id,category,description,menu,
                operating_hours,accessibility,participation_status,approved_by,approved_at)
                VALUES(%s,%s,%s,'CAFE','지역 농산물 음료와 다회용 컵을 제공합니다.',%s,%s,%s,'APPROVED',%s,now()) RETURNING *""",
                (festival["id"],business["id"],memberships["MERCHANT"]["id"],Jsonb([{"name":"감귤 에이드","price":5000}]),Jsonb({"daily":"10:00-20:00"}),Jsonb({"wheelchair":True}),users["SUPER_ADMIN"]["id"])))
        connection.execute("""INSERT INTO booths(festival_business_id,area_id,booth_no)
            SELECT %s,%s,'L-01' WHERE NOT EXISTS(SELECT 1 FROM booths WHERE festival_business_id=%s AND booth_no='L-01')""",
            (festival_business["id"],area["id"],festival_business["id"]))
        connection.execute("""INSERT INTO coupons(festival_business_id,name,description,benefit_type,benefit_value,issue_limit,valid_from,valid_until,created_by)
            SELECT %s,'다회용 컵 할인','다회용 컵 사용 시 1천 원 할인','FIXED',1000,100,%s,%s,%s
            WHERE NOT EXISTS(SELECT 1 FROM coupons WHERE festival_business_id=%s AND name='다회용 컵 할인')""",
            (festival_business["id"],festival["starts_at"],festival["ends_at"],users["MERCHANT"]["id"],festival_business["id"]))
        connection.execute("""INSERT INTO crowd_snapshots(festival_id,area_id,source_type,crowd_level,people_count,estimated_wait_min,captured_at,expires_at,created_by)
            SELECT %s,%s,'MANUAL','MODERATE',85,10,now(),now()+interval '30 minutes',%s
            WHERE NOT EXISTS(SELECT 1 FROM crowd_snapshots WHERE festival_id=%s)""",
            (festival["id"],area["id"],users["FIELD_OPERATOR"]["id"],festival["id"]))
        if not one(connection, "SELECT 1 FROM reward_campaigns WHERE festival_id=%s AND name='친환경 축제 행동'",(festival["id"],)):
            connection.execute("""INSERT INTO reward_campaigns(festival_id,name,starts_at,ends_at,daily_point_limit,created_by)
                VALUES(%s,'친환경 축제 행동',now(),%s,100,%s)""",(festival["id"],festival["ends_at"],users["FESTIVAL_MANAGER"]["id"]))
        # 축제 시작 전에도 데모에서 스탬프를 찍을 수 있도록 캠페인 기간을 지금부터 열어둔다.
        campaign=one(connection, """UPDATE reward_campaigns SET starts_at=least(starts_at,now()),status='ACTIVE'
            WHERE festival_id=%s AND name='친환경 축제 행동' RETURNING *""",(festival["id"],))
        connection.execute("""INSERT INTO reward_actions(campaign_id,action_type,verification_type,points,per_user_limit,rule)
            VALUES(%s,'REUSABLE_CUP_RETURN','QR',10,3,%s) ON CONFLICT(campaign_id,action_type) DO NOTHING""",
            (campaign["id"],Jsonb({"verificationKeys":["cup-return-main"]})))
        # 스탬프 투어 스팟. QR 스캐너가 붙기 전까지는 방문객이 직접 인증(SELF)한다.
        for action_type,name,location in [("STAMP_GUIDE_CENTER","통합 안내소","정문 입구"),("STAMP_UPCYCLE","업사이클링 공방","체험존 A-2"),
                ("STAMP_GREEN_MARKET","그린마켓","마켓존 G-1"),("STAMP_PHOTO_EXHIBIT","지속가능 사진전","전시홀"),("STAMP_PHOTO_ZONE","물빛광장 포토존","물빛광장")]:
            connection.execute("""INSERT INTO reward_actions(campaign_id,action_type,verification_type,points,per_user_limit,rule)
                VALUES(%s,%s,'SELF',10,1,%s) ON CONFLICT(campaign_id,action_type) DO NOTHING""",
                (campaign["id"],action_type,Jsonb({"name":name,"location":location})))
        connection.execute("""INSERT INTO internal_documents(festival_id,title,document_type,body,allowed_roles,created_by)
            SELECT %s,'폭염 대응 매뉴얼','SAFETY_MANUAL','온열 증상 발생 시 의료 부스로 안내하고 현장 책임자에게 즉시 보고합니다.',%s,%s
            WHERE NOT EXISTS(SELECT 1 FROM internal_documents WHERE festival_id=%s AND title='폭염 대응 매뉴얼')""",
            (festival["id"],Jsonb(["SUPER_ADMIN","FESTIVAL_MANAGER","FIELD_OPERATOR"]),users["FESTIVAL_MANAGER"]["id"],festival["id"]))
    print("seeded demo data")
    print("accounts: admin/manager/reviewer/operator/merchant @example.com, password: ChangeMe123!")


if __name__ == "__main__":
    main()
