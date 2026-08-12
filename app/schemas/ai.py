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


class AiGuideRequest(BaseModel):
    message: str = Field(min_length=2, max_length=240)
    language: str = "ko"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accessibility_preferences: list[str] = Field(default_factory=list)
    conversation_id: str | None = None


class AiGuideAction(BaseModel):
    type: Literal["open_map", "open_schedule", "open_business", "call_staff", "retry"]
    label: str
    target: str = ""


class AiGuideSourceItem(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    kind: str
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class AiGuideResponse(BaseModel):
    intent: Literal["schedule", "navigation", "culture", "safety", "esg", "business", "fallback"]
    language: Literal["ko", "en"]
    display_text: str
    speech_text: str
    source_type: str
    source_items: list[AiGuideSourceItem] = Field(default_factory=list)
    actions: list[AiGuideAction] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None
    generated_at: str
    source_updated_at: str | None = None


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
