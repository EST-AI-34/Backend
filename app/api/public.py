from fastapi import APIRouter

from app.api.responses import listed, ok
from app.services.festival_service import FestivalService
from app.services.map_service import MapService
from app.services.survey_service import SurveyService

router = APIRouter()
festival_service = FestivalService()
map_service = MapService()
survey_service = SurveyService()


@router.get("/festivals/{festival_code}", summary="Get published festival")
def get_festival(festival_code: str) -> dict:
    return ok(festival_service.get_overview().festival)


@router.get("/festivals/{festival_code}/programs", summary="List published programs")
def list_programs(festival_code: str, limit: int = 20) -> dict:
    return listed(festival_service.list_programs(), limit)


@router.get("/festivals/{festival_code}/facilities", summary="List published facilities")
def list_facilities(festival_code: str, limit: int = 20) -> dict:
    return listed(festival_service.list_facilities(), limit)


@router.get("/festivals/{festival_code}/map", summary="Get public festival map")
def get_map(festival_code: str, limit: int = 100) -> dict:
    return listed(map_service.get_locations(), limit)


@router.get("/festivals/{festival_code}/announcements", summary="List published announcements")
def list_announcements(festival_code: str, limit: int = 20) -> dict:
    return listed(festival_service.list_notices(), limit)


@router.get("/festivals/{festival_code}/stores", summary="List published local stores")
def list_stores(festival_code: str, limit: int = 20) -> dict:
    return listed(festival_service.list_stores(), limit)


@router.get("/festivals/{festival_code}/coupons", summary="List public coupons")
def list_coupons(festival_code: str, limit: int = 20) -> dict:
    return listed(festival_service.list_coupons(), limit)


@router.get("/festivals/{festival_code}/surveys", summary="List active visitor surveys")
def list_surveys(festival_code: str) -> dict:
    return ok(
        {
            "id": "default",
            "festivalCode": festival_code,
            "questions": survey_service.list_questions(),
        }
    )
