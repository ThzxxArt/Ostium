"""Public, token-authenticated subscription endpoints."""

from __future__ import annotations

import re
from urllib.parse import quote

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_safe
from django_ratelimit.decorators import ratelimit

from ostium.proxy.models import ProxyUser, hash_subscription_token

from .endpoints import build_endpoints
from .renderers import content_type_for, extension_for, render
from .services import normalize_target, profile_title_header, public_host, userinfo_header

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
IP_RATE = "60/m"
TOKEN_RATE = 120


def _text(message: str, status: int) -> HttpResponse:
    response = HttpResponse(message + "\n", status=status, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _too_many() -> HttpResponse:
    response = _text("Too many subscription requests. Try again shortly.", 429)
    response["Retry-After"] = "60"
    return response


def _token_limited(token_hash: str) -> bool:
    key = f"ostium:sub:rate:{token_hash}"
    cache.add(key, 0, timeout=60)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=60)
        count = 1
    return count > TOKEN_RATE


@require_safe
@ratelimit(key="ip", rate=IP_RATE, block=False)
def subscription(request: HttpRequest, token: str, path_target: str | None = None) -> HttpResponse:
    if getattr(request, "limited", False):
        return _too_many()
    if not TOKEN_RE.match(token):
        return _text("Subscription not found.", 404)

    token_hash = hash_subscription_token(token)
    if _token_limited(token_hash):
        return _too_many()

    user = ProxyUser.objects.filter(subscription_token_hash=token_hash).first()
    if user is None:
        return _text("Subscription not found.", 404)
    if not user.is_active:
        return _text("This subscription is not active.", 403)

    query_target = request.GET.get("target") or request.GET.get("format") or request.GET.get("flag")
    raw_target = query_target or path_target
    target = normalize_target(raw_target)
    if target is None:
        return _text("Unknown subscription format.", 400)

    endpoints = build_endpoints(user, public_host(request))
    if not endpoints:
        return _text("No enabled inbound is available for this subscription.", 403)

    body = render(target, endpoints)
    response = HttpResponse(body, content_type=content_type_for(target))
    filename = f"ostium-{user.name}.{extension_for(target)}"
    ascii_name = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    response["Content-Disposition"] = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
    )
    response["Subscription-Userinfo"] = userinfo_header(user)
    from constance import config as runtime_config

    try:
        interval = int(runtime_config.subscription_update_interval)
    except TypeError, ValueError:
        interval = 24
    response["Profile-Update-Interval"] = str(min(720, max(1, interval)))
    response["Profile-Title"] = profile_title_header(user)
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
