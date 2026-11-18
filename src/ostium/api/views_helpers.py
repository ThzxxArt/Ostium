"""Shared API payload builders."""

from __future__ import annotations

from ostium.subscriptions.services import (
    TARGETS,
    masked_token,
    subscription_links,
    userinfo_header,
)


def subscription_payload(user, request, *, reveal: bool) -> dict:
    payload = {
        "user": str(user.id),
        "name": user.name,
        "token": user.reveal_subscription_token() if reveal else masked_token(user),
        "revealed": reveal,
        "userinfo": userinfo_header(user),
        "formats": [
            {
                "target": target,
                "label": spec["label"],
                "description": spec["description"],
                "path": f"/sub/{{token}}{spec['suffix']}",
            }
            for target, spec in TARGETS.items()
        ],
    }
    if reveal:
        payload["links"] = subscription_links(user, request)
    else:
        payload["note"] = "POST to this resource's /reveal action to obtain the full token and URLs."
    return payload
