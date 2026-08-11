from fastapi import APIRouter, HTTPException

from app.api.responses import listed, ok
from app.repositories.ai_repository import AllenAPIError
from app.schemas.ai import CourseRecommendRequest, GuideQuestionRequest
from app.schemas.survey import SurveySubmission
from app.services.ai_service import AIService
from app.services.festival_service import FestivalService
from app.services.survey_service import SurveyService

router = APIRouter()
ai_service = AIService()
festival_service = FestivalService()
survey_service = SurveyService()


@router.post("/ai/conversations", summary="Start anonymous AI conversation")
def create_conversation(payload: dict | None = None) -> dict:
    return ok(
        {
            "conversationId": "current",
            "festivalCode": (payload or {}).get("festivalCode", "EST34-2026"),
        }
    )


@router.post("/ai/conversations/{conversation_id}/messages", summary="Send visitor AI message")
def send_ai_message(conversation_id: str, payload: dict) -> dict:
    request = GuideQuestionRequest(
        question=payload.get("message", ""),
        language=payload.get("language", "ko"),
        visitor_type=payload.get("visitorType"),
        interests=payload.get("interests", []),
        stay_minutes=payload.get("stayMinutes"),
    )
    try:
        answer = ai_service.answer_guide_question(request)
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ok(
        {
            "messageId": f"msg_{conversation_id}",
            "answer": answer.answer,
            "safetyStatus": "ALLOWED",
            "freshnessAt": answer.last_updated_at,
            "sources": [
                {
                    "title": source,
                    "resourceType": "FESTIVAL_DATA",
                    "rank": index + 1,
                }
                for index, source in enumerate(answer.sources)
            ],
            "relatedProgramIds": answer.related_program_ids,
            "relatedLocationIds": answer.related_location_ids,
            "fallback": None,
        }
    )


@router.get("/ai/conversations/{conversation_id}/messages", summary="List visitor AI messages")
def list_ai_messages(conversation_id: str) -> dict:
    return listed([])


@router.post("/course-plans", summary="Create personalized visitor course plan")
def create_course_plan(payload: CourseRecommendRequest) -> dict:
    return ok(ai_service.recommend_course(payload))


@router.get("/program-sessions/wait-tickets", summary="List visitor wait tickets")
def list_wait_tickets() -> dict:
    programs = festival_service.list_programs()
    data = [
        {
            "id": str(program.id),
            "program": program.name,
            "number": 100 + program.id,
            "peopleAhead": max(0, program.reserved_count - program.capacity + 5),
            "estimatedWaitMinutes": 15 if program.status == "crowded" else 0,
            "status": "WAITLISTED" if program.status == "crowded" else "CONFIRMED",
        }
        for program in programs[:2]
    ]
    return listed(data)


@router.post("/surveys/{survey_id}/responses", summary="Submit anonymous survey response")
def submit_survey_response(survey_id: str, payload: SurveySubmission) -> dict:
    return ok(survey_service.submit(payload))
