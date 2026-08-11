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
    ALLEN_API_BASE_URL: str = "https://api.allen.ai"
    ALLEN_API_KEY: str = ""
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
    ALLEN_API_BASE_URL=os.getenv("ALLEN_API_BASE_URL", "https://api.allen.ai"),
    ALLEN_API_KEY=os.getenv("ALLEN_API_KEY", ""),
    BACKEND_CORS_ORIGINS=os.getenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ),
)
