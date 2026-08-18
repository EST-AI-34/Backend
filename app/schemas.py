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


class PasswordChangeIn(APIModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def different(self):
        if self.current_password == self.new_password:
            raise ValueError("새 비밀번호는 현재 비밀번호와 달라야 합니다.")
        return self


class VisitorSessionIn(APIModel):
    language: str = Field(default="ko", max_length=10)
    accessibility_preferences: dict[str, Any] = Field(default_factory=dict)
    consents: dict[str, bool] = Field(default_factory=dict)
    # VIS-12 진입 QR이 설치된 구역. 위치정보는 쓰지 않고 이 값과 수동 선택만으로 구역을 판정한다.
    area_id: str | None = None


class VisitorAreaIn(APIModel):
    """VIS-12 구역 판정. source는 진입 QR(QR)과 방문객 수동 선택(MANUAL)만 허용한다."""
    area_id: str | None = None
    source: Literal["QR", "MANUAL"] = "MANUAL"


class KioskAssistEventIn(APIModel):
    """KIOSK-A11Y-01 익명 효과 지표. 개인과 이을 수 있는 값은 받지 않는다.

    추정 연령·신뢰도·프레임은 키오스크 밖으로 나오지 않으므로 여기에 필드가 없다.
    model_version은 ESG-G-08 편향 점검이 어느 모델의 결과인지 구분하기 위한 것이다.
    """
    event_type: Literal["CONSENT_SHOWN", "CONSENT_GRANTED", "CONSENT_DECLINED", "ESTIMATE_FAILED",
                        "ESTIMATE_RESULT", "SUGGESTED", "ACCEPTED", "DISMISSED", "MANUAL_LARGE_TEXT", "TASK_COMPLETED"]
    model_version: str | None = Field(default=None, max_length=100)
    result: Literal["SENIOR", "OTHER", "UNAVAILABLE"] | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if self.event_type == "ESTIMATE_RESULT" and self.result is None:
            raise ValueError("ESTIMATE_RESULT에는 result가 필요합니다.")
        if self.event_type != "ESTIMATE_RESULT" and self.result is not None:
            raise ValueError("result는 ESTIMATE_RESULT에서만 사용할 수 있습니다.")
        return self


class KioskCameraPatch(APIModel):
    """ESG-G-08 카메라 제안 중지 스위치. 끌 때는 사유를 남긴다(편향·오탐 점검 기록)."""
    enabled: bool
    stop_reason: str | None = Field(default=None, max_length=500)


class ConsentPatch(APIModel):
    consents: dict[str, bool] = Field(min_length=1)


class PrivacyRequestIn(APIModel):
    request_type: Literal["ACCESS", "DELETE"]
    detail: str | None = Field(default=None, max_length=1000)


class PrivacyRequestPatch(APIModel):
    status: Literal["IN_PROGRESS", "COMPLETED", "REJECTED"]
    note: str | None = Field(default=None, max_length=1000)


class MerchantInviteIn(APIModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)


class MerchantInviteLookupIn(APIModel):
    token: str = Field(pattern=r"^mi_")


class MerchantInviteAcceptIn(APIModel):
    """초대 수락. 이미 상인 계정이 있는 이메일이면 비밀번호 없이 업체 연결만 늘린다."""
    token: str = Field(pattern=r"^mi_")
    password: str | None = Field(default=None, min_length=8, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=100)


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


class TransportOptionIn(APIModel):
    """방문객 화면 교통 안내 한 줄. 프론트 상수로 하드코딩돼 있어 운영자가 못 고치던 값이다."""
    mode: Literal["지하철", "버스", "셔틀", "주차", "자전거", "도보"]
    label: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=300)
    status: Literal["원활", "보통", "혼잡", "지연"] = "원활"


class FestivalPatch(APIModel):
    name: str | None = None
    description: str | None = None
    timezone: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["DRAFT", "PUBLISHED", "ONGOING", "ENDED", "ARCHIVED"] | None = None
    default_language: str | None = None
    supported_languages: list[str] | None = None
    visitor_menus: dict[str, bool] | None = None
    transport: list[TransportOptionIn] | None = None
    version: int | None = None


AreaStatus = Literal["ACTIVE", "INACTIVE", "ARCHIVED"]
FacilityStatus = Literal["ACTIVE", "INACTIVE", "ARCHIVED"]
ProgramStatus = Literal["DRAFT", "PUBLISHED", "UNPUBLISHED", "ARCHIVED"]
SessionStatus = Literal["OPEN", "CLOSED", "CANCELLED", "ENDED"]


