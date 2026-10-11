import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

log = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error with a stable machine code and a user-safe message."""

    status_code = 400
    code = "app_error"
    user_message = "Something went wrong. Please try again."

    def __init__(self, user_message: str | None = None, **context: object) -> None:
        super().__init__(user_message or self.user_message)
        self.user_message = user_message or self.user_message
        self.context = context
        self.headers: dict[str, str] | None = None


class RateLimitedError(AppError):
    status_code, code, user_message = 429, "rate_limited", "Too many attempts. Please wait and try again."


class ServiceUnavailableError(AppError):
    status_code, code, user_message = 503, "service_unavailable", "This service is temporarily unavailable."


class NotFoundError(AppError):
    status_code, code, user_message = 404, "not_found", "The requested item was not found."


class UnauthorizedError(AppError):
    status_code, code, user_message = 401, "unauthorized", "Please sign in to continue."


class ForbiddenError(AppError):
    status_code, code, user_message = 403, "forbidden", "You do not have permission to do this."


class ConflictError(AppError):
    status_code, code, user_message = 409, "conflict", "This request conflicts with an earlier one."


def error_body(code: str, message: str, details: object | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message, "request_id": request_id_ctx.get()}
    if details is not None:
        error["details"] = details
    return {"success": False, "error": error}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        log.warning("app_error", extra={"code": exc.code, **exc.context})
        return JSONResponse(error_body(exc.code, exc.user_message), status_code=exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["msg"]} for e in exc.errors()]
        return JSONResponse(error_body("validation_error", "Some details are invalid.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error")
        return JSONResponse(error_body("internal_error", "Something went wrong on our side."), status_code=500)
