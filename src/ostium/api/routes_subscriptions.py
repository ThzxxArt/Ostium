"""Public subscription endpoints (no admin session)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_services, get_session
from ostium.api.ratelimit import LIMITER
from ostium.services.subscriptions import SubscriptionInactive, render_subscription
from ostium.services.users import get_user_by_subscription_token

router = APIRouter(tags=["subscriptions"])


@router.get("/sub/{token}")
async def subscription(
    token: str,
    request: Request,
    fmt: str = Query(default="ostium", alias="format"),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Response:
    ip = client_ip(request)
    if not LIMITER.allow(f"sub:{ip}", 60, 60.0):
        return Response(
            status_code=429,
            content=b"too many requests",
            media_type="text/plain",
            headers={"Retry-After": "60", "Referrer-Policy": "no-referrer"},
        )
    user = await get_user_by_subscription_token(session, services.store, token)
    if user is None:
        return Response(status_code=404, content=b"not found", media_type="text/plain")
    try:
        content, media_type = await render_subscription(session, services.store, user, fmt)
    except SubscriptionInactive:
        return Response(status_code=403, content=b"subscription inactive", media_type="text/plain")
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
    }
    if fmt in {"clash"}:
        extension = "yaml"
        disposition = "attachment"
    else:
        extension = "txt"
        disposition = "inline"
    # HTTP headers are latin-1.  ASCII fallback plus RFC 5987 gives Chinese
    # user names a working download instead of a UnicodeEncodeError.
    encoded_name = quote(f"ostium-{user.name}.{extension}", safe="")
    headers["Content-Disposition"] = (
        f'{disposition}; filename="ostium-subscription.{extension}"; '
        f"filename*=UTF-8''{encoded_name}"
    )
    return Response(content=content, media_type=media_type, headers=headers)
