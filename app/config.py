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
    # 프록시(Railway·Vercel) 뒤에서는 request.client.host가 프록시 IP라 모든 방문자가 레이트 리밋
    # 버킷 하나를 공유한다. 프록시가 X-Forwarded-For를 붙여 준다고 확신할 때만 켠다 —
    # 직결 배포에서 켜면 클라이언트가 헤더를 위조해 한도를 우회할 수 있다.
    # 명시적으로 지정하지 않으면 PaaS 표식(RAILWAY_*/VERCEL)이 있을 때만 켠다. 기본값 false로
    # 두면 Railway 배포에서 로그인 10회/분이 서비스 전체 합산이 되어 보호도 안 되고 정상
    # 사용자도 막히는데, 실제로 그 상태로 배포돼 있었다.
    trust_proxy_headers: bool = (os.getenv("TRUST_PROXY_HEADERS") or
                                 str(bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("VERCEL")))).lower() == "true"
    # 로그인 실패 잠금. 계정당 실패가 이 횟수를 넘으면 잠금 시간 동안 비밀번호를 받지 않는다.
    login_max_failures: int = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
    login_lock_minutes: int = int(os.getenv("LOGIN_LOCK_MINUTES", "5"))
    # 만료·폐기 데이터 보존 기간. 잡 워커가 주기적으로 지운다.
    idempotency_retention_days: int = int(os.getenv("IDEMPOTENCY_RETENTION_DAYS", "7"))
    visitor_session_retention_days: int = int(os.getenv("VISITOR_SESSION_RETENTION_DAYS", "180"))
    external_ai_enabled: bool = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() == "true"
    alan_question_url: str = os.getenv("ALAN_QUESTION_URL", "https://kdt-api-function.azurewebsites.net/api/v1/question")
    alan_client_id: str = os.getenv("ALAN_CLIENT_ID", "")
    alan_connect_timeout: float = float(os.getenv("ALAN_CONNECT_TIMEOUT_SECONDS", "3"))
    # 대시보드 응답이 Alan 지연에 묶이지 않도록 짧게 잡는다. 브리핑 한 문장은 이 안에 온다.
    alan_read_timeout: float = float(os.getenv("ALAN_READ_TIMEOUT_SECONDS", "8"))
    alan_max_retries: int = int(os.getenv("ALAN_MAX_RETRIES", "1"))
    # 추천 노출 이력은 위치정보법 제16조의 수집·이용·제공사실 확인자료에 해당한다(OPS-11 정책표: 6개월).
    recommendation_event_retention_days: int = int(os.getenv("RECOMMENDATION_EVENT_RETENTION_DAYS", "180"))

    def validate(self) -> None:
        # development 외의 환경(staging 포함)은 코드에 박힌 기본 키로 뜨면 안 된다.
        # 예전에는 production만 검사해서 staging이 기본 시크릿으로 무방비였다.
        if self.environment != "development":
            if os.getenv("JWT_SECRET") is None:
                raise RuntimeError(f"JWT_SECRET must be set when ENVIRONMENT={self.environment}")
            if len(self.jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be at least 32 characters outside development")


settings = Settings()
settings.validate()

