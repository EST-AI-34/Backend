import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgres://festival:festival@localhost:5432/festival")
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-secret-change-me-now")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    visitor_session_hours: int = int(os.getenv("VISITOR_SESSION_HOURS", "24"))
    environment: str = os.getenv("ENVIRONMENT", "development")
    external_ai_enabled: bool = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() == "true"
    allen_base_url: str = os.getenv("ALLEN_API_BASE_URL", "https://api.myalan.ai/api/v1")
    allen_auth_mode: str = os.getenv("ALLEN_AUTH_MODE", "bearer")
    allen_auth_base_url: str = os.getenv("ALLEN_AUTH_BASE_URL", "https://api.myalan.ai")
    allen_api_key: str = os.getenv("ALLEN_API_KEY", "")
    allen_client_id: str = os.getenv("ALLEN_CLIENT_ID", "")
    allen_channels_path: str = os.getenv("ALLEN_LLM_ENDPOINT", "/channels")
    allen_persona_id: str = os.getenv("ALLEN_PERSONA_ID", "69ce0aeab459faf50a427005")
    allen_device_platform: str = os.getenv("ALLEN_DEVICE_PLATFORM", "web")
    allen_device_version: str = os.getenv("ALLEN_DEVICE_VERSION", "2.0.4")
    allen_connect_timeout: float = float(os.getenv("ALLEN_CONNECT_TIMEOUT_SECONDS", "3"))
    allen_read_timeout: float = float(os.getenv("ALLEN_READ_TIMEOUT_SECONDS", "30"))
    allen_max_retries: int = int(os.getenv("ALLEN_MAX_RETRIES", "2"))
    allen_poll_seconds: float = float(os.getenv("ALLEN_MESSAGE_POLL_SECONDS", "2"))
    allen_poll_attempts: int = int(os.getenv("ALLEN_MESSAGE_POLL_ATTEMPTS", "20"))

    def validate(self) -> None:
        if self.environment == "production" and len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")


settings = Settings()
settings.validate()

