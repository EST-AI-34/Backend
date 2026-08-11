from fastapi import APIRouter

from app.schemas.festival import Coupon, Facility, FestivalOverview, Notice, Program, Store
from app.services.festival_service import FestivalService

router = APIRouter()
service = FestivalService()


@router.get("/overview", response_model=FestivalOverview, summary="Get visitor festival overview")
def get_overview() -> FestivalOverview:
    return service.get_overview()


@router.get("/programs", response_model=list[Program], summary="List festival programs")
def list_programs() -> list[Program]:
    return service.list_programs()


@router.get("/facilities", response_model=list[Facility], summary="List festival facilities")
def list_facilities() -> list[Facility]:
    return service.list_facilities()


@router.get("/stores", response_model=list[Store], summary="List local stores")
def list_stores() -> list[Store]:
    return service.list_stores()


@router.get("/coupons", response_model=list[Coupon], summary="List local coupons")
def list_coupons() -> list[Coupon]:
    return service.list_coupons()


@router.get("/notices", response_model=list[Notice], summary="List official notices")
def list_notices() -> list[Notice]:
    return service.list_notices()
