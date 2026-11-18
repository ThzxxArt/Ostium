"""RFC 9457 problem-details error responses."""

from __future__ import annotations

import uuid

from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def _request_id(request) -> str:
    request_id = getattr(request, "request_id", None)
    if not request_id:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
    return request_id


def _problem(status: int, detail: str, code: str, request_id: str) -> dict:
    return {
        "type": "about:blank",
        "title": "Not Found" if status == 404 else "Server Error",
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": request_id,
    }


def api_not_found(request, exception=None, **kwargs):
    from django.http import JsonResponse

    request_id = uuid.uuid4().hex
    return JsonResponse(
        _problem(404, "The requested API resource does not exist.", "not_found", request_id),
        status=404,
        content_type="application/problem+json",
        headers={"X-Request-ID": request_id},
    )


class APIProblemMiddleware:
    """Return RFC 9457 JSON for uncaught errors under /api/v1/."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            if not request.path.startswith("/api/v1/"):
                raise
            import logging

            logging.getLogger("ostium.api").exception("unhandled API error")
            from django.http import JsonResponse

            request_id = uuid.uuid4().hex
            return JsonResponse(
                _problem(500, "An internal error occurred.", "internal_error", request_id),
                status=500,
                content_type="application/problem+json",
                headers={"X-Request-ID": request_id},
            )


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    request = context.get("request")
    if response is None:
        return None
    if isinstance(exc, ValidationError):
        detail = exc.detail
        code = "validation_error"
        title = "Request validation failed"
    elif isinstance(exc, APIException):
        detail = exc.detail
        code = getattr(exc, "default_code", "api_error")
        title = str(exc.default_detail)
    else:
        detail = str(exc)
        code = "error"
        title = "Request failed"

    message = detail if isinstance(detail, dict | list) else str(detail)

    body = {
        "type": "about:blank",
        "title": title,
        "status": response.status_code,
        "detail": message,
        "code": code,
        "request_id": _request_id(request) if request is not None else "",
    }
    response.data = body
    response.content_type = "application/problem+json"
    response["Content-Type"] = "application/problem+json"
    if request is not None:
        response["X-Request-ID"] = body["request_id"]
    return response


__all__ = ["APIProblemMiddleware", "api_not_found", "exception_handler"]
