"""Subscription header safety for non-ASCII names."""

from __future__ import annotations

import pytest

from ostium.proxy.services import create_proxy_user


@pytest.mark.django_db
def test_unicode_profile_title_is_ascii(client, inbounds):
    user, _token = create_proxy_user("用户")
    response = client.get(f"/sub/{user.reveal_subscription_token()}")
    assert response.status_code == 200
    assert response["Profile-Title"].isascii()