class AreaIn(APIModel):
    name: str = Field(min_length=1)
    area_type: str = Field(min_length=1)
    description: str | None = Field(default=None, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: AreaStatus = "ACTIVE"


class AreaPatch(APIModel):
    name: str | None = None
    area_type: str | None = None
    description: str | None = Field(default=None, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: AreaStatus | None = None
    version: int | None = None


class FacilityIn(APIModel):
    area_id: str
    name: str = Field(min_length=1)
    facility_type: str = Field(min_length=1)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    status: FacilityStatus = "ACTIVE"


class FacilityPatch(APIModel):
    area_id: str | None = None
    name: str | None = None
    facility_type: str | None = None
    accessibility: dict[str, Any] | None = None
    operating_hours: dict[str, Any] | None = None
    status: FacilityStatus | None = None
    version: int | None = None


class ProgramIn(APIModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    summary: str | None = None
    category: str = Field(min_length=1)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    status: ProgramStatus = "DRAFT"


class ProgramPatch(APIModel):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    accessibility: dict[str, Any] | None = None
    status: ProgramStatus | None = None
    version: int | None = None


class ProgramSessionIn(DateRangeModel):
    area_id: str
    capacity: int | None = Field(default=None, ge=0)
    status: SessionStatus = "OPEN"


class ProgramSessionPatch(APIModel):
    area_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=0)
    status: SessionStatus | None = None
    version: int | None = None


class CloneFestivalIn(DateRangeModel):
    code: str = Field(min_length=2)
    name: str = Field(min_length=1)


class ContentItemIn(APIModel):
    content_type: Literal["ANNOUNCEMENT", "PROGRAM"]
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


class AnnouncementDraftIn(APIModel):
    """공지 생성부터 게시까지 한 번에 받는 입력.

    예전에는 클라이언트가 공지 생성 → 콘텐츠 항목 → 버전 → 검수 제출 → 승인 → 게시를
    6번의 요청으로 나눠 호출했다. 중간에 하나라도 실패하면 방문객에게 보이지 않는
    DRAFT 공지와 콘텐츠 항목이 남고, 지울 API도 없었다.
    """
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    severity: Literal["INFO", "WARNING", "EMERGENCY"]
    audience: list[str] = Field(min_length=1)
    target_area_ids: list[str] = Field(default_factory=list)
    starts_at: datetime
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def valid_window(self):
        if self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("endsAt은 startsAt 이후여야 합니다.")
        return self


class SurveyQuestionIn(APIModel):
    prompt: str = Field(min_length=1, max_length=500)
    question_type: Literal["RATING", "SINGLE_CHOICE", "MULTIPLE_CHOICE", "TEXT"]
    options: list[str] = Field(default_factory=list, max_length=20)
    required: bool = False

    @model_validator(mode="after")
    def options_for_choices(self):
        if self.question_type in ("SINGLE_CHOICE", "MULTIPLE_CHOICE") and not self.options:
            raise ValueError("선택형 질문에는 보기가 필요합니다.")
        return self


class SurveyIn(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    prevent_duplicates: bool = True
    status: Literal["DRAFT", "ACTIVE"] = "DRAFT"
    questions: list[SurveyQuestionIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_window(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("endsAt은 startsAt 이후여야 합니다.")
        return self


class SurveyPatch(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["DRAFT", "ACTIVE", "CLOSED"] | None = None
    version: int | None = None


class TicketIn(APIModel):
    ticket_type: Literal["COMPLAINT", "INCIDENT"]
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    area_id: str | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "EMERGENCY"] = "NORMAL"
    assignee_id: str | None = None


class ComplaintIn(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=20)


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
    address: dict[str, Any] = Field(default_factory=dict)
    menu: list[dict[str, Any]] = Field(default_factory=list)
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    accessibility: dict[str, Any] = Field(default_factory=dict)
    owner_membership_id: str | None = None
    area_id: str | None = None
    booth_no: str | None = Field(default=None, max_length=50)


class FestivalBusinessPatch(APIModel):
    """운영자가 고치는 참여업체 속성.

    is_sponsored(광고 노출)와 esg_participating(ESG 참여)은 추천 점수·광고 분리의 입력값인데
    등록·검토 어디에도 없어서 DB를 직접 고치지 않으면 켤 수 없었다.
    """
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    is_sponsored: bool | None = None
    esg_participating: bool | None = None
    # BIZ-04 매출 데이터 수집 동의. 철회하면 파기 배치가 해당 업체의 매출 이벤트를 즉시 지운다.
    sales_consent: bool | None = None
    version: int | None = None


class BusinessPatch(APIModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    menu: list[dict[str, Any]] | None = None
    operating_hours: dict[str, Any] | None = None
    accessibility: dict[str, Any] | None = None
    version: int


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


class InternalDocumentPatch(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    body: str | None = Field(default=None, min_length=1, max_length=100_000)
    source_url: str | None = None
    allowed_roles: list[Role] | None = Field(default=None, min_length=1)


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
