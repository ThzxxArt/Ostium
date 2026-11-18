"""Run npm audit with a narrow, expiring exception for unfixed dev-only advisories.

The alternative -- lowering the audit threshold or running `npm audit fix
--force` -- would hide unrelated high findings or introduce breaking runtime
changes.  Every non-allowlisted advisory still fails the gate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# GHSA-fc5q-39xc-vjpf: picomatch <= 4.0.7 ReDoS through repeated extglobs.
# 4.0.7 is the newest release; the package is only used by the frontend build
# and test toolchain, not shipped in the wheel or web bundle.  Remove this entry
# as soon as a fixed picomatch release is available.
ALLOWLIST: dict[str, dt.date] = {
    "GHSA-fc5q-39xc-vjpf": dt.date(2026, 12, 18),
}


def _advisories(payload: dict[str, Any]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for package, entry in (payload.get("vulnerabilities") or {}).items():
        if not isinstance(entry, dict):
            continue
        for item in entry.get("via") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            identifier = url.rsplit("/", 1)[-1] if "/" in url else ""
            if not identifier:
                continue
            found[identifier] = {
                "id": identifier,
                "package": str(package),
                "severity": str(item.get("severity") or entry.get("severity") or "unknown"),
                "title": str(item.get("title") or ""),
                "url": url,
            }
    return list(found.values())


def evaluate(payload: dict[str, Any], *, today: dt.date | None = None) -> tuple[bool, list[str]]:
    today = today or dt.datetime.now(dt.UTC).date()
    messages: list[str] = []
    failed = False
    advisories = _advisories(payload)
    if not advisories:
        return True, ["npm audit: no advisories"]
    for advisory in sorted(advisories, key=lambda item: (item["package"], item["id"])):
        expiry = ALLOWLIST.get(advisory["id"])
        if expiry is None:
            failed = True
            messages.append(
                f"FAIL {advisory['package']} {advisory['severity']} "
                f"{advisory['id']}: {advisory['title']} ({advisory['url']})"
            )
            continue
        if today > expiry:
            failed = True
            messages.append(
                f"FAIL {advisory['id']} exception expired on {expiry.isoformat()}; "
                "upgrade or renew the documented exception"
            )
            continue
        messages.append(
            f"ALLOW {advisory['package']} {advisory['severity']} {advisory['id']} "
            f"until {expiry.isoformat()}: {advisory['title']}"
        )
    return not failed, messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="web")
    parser.add_argument("--registry", default="https://registry.npmjs.org")
    args = parser.parse_args()
    directory = Path(args.directory)
    command = ["npm", "audit", "--json", f"--registry={args.registry}"]
    result = subprocess.run(
        command,
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        print("npm audit did not return JSON", file=sys.stderr)
        print((result.stderr or result.stdout)[-2000:], file=sys.stderr)
        return 1
    ok, messages = evaluate(payload)
    for message in messages:
        print(message)
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
