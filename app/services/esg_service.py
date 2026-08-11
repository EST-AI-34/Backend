from datetime import datetime
from zoneinfo import ZoneInfo

from app.repositories.esg_repository import ESGRepository
from app.schemas.esg import ESGMetric, ESGMetricCreate, ESGReport, ESGSummary


KST = ZoneInfo("Asia/Seoul")


class ESGService:
    def __init__(self) -> None:
        self.repo = ESGRepository()

    def list_metrics(self) -> list[ESGMetric]:
        return [ESGMetric(**item) for item in self.repo.list_metrics()]

    def create_metric(self, payload: ESGMetricCreate) -> ESGMetric:
        return ESGMetric(**self.repo.create_metric(payload.model_dump()))

    def get_summary(self) -> ESGSummary:
        metrics = self.list_metrics()
        by_category = {
            "environment": [item.value for item in metrics if item.category == "environment"],
            "social": [item.value for item in metrics if item.category == "social"],
            "governance": [item.value for item in metrics if item.category == "governance"],
        }
        return ESGSummary(
            environment_score=min(sum(by_category["environment"]) / 20, 100),
            social_score=min(sum(by_category["social"]) / 5, 100),
            governance_score=min(sum(by_category["governance"]) * 4, 100),
            highlights=[
                "Mobile leaflet usage is replacing printed 안내문 in the visitor flow.",
                "Local coupon usage is measurable through issued and used counts.",
                "Verified operating updates provide governance traceability.",
            ],
            metrics=metrics,
        )

    def generate_report(self) -> ESGReport:
        summary = self.get_summary()
        return ESGReport(
            title="FEST ESG Performance Draft",
            summary=(
                "The festival is tracking environmental, social, and governance activity through "
                "QR usage, local coupon participation, and verified operating updates."
            ),
            achievements=summary.highlights,
            risks=[
                "Crowding and complaint response times should be reviewed after peak programs.",
                "Offline backup guidance is needed if network or AI services are unavailable.",
            ],
            next_actions=[
                "Connect ESG metrics to PostgreSQL for auditable history.",
                "Add operator approval before publishing AI-generated ESG reports.",
                "Expand accessibility and multilingual usage metrics.",
            ],
            generated_at=datetime.now(KST),
        )
