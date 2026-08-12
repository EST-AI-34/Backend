import base64
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PLACEHOLDER_KEYS = {"", "your_allen_api_key_here", "changeme", "replace_me"}


class AllenAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {"message": message}


class AIRepository:
    def __init__(self) -> None:
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def analyze_image(self, image_url: str) -> dict[str, Any]:
        data = self._post_allen("/vision/analyze", {"image_url": image_url})
        return {
            "summary": data.get("summary", "Allen returned no summary."),
            "labels": data.get("labels", []),
            "metadata": data.get("metadata", {}),
        }

    def analyze_image_file(self, file: Any) -> dict[str, Any]:
        file_content = file.file.read()
        encoded = base64.b64encode(file_content).decode("utf-8")
        data = self._post_allen("/vision/analyze", {"image_base64": encoded})
        return {
            "summary": data.get("summary", "Allen returned no summary."),
            "labels": data.get("labels", []),
            "metadata": data.get("metadata", {}),
        }

    def call_llm(self, prompt: str, context: list[str]) -> dict[str, str]:
        logger.info("Calling myAlan channel API with prompt length=%s", len(prompt))
        channel_id = self._create_allen_channel()
        data = self._post_allen(
            f"{settings.ALLEN_LLM_ENDPOINT.rstrip('/')}/{channel_id}/messages",
            {
                "channel_id": channel_id,
                "persona_id": settings.ALLEN_PERSONA_ID,
                "content": self._compose_user_prompt(prompt, context),
                "options": {"file_ids": []},
            },
        )
        reply = self._extract_llm_reply(data)
        if not reply:
            data = self._poll_allen_message(channel_id)
            reply = self._extract_llm_reply(data)

        if not isinstance(reply, str) or not reply.strip():
            raise AllenAPIError(
                "Allen returned an empty LLM reply.",
                detail={"message": "Allen returned an empty LLM reply.", "provider": "allen"},
            )

        return {"reply": reply.strip(), "source": "allen"}

    def create_esg_briefing(self, context: list[str]) -> dict[str, str]:
        prompt = (
            "Use only the verified ESG context below. "
            "Write exactly one Korean sentence for an admin dashboard ESG briefing. "
            "Mention the most important ESG status and one action if needed. "
            "Do not search the web, do not cite sources, do not use markdown, "
            "and do not invent or calculate new numbers."
        )
        result = self.call_llm(prompt, context)
        return {"briefing": self._one_sentence(result["reply"]), "source": "allen"}

    def create_risk_briefing(self, context: list[str]) -> dict[str, str]:
        prompt = (
            "Use only the verified festival operations risk context below. "
            "Write exactly one concise Korean admin risk summary sentence. "
            "Do not add new scores, names, phone numbers, personal data, or unverified causes."
        )
        result = self.call_llm(prompt, context)
        return {"briefing": self._one_sentence(result["reply"]), "source": "allen"}

    def _compose_user_prompt(self, prompt: str, context: list[str]) -> str:
        context_text = "\n".join(f"- {item}" for item in context)
        return (
            "You are the FESTAI festival assistant. Use only verified context supplied by the backend. "
            "Do not invent statistics, schedules, congestion, reservations, complaints, or ESG values.\n\n"
            f"{prompt}\n\nVerified context:\n{context_text}"
        )

    def _create_allen_channel(self) -> str:
        data = self._post_allen(
            settings.ALLEN_LLM_ENDPOINT,
            {"persona_id": settings.ALLEN_PERSONA_ID, "temporary": True},
        )
        channel_id = data.get("inserted_id") or data.get("_id") or data.get("channel_id")
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise AllenAPIError(
                "Allen returned no channel id.",
                detail={"message": "Allen returned no channel id.", "provider": "allen", "body": data},
            )
        return channel_id.strip()

    def _poll_allen_message(self, channel_id: str) -> dict[str, Any]:
        for _ in range(settings.ALLEN_MESSAGE_POLL_ATTEMPTS):
            time.sleep(settings.ALLEN_MESSAGE_POLL_SECONDS)
            data = self._get_allen(f"{settings.ALLEN_LLM_ENDPOINT.rstrip('/')}/{channel_id}/messages")
            if self._extract_llm_reply(data):
                return data
        raise AllenAPIError(
            "Allen message response timed out.",
            status_code=504,
            detail={"message": "Allen message response timed out.", "provider": "allen"},
        )

    def _extract_llm_reply(self, data: dict[str, Any]) -> str | None:
        if isinstance(data.get("content"), str) and data["content"].strip():
            return data["content"]
        if isinstance(data.get("message"), dict) and isinstance(data["message"].get("content"), str):
            return data["message"]["content"]
        if isinstance(data.get("messages"), list):
            for item in reversed(data["messages"]):
                if isinstance(item, dict) and item.get("userRole") != "user":
                    content = item.get("content")
                    if isinstance(content, str) and content.strip():
                        return content
        return None

    def _one_sentence(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        compact = re.sub(r"\[(?:출처|source)\d*\]\([^)]+\)", "", compact, flags=re.IGNORECASE).strip()
        compact = compact.strip(" -*#")
        for match in re.finditer(r"(?<!\d)[.!?。](?!\d)", compact):
            return compact[: match.end()].strip()
        return compact[:220].strip()

    def _post_allen(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_allen_config()
        return self._request_allen("POST", path, json=payload)

    def _get_allen(self, path: str) -> dict[str, Any]:
        self._require_allen_config()
        return self._request_allen("GET", path)

    def _request_allen(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{settings.ALLEN_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        timeout = self._timeout()
        attempts = max(1, settings.ALLEN_MAX_RETRIES + 1)
        last_error: Exception | None = None
        auth_refreshed = False

        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.request(method, url, headers=self._headers(), **kwargs)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise AllenAPIError(
                        "Allen returned a non-object JSON response.",
                        detail={"message": "Allen returned a non-object JSON response.", "provider": "allen"},
                    )
                return data
            except httpx.ConnectTimeout as exc:
                last_error = exc
                status_code = 504
                message = "Allen connection timed out."
            except httpx.ReadTimeout as exc:
                last_error = exc
                status_code = 504
                message = "Allen response read timed out."
            except httpx.HTTPStatusError as exc:
                if (
                    exc.response.status_code == 401
                    and settings.ALLEN_AUTH_MODE.strip().lower() == "implicit"
                    and not auth_refreshed
                ):
                    self._clear_implicit_token()
                    auth_refreshed = True
                    last_error = exc
                    logger.warning("Allen implicit access token expired or was rejected; retrying once in implicit mode.")
                    continue
                raise AllenAPIError(
                    "Allen API returned an error status.",
                    status_code=502,
                    detail={
                        "message": "Allen API returned an error status.",
                        "provider": "allen",
                        "status_code": exc.response.status_code,
                        "body": exc.response.text[:500],
                    },
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                status_code = 502
                message = "Allen API request failed."

            logger.warning("Allen request failed on attempt %s/%s: %s", attempt, attempts, last_error)
            if attempt < attempts:
                time.sleep(min(0.5 * attempt, 2.0))

        raise AllenAPIError(
            message,
            status_code=status_code,
            detail={
                "message": message,
                "provider": "allen",
                "attempts": attempts,
                "error": str(last_error) if last_error else None,
            },
        )

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=settings.ALLEN_CONNECT_TIMEOUT_SECONDS,
            read=settings.ALLEN_READ_TIMEOUT_SECONDS,
            write=settings.ALLEN_CONNECT_TIMEOUT_SECONDS,
            pool=settings.ALLEN_CONNECT_TIMEOUT_SECONDS,
        )

    def _require_allen_config(self) -> None:
        mode = settings.ALLEN_AUTH_MODE.strip().lower()
        if mode == "bearer" and settings.ALLEN_API_KEY.strip() in PLACEHOLDER_KEYS:
            raise AllenAPIError(
                "ALLEN_API_KEY is required for AI endpoints.",
                status_code=503,
                detail={"message": "ALLEN_API_KEY is required for AI endpoints.", "provider": "allen"},
            )
        if mode == "implicit" and settings.ALLEN_CLIENT_ID.strip() in PLACEHOLDER_KEYS:
            raise AllenAPIError(
                "ALLEN_CLIENT_ID is required when ALLEN_AUTH_MODE=implicit.",
                status_code=503,
                detail={
                    "message": "ALLEN_CLIENT_ID is required when ALLEN_AUTH_MODE=implicit.",
                    "provider": "allen",
                },
            )
        if mode not in {"bearer", "implicit"}:
            raise AllenAPIError(
                "Unsupported ALLEN_AUTH_MODE.",
                status_code=500,
                detail={"message": "Unsupported ALLEN_AUTH_MODE.", "provider": "allen", "mode": settings.ALLEN_AUTH_MODE},
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth_token()}",
            "Content-Type": "application/json",
        }

    def _auth_token(self) -> str:
        mode = settings.ALLEN_AUTH_MODE.strip().lower()
        if mode == "bearer":
            return settings.ALLEN_API_KEY
        if mode == "implicit":
            return self._implicit_access_token()
        raise AllenAPIError(
            "Unsupported ALLEN_AUTH_MODE.",
            status_code=500,
            detail={"message": "Unsupported ALLEN_AUTH_MODE.", "provider": "allen", "mode": settings.ALLEN_AUTH_MODE},
        )

    def _implicit_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token

        auth_base = settings.ALLEN_AUTH_BASE_URL.rstrip("/")
        client_id = settings.ALLEN_CLIENT_ID.strip()
        try:
            with httpx.Client(timeout=self._timeout()) as client:
                client.post(
                    f"{auth_base}/device-info",
                    json={
                        "device_id": client_id,
                        "platform": settings.ALLEN_DEVICE_PLATFORM,
                        "version": settings.ALLEN_DEVICE_VERSION,
                    },
                ).raise_for_status()
                response = client.post(
                    f"{auth_base}/oauth2/token",
                    data={"client_id": client_id, "grant_type": "implicit_grant"},
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise AllenAPIError(
                "Allen implicit token request failed.",
                status_code=502,
                detail={"message": "Allen implicit token request failed.", "provider": "allen", "error": str(exc)},
            ) from exc

        token = data.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise AllenAPIError(
                "Allen returned no implicit access token.",
                status_code=502,
                detail={"message": "Allen returned no implicit access token.", "provider": "allen"},
            )
        self._access_token = token.strip()
        self._access_token_expires_at = time.monotonic() + self._token_ttl_seconds(data)
        return self._access_token

    def _clear_implicit_token(self) -> None:
        self._access_token = None
        self._access_token_expires_at = 0.0

    def _token_ttl_seconds(self, data: dict[str, Any]) -> float:
        expires_in = data.get("expires_in")
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            ttl = 900.0
        return max(30.0, ttl - 30.0)
