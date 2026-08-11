from fastapi import APIRouter

from app.schemas.operations import DashboardStats, Incident, IncidentCreate
from app.services.operations_service import OperationsService

router = APIRouter()
service = OperationsService()


@router.get("/dashboard", response_model=DashboardStats, summary="Get operator dashboard stats")
def get_dashboard_stats() -> DashboardStats:
    return service.get_dashboard_stats()


@router.get("/incidents", response_model=list[Incident], summary="List complaints and incidents")
def list_incidents() -> list[Incident]:
    return service.list_incidents()


@router.post("/incidents", response_model=Incident, summary="Create complaint or incident")
def create_incident(payload: IncidentCreate) -> Incident:
    return service.create_incident(payload)
