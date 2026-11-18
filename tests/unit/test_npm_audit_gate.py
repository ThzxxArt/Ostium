from __future__ import annotations

import datetime as dt

from scripts.npm_audit_gate import evaluate


def _payload(identifier: str, package: str, severity: str, title: str) -> dict:
    return {
        "vulnerabilities": {
            package: {
                "name": package,
                "severity": severity,
                "via": [
                    {
                        "name": package,
                        "severity": severity,
                        "title": title,
                        "url": f"https://github.com/advisories/{identifier}",
                    }
                ],
            }
        }
    }


def test_clean_audit_passes() -> None:
    ok, messages = evaluate({"vulnerabilities": {}})
    assert ok is True
    assert messages == ["npm audit: no advisories"]


def test_allowlisted_advisory_passes_until_expiry() -> None:
    payload = _payload(
        "GHSA-fc5q-39xc-vjpf",
        "picomatch",
        "high",
        "picomatch vulnerable to ReDoS",
    )
    ok, messages = evaluate(payload, today=dt.date(2026, 11, 18))
    assert ok is True
    assert any("ALLOW picomatch high GHSA-fc5q-39xc-vjpf" in message for message in messages)


def test_allowlist_expires() -> None:
    payload = _payload(
        "GHSA-fc5q-39xc-vjpf",
        "picomatch",
        "high",
        "picomatch vulnerable to ReDoS",
    )
    ok, messages = evaluate(payload, today=dt.date(2026, 12, 19))
    assert ok is False
    assert any("exception expired" in message for message in messages)


def test_unknown_advisory_fails() -> None:
    payload = _payload("GHSA-aaaa-bbbb-cccc", "other", "critical", "other issue")
    ok, messages = evaluate(payload, today=dt.date(2026, 11, 18))
    assert ok is False
    assert any("GHSA-aaaa-bbbb-cccc" in message for message in messages)
