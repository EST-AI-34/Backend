from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncidentCreate(BaseModel):
    category: Literal["complaint", "safety", "facility", "lost_item", "crowd", "etc"]
    description: str = Field(min_length=2)
    location_id: int | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class Incident(BaseModel):
    id: int
    category: str
    description: str
    location_id: int | None = None
    priority: str
    status: Literal["received", "in_progress", "resolved"]
    assigned_user: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class DashboardStats(BaseModel):
    current_visitors: int
    ai_question_count: int
    open_incident_count: int
    coupon_used_count: int
    crowded_location_count: int
    esg_participation_count: int
