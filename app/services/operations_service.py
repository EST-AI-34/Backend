from app.repositories.festival_repository import FestivalRepository
from app.repositories.esg_repository import ESGRepository
from app.repositories.operations_repository import OperationsRepository
from app.schemas.operations import DashboardStats, Incident, IncidentCreate


class OperationsService:
    def __init__(self) -> None:
        self.repo = OperationsRepository()
        self.festival_repo = FestivalRepository()
        self.esg_repo = ESGRepository()

    def list_incidents(self) -> list[Incident]:
        return [Incident(**item) for item in self.repo.list_incidents()]

    def create_incident(self, payload: IncidentCreate) -> Incident:
        return Incident(**self.repo.create_incident(payload.model_dump()))

    def get_dashboard_stats(self) -> DashboardStats:
        open_incidents = [item for item in self.repo.list_incidents() if item["status"] != "resolved"]
        coupons = self.festival_repo.list_coupons()
        crowded_programs = [item for item in self.festival_repo.list_programs() if item["status"] == "crowded"]
        esg_metrics = self.esg_repo.list_metrics()
        return DashboardStats(
            current_visitors=1860,
            ai_question_count=342,
            open_incident_count=len(open_incidents),
            coupon_used_count=sum(item["used_count"] for item in coupons),
            crowded_location_count=len(crowded_programs),
            esg_participation_count=int(sum(item["value"] for item in esg_metrics if item["category"] != "governance")),
        )
