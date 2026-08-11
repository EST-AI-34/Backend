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
    ENABLE_EXTERNAL_AI: bool = False
    ALLEN_API_BASE_URL: str = "https://api.allen.ai"
    ALLEN_API_KEY: str = ""
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings(
    PROJECT_NAME=os.getenv("PROJECT_NAME", "FEST Backend"),
    VERSION=os.getenv("VERSION", "1.0.0"),
    DEBUG=os.getenv("DEBUG", "true").lower() == "true",
    ENABLE_EXTERNAL_AI=os.getenv("ENABLE_EXTERNAL_AI", "false").lower() == "true",
    ALLEN_API_BASE_URL=os.getenv("ALLEN_API_BASE_URL", "https://api.allen.ai"),
    ALLEN_API_KEY=os.getenv("ALLEN_API_KEY", ""),
    BACKEND_CORS_ORIGINS=os.getenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ),
)
