"""Browser screenshots and accessibility checks.

Run with ``OSTIUM_UI=1 uv run pytest tests/ui`` after installing Chromium.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

pytest.importorskip("playwright")
pytest.importorskip("axe_playwright_python")

if os.environ.get("OSTIUM_UI") != "1":
    pytest.skip("set OSTIUM_UI=1 and install Chromium to run UI tests", allow_module_level=True)

pytestmark = pytest.mark.ui

SCREENSHOTS = Path(__file__).parent / "screenshots"


@pytest.fixture(scope="module", autouse=True)
def require_ui():
    if os.environ.get("OSTIUM_UI") != "1":
        pytest.skip("set OSTIUM_UI=1 and install Chromium to run UI tests")
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def browser_user(db):
    from ostium.proxy.models import Inbound
    from ostium.proxy.services import create_proxy_user, initialize_inbounds

    User = get_user_model()
    user = User.objects.create_superuser("admin", "admin@example.com", "Ostium-UI-Password-2026")
    user.ostium_profile.must_change_password = False
    user.ostium_profile.save(update_fields=["must_change_password"])
    initialize_inbounds(enable=("vless", "shadowsocks"))
    alice, _token = create_proxy_user("alice", quota_bytes=100 * 1024**3, quota_cycle="monthly")
    bob, _token = create_proxy_user("bob", quota_bytes=20 * 1024**3)
    assert Inbound.objects.filter(enabled=True).count() == 2

    from datetime import date, timedelta

    from django.utils import timezone

    from ostium.engine.runtime import write_usage
    from ostium.operations.models import RuntimeState
    from ostium.proxy.models import TrafficDaily

    now = timezone.now()
    RuntimeState.objects.filter(pk=1).update(
        desired_revision=12,
        applied_revision=12,
        singbox_running=True,
        singbox_pid=4242,
        singbox_started_at=now - timedelta(days=2, hours=4),
        worker_heartbeat=now,
        config_sha256="a" * 64,
    )
    for offset in range(30):
        TrafficDaily.objects.create(
            user=alice,
            day=date.today() - timedelta(days=offset),
            uplink=(offset % 5 + 1) * 1024**2,
            downlink=(offset % 7 + 2) * 3 * 1024**2,
        )
    TrafficDaily.objects.create(user=bob, day=date.today(), uplink=1024**2, downlink=2 * 1024**2)
    alice.last_seen_at = now
    alice.save(update_fields=["last_seen_at"])
    bob.last_seen_at = now
    bob.save(update_fields=["last_seen_at"])
    write_usage(
        {
            "stats_ok": True,
            "users": {
                "alice": {
                    "uplink_rate": 184320,
                    "downlink_rate": 963379,
                    "online": True,
                    "last_activity": now.isoformat(),
                },
                "bob": {
                    "uplink_rate": 20480,
                    "downlink_rate": 61440,
                    "online": True,
                    "last_activity": now.isoformat(),
                },
            },
        }
    )
    return user


def login(page, live_server):
    page.goto(f"{live_server.url}/accounts/login/")
    page.fill("#id_username", "admin")
    page.fill("#id_password", "Ostium-UI-Password-2026")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/")


def _axe(page):
    from axe_playwright_python.sync_playwright import Axe

    return Axe().run(page)


@pytest.mark.django_db(transaction=True)
def test_screenshots_and_axe(page, live_server, browser_user):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    login(page, live_server)

    viewports = [(1440, 900), (1024, 768), (390, 844)]
    pages = ["/", "/users/", "/subscriptions/", "/system/"]
    for width, height in viewports:
        page.set_viewport_size({"width": width, "height": height})
        for route in pages:
            page.goto(f"{live_server.url}{route}")
            page.emulate_media(color_scheme="dark")
            page.evaluate("document.documentElement.dataset.theme = 'dark'")
            page.wait_for_timeout(250)
            name = route.strip("/").replace("/", "-") or "dashboard"
            full_page = width >= 768
            page.screenshot(path=str(SCREENSHOTS / f"{name}-{width}-dark.png"), full_page=full_page)
            page.emulate_media(color_scheme="light")
            page.evaluate("document.documentElement.dataset.theme = 'light'")
            page.wait_for_timeout(250)
            page.screenshot(path=str(SCREENSHOTS / f"{name}-{width}-light.png"), full_page=full_page)

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{live_server.url}/")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    assert page.evaluate("typeof window.Chart") == "function"
    assert not errors, errors
    assert page.evaluate("Boolean(window.__ostiumChart)") is True
    results = _axe(page)
    critical = [violation for violation in results.response["violations"] if violation.get("impact") == "critical"]
    assert not critical, critical


@pytest.mark.django_db(transaction=True)
def test_mobile_navigation(page, live_server, browser_user):
    page.set_viewport_size({"width": 390, "height": 844})
    login(page, live_server)
    page.click(".mobile-menu-btn")
    assert page.locator(".sidebar.sidebar--open").is_visible()
    page.evaluate("document.querySelector(\".sidebar .nav-item[href='/users/']\").click()")
    page.wait_for_url(f"{live_server.url}/users/")
