from datetime import datetime
from zoneinfo import ZoneInfo

from app.repositories.ai_repository import AIRepository
from app.repositories.esg_repository import ESGRepository
from app.schemas.esg import ESGBriefing, ESGMetric, ESGMetricCreate, ESGReport, ESGSummary


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
                "모바일 안내문 조회가 종이 안내물 사용을 대체하고 있습니다.",
                "지역 쿠폰 사용량을 발급 및 사용 기록으로 측정하고 있습니다.",
                "검증된 운영 업데이트 기록으로 행사 운영의 추적 가능성을 확보하고 있습니다.",
            ],
            metrics=metrics,
        )

    def generate_report(self) -> ESGReport:
        summary = self.get_summary()
        return ESGReport(
            title="FEST ESG 성과 보고서 초안",
            summary=(
                "본 축제는 QR 안내 이용, 지역 쿠폰 참여, 검증된 운영 업데이트를 기반으로 "
                "환경, 사회, 거버넌스 활동을 추적하고 있습니다."
            ),
            achievements=summary.highlights,
            risks=[
                "인기 프로그램 종료 후 혼잡도와 민원 대응 시간을 추가로 점검해야 합니다.",
                "네트워크 또는 AI 서비스 장애에 대비한 오프라인 안내 백업이 필요합니다.",
            ],
            next_actions=[
                "ESG 지표를 PostgreSQL 기록과 연결해 감사 가능한 이력을 유지합니다.",
                "AI가 생성한 ESG 보고서를 공개하기 전에 운영자 승인 절차를 추가합니다.",
                "접근성 및 다국어 이용 지표를 확대합니다.",
            ],
            generated_at=datetime.now(KST),
        )

    def generate_admin_briefing(self) -> ESGBriefing:
        metrics = self.list_metrics()
        summary = self.get_summary()
        context = self._build_esg_briefing_context(summary)
        result = self.ai_repo.create_esg_briefing(context)
        self.repo.save_ai_briefing(
            question="관리자용 ESG 한줄 브리핑 생성",
            context=context,
            verified_result={
                "environment_score": summary.environment_score,
                "social_score": summary.social_score,
                "governance_score": summary.governance_score,
                "metric_count": len(metrics),
            },
            answer=result["briefing"],
        )
        return ESGBriefing(
            briefing=result["briefing"],
            source=result["source"],
            metrics=metrics,
            generated_at=datetime.now(KST),
        )

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
