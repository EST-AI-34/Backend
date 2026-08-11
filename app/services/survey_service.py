from app.repositories.survey_repository import SurveyRepository
from app.schemas.survey import SurveyQuestion, SurveySubmission, SurveySubmissionResponse


class SurveyService:
    def __init__(self) -> None:
        self.repo = SurveyRepository()

    def list_questions(self) -> list[SurveyQuestion]:
        return [SurveyQuestion(**item) for item in self.repo.list_questions()]

    def submit(self, payload: SurveySubmission) -> SurveySubmissionResponse:
        return SurveySubmissionResponse(**self.repo.save_submission(payload.model_dump()))
