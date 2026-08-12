from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.repositories.ai_repository import AIRepository, AllenAPIError
from app.repositories.esg_repository import ESGRepository
from app.schemas.esg import ESGBriefing, ESGMetric, ESGMetricCreate, ESGReport, ESGSummary, FestivalAIBrief


KST = ZoneInfo("Asia/Seoul")


class ESGService:
    def __init__(self) -> None:
        self.repo = ESGRepository()
        self.ai_repo = AIRepository()

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

    def generate_admin_briefing(self) -> ESGBriefing:
        metrics = self.list_metrics()
        summary = self.get_summary()
        context = self._build_esg_briefing_context(summary)
        result = self.ai_repo.create_esg_briefing(context)
        return ESGBriefing(
            briefing=result["briefing"],
            source=result["source"],
            metrics=metrics,
            generated_at=datetime.now(KST),
        )

    def get_or_create_admin_ai_brief(
        self,
        festival_code: str,
        focus: str = "esg",
        refresh: bool = False,
    ) -> FestivalAIBrief:
        if focus != "esg":
            focus = "esg"

        if not refresh:
            saved = self.repo.get_latest_briefing(festival_code, focus)
            if saved:
                return FestivalAIBrief(**saved)

        metrics = self.list_metrics()
        summary = self.get_summary()
        context = self._build_esg_briefing_context(summary)
        metric = self._select_primary_metric(metrics)
        if settings.ENABLE_EXTERNAL_AI:
            try:
                result = self.ai_repo.create_esg_briefing(context)
            except AllenAPIError:
                result = {
                    "briefing": self._build_fast_db_briefing(summary, metric),
                    "source": "db-fast-fallback",
                }
        else:
            result = {
                "briefing": self._build_fast_db_briefing(summary, metric),
                "source": "db-fast-fallback",
            }
        payload = {
            "summary": result["briefing"],
            "allen_comment": result["briefing"],
            "metric_label": metric.metric_name,
            "metric_value": f"{metric.value:g}{metric.unit}",
            "status": self._status_from_summary(summary),
            "sources": [metric.source for metric in metrics if metric.source],
            "provider": result["source"],
            "context_snapshot": context,
            "generated_at": datetime.now(KST),
        }
        return FestivalAIBrief(**self.repo.save_briefing(festival_code, focus, payload))

    def _build_esg_briefing_context(self, summary: ESGSummary) -> list[str]:
        rows = [
            f"environment_score={summary.environment_score:.1f}",
            f"social_score={summary.social_score:.1f}",
            f"governance_score={summary.governance_score:.1f}",
        ]
        rows.extend(f"highlight={item}" for item in summary.highlights)
        for metric in summary.metrics:
            rows.append(
                "metric="
                f"category:{metric.category}; "
                f"name:{metric.metric_name}; "
                f"value:{metric.value:g}{metric.unit}; "
                f"source:{metric.source}; "
                f"recorded_at:{metric.recorded_at.isoformat()}"
            )
        return rows

    def _select_primary_metric(self, metrics: list[ESGMetric]) -> ESGMetric:
        environment = [item for item in metrics if item.category == "environment"]
        if environment:
            return environment[0]
        if metrics:
            return metrics[0]
        return ESGMetric(
            id="fallback",
            festival_id="fallback",
            category="environment",
            metric_name="ESG 운영 지표",
            value=0,
            unit="",
            source="No ESG metric rows",
            recorded_at=datetime.now(KST),
        )

    def _build_fast_db_briefing(self, summary: ESGSummary, metric: ESGMetric) -> str:
        score_by_category = {
            "environment": summary.environment_score,
            "social": summary.social_score,
            "governance": summary.governance_score,
        }
        category_label = {
            "environment": "환경",
            "social": "사회",
            "governance": "거버넌스",
        }.get(metric.category, "ESG")
        lowest_category = min(score_by_category, key=score_by_category.get)
        lowest_label = {
            "environment": "환경",
            "social": "사회",
            "governance": "거버넌스",
        }[lowest_category]
        return (
            f"{lowest_label} 점수가 상대적으로 낮아 {category_label} 지표 '{metric.metric_name}' "
            f"{metric.value:g}{metric.unit}를 먼저 점검하면 ESG 개선 속도를 가장 빠르게 높일 수 있습니다."
        )

    def _status_from_summary(self, summary: ESGSummary) -> str:
        lowest_score = min(summary.environment_score, summary.social_score, summary.governance_score)
        if lowest_score < 40:
            return "critical"
        if lowest_score < 70:
            return "warning"
        return "normal"
