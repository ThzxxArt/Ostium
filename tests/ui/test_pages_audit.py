"""Full-page visual audit for pages not covered by the main UI suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright")

if os.environ.get("OSTIUM_UI") != "1":
    pytest.skip("set OSTIUM_UI=1 and install Chromium to run UI tests", allow_module_level=True)

SCREENSHOTS = Path(__file__).parent / "screenshots"


@pytest.fixture
def browser_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_superuser("admin", "admin@example.com", "Ostium-UI-Password-2026")
    user.ostium_profile.must_change_password = False
    user.ostium_profile.save(update_fields=["must_change_password"])
    return user


def login(page, live_server):
    page.goto(f"{live_server.url}/accounts/login/")
    page.fill("#id_username", "admin")
    page.fill("#id_password", "Ostium-UI-Password-2026")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/")


@pytest.mark.django_db(transaction=True)
def test_settings_system_admin_and_api_docs(page, live_server, browser_user):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.set_viewport_size({"width": 1440, "height": 900})
    login(page, live_server)

    pages = {
        "settings": "/settings/",
        "system": "/system/",
        "admin": "/admin/",
        "admin-users": "/admin/proxy/proxyuser/",
        "admin-certificates": "/admin/certificates/certificate/",
        "admin-certificate-import": "/admin/certificates/certificate/import/",
        "certificate-import": "/certificates/import/",
        "api-docs": "/api/docs",
    }
    for name, route in pages.items():
        page.goto(f"{live_server.url}{route}")
        page.wait_for_timeout(500)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), route
        page.screenshot(path=str(SCREENSHOTS / f"audit-{name}.png"), full_page=True)

    page.goto(f"{live_server.url}/settings/")
    settings_text = page.locator("body").inner_text()
    # The settings page previously rendered field objects instead of inputs.
    assert "<django.forms.fields" not in settings_text
    assert page.locator("form.settings-layout input, form.settings-layout select").count() > 5
    assert "服务器名称" in settings_text
    assert "阻止私网出口" in settings_text

    # The console certificate import page must match the rest of Aurora.
    page.goto(f"{live_server.url}/certificates/import/")
    body = page.locator("body").inner_text()
    assert "导入证书" in body
    assert "上传证书文件" in body
    assert page.locator("form input[type=file]").count() == 2
    assert page.locator("form select#id_server_certificate").count() == 1
    assert page.locator("form textarea").count() == 2

    # Swagger UI is loaded from the local sidecar and must render under CSP.
    page.goto(f"{live_server.url}/api/docs")
    page.wait_for_timeout(1000)
    assert page.locator(".swagger-ui").count() == 1
    assert not [error for error in errors if "Content Security Policy" in error], errors
    # Swagger UI triggers a Chromium permissions-policy warning for unload.
    ignored = "Permissions policy violation: unload"
    assert not [error for error in errors if ignored not in error], errors
