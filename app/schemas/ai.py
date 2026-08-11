from typing import Literal

from pydantic import BaseModel, Field


class VisionRequest(BaseModel):
    image_url: str


class VisionResponse(BaseModel):
    summary: str
    labels: list[str]
    metadata: dict[str, str] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    prompt: str
    context: list[str] = Field(default_factory=list)


class LLMResponse(BaseModel):
    reply: str
    source: str | None = None


class GuideQuestionRequest(BaseModel):
    question: str = Field(min_length=2)
    language: str = "ko"
    visitor_type: Literal["solo", "couple", "friends", "family", "senior"] | None = None
    interests: list[str] = Field(default_factory=list)
    stay_minutes: int | None = Field(default=None, ge=15, le=720)


class GuideQuestionResponse(BaseModel):
    answer: str
    related_program_ids: list[int] = Field(default_factory=list)
    related_location_ids: list[int] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    last_updated_at: str


class CourseRecommendRequest(BaseModel):
    visitor_type: Literal["solo", "couple", "friends", "family", "senior"]
    interests: list[str] = Field(default_factory=list)
    stay_minutes: int = Field(ge=30, le=720)
    accessibility_required: bool = False


class CourseStop(BaseModel):
    order: int
    title: str
    location_id: int
    program_id: int | None = None
    estimated_minutes: int
    reason: str


class CourseRecommendResponse(BaseModel):
    title: str
    total_minutes: int
    stops: list[CourseStop]
    notes: list[str] = Field(default_factory=list)
