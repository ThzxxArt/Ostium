"""Public URL derivation shared by the API, CLI, QR codes and subscriptions."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from ostium.config import Settings
from ostium.services.settings import get_setting


def normalize_base_url(value: str) -> str:
    """Validate and normalise a user-supplied public base URL."""

    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("public_base_url must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("public_base_url must not contain a query string or fragment")
    if parsed.username or parsed.password:
        raise ValueError("public_base_url must not contain credentials")
    return candidate


async def public_base_url(session: AsyncSession, settings: Settings) -> str:
    """Resolve the address clients should use for subscription links.

    Order: explicit ``public_base_url`` setting, then the configured server
    domain (HTTPS), then the local listener.  Request ``Host`` headers are never
    used: behind an SSH tunnel they would produce an unreachable URL.
    """

    stored = await get_setting(session, "public_base_url")
    if isinstance(stored, str) and stored.strip():
        try:
            return normalize_base_url(stored)
        except ValueError:
            pass
    server = await get_setting(session, "server", {})
    if isinstance(server, dict):
        domain = server.get("domain") or server.get("public_host")
        if isinstance(domain, str) and domain.strip():
            host = domain.strip().lower()
            if host.startswith(("http://", "https://")):
                try:
                    return normalize_base_url(host)
                except ValueError:
                    pass
            else:
                return f"https://{host}"
    return f"http://127.0.0.1:{settings.port}"


async def public_base_url_or_default(session: AsyncSession, settings: Settings) -> str:
    try:
        return await public_base_url(session, settings)
    except Exception:
        return f"http://127.0.0.1:{settings.port}"
