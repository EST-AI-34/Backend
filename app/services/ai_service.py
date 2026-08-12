from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.repositories.ai_repository import AIRepository
from app.repositories.festival_repository import FestivalRepository
from app.repositories.insights_repository import InsightsRepository
from app.schemas.ai import (
    AiGuideAction,
    AiGuideRequest,
    AiGuideResponse,
    AiGuideSourceItem,
    CourseRecommendRequest,
    CourseRecommendResponse,
    CourseStop,
    GuideQuestionRequest,
    GuideQuestionResponse,
    LLMRequest,
    LLMResponse,
    VisionRequest,
    VisionResponse,
)
from app.services.insights_service import InsightsService


KST = ZoneInfo("Asia/Seoul")
SUPPORTED_LANGUAGES = {"ko", "en"}


class AIService:
    def __init__(self) -> None:
        self.repo = AIRepository()
        self.festival_repo = FestivalRepository()
        self.insights_repo = InsightsRepository()
        self.insights_service = InsightsService()

    def analyze_image(self, payload: VisionRequest) -> VisionResponse:
        result = self.repo.analyze_image(payload.image_url)
        return VisionResponse(
            summary=result["summary"],
            labels=result["labels"],
            metadata=result.get("metadata", {}),
        )

    def analyze_image_file(self, file: Any) -> VisionResponse:
        result = self.repo.analyze_image_file(file)
        return VisionResponse(
            summary=result["summary"],
            labels=result["labels"],
            metadata=result.get("metadata", {}),
        )

    def get_llm_reply(self, payload: LLMRequest) -> LLMResponse:
        result = self.repo.call_llm(payload.prompt, payload.context)
        return LLMResponse(reply=result["reply"], source=result.get("source"))

    def answer_guide_question(self, payload: GuideQuestionRequest) -> GuideQuestionResponse:
        context = self.festival_repo.build_search_context()
        programs = self.festival_repo.list_programs()
        locations = self._match_location_ids(payload.question)
        related_programs = self._match_program_ids(payload.question, payload.interests)

        prompt = (
            "You are a Korean festival guide that explains verified backend data. "
            "Use only the provided festival context and API/search results. "
            "Do not invent or calculate visitor counts, congestion, reservations, complaints, ESG metrics, "
            "rankings, or trends. If a statistic is not included in the verified context, say it is unavailable. "
            "Alan AI/search is retrieval only; the LLM only composes the final answer. "
            "If safety, emergency, cancellation, parking, or operating hours are uncertain, tell the visitor "
            "to confirm with staff or official notices.\n\n"
            f"Visitor question: {payload.question}"
        )
        result = self.repo.call_llm(prompt, context)
        answer = result["reply"]

        return GuideQuestionResponse(
            answer=answer,
            related_program_ids=related_programs,
            related_location_ids=locations,
            sources=["등록된 축제 데이터", "공식 공지"],
            last_updated_at=str(self.festival_repo.get_festival()["last_updated_at"]),
        )

    def answer_visitor_ai_guide(self, festival_id: str, payload: AiGuideRequest) -> AiGuideResponse:
        if str(festival_id) not in {"1", "EST34-2026"}:
            raise ValueError("Festival was not found.")
        if (payload.latitude is None) != (payload.longitude is None):
            raise ValueError("latitude and longitude must be provided together.")

        language = payload.language if payload.language in SUPPORTED_LANGUAGES else "ko"
        intent = self._guide_intent(payload.message)
        generated_at = datetime.now(KST).isoformat()
        source_updated_at = str(self.festival_repo.get_festival()["last_updated_at"])
        result = self._rule_based_guide(intent, language, festival_id, payload)

        if settings.ENABLE_EXTERNAL_AI and result.source_items:
            try:
                llm = self.repo.call_llm(
                    self._guide_prompt(payload.message, language),
                    [self._source_line(item) for item in result.source_items],
                )
                text = self._strip_sensitive_text(llm["reply"])
                result.display_text = text
                result.speech_text = text
                result.fallback_used = False
                result.fallback_reason = None
            except Exception:
                result.fallback_used = True
                result.fallback_reason = "external_ai_unavailable"

        result.generated_at = generated_at
        result.source_updated_at = source_updated_at
        return result

    def recommend_course(self, payload: CourseRecommendRequest) -> CourseRecommendResponse:
        programs = self.festival_repo.list_programs()
        interest_set = {item.lower() for item in payload.interests}

        def score(program: dict) -> int:
            tags = {item.lower() for item in program["tags"]}
            return len(tags & interest_set) * 10 + (5 if program["status"] == "open" else 0)

        selected = sorted(programs, key=score, reverse=True)
        remaining = payload.stay_minutes
        stops: list[CourseStop] = []
        for program in selected:
            if remaining < 30:
                break
            estimated = min(60, max(30, remaining // 2 if stops else 45))
            stops.append(
                CourseStop(
                    order=len(stops) + 1,
                    title=program["name"],
                    location_id=program["location_id"],
                    program_id=program["id"],
                    estimated_minutes=estimated,
                    reason=self._course_reason(program, payload.visitor_type),
                )
            )
            remaining -= estimated

        if remaining >= 20:
            stores = self.festival_repo.list_stores()
            if stores:
                store = stores[0]
                stops.append(
                    CourseStop(
                        order=len(stops) + 1,
                        title=f"{store['name']} 쿠폰 방문",
                        location_id=store["location_id"],
                        estimated_minutes=min(30, remaining),
                        reason="지역상권 쿠폰을 사용할 수 있어 방문 효과를 운영 데이터로 집계할 수 있습니다.",
                    )
                )

        return CourseRecommendResponse(
            title=f"{payload.stay_minutes}분 {self._visitor_type_label(payload.visitor_type)} 맞춤 코스",
            total_minutes=sum(item.estimated_minutes for item in stops),
            stops=stops,
            notes=[
                "혼잡도는 운영자가 입력한 현재 상태를 기준으로 단순화했습니다.",
                "안전, 취소, 응급 상황은 현장 스태프와 공식 공지를 우선 확인하세요.",
            ],
        )

    def _guide_intent(self, message: str) -> str:
        text = message.lower()
        if self._matches(text, ["crowd", "crowded", "congestion", "busy", "혼잡", "붐비", "사람 많", "대기"]):
            return "crowding"
        if self._matches(text, ["응급", "안전", "구급", "분실", "위험", "safe", "emergency", "medical", "lost", "danger"]):
            return "safety"
        if self._matches(text, ["음식", "부스", "맛집", "카페", "쿠폰", "업체", "상점", "food", "restaurant", "cafe", "coupon", "business", "booth", "vendor", "stall"]):
            return "business"
        if self._matches(text, ["포인트", "분리", "재활용", "스탬프", "친환경", "esg", "recycle", "stamp", "eco", "trash", "point"]):
            return "esg"
        if self._matches(text, ["일정", "공연", "프로그램", "오늘", "schedule", "program", "show", "performance", "today"]):
            return "schedule"
        if self._matches(text, ["어디", "지도", "무대", "메인", "화장실", "주차", "길", "where", "map", "route", "stage", "main stage", "restroom", "toilet", "parking"]):
            return "navigation"
        if self._matches(text, ["관광", "문화", "근처", "지역", "tour", "culture", "nearby", "photo", "local"]):
            return "culture"
        if self._matches(text, ["safe", "emergency", "medical", "lost", "danger", "응급", "안전", "구급", "분실", "위험"]):
            return "safety"
        if self._matches(text, ["food", "restaurant", "cafe", "coupon", "business", "상점", "맛집", "카페", "쿠폰", "업체"]):
            return "business"
        if self._matches(text, ["esg", "recycle", "stamp", "eco", "trash", "분리", "재활용", "스탬프", "친환경"]):
            return "esg"
        if self._matches(text, ["schedule", "program", "show", "performance", "today", "일정", "공연", "프로그램", "오늘"]):
            return "schedule"
        if self._matches(text, ["where", "map", "route", "stage", "restroom", "toilet", "parking", "길", "어디", "지도", "무대", "화장실", "주차"]):
            return "navigation"
        if self._matches(text, ["tour", "culture", "nearby", "photo", "local", "관광", "문화", "근처", "지역"]):
            return "culture"
        return "fallback"

    def _rule_based_guide(
        self,
        intent: str,
        language: str,
        festival_id: str,
        payload: AiGuideRequest,
    ) -> AiGuideResponse:
        if intent == "schedule":
            return self._schedule_guide(language)
        if intent == "navigation":
            return self._navigation_guide(language, payload.message)
        if intent == "culture":
            return self._culture_guide(language)
        if intent == "safety":
            return self._safety_guide(language)
        if intent == "crowding":
            return self._crowding_guide(language)
        if intent == "esg":
            return self._esg_guide(language)
        if intent == "business":
            return self._business_guide(language, festival_id, payload)
        return self._fallback_guide(language)

    def _schedule_guide(self, language: str) -> AiGuideResponse:
        programs = self.festival_repo.list_programs()[:3]
        items = [
            AiGuideSourceItem(
                id=str(program["id"]),
                title=program["name"],
                subtitle=f"{program['start_time'].strftime('%m/%d %H:%M')} - {program['end_time'].strftime('%H:%M')}",
                kind="program",
                metadata={"location_id": program["location_id"], "status": program["status"]},
            )
            for program in programs
        ]
        text = self._text(
            language,
            "오늘 주요 일정은 등록된 프로그램 기준으로 안내해 드릴게요. 첫 일정은 {name}입니다.",
            "Here are the main programs from the registered schedule. The first one is {name}.",
        ).format(name=programs[0]["name"] if programs else self._text(language, "확인된 일정 없음", "no verified program"))
        return self._guide_response("schedule", language, text, "program", items, [
            AiGuideAction(type="open_schedule", label=self._text(language, "일정 보기", "Open schedule"), target="/visitor/schedule")
        ])

    def _navigation_guide(self, language: str, message: str) -> AiGuideResponse:
        facilities = self.festival_repo.list_facilities()
        programs = self.festival_repo.list_programs()
        message_text = message.lower()
        if self._matches(message_text, ["stage", "main stage", "무대", "메인"]):
            selected_program = next((item for item in programs if item.get("location_id") == 1), programs[0] if programs else None)
            if selected_program:
                item = AiGuideSourceItem(
                    id=str(selected_program["id"]),
                    title=selected_program["name"],
                    subtitle=selected_program["description"],
                    kind="program",
                    metadata={"location_id": selected_program["location_id"], "status": selected_program["status"]},
                )
                text = self._text(
                    language,
                    "메인 무대는 지도 location_id 1 구역입니다. 현장 표지판과 안내요원 안내를 함께 확인해 주세요.",
                    "The main stage is the map area with location_id 1. Please also follow signs and staff guidance on site.",
                )
                return self._guide_response("navigation", language, text, "map", [item], [
                    AiGuideAction(type="open_map", label=self._text(language, "지도에서 보기", "Open map"), target="/visitor/map"),
                    AiGuideAction(type="call_staff", label=self._text(language, "운영요원 찾기", "Find staff"), target="staff"),
                ])
        selected = facilities[0]
        if self._matches(message.lower(), ["medical", "emergency", "응급", "구급"]):
            selected = next((item for item in facilities if item["category"] == "medical"), selected)
        elif self._matches(message.lower(), ["parking", "주차"]):
            selected = next((item for item in facilities if item["category"] == "parking"), selected)
        item = AiGuideSourceItem(
            id=str(selected["id"]),
            title=selected["name"],
            subtitle=selected["description"],
            kind="facility",
            metadata={"location_id": selected["location_id"], "category": selected["category"]},
        )
        text = self._text(
            language,
            "{name} 위치는 지도에서 확인할 수 있어요. 현장 표지판과 안내요원 안내를 함께 확인해 주세요.",
            "{name} is available on the map. Please also follow signs and staff guidance on site.",
        ).format(name=selected["name"])
        return self._guide_response("navigation", language, text, "map", [item], [
            AiGuideAction(type="open_map", label=self._text(language, "지도에서 보기", "Open map"), target="/visitor/map")
        ])

    def _culture_guide(self, language: str) -> AiGuideResponse:
        festival = self.festival_repo.get_festival()
        programs = [program for program in self.festival_repo.list_programs() if "ESG" in program.get("tags", [])]
        items = [
            AiGuideSourceItem(
                id=str(program["id"]),
                title=program["name"],
                subtitle=program["description"],
                kind="program",
                metadata={"location_id": program["location_id"]},
            )
            for program in programs[:2]
        ]
        text = self._text(
            language,
            "{festival} 안에서는 지역과 친환경 주제의 전시와 체험을 먼저 추천해요.",
            "Inside {festival}, start with the local culture and eco-themed exhibitions or activities.",
        ).format(festival=festival["name"])
        return self._guide_response("culture", language, text, "festival_data", items, [
            AiGuideAction(type="open_schedule", label=self._text(language, "관련 일정 보기", "Open related programs"), target="/visitor/schedule")
        ])

    def _safety_guide(self, language: str) -> AiGuideResponse:
        medical = next((item for item in self.festival_repo.list_facilities() if item["category"] == "medical"), None)
        items = []
        if medical:
            items.append(
                AiGuideSourceItem(
                    id=str(medical["id"]),
                    title=medical["name"],
                    subtitle=medical["description"],
                    kind="facility",
                    metadata={"location_id": medical["location_id"], "category": medical["category"]},
                )
            )
        text = self._text(
            language,
            "응급 상황이면 가까운 운영요원에게 바로 알리고, 긴급하면 119에 연락하세요. 축제 응급부스 위치도 안내할게요.",
            "For an emergency, notify nearby staff immediately and call 119 if urgent. I can show the medical booth location.",
        )
        return self._guide_response("safety", language, text, "safety", items, [
            AiGuideAction(type="open_map", label=self._text(language, "응급부스 위치", "Medical booth"), target="/visitor/map"),
            AiGuideAction(type="call_staff", label=self._text(language, "운영요원 찾기", "Find staff"), target="staff"),
        ])

    def _crowding_guide(self, language: str) -> AiGuideResponse:
        crowded_programs = [item for item in self.festival_repo.list_programs() if item.get("status") == "crowded"]
        if not crowded_programs:
            return self._no_data_guide(language, "crowding")
        items = [
            AiGuideSourceItem(
                id=str(program["id"]),
                title=program["name"],
                subtitle=program["description"],
                kind="program",
                metadata={
                    "location_id": program["location_id"],
                    "status": program["status"],
                    "reserved_count": program.get("reserved_count"),
                    "capacity": program.get("capacity"),
                },
            )
            for program in crowded_programs[:3]
        ]
        text = self._text(
            language,
            "현재 등록된 운영 데이터 기준으로 혼잡 표시가 있는 구역은 {name}입니다. 이동 전 현장 안내요원 안내를 확인해 주세요.",
            "Based on verified operations data, the crowded area is {name}. Please check staff guidance before moving.",
        ).format(name=crowded_programs[0]["name"])
        return self._guide_response("safety", language, text, "crowding", items, [
            AiGuideAction(type="open_map", label=self._text(language, "혼잡 구역 보기", "Open crowded area"), target="/visitor/map"),
            AiGuideAction(type="call_staff", label=self._text(language, "운영요원 찾기", "Find staff"), target="staff"),
        ])

    def _esg_guide(self, language: str) -> AiGuideResponse:
        notices = self.festival_repo.list_notices()
        esg_notice = next((item for item in notices if "ESG" in item["body"] or "ESG" in item["title"]), notices[-1])
        item = AiGuideSourceItem(
            id=str(esg_notice["id"]),
            title=esg_notice["title"],
            subtitle=esg_notice["body"],
            kind="notice",
            metadata={"level": esg_notice["level"]},
        )
        text = self._text(
            language,
            "ESG 참여는 공식 공지와 현장 부스 안내를 기준으로 진행해 주세요. 재사용컵 반납이나 친환경 참여 안내를 확인할 수 있어요.",
            "Please follow official notices and booth guidance for ESG participation, such as reusable cup returns or eco activities.",
        )
        return self._guide_response("esg", language, text, "notice", [item], [
            AiGuideAction(type="open_map", label=self._text(language, "ESG 부스 찾기", "Find ESG booth"), target="/visitor/map")
        ])

    def _business_guide(self, language: str, festival_id: str, payload: AiGuideRequest) -> AiGuideResponse:
        recommendations = self.insights_service.recommend_businesses(
            festival_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            limit=3,
        )
        open_items = [*recommendations.items, *recommendations.sponsored_items]
        source_items = [
            AiGuideSourceItem(
                id=item.business_id,
                title=item.name,
                subtitle=" / ".join(item.reasons),
                kind="business",
                metadata={
                    "category": item.category,
                    "is_sponsored": item.is_sponsored,
                    "score": item.score,
                    "operating_status": item.operating_status,
                    "location_id": item.location_id,
                },
            )
            for item in open_items
        ]
        if not source_items:
            return self._no_data_guide(language, "business")
        text = self._text(
            language,
            "현재 영업 중인 참여업체 중 {name}을 먼저 추천해요. 후원 업체는 별도로 표시됩니다.",
            "Among currently open participating businesses, start with {name}. Sponsored businesses are labeled separately.",
        ).format(name=open_items[0].name)
        return self._guide_response("business", language, text, "business", source_items, [
            AiGuideAction(type="open_business", label=self._text(language, "추천 업체 보기", "Open recommendations"), target="/visitor/ai-guide")
        ])

    def _fallback_guide(self, language: str) -> AiGuideResponse:
        text = self._text(
            language,
            "확인된 축제 데이터로 답할 수 있는 질문을 골라 주세요. 일정, 길찾기, 문화관광, 안전, ESG, 참여업체를 안내할 수 있어요.",
            "Please choose a question I can answer from verified festival data: schedule, navigation, culture, safety, ESG, or businesses.",
        )
        return self._guide_response("fallback", language, text, "none", [], [
            AiGuideAction(type="retry", label=self._text(language, "다시 질문하기", "Ask again"), target="")
        ], fallback_used=True, fallback_reason="unsupported_intent")

    def _no_data_guide(self, language: str, source_type: str) -> AiGuideResponse:
        text = self._text(
            language,
            "현재 이 항목에 사용할 수 있는 확인된 데이터가 없습니다. 현장 안내소에서 최신 정보를 확인해 주세요.",
            "There is no verified data available for this topic right now. Please check the information desk for updates.",
        )
        return self._guide_response("fallback", language, text, source_type, [], [
            AiGuideAction(type="open_map", label=self._text(language, "안내소 찾기", "Find information desk"), target="/visitor/map")
        ], fallback_used=True, fallback_reason="no_verified_data")

    def _guide_response(
        self,
        intent: str,
        language: str,
        text: str,
        source_type: str,
        source_items: list[AiGuideSourceItem],
        actions: list[AiGuideAction],
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> AiGuideResponse:
        return AiGuideResponse(
            intent=intent,
            language=language,
            display_text=text,
            speech_text=text,
            source_type=source_type,
            source_items=source_items,
            actions=actions,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            generated_at="",
            source_updated_at=None,
        )

    def _guide_prompt(self, message: str, language: str) -> str:
        target = "Korean" if language == "ko" else "English"
        return (
            f"Answer the visitor in {target}. Use only the verified source items below. "
            "Do not invent schedules, locations, safety status, ESG rewards, or business rankings. "
            f"Visitor question: {message}"
        )

    def _source_line(self, item: AiGuideSourceItem) -> str:
        return f"{item.kind}: {item.title}; {item.subtitle or ''}; {item.metadata}"

    def _strip_sensitive_text(self, text: str) -> str:
        text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[masked-email]", text)
        text = re.sub(r"\b\d{2,3}-\d{3,4}-\d{4}\b", "[masked-phone]", text)
        return text.strip()

    def _matches(self, text: str, keywords: list[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    def _text(self, language: str, ko: str, en: str) -> str:
        return en if language == "en" else ko

    def _match_program_ids(self, question: str, interests: list[str]) -> list[int]:
        words = {question.lower(), *[item.lower() for item in interests]}
        matched = []
        for program in self.festival_repo.list_programs():
            text = " ".join([program["name"], program["description"], program["category"], *program["tags"]]).lower()
            if any(word and word in text for word in words):
                matched.append(program["id"])
        return matched[:3]

    def _match_location_ids(self, question: str) -> list[int]:
        keywords = {
            "parking": [6],
            "주차": [6],
            "restroom": [4],
            "화장실": [4],
            "medical": [5],
            "응급": [5],
            "stage": [1],
            "공연": [1],
            "food": [3, 7],
            "먹거리": [3, 7],
            "혼잡": [1, 6],
        }
        lower = question.lower()
        result: list[int] = []
        for keyword, ids in keywords.items():
            if keyword in lower:
                result.extend(ids)
        return list(dict.fromkeys(result))

    def _build_local_answer(self, question: str, programs: list[dict], interests: list[str] | None = None) -> str:
        lower = question.lower()
        interest_set = {item.lower() for item in (interests or [])}
        if "혼잡" in lower or "crowd" in lower or "crowd" in interest_set:
            return "현재 등록 데이터 기준으로 메인스테이지와 여의도 임시주차장 A가 혼잡합니다. 먼저 체험존 A나 로컬푸드존 쪽으로 이동하는 코스를 추천합니다."
        if "주차" in lower or "parking" in lower or "parking" in interest_set:
            return "주차는 여의도 임시주차장 A를 이용하세요. 혼잡 시에는 현장 안내요원의 최신 안내를 우선 확인해 주세요."
        if "화장실" in lower or "restroom" in lower or "restroom" in interest_set:
            return "가까운 편의시설은 통합 안내소 주변 시설 목록에서 확인할 수 있습니다. 접근성 지원이 필요하면 통합 안내소를 이용해 주세요."
        if "먹거리" in lower or "food" in lower or "food" in interest_set:
            return "로컬푸드 마켓 투어와 로컬비건 빵집 바람 쿠폰 방문을 추천합니다. 쿠폰 사용 가능 여부는 상점/쿠폰 데이터 기준입니다."
        open_programs = [item for item in programs if item["status"] in {"open", "scheduled"}]
        names = ", ".join(item["name"] for item in open_programs[:3])
        return f"등록된 축제 데이터 기준으로 {names}를 먼저 확인해 보세요. 혼잡도와 안전 정보는 공식 공지를 우선합니다."

    def _course_reason(self, program: dict, visitor_type: str) -> str:
        if visitor_type == "family" and "아이" in program["tags"]:
            return "가족 방문객에게 맞는 체험형 프로그램입니다."
        if program["status"] == "open":
            return "현재 참여 가능한 상태로 등록된 프로그램입니다."
        return "관심사와 가까운 등록 프로그램입니다."

    def _visitor_type_label(self, visitor_type: str) -> str:
        labels = {
            "solo": "혼자",
            "couple": "연인",
            "friends": "친구",
            "family": "가족",
            "senior": "고령자 동반",
        }
        return labels.get(visitor_type, visitor_type)
