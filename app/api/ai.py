from fastapi import APIRouter, UploadFile, File

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
    return service.analyze_image(payload)


@router.post("/vision/upload", response_model=VisionResponse, summary="Analyze uploaded image file")
def analyze_image_upload(file: UploadFile = File(...)) -> VisionResponse:
    return service.analyze_image_file(file)


@router.post("/llm/reply", response_model=LLMResponse, summary="Compose an answer from verified context")
def llm_reply(payload: LLMRequest) -> LLMResponse:
    return service.get_llm_reply(payload)


@router.post("/guide/ask", response_model=GuideQuestionResponse, summary="Ask guide using verified festival data")
def ask_guide(payload: GuideQuestionRequest) -> GuideQuestionResponse:
    return service.answer_guide_question(payload)


@router.post("/guide/course", response_model=CourseRecommendResponse, summary="Recommend personalized festival course")
def recommend_course(payload: CourseRecommendRequest) -> CourseRecommendResponse:
    return service.recommend_course(payload)
