from typing import Literal

from pydantic import BaseModel, Field


class SurveyQuestion(BaseModel):
    id: str
    question: str
    type: Literal["rating", "choice"]
    options: list[str] | None = None


class SurveyAnswer(BaseModel):
    question_id: str
    value: str | int | float


class SurveySubmission(BaseModel):
    answers: list[SurveyAnswer] = Field(min_length=1)


class SurveySubmissionResponse(BaseModel):
    status: Literal["received"]
    answer_count: int
