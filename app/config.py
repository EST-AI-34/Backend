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
    allen_question_url: str = os.getenv("ALLEN_QUESTION_URL", "https://kdt-api-function.azurewebsites.net/api/v1/question")
    allen_client_id: str = os.getenv("ALLEN_CLIENT_ID", "")
    allen_connect_timeout: float = float(os.getenv("ALLEN_CONNECT_TIMEOUT_SECONDS", "3"))
    allen_read_timeout: float = float(os.getenv("ALLEN_READ_TIMEOUT_SECONDS", "30"))
    allen_max_retries: int = int(os.getenv("ALLEN_MAX_RETRIES", "2"))

    def validate(self) -> None:
        if self.environment == "production" and len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")


settings = Settings()
settings.validate()

