from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Festival(BaseModel):
    id: int
    name: str
    location: str
    start_date: date
    end_date: date
    description: str
    last_updated_at: datetime


class Program(BaseModel):
    id: int
    festival_id: int
    name: str
    description: str
    category: str
    start_time: datetime
    end_time: datetime
    location_id: int
    capacity: int
    reserved_count: int
    status: Literal["scheduled", "open", "crowded", "closed", "cancelled"]
    tags: list[str] = Field(default_factory=list)


class Facility(BaseModel):
    id: int
    festival_id: int
    category: Literal["restroom", "parking", "medical", "info", "accessibility", "transport"]
    name: str
    location_id: int
    description: str
    accessibility: list[str] = Field(default_factory=list)


class Store(BaseModel):
    id: int
    festival_id: int
    name: str
    category: Literal["restaurant", "cafe", "market", "souvenir"]
    location_id: int
    coupon_available: bool
    description: str


class Coupon(BaseModel):
    id: int
    store_id: int
    title: str
    issued_count: int
    used_count: int
    expires_at: datetime


class Notice(BaseModel):
    id: int
    festival_id: int
    title: str
    body: str
    level: Literal["normal", "important", "emergency"]
    published_at: datetime


class FestivalOverview(BaseModel):
    festival: Festival
    notices: list[Notice]
    today_programs: list[Program]
    recommended_stores: list[Store]
