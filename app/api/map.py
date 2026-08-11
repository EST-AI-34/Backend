from fastapi import APIRouter
from typing import List

from app.schemas.map import MapLocation
from app.services.map_service import MapService

router = APIRouter()
service = MapService()


@router.get("/locations", response_model=List[MapLocation], summary="Get festival map locations")
def list_locations() -> List[MapLocation]:
    return service.get_locations()
