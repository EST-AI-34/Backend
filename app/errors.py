class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None, retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        self.retryable = retryable
        super().__init__(message)


def bad_request(code: str, message: str) -> AppError:
    return AppError(400, code, message)


def unauthorized(code: str = "UNAUTHENTICATED", message: str = "인증이 필요합니다.") -> AppError:
    return AppError(401, code, message)


def forbidden(code: str = "FORBIDDEN", message: str = "접근 권한이 없습니다.") -> AppError:
    return AppError(403, code, message)


def not_found(message: str = "리소스를 찾을 수 없습니다.") -> AppError:
    return AppError(404, "RESOURCE_NOT_FOUND", message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unprocessable(code: str, message: str) -> AppError:
    return AppError(422, code, message)

