from fastapi import APIRouter, HTTPException

from app.repositories.ai_repository import AllenAPIError
from app.schemas.esg import ESGBriefing, ESGMetric, ESGMetricCreate, ESGReport, ESGSummary
from app.services.esg_service import ESGService

router = APIRouter()
service = ESGService()


@router.get("/metrics", response_model=list[ESGMetric], summary="List ESG metrics")
def list_metrics() -> list[ESGMetric]:
    return service.list_metrics()


@router.post("/metrics", response_model=ESGMetric, summary="Create ESG metric")
def create_metric(payload: ESGMetricCreate) -> ESGMetric:
    return service.create_metric(payload)


@router.get("/summary", response_model=ESGSummary, summary="Get ESG dashboard summary")
def get_summary() -> ESGSummary:
    return service.get_summary()


@router.post("/report", response_model=ESGReport, summary="Generate ESG performance report draft")
def generate_report() -> ESGReport:
    return service.generate_report()


@router.get("/briefing", response_model=ESGBriefing, summary="Generate one-line admin ESG briefing with Allen")
def generate_briefing() -> ESGBriefing:
    try:
        return service.generate_admin_briefing()
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
