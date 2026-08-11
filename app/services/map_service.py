from app.repositories.map_repository import MapRepository
from app.schemas.map import MapLocation


class MapService:
    def __init__(self) -> None:
        self.repo = MapRepository()

    def get_locations(self) -> list[MapLocation]:
        return [MapLocation(**item) for item in self.repo.fetch_locations()]
