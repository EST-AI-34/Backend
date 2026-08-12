from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["normal", "warning", "critical", "insufficient_data"]


class RiskEvidence(BaseModel):
    type: str
    value: float | int | str
    threshold: float | int | str | None = None
    source_updated_at: datetime


class RiskBrief(BaseModel):
    festival_id: str
    risk_level: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    summary: str
    evidence: list[RiskEvidence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    operator_notes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    generated_at: datetime
    source_updated_at: datetime | None = None
    external_ai_used: bool = False
    fallback_used: bool = True
    policy_version: str = "risk-v1"


class BusinessRecommendationItem(BaseModel):
    business_id: str
    name: str
    score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    is_sponsored: bool = False
    operating_status: Literal["open", "closed", "paused", "ended"]
    distance_meters: int | None = None
    category: str
    location_id: int | str | None = None


class BusinessRecommendations(BaseModel):
    festival_id: str
    items: list[BusinessRecommendationItem] = Field(default_factory=list)
    sponsored_items: list[BusinessRecommendationItem] = Field(default_factory=list)
    recommendation_policy_version: str = "biz-rec-v1"
    generated_at: datetime


class RecommendationBiasBusinessExposure(BaseModel):
    business_id: str
    name: str
    category: str
    total_exposures: int
    general_exposures: int = 0
    sponsored_exposures: int = 0
    exposure_share: float = Field(ge=0, le=1)
    is_over_threshold: bool = False


class RecommendationBiasCategoryExposure(BaseModel):
    category: str
    total_exposures: int
    exposure_share: float = Field(ge=0, le=1)
    is_over_threshold: bool = False


class RecommendationBiasAudit(BaseModel):
    festival_id: str
    status: Literal["pass", "warning", "insufficient_data"]
    summary: str
    checked_event_count: int
    total_exposures: int
    general_exposures: int
    sponsored_exposures: int
    business_exposures: list[RecommendationBiasBusinessExposure] = Field(default_factory=list)
    category_exposures: list[RecommendationBiasCategoryExposure] = Field(default_factory=list)
    thresholds: dict[str, float | int | str]
    recommended_actions: list[str] = Field(default_factory=list)
    cadence: str = "weekly"
    window_days: int = 7
    generated_at: datetime
    next_recommended_check_at: datetime
    policy_version: str = "bias-audit-v1"
