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
        transport = Jsonb([
            {"mode": "지하철", "status": "원활", "label": "5호선 여의나루역 2번 출구", "detail": "도보 5분, 엘리베이터 이용 가능"},
            {"mode": "버스", "status": "보통", "label": "간선 462, 753 여의나루역 정류장", "detail": "배차 8~10분"},
            {"mode": "셔틀", "status": "원활", "label": "여의도역 ↔ 축제장 무료 셔틀", "detail": "15분 간격 운행 · 전기버스"},
        ])
        festival = one(connection, """INSERT INTO festivals(organization_id,code,name,description,starts_at,ends_at,status,supported_languages,transport)
            VALUES(%s,'EST34-2026','2026 지역문화축제','AI·ESG 기반 지역축제 DX 데모','2026-09-12T00:00:00Z','2026-09-14T12:00:00Z','PUBLISHED','["ko","en","zh","ja"]',%s)
            ON CONFLICT(code) DO UPDATE SET name=excluded.name,status='PUBLISHED',
                supported_languages=excluded.supported_languages,transport=excluded.transport,updated_at=now() RETURNING *""",
            (organization["id"], transport))
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
        # 방문자 AI의 근거 코퍼스. PUBLISHED + APPROVED만 검색되므로(app/routes/visitor.py)
        # 여기 없는 주제는 전부 "근거 없음"으로 떨어진다. 데모 질문 범위를 여기서 정한다.
        # 검색은 질문 토큰 ILIKE이라 본문에 방문객이 실제로 쓰는 낱말을 그대로 넣어둔다.
        knowledge = [
            ("family-craft", "PROGRAM", "PROGRAM", program["id"], "가족 공예 체험",
             "아이와 함께 참여할 수 있으며 가족 수유실이 메인 광장에 있습니다.",
             "가족 공예 체험은 메인 광장 체험존에서 회차당 30명 규모로 운영합니다. 유아 동반 관람객은 메인 광장 가족 수유실과 기저귀 교환대를 이용할 수 있습니다."),
            ("guide-hours", "GUIDE", None, None, "운영 시간과 입장 안내",
             "축제는 2026년 9월 12일부터 14일까지 매일 10시에 열고 20시에 닫습니다. 입장료는 없습니다.",
             "축제 기간은 9월 12일 금요일부터 9월 14일 일요일까지입니다. 운영 시간은 매일 오전 10시부터 오후 8시까지이며 마지막 날은 오후 5시에 조기 종료합니다. 입장은 무료이고 별도 예매나 티켓, 표가 필요하지 않습니다. 프로그램 체험은 현장 접수 또는 앱 예약으로 참여합니다."),
            ("guide-transport", "GUIDE", None, None, "교통과 주차 안내",
             "지하철 5호선 여의나루역 2번 출구에서 도보 5분이며 무료 셔틀버스가 15분 간격으로 운행합니다.",
             "대중교통 이용을 권장합니다. 지하철은 5호선 여의나루역 2번 출구에서 걸어서 5분 거리이고 엘리베이터가 있습니다. 버스는 간선 462번, 753번이 여의나루역 정류장에 서며 배차 간격은 8~10분입니다. 여의도역과 축제장을 오가는 무료 셔틀 전기버스가 15분 간격으로 다닙니다. 축제장 전용 주차장은 없으며 주차 공간이 매우 부족하니 자가용 대신 지하철과 셔틀을 이용해 주세요. 인근 공영주차장은 유료로 운영합니다."),
            ("guide-toilet", "GUIDE", None, None, "화장실과 편의시설 위치",
             "화장실은 메인 광장, 체험존 A-2, 마켓존 G-1 세 곳에 있고 모두 장애인 화장실을 갖췄습니다.",
             "공용 화장실은 메인 광장 안내소 옆, 체험존 A-2 뒤편, 마켓존 G-1 입구까지 모두 세 곳입니다. 세 곳 모두 장애인 화장실과 기저귀 교환대를 갖추고 있습니다. 물품 보관함과 휴대폰 충전 구역은 통합 안내소에 있으며 무료 와이파이는 축제장 전 구역에서 잡힙니다."),
            ("guide-accessibility", "GUIDE", None, None, "휠체어와 유모차 접근성",
             "전 구역이 무장애 동선이며 휠체어와 유모차를 통합 안내소에서 무료로 빌려드립니다.",
             "축제장 주요 동선은 경사로와 평탄 포장으로 연결한 무장애 동선입니다. 휠체어와 유모차는 정문 입구 통합 안내소에서 신분증을 맡기고 무료로 대여할 수 있으며 수량이 한정되어 있습니다. 장애인 전용 주차 구역은 정문 옆에 마련되어 있고 수어 통역은 메인 무대 공연 시간에 제공합니다. 안내견은 모든 구역에 동반 입장할 수 있습니다."),
            ("guide-lost", "GUIDE", None, None, "잃어버린 물건과 아이 안내",
             "분실물과 미아 접수는 정문 통합 안내소에서 하며 축제 종료 후 7일간 보관합니다.",
             "물건을 잃어버렸거나 습득했다면 정문 입구 통합 안내소로 오시면 됩니다. 분실물은 축제가 끝난 뒤 7일 동안 보관하고 이후에는 관할 경찰서로 인계합니다. 아이를 잃어버렸거나 미아가 발생하면 즉시 가까운 운영 요원이나 안내소에 알려 주세요. 미아 방지 손목 밴드를 안내소에서 무료로 나눠 드립니다."),
            ("guide-medical", "GUIDE", None, None, "응급 상황과 의료 지원",
             "의료 부스는 메인 광장에 있고 폭염 시 온열 증상은 즉시 의료 부스로 안내합니다.",
             "응급 의료 부스는 메인 광장 무대 왼편에 있으며 운영 시간 내내 구급 인력이 상주합니다. 더위로 어지럽거나 메스꺼운 온열 증상이 나타나면 그늘막 쉼터에서 쉬고 의료 부스로 이동해 주세요. 그늘막 쉼터와 무료 식수대는 메인 광장과 마켓존에 있습니다. 중대한 사고는 119에 신고한 뒤 현장 책임자에게 알립니다."),
            ("guide-eco", "GUIDE", None, None, "다회용기와 친환경 참여",
             "다회용 컵을 반납하면 그린 스테이션에서 보증금을 돌려받고 리워드 포인트도 쌓입니다.",
             "축제장 음료는 일회용 컵 대신 다회용 컵으로 제공합니다. 보증금 1천 원을 내고 받은 다회용기는 그린 스테이션에 반납하면 보증금을 그대로 돌려드립니다. 반납 QR을 찍으면 친환경 축제 행동 캠페인 포인트가 하루 최대 세 번까지 적립됩니다. 그린 스테이션은 메인 광장과 마켓존 G-1 두 곳이며 분리배출 안내 요원이 상주합니다."),
            ("guide-food", "GUIDE", None, None, "먹거리와 상점 안내",
             "마켓존 G-1에 지역 농산물 음료와 먹거리 상점이 있으며 다회용 컵 사용 시 1천 원 할인 쿠폰을 씁니다.",
             "먹거리 상점과 지역 상인 부스는 마켓존 G-1에 모여 있습니다. 제주 로컬 카페는 감귤 에이드 등 지역 농산물 음료를 판매하고 운영 시간은 오전 10시부터 오후 8시까지입니다. 다회용 컵 할인 쿠폰을 쓰면 1천 원을 깎아 드립니다. 결제는 카드와 간편결제 모두 가능하고 채식 메뉴와 알레르기 성분 표시는 각 부스 메뉴판에서 확인할 수 있습니다."),
            ("guide-stamp", "GUIDE", None, None, "스탬프 투어와 리워드",
             "다섯 곳의 스탬프 스팟에서 현장 QR을 찍으면 스팟마다 10포인트를 받습니다.",
             "스탬프 투어 스팟은 정문 입구 통합 안내소, 체험존 A-2 업사이클링 공방, 마켓존 G-1 그린마켓, 전시홀 지속가능 사진전, 물빛광장 포토존까지 다섯 곳입니다. 각 스팟에 붙은 QR 코드를 앱으로 찍으면 스팟당 10포인트가 한 번씩 적립되고 하루 적립 한도는 100포인트입니다. 모은 포인트는 참여 상점 쿠폰으로 교환합니다."),
            ("guide-weather", "GUIDE", None, None, "우천과 폭염 시 운영",
             "비가 와도 실내 프로그램은 그대로 열리며 야외 공연만 취소되고 예약은 자동 환불됩니다.",
             "비가 오면 어떻게 되는지 자주 묻습니다. 가벼운 비에는 정상 운영하며 취소하지 않습니다. 호우나 강풍 특보가 내리면 야외 무대 공연과 체험 프로그램을 취소하고 예약자에게 앱 알림을 보내며 유료 예약은 자동 환불합니다. 실내 전시홀 프로그램은 날씨와 관계없이 진행합니다. 폭염 경보가 발령되면 그늘막 쉼터와 식수대를 늘리고 낮 시간 야외 프로그램을 단축 운영합니다."),
            ("guide-pet", "GUIDE", None, None, "반려동물 동반 안내",
             "반려동물은 목줄과 배변봉투를 갖추면 야외 구역에 동반할 수 있고 실내 전시홀은 안내견만 들어갑니다.",
             "강아지와 고양이 같은 반려동물은 목줄 또는 이동장과 배변봉투를 갖추면 야외 구역에 함께 오실 수 있습니다. 실내 전시홀과 먹거리 부스 내부는 안내견을 제외하고 출입이 제한됩니다. 반려동물 급수대는 물빛광장 포토존 옆에 있습니다."),
        ]
        for slug, content_type, resource_type, resource_id, title, summary, description in knowledge:
            item=(one(connection, "SELECT * FROM content_items WHERE festival_id=%s AND slug=%s",(festival["id"],slug))
                  or one(connection, "INSERT INTO content_items(festival_id,content_type,resource_type,resource_id,slug) VALUES(%s,%s,%s,%s,%s) RETURNING *",
                         (festival["id"],content_type,resource_type,resource_id,slug)))
            version=one(connection, "SELECT * FROM content_versions WHERE content_item_id=%s AND language='ko' ORDER BY version_no DESC LIMIT 1",(item["id"],))
            body=Jsonb({"title":title,"summary":summary,"description":description})
            if version:
                # 문구를 고쳐도 재실행으로 반영되게 한다. 데모 코퍼스는 최신 문장 하나면 충분하다.
                connection.execute("UPDATE content_versions SET body=%s,status='APPROVED' WHERE id=%s",(body,version["id"]))
            else:
                version=one(connection, """INSERT INTO content_versions(content_item_id,author_id,version_no,language,body,status)
                    VALUES(%s,%s,1,'ko',%s,'APPROVED') RETURNING *""",(item["id"],users["FESTIVAL_MANAGER"]["id"],body))
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
            VALUES(%s,'REUSABLE_CUP_RETURN','QR',10,3,%s) ON CONFLICT(campaign_id,action_type) DO UPDATE SET rule=excluded.rule""",
            (campaign["id"],Jsonb({"name":"다회용기 반납","location":"그린 스테이션","verificationKeys":["cup-return-main"]})))
        # 스탬프 투어 스팟. 현장 QR을 찍어 인증한다 — verificationKeys가 QR에 담기는 값이다.
        # 예전에는 SELF(자가 인증)라 현장에 가지 않아도 포인트를 받을 수 있었다.
        for action_type,name,location in [("STAMP_GUIDE_CENTER","통합 안내소","정문 입구"),("STAMP_UPCYCLE","업사이클링 공방","체험존 A-2"),
                ("STAMP_GREEN_MARKET","그린마켓","마켓존 G-1"),("STAMP_PHOTO_EXHIBIT","지속가능 사진전","전시홀"),("STAMP_PHOTO_ZONE","물빛광장 포토존","물빛광장")]:
            key=f"stamp:{action_type.lower().replace('_','-')}"
            connection.execute("""INSERT INTO reward_actions(campaign_id,action_type,verification_type,points,per_user_limit,rule)
                VALUES(%s,%s,'QR',10,1,%s) ON CONFLICT(campaign_id,action_type) DO UPDATE SET
                    verification_type=excluded.verification_type,rule=excluded.rule""",
                (campaign["id"],action_type,Jsonb({"name":name,"location":location,"verificationKeys":[key]})))
        connection.execute("""INSERT INTO internal_documents(festival_id,title,document_type,body,allowed_roles,created_by)
            SELECT %s,'폭염 대응 매뉴얼','SAFETY_MANUAL','온열 증상 발생 시 의료 부스로 안내하고 현장 책임자에게 즉시 보고합니다.',%s,%s
            WHERE NOT EXISTS(SELECT 1 FROM internal_documents WHERE festival_id=%s AND title='폭염 대응 매뉴얼')""",
            (festival["id"],Jsonb(["SUPER_ADMIN","FESTIVAL_MANAGER","FIELD_OPERATOR"]),users["FESTIVAL_MANAGER"]["id"],festival["id"]))
    print("seeded demo data")
    print("accounts: admin/manager/reviewer/operator/merchant @example.com, password: ChangeMe123!")


if __name__ == "__main__":
    main()
