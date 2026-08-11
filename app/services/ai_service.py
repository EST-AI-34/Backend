from typing import Any

from app.repositories.ai_repository import AIRepository
from app.repositories.festival_repository import FestivalRepository
from app.schemas.ai import (
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


class AIService:
    def __init__(self) -> None:
        self.repo = AIRepository()
        self.festival_repo = FestivalRepository()

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
            "You are a verified Korean festival guide. Answer only from the provided festival context. "
            "If safety, emergency, cancellation, parking, or operating hours are uncertain, tell the visitor "
            "to confirm with staff or official notices.\n\n"
            f"Visitor question: {payload.question}"
        )
        result = self.repo.call_llm(prompt, context)
        fallback_answer = self._build_local_answer(payload.question, programs, payload.interests)
        answer = result["reply"] if result.get("source") == "allen" else fallback_answer

        return GuideQuestionResponse(
            answer=answer,
            related_program_ids=related_programs,
            related_location_ids=locations,
            sources=["등록된 축제 데이터", "공식 공지"],
            last_updated_at=str(self.festival_repo.get_festival()["last_updated_at"]),
        )

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
