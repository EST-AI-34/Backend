from pydantic import BaseModel


class MapLocation(BaseModel):
    id: int
    name: str
    category: str = "program"
    latitude: float
    longitude: float
    description: str | None = None
    congestion_level: str = "normal"
