from fastapi import APIRouter, File, HTTPException, UploadFile

from app.repositories.ai_repository import AllenAPIError
from app.schemas.ai import (
    CourseRecommendRequest,
    CourseRecommendResponse,
    GuideQuestionRequest,
    GuideQuestionResponse,
    VisionRequest,
    VisionResponse,
    LLMRequest,
    LLMResponse,
)
from app.services.ai_service import AIService

router = APIRouter()
service = AIService()


@router.post("/vision/analyze", response_model=VisionResponse, summary="Analyze an uploaded image")
def analyze_image(payload: VisionRequest) -> VisionResponse:
    try:
        return service.analyze_image(payload)
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/vision/upload", response_model=VisionResponse, summary="Analyze uploaded image file")
def analyze_image_upload(file: UploadFile = File(...)) -> VisionResponse:
    try:
        return service.analyze_image_file(file)
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/llm/reply", response_model=LLMResponse, summary="Compose an answer from verified context")
def llm_reply(payload: LLMRequest) -> LLMResponse:
    try:
        return service.get_llm_reply(payload)
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/guide/ask", response_model=GuideQuestionResponse, summary="Ask guide using verified festival data")
def ask_guide(payload: GuideQuestionRequest) -> GuideQuestionResponse:
    try:
        return service.answer_guide_question(payload)
    except AllenAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/guide/course", response_model=CourseRecommendResponse, summary="Recommend personalized festival course")
def recommend_course(payload: CourseRecommendRequest) -> CourseRecommendResponse:
    return service.recommend_course(payload)
