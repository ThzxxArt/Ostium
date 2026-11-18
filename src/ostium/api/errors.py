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


__all__ = ["exception_handler"]
