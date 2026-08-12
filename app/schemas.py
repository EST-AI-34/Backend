from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


def camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra="forbid")


class LoginIn(APIModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenIn(APIModel):
    refresh_token: str = Field(pattern=r"^rt_")


class VisitorSessionIn(APIModel):
    language: str = Field(default="ko", max_length=10)
    accessibility_preferences: dict[str, Any] = Field(default_factory=dict)
    consents: dict[str, bool] = Field(default_factory=dict)


class ConversationIn(APIModel):
    festival_code: str | None = None
    language: str = Field(default="ko", max_length=10)


class MessageIn(APIModel):
    message: str = Field(min_length=1, max_length=1000)
    context: dict[str, Any] = Field(default_factory=dict)


class ReportMessageIn(APIModel):
    reason: str = Field(min_length=1, max_length=100)
    detail: str | None = Field(default=None, max_length=1000)


class SurveyAnswer(APIModel):
    question_id: str
    value: Any


class SurveyResponseIn(APIModel):
    answers: list[SurveyAnswer] = Field(min_length=1)


class DateRangeModel(APIModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def valid_range(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("endsAt은 startsAt 이후여야 합니다.")
        return self


class FestivalIn(DateRangeModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    timezone: str = "Asia/Seoul"
    default_language: str = "ko"
    supported_languages: list[str] = Field(default_factory=lambda: ["ko", "en"], min_length=1)


class FestivalPatch(APIModel):
    name: str | None = None
    description: str | None = None
    timezone: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["DRAFT", "PUBLISHED", "ONGOING", "ENDED", "ARCHIVED"] | None = None
    default_language: str | None = None
    supported_languages: list[str] | None = None
    version: int | None = None


class AreaIn(APIModel):
    name: str = Field(min_length=1)
    area_type: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: str = "ACTIVE"


class AreaPatch(APIModel):
    name: str | None = None
    area_type: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: str | None = None
    version: int | None = None


class FacilityIn(APIModel):
    area_id: str
    name: str = Field(min_length=1)
    facility_type: str = Field(min_length=1)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"


class FacilityPatch(APIModel):
    area_id: str | None = None
    name: str | None = None
    facility_type: str | None = None
    accessibility: dict[str, Any] | None = None
    operating_hours: dict[str, Any] | None = None
    status: str | None = None
    version: int | None = None


class ProgramIn(APIModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    summary: str | None = None
    category: str = Field(min_length=1)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"


class ProgramPatch(APIModel):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    accessibility: dict[str, Any] | None = None
    status: str | None = None
    version: int | None = None


class ProgramSessionIn(DateRangeModel):
    area_id: str
    capacity: int | None = Field(default=None, ge=0)
    status: str = "OPEN"


class ProgramSessionPatch(APIModel):
    area_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=0)
    status: str | None = None
    version: int | None = None


class CloneFestivalIn(DateRangeModel):
    code: str = Field(min_length=2)
    name: str = Field(min_length=1)


class ContentItemIn(APIModel):
    content_type: str
    resource_type: str | None = None
    resource_id: str | None = None
    slug: str = Field(pattern=r"^[a-z0-9-]+$")


class ContentVersionIn(APIModel):
    language: str = Field(min_length=2, max_length=10)
    body: dict[str, Any]
    change_note: str | None = Field(default=None, max_length=1000)


class ReviewIn(APIModel):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str | None = Field(default=None, max_length=2000)


class PublishContentIn(APIModel):
    version_id: str


class AIDecisionIn(APIModel):
    decision: str = Field(min_length=1, max_length=100)


class AnnouncementIn(APIModel):
    title: str = Field(min_length=1, max_length=200)


class AnnouncementPatch(APIModel):
    title: str | None = None
    severity: Literal["INFO", "WARNING"] | None = None
    audience: list[str] | None = None
    target_area_ids: list[str] | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    version: int


class PublishAnnouncementIn(APIModel):
    content_version_id: str
    severity: Literal["INFO", "WARNING", "EMERGENCY"]
    audience: list[str] = Field(min_length=1)
    target_area_ids: list[str] = Field(default_factory=list)
    starts_at: datetime
    ends_at: datetime | None = None


class TicketIn(APIModel):
    ticket_type: Literal["COMPLAINT", "INCIDENT"]
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    area_id: str | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "EMERGENCY"] = "NORMAL"
    assignee_id: str | None = None


class TicketPatch(APIModel):
    assignee_id: str | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "EMERGENCY"] | None = None
    version: int


class TicketTransitionIn(APIModel):
    to_status: Literal["ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED"]
    note: str | None = Field(default=None, max_length=2000)
    attachments: list[dict[str, str]] = Field(default_factory=list)


Role = Literal["SUPER_ADMIN", "FESTIVAL_MANAGER", "FIELD_OPERATOR", "MERCHANT", "REVIEWER"]


class MembershipIn(APIModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    role: Role
    festival_scope: list[str] = Field(default_factory=list)


class MembershipPatch(APIModel):
    role: Role | None = None
    festival_scope: list[str] | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class MetricIn(APIModel):
    name: str
    category: Literal["E", "S", "G"]


class MetricVersionIn(APIModel):
    formula: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    target: float | None = None
    source_requirements: dict[str, Any] = Field(min_length=1)
    evidence_required: bool = False


class MeasurementIn(APIModel):
    metric_version_id: str
    value: float
    source_type: str
    source_ref: str | None = None
    dedupe_key: str
    measured_at: datetime
    supersedes_id: str | None = None


class MeasurementPatch(APIModel):
    value: float | None = None
    source_type: str | None = None
    source_ref: str | None = None
    measured_at: datetime | None = None


class EvidenceIn(APIModel):
    file_id: str
    file_hash: str
    evidence_type: str
    issued_at: datetime | None = None


class Period(APIModel):
    from_: datetime = Field(alias="from")
    to: datetime


class EsgReportIn(APIModel):
    title: str
    period: Period
    compare_with_festival_id: str | None = None
    format: Literal["EDITABLE_DOCUMENT", "PDF", "DOCX"]


class ReportPatch(APIModel):
    edit_metadata: dict[str, Any]


class ExportIn(APIModel):
    format: Literal["PDF", "DOCX"]


class GenericExportIn(APIModel):
    resource_type: str
    format: Literal["CSV", "JSON"]


class VisitorPreferencesPatch(APIModel):
    language: str | None = Field(default=None, min_length=2, max_length=10)
    accessibility_preferences: dict[str, Any] | None = None


class StaffAssignmentIn(DateRangeModel):
    membership_id: str
    area_id: str
    duty_role: str = Field(min_length=1, max_length=100)
    task: str | None = Field(default=None, max_length=1000)


class CrowdSnapshotIn(APIModel):
    area_id: str
    program_session_id: str | None = None
    source_type: Literal["MANUAL", "ENTRY", "RESERVATION", "SENSOR"] = "MANUAL"
    crowd_level: Literal["QUIET", "MODERATE", "BUSY", "FULL"]
    people_count: int | None = Field(default=None, ge=0)
    estimated_wait_min: int | None = Field(default=None, ge=0)
    captured_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def valid_expiry(self):
        if self.captured_at >= self.expires_at:
            raise ValueError("expiresAt은 capturedAt 이후여야 합니다.")
        return self


class BookingIn(APIModel):
    party_size: int = Field(default=1, ge=1, le=20)
    contact: dict[str, str] | None = None


class BookingStatusIn(APIModel):
    status: Literal["CALLED", "NO_SHOW", "COMPLETED"]
    note: str | None = Field(default=None, max_length=500)


class CoursePlanIn(APIModel):
    interests: list[str] = Field(default_factory=list, max_length=10)
    companion_type: str | None = Field(default=None, max_length=50)
    duration_min: int = Field(ge=30, le=720)
    starts_at: datetime | None = None
    area_id: str | None = None
    accessibility: dict[str, Any] = Field(default_factory=dict)
    excluded_program_ids: list[str] = Field(default_factory=list)


class BusinessIn(APIModel):
    registration_no: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    contact: dict[str, str] | None = None
    address: dict[str, Any] = Field(default_factory=dict)
    menu: list[dict[str, Any]] = Field(default_factory=list)
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    owner_membership_id: str | None = None
    area_id: str | None = None
    booth_no: str | None = Field(default=None, max_length=50)


class BusinessPatch(APIModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    menu: list[dict[str, Any]] | None = None
    operating_hours: dict[str, Any] | None = None
    accessibility: dict[str, Any] | None = None
    version: int


class BusinessReviewIn(APIModel):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str | None = Field(default=None, max_length=2000)


class CouponIn(DateRangeModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    benefit_type: Literal["FIXED", "PERCENT", "GIFT"]
    benefit_value: float = Field(ge=0)
    issue_limit: int = Field(gt=0)
    per_visitor_limit: int = Field(default=1, gt=0)


class CouponRedeemIn(APIModel):
    issue_token: str = Field(pattern=r"^cp_")


class CouponReverseIn(APIModel):
    reason: str = Field(min_length=1, max_length=500)


class RewardCampaignIn(DateRangeModel):
    name: str = Field(min_length=1, max_length=200)
    daily_point_limit: int = Field(gt=0)


class RewardActionIn(APIModel):
    action_type: str = Field(min_length=1, max_length=100)
    verification_type: str = Field(min_length=1, max_length=100)
    points: int = Field(gt=0)
    per_user_limit: int = Field(default=1, gt=0)
    rule: dict[str, Any] = Field(default_factory=dict)


class RewardEventIn(APIModel):
    reward_action_id: str
    verification_key: str = Field(min_length=1, max_length=200)
    evidence: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class InternalDocumentIn(APIModel):
    title: str = Field(min_length=1, max_length=200)
    document_type: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=100_000)
    source_url: str | None = None
    allowed_roles: list[Role] = Field(default_factory=lambda: ["SUPER_ADMIN", "FESTIVAL_MANAGER"])


class InternalSearchIn(APIModel):
    question: str = Field(min_length=2, max_length=1000)


class IssueAnalysisPatch(APIModel):
    topic: str = Field(min_length=1, max_length=100)
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]
    urgent: bool = False
    note: str | None = Field(default=None, max_length=1000)


class BusinessEventIn(APIModel):
    event_type: Literal["VISIT", "SALE"]
    sales_amount: float | None = Field(default=None, ge=0)
    source: str = Field(default="MERCHANT", min_length=1, max_length=100)
