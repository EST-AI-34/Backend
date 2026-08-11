from datetime import datetime
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


class ESGRepository:
    def __init__(self) -> None:
        now = datetime.now(KST)
        self._metrics = [
            {
                "id": 1,
                "festival_id": 1,
                "category": "environment",
                "metric_name": "모바일 리플릿 조회수",
                "value": 1240,
                "unit": "건",
                "source": "방문객 QR 접속 로그",
                "recorded_at": now,
            },
            {
                "id": 2,
                "festival_id": 1,
                "category": "social",
                "metric_name": "지역상권 쿠폰 사용수",
                "value": 155,
                "unit": "건",
                "source": "쿠폰 사용 로그",
                "recorded_at": now,
            },
            {
                "id": 3,
                "festival_id": 1,
                "category": "governance",
                "metric_name": "운영자 검증 업데이트",
                "value": 18,
                "unit": "건",
                "source": "관리자 승인 이력",
                "recorded_at": now,
            },
        ]

    def list_metrics(self) -> list[dict]:
        return list(self._metrics)

    def create_metric(self, payload: dict) -> dict:
        metric = {
            "id": len(self._metrics) + 1,
            "festival_id": 1,
            "recorded_at": datetime.now(KST),
            **payload,
        }
        self._metrics.append(metric)
        return metric
