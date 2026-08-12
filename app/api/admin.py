from fastapi import APIRouter, HTTPException

from app.api.responses import listed, ok
from app.repositories.ai_repository import AllenAPIError
from app.schemas.esg import ESGMetricCreate
from app.schemas.operations import IncidentCreate
from app.services.esg_service import ESGService
from app.services.festival_service import FestivalService
from app.services.operations_service import OperationsService

router = APIRouter()
festival_service = FestivalService()
operations_service = OperationsService()
esg_service = ESGService()


@router.get("/festivals/{festival_id}", summary="Get admin festival overview")
def get_admin_festival(festival_id: int) -> dict:
    return ok(festival_service.get_overview())


@router.get("/festivals/{festival_id}/programs", summary="List admin programs")
def list_admin_programs(festival_id: int, limit: int = 20) -> dict:
    return listed(festival_service.list_programs(), limit)


@router.get("/festivals/{festival_id}/facilities", summary="List admin facilities")
def list_admin_facilities(festival_id: int, limit: int = 20) -> dict:
    return listed(festival_service.list_facilities(), limit)


@router.get("/festivals/{festival_id}/dashboard", summary="Get admin dashboard")
def get_dashboard(festival_id: int) -> dict:
    return ok(operations_service.get_dashboard_stats())


@router.get("/festivals/{festival_id}/ops-tickets", summary="List operations tickets")
def list_ops_tickets(festival_id: int, limit: int = 20) -> dict:
    return listed(operations_service.list_incidents(), limit)


@router.post("/festivals/{festival_id}/ops-tickets", summary="Create operations ticket")
def create_ops_ticket(festival_id: int, payload: IncidentCreate) -> dict:
    return ok(operations_service.create_incident(payload))


@router.get("/festivals/{festival_id}/esg/metrics", summary="List ESG metrics")
def list_esg_metrics(festival_id: int, limit: int = 20) -> dict:
    return listed(esg_service.list_metrics(), limit)


@router.post("/festivals/{festival_id}/esg/metrics", summary="Create ESG metric")
def create_esg_metric(festival_id: int, payload: ESGMetricCreate) -> dict:
    return ok(esg_service.create_metric(payload))


@router.get("/festivals/{festival_id}/esg/summary", summary="Get ESG summary")
def get_esg_summary(festival_id: int) -> dict:
    return ok(esg_service.get_summary())


@router.post("/festivals/{festival_id}/esg/reports", summary="Generate ESG report")
def create_esg_report(festival_id: int) -> dict:
    return ok(esg_service.generate_report())


@router.get("/festivals/{festival_id}/ai-brief", summary="Get or generate admin AI brief")
def get_admin_ai_brief(festival_id: str, focus: str = "esg", refresh: bool = False) -> dict:
    try:
        return ok(esg_service.get_or_create_admin_ai_brief(festival_id, focus, refresh))
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
