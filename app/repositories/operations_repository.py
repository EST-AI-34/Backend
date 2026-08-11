from datetime import datetime
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


class OperationsRepository:
    def __init__(self) -> None:
        self._incidents = [
            {
                "id": 1,
                "category": "crowd",
                "description": "메인스테이지 입장 대기열이 길어지고 있습니다.",
                "location_id": 1,
                "priority": "high",
                "status": "in_progress",
                "assigned_user": "현장운영 A팀",
                "created_at": datetime.now(KST),
                "resolved_at": None,
            }
        ]

    def list_incidents(self) -> list[dict]:
        return list(self._incidents)

    def create_incident(self, payload: dict) -> dict:
        incident = {
            "id": len(self._incidents) + 1,
            "category": payload["category"],
            "description": payload["description"],
            "location_id": payload.get("location_id"),
            "priority": payload["priority"],
            "status": "received",
            "assigned_user": None,
            "created_at": datetime.now(KST),
            "resolved_at": None,
        }
        self._incidents.append(incident)
        return incident
