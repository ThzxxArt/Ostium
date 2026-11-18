"""Redaction helpers for logs, alerts and diagnostics."""

from __future__ import annotations

import re

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
_BASE64_RE = re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b")
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.DOTALL)
_HEADER_RE = re.compile(r"(?i)(authorization|api-key|cookie)\s*[:=]\s*\S+")
_URI_RE = re.compile(r"\b(vless|hysteria2|trojan|ss)://\S+")


def redact(text: str, *, max_length: int = 4000) -> str:
    if not text:
        return ""
    text = _PEM_RE.sub("[redacted key]", text)
    text = _HEADER_RE.sub(r"\1: [redacted]", text)
    text = _URI_RE.sub("[redacted uri]", text)
    text = _LONG_TOKEN_RE.sub("[redacted]", text)
    text = _BASE64_RE.sub("[redacted]", text)
    text = _UUID_RE.sub("[redacted uuid]", text)
    return text[:max_length]


__all__ = ["redact"]
