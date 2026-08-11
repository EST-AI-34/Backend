from typing import List


class MapRepository:
    def fetch_locations(self) -> List[dict]:
        return [
            {
                "id": 1,
                "name": "메인스테이지",
                "category": "program",
                "latitude": 37.5266,
                "longitude": 126.9338,
                "description": "개막 공연과 주요 무대 프로그램이 열리는 공간입니다.",
                "congestion_level": "crowded",
            },
            {
                "id": 2,
                "name": "체험존 A",
                "category": "program",
                "latitude": 37.5270,
                "longitude": 126.9328,
                "description": "업사이클링 공방과 가족 체험 프로그램을 운영합니다.",
                "congestion_level": "normal",
            },
            {
                "id": 3,
                "name": "로컬푸드존",
                "category": "food",
                "latitude": 37.5261,
                "longitude": 126.9347,
                "description": "지역 상점 메뉴와 다회용기 참여 부스가 모여 있습니다.",
                "congestion_level": "normal",
            },
            {
                "id": 4,
                "name": "통합 안내소",
                "category": "facility",
                "latitude": 37.5264,
                "longitude": 126.9332,
                "description": "분실물, 접근성 지원, 프로그램 안내를 제공합니다.",
                "congestion_level": "free",
            },
            {
                "id": 5,
                "name": "축제 응급부스",
                "category": "facility",
                "latitude": 37.5269,
                "longitude": 126.9335,
                "description": "응급 처치와 안전 지원을 받을 수 있습니다.",
                "congestion_level": "free",
            },
            {
                "id": 6,
                "name": "여의도 임시주차장 A",
                "category": "parking",
                "latitude": 37.5256,
                "longitude": 126.9324,
                "description": "사전예약 차량이 이용하는 임시주차장입니다.",
                "congestion_level": "crowded",
            },
            {
                "id": 7,
                "name": "로컬비건 빵집 바람",
                "category": "local_store",
                "latitude": 37.5259,
                "longitude": 126.9352,
                "description": "축제 쿠폰 사용이 가능한 지역 베이커리입니다.",
                "congestion_level": "normal",
            },
            {
                "id": 8,
                "name": "여의도 한강커피",
                "category": "local_store",
                "latitude": 37.5272,
                "longitude": 126.9341,
                "description": "텀블러 쿠폰을 사용할 수 있는 정문 근처 카페입니다.",
                "congestion_level": "free",
            },
        ]
