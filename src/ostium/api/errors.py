"""RFC 9457-style API errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str = "api_error",
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(request: Request, error: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": "Ostium API error",
        "status": error.status_code,
        "detail": error.detail,
        "code": error.code,
        "request_id": request_id,
    }
    payload.update(error.extra)
    return JSONResponse(
        status_code=error.status_code,
        content=payload,
        media_type="application/problem+json",
        headers=error.headers,
    )
