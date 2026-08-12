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
    id: int | str
    festival_id: int | str
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


class ESGBriefing(BaseModel):
    briefing: str
    source: str
    metrics: list[ESGMetric]
    generated_at: datetime


class FestivalAIBrief(BaseModel):
    summary: str
    allen_comment: str
    metric_label: str
    metric_value: str
    status: Literal["normal", "warning", "critical"]
    sources: list[str]
    generated_at: datetime
