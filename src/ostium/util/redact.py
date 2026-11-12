"""Log and diagnostic redaction."""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_TOKEN_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|authorization|api[_-]?key|private[_-]?key|cookie)"
    r"(\s*[:=]\s*|\s+)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_AUTH_HEADER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_SS_URI_RE = re.compile(r"ss://[^\s]+")
_VLESS_URI_RE = re.compile(r"(?:vless|trojan|hysteria2|hy2)://[^\s]+")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)


def redact(value: str, *, redact_ids: bool = True) -> str:
    """Redact credentials and, by default, user identifiers from a string."""

    if not value:
        return value
    result = _PEM_RE.sub("[REDACTED PRIVATE KEY]", value)
    result = _AUTH_HEADER_RE.sub(r"\1 [REDACTED]", result)
    result = _TOKEN_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", result)
    result = _SS_URI_RE.sub("ss://[REDACTED]", result)
    result = _VLESS_URI_RE.sub("vless://[REDACTED]", result)
    if redact_ids:
        result = _UUID_RE.sub("[REDACTED-UUID]", result)
    return result


def redact_mapping(data: dict[str, object]) -> dict[str, object]:
    sensitive = {
        "token",
        "password",
        "secret",
        "authorization",
        "private_key",
        "cookie",
        "subscription_token",
        "uuid",
    }
    out: dict[str, object] = {}
    for key, value in data.items():
        if key.lower() in sensitive:
            out[key] = "[REDACTED]"
        elif isinstance(value, str):
            out[key] = redact(value)
        elif isinstance(value, dict):
            out[key] = redact_mapping(value)
        else:
            out[key] = value
    return out
