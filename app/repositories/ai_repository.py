import base64
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PLACEHOLDER_KEYS = {"", "your_allen_api_key_here", "changeme", "replace_me"}


class AIRepository:
    def _has_external_key(self) -> bool:
        return settings.ENABLE_EXTERNAL_AI and settings.ALLEN_API_KEY.strip() not in PLACEHOLDER_KEYS

    def analyze_image(self, image_url: str) -> dict[str, Any]:
        logger.info("Analyzing image URL: %s", image_url)
        if not self._has_external_key():
            return {
                "summary": "이미지 분석 요청을 받았습니다. 외부 AI 연동이 꺼져 있어 현재는 축제 운영 데이터 기반 안내 모드로 응답합니다.",
                "labels": ["festival", "image", "local_fallback"],
                "metadata": {"image_url": image_url, "source": "local-fallback"},
            }

        headers = self._headers()
        payload = {"image_url": image_url}

        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.post(
                    f"{settings.ALLEN_API_BASE_URL}/vision/analyze",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Allen AI image analyze failed: %s", exc)
            return {
                "summary": "외부 이미지 분석 응답이 지연되어 축제 데이터 기반 안내로 전환했습니다.",
                "labels": ["local_fallback"],
                "metadata": {"error": str(exc), "source": "error"},
            }

        return {
            "summary": data.get("summary", "분석 결과가 없습니다."),
            "labels": data.get("labels", []),
            "metadata": data.get("metadata", {}),
        }

    def analyze_image_file(self, file: Any) -> dict[str, Any]:
        logger.info("Analyzing uploaded image file: %s", file.filename)
        file_content = file.file.read()
        if not self._has_external_key():
            return {
                "summary": "업로드 이미지를 받았습니다. 외부 AI 연동이 꺼져 있어 현재는 파일 수신 정보만 기록합니다.",
                "labels": ["uploaded_image", "local_fallback"],
                "metadata": {"filename": file.filename, "bytes": str(len(file_content)), "source": "local-fallback"},
            }

        encoded = base64.b64encode(file_content).decode("utf-8")
        headers = self._headers()
        payload = {"image_base64": encoded}

        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.post(
                    f"{settings.ALLEN_API_BASE_URL}/vision/analyze",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Allen AI image file analyze failed: %s", exc)
            return {
                "summary": "외부 이미지 분석 응답이 지연되어 축제 데이터 기반 안내로 전환했습니다.",
                "labels": ["local_fallback"],
                "metadata": {"error": str(exc), "source": "error"},
            }

        return {
            "summary": data.get("summary", "분석 결과가 없습니다."),
            "labels": data.get("labels", []),
            "metadata": data.get("metadata", {}),
        }

    def call_llm(self, prompt: str, context: list[str]) -> dict[str, str]:
        logger.info("Calling AI guide with prompt length=%s", len(prompt))
        if not self._has_external_key():
            return {
                "reply": "외부 AI 연동이 꺼져 있어 등록된 축제 데이터 기반 로컬 안내로 응답합니다.",
                "source": "local-fallback",
            }

        payload = {
            "prompt": prompt,
            "context": context,
            "model": "gpt-4.1",
        }

        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.post(
                    f"{settings.ALLEN_API_BASE_URL}/llm/reply",
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Allen LLM call failed: %s", exc)
            return {
                "reply": "외부 AI 응답이 지연되어 등록된 축제 데이터 기반 로컬 안내로 전환했습니다.",
                "source": "error",
            }

        return {
            "reply": data.get("reply", "응답 결과가 없습니다."),
            "source": data.get("source", "allen"),
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.ALLEN_API_KEY}",
            "Content-Type": "application/json",
        }
