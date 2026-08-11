from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


class FestivalRepository:
    def __init__(self) -> None:
        now = datetime.now(KST)
        self._festival = {
            "id": 1,
            "name": "2026 그린한강 페스티벌",
            "location": "서울 영등포구 여의도 한강공원 물빛광장 일대",
            "start_date": "2026-09-18",
            "end_date": "2026-09-20",
            "description": "AI 맞춤 안내, 지역상권 쿠폰, 친환경 참여를 하나로 연결하는 지역축제 DX 플랫폼 데모입니다.",
            "last_updated_at": now,
        }
        self._programs = [
            {
                "id": 1,
                "festival_id": 1,
                "name": "개막 축하공연 - 로컬 인디밴드",
                "description": "메인스테이지에서 진행되는 지역 아티스트 개막 공연입니다.",
                "category": "공연",
                "start_time": datetime(2026, 9, 18, 19, 0, tzinfo=KST),
                "end_time": datetime(2026, 9, 18, 20, 30, tzinfo=KST),
                "location_id": 1,
                "capacity": 500,
                "reserved_count": 430,
                "status": "crowded",
                "tags": ["공연", "음악", "인기"],
            },
            {
                "id": 2,
                "festival_id": 1,
                "name": "업사이클링 가족 공방",
                "description": "아이와 보호자가 함께 참여하는 친환경 체험 프로그램입니다.",
                "category": "체험",
                "start_time": datetime(2026, 9, 19, 14, 0, tzinfo=KST),
                "end_time": datetime(2026, 9, 19, 15, 30, tzinfo=KST),
                "location_id": 2,
                "capacity": 80,
                "reserved_count": 42,
                "status": "open",
                "tags": ["가족", "체험", "아이", "공방"],
            },
            {
                "id": 3,
                "festival_id": 1,
                "name": "로컬푸드 마켓 투어",
                "description": "지역 상점 메뉴를 맛보고 디지털 쿠폰을 사용할 수 있는 먹거리 코스입니다.",
                "category": "먹거리",
                "start_time": datetime(2026, 9, 19, 17, 30, tzinfo=KST),
                "end_time": datetime(2026, 9, 19, 19, 0, tzinfo=KST),
                "location_id": 3,
                "capacity": 120,
                "reserved_count": 65,
                "status": "open",
                "tags": ["먹거리", "지역상권", "쿠폰"],
            },
            {
                "id": 4,
                "festival_id": 1,
                "name": "지속가능 사진전 - 우리가 지킨 강",
                "description": "한강과 지역 환경을 주제로 한 전시 프로그램입니다.",
                "category": "전시",
                "start_time": datetime(2026, 9, 20, 13, 0, tzinfo=KST),
                "end_time": datetime(2026, 9, 20, 18, 0, tzinfo=KST),
                "location_id": 2,
                "capacity": 200,
                "reserved_count": 40,
                "status": "open",
                "tags": ["전시", "사진", "ESG"],
            },
        ]
        self._facilities = [
            {
                "id": 1,
                "festival_id": 1,
                "category": "info",
                "name": "통합 안내소",
                "location_id": 4,
                "description": "분실물, 프로그램 문의, 접근성 지원을 받을 수 있는 안내 부스입니다.",
                "accessibility": ["wheelchair_accessible"],
            },
            {
                "id": 2,
                "festival_id": 1,
                "category": "medical",
                "name": "축제 응급부스",
                "location_id": 5,
                "description": "응급 처치와 안전 지원을 제공하는 현장 부스입니다.",
                "accessibility": ["wheelchair_accessible", "priority_support"],
            },
            {
                "id": 3,
                "festival_id": 1,
                "category": "parking",
                "name": "여의도 임시주차장 A",
                "location_id": 6,
                "description": "축제장과 가장 가까운 사전예약 임시주차장입니다.",
                "accessibility": ["accessible_parking"],
            },
        ]
        self._stores = [
            {
                "id": 1,
                "festival_id": 1,
                "name": "로컬비건 빵집 바람",
                "category": "restaurant",
                "location_id": 7,
                "coupon_available": True,
                "description": "다회용기 이용 시 축제 쿠폰을 사용할 수 있는 지역 베이커리입니다.",
            },
            {
                "id": 2,
                "festival_id": 1,
                "name": "여의도 한강커피",
                "category": "cafe",
                "location_id": 8,
                "coupon_available": True,
                "description": "정문 근처 카페로 텀블러 이용 쿠폰을 제공합니다.",
            },
        ]
        self._coupons = [
            {
                "id": 1,
                "store_id": 1,
                "title": "다회용기 이용 시 10% 할인",
                "issued_count": 260,
                "used_count": 91,
                "expires_at": datetime(2026, 9, 20, 23, 59, tzinfo=KST),
            },
            {
                "id": 2,
                "store_id": 2,
                "title": "텀블러 지참 시 사이즈업",
                "issued_count": 180,
                "used_count": 64,
                "expires_at": datetime(2026, 9, 20, 23, 59, tzinfo=KST),
            },
        ]
        self._notices = [
            {
                "id": 1,
                "festival_id": 1,
                "title": "메인스테이지 혼잡 안내",
                "body": "메인스테이지 입장 대기가 길어지고 있습니다. 동쪽 진입로를 이용해 주세요.",
                "level": "important",
                "published_at": now,
            },
            {
                "id": 2,
                "festival_id": 1,
                "title": "다회용컵 반납 스탬프 이벤트",
                "body": "ESG 부스에서 다회용컵을 반납하면 스탬프를 받을 수 있습니다.",
                "level": "normal",
                "published_at": now,
            },
        ]

    def get_festival(self) -> dict:
        return deepcopy(self._festival)

    def list_programs(self) -> list[dict]:
        return deepcopy(self._programs)

    def list_facilities(self) -> list[dict]:
        return deepcopy(self._facilities)

    def list_stores(self) -> list[dict]:
        return deepcopy(self._stores)

    def list_coupons(self) -> list[dict]:
        return deepcopy(self._coupons)

    def list_notices(self) -> list[dict]:
        return deepcopy(self._notices)

    def build_search_context(self) -> list[str]:
        rows = [self._festival["description"]]
        rows.extend(f"{item['name']}: {item['description']} status={item.get('status')}" for item in self._programs)
        rows.extend(f"{item['name']}: {item['description']} category={item['category']}" for item in self._facilities)
        rows.extend(f"{item['name']}: {item['description']} coupon={item['coupon_available']}" for item in self._stores)
        rows.extend(f"{item['title']}: {item['body']} level={item['level']}" for item in self._notices)
        return rows
