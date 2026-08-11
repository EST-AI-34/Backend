from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ESGMetricCreate(BaseModel):
    category: Literal["environment", "social", "governance"]
    metric_name: str = Field(min_length=2)
    value: float
    unit: str
    source: str


class ESGMetric(BaseModel):
    id: int
    festival_id: int
    category: str
    metric_name: str
    value: float
    unit: str
    source: str
    recorded_at: datetime


class ESGSummary(BaseModel):
    environment_score: float
    social_score: float
    governance_score: float
    highlights: list[str]
    metrics: list[ESGMetric]


class ESGReport(BaseModel):
    title: str
    summary: str
    achievements: list[str]
    risks: list[str]
    next_actions: list[str]
    generated_at: datetime
