from fastapi import APIRouter

from app.schemas.survey import SurveyQuestion, SurveySubmission, SurveySubmissionResponse
from app.services.survey_service import SurveyService

router = APIRouter()
service = SurveyService()


@router.get("/questions", response_model=list[SurveyQuestion], summary="List visitor survey questions")
def list_questions() -> list[SurveyQuestion]:
    return service.list_questions()


@router.post("/responses", response_model=SurveySubmissionResponse, summary="Submit visitor survey answers")
def submit(payload: SurveySubmission) -> SurveySubmissionResponse:
    return service.submit(payload)
