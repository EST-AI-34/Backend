import os
from dataclasses import dataclass


try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    PROJECT_NAME: str = "FEST Backend"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    JWT_SECRET: str = "replace-with-at-least-32-random-characters"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 7
    VISITOR_SESSION_HOURS: int = 24
    ENABLE_EXTERNAL_AI: bool = False
    ALLEN_API_BASE_URL: str = "https://api.myalan.ai/api/v1"
    ALLEN_AUTH_MODE: str = "bearer"
    ALLEN_AUTH_BASE_URL: str = "https://api.myalan.ai"
    ALLEN_CLIENT_ID: str = ""
    ALLEN_LLM_ENDPOINT: str = "/channels"
    ALLEN_PERSONA_ID: str = "69ce0aeab459faf50a427005"
    ALLEN_MODEL: str = ""
    ALLEN_DEVICE_PLATFORM: str = "web"
    ALLEN_DEVICE_VERSION: str = "2.0.4"
    ALLEN_MESSAGE_POLL_SECONDS: float = 2.0
    ALLEN_MESSAGE_POLL_ATTEMPTS: int = 20
    ALLEN_API_KEY: str = ""
    ALLEN_CONNECT_TIMEOUT_SECONDS: float = 3.0
    ALLEN_READ_TIMEOUT_SECONDS: float = 30.0
    ALLEN_MAX_RETRIES: int = 2
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL


settings = Settings(
    PROJECT_NAME=os.getenv("PROJECT_NAME", "FEST Backend"),
    VERSION=os.getenv("VERSION", "1.0.0"),
    DEBUG=os.getenv("DEBUG", "true").lower() == "true",
    ENVIRONMENT=os.getenv("ENVIRONMENT", "development"),
    DATABASE_URL=os.getenv("DATABASE_URL", ""),
    SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
    SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY", ""),
    SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
    JWT_SECRET=os.getenv("JWT_SECRET", "replace-with-at-least-32-random-characters"),
    ACCESS_TOKEN_MINUTES=int(os.getenv("ACCESS_TOKEN_MINUTES", "15")),
    REFRESH_TOKEN_DAYS=int(os.getenv("REFRESH_TOKEN_DAYS", "7")),
    VISITOR_SESSION_HOURS=int(os.getenv("VISITOR_SESSION_HOURS", "24")),
    ENABLE_EXTERNAL_AI=os.getenv("ENABLE_EXTERNAL_AI", "false").lower() == "true",
    ALLEN_API_BASE_URL=os.getenv("ALLEN_API_BASE_URL", "https://api.myalan.ai/api/v1"),
    ALLEN_AUTH_MODE=os.getenv("ALLEN_AUTH_MODE", "bearer"),
    ALLEN_AUTH_BASE_URL=os.getenv("ALLEN_AUTH_BASE_URL", "https://api.myalan.ai"),
    ALLEN_CLIENT_ID=os.getenv("ALLEN_CLIENT_ID", ""),
    ALLEN_LLM_ENDPOINT=os.getenv("ALLEN_LLM_ENDPOINT", "/channels"),
    ALLEN_PERSONA_ID=os.getenv("ALLEN_PERSONA_ID", "69ce0aeab459faf50a427005"),
    ALLEN_MODEL=os.getenv("ALLEN_MODEL", ""),
    ALLEN_DEVICE_PLATFORM=os.getenv("ALLEN_DEVICE_PLATFORM", "web"),
    ALLEN_DEVICE_VERSION=os.getenv("ALLEN_DEVICE_VERSION", "2.0.4"),
    ALLEN_MESSAGE_POLL_SECONDS=float(os.getenv("ALLEN_MESSAGE_POLL_SECONDS", "2.0")),
    ALLEN_MESSAGE_POLL_ATTEMPTS=int(os.getenv("ALLEN_MESSAGE_POLL_ATTEMPTS", "20")),
    ALLEN_API_KEY=os.getenv("ALLEN_API_KEY", ""),
    ALLEN_CONNECT_TIMEOUT_SECONDS=float(os.getenv("ALLEN_CONNECT_TIMEOUT_SECONDS", "3.0")),
    ALLEN_READ_TIMEOUT_SECONDS=float(os.getenv("ALLEN_READ_TIMEOUT_SECONDS", "30.0")),
    ALLEN_MAX_RETRIES=int(os.getenv("ALLEN_MAX_RETRIES", "2")),
    BACKEND_CORS_ORIGINS=os.getenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ),
)
