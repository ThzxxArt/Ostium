from __future__ import annotations

import contextlib
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import ClassVar

import pytest
from acme import errors

from ostium.acme import client as acme_module
from ostium.acme.client import AcmeError, AcmeIssuer, challenge_server
from ostium.config import Settings
from ostium.services.crypto import SecretStore


class FakeResponse:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeNetwork:
    key = object()

    def __init__(self, *args, **kwargs) -> None:
        pass

    def get(self, url: str) -> FakeResponse:
        return FakeResponse({"newAccount": "x"})


class FakeChallenge:
    def __init__(self, token: str = "tok", typ: str = "http-01") -> None:
        self.chall = SimpleNamespace(token=token, typ=typ)

    def response_and_validation(self, key):  # type: ignore[no-untyped-def]
        return ("response", f"validation-{self.chall.token}")


class FakeAuthorization:
    def __init__(self, challenges: list[FakeChallenge], name: str = "example.com") -> None:
        self.body = SimpleNamespace(challenges=challenges, identifier=SimpleNamespace(value=name))


class FakeOrder:
    def __init__(self, authorizations: list[FakeAuthorization]) -> None:
        self.authorizations = authorizations


class FakeClient:
    instances: ClassVar[list[FakeClient]] = []
    conflict = False
    fail_order = False
    fullchain = "-----BEGIN CERTIFICATE-----\nchain\n-----END CERTIFICATE-----\n"
    offer_http = True
    error: Exception | None = None

    def __init__(self, directory, network) -> None:
        self.directory = directory
        self.net = network
        self.answered: list[FakeChallenge] = []
        self.instances.append(self)

    def new_account(self, registration) -> None:
        if self.conflict:
            raise errors.ConflictError("already registered")

    def new_order(self, csr):  # type: ignore[no-untyped-def]
        if self.fail_order:
            raise self.error or RuntimeError("order failed")
        challenges = [FakeChallenge()] if self.offer_http else [FakeChallenge("dns", "dns-01")]
        return FakeOrder([FakeAuthorization(challenges)])

    def answer_challenge(self, challenge, response) -> None:
        self.answered.append(challenge)

    def poll_and_finalize(self, order, deadline):  # type: ignore[no-untyped-def]
        return SimpleNamespace(fullchain_pem=self.fullchain)


@pytest.fixture
def fake_acme(monkeypatch):
    FakeClient.instances.clear()
    FakeClient.conflict = False
    FakeClient.fail_order = False
    FakeClient.offer_http = True
    FakeClient.error = None
    FakeClient.fullchain = "-----BEGIN CERTIFICATE-----\nchain\n-----END CERTIFICATE-----\n"
    monkeypatch.setattr(acme_module.client, "ClientNetwork", FakeNetwork)
    monkeypatch.setattr(acme_module.client, "ClientV2", FakeClient)
    monkeypatch.setattr(
        acme_module.messages.Directory, "from_json", staticmethod(lambda payload: object())
    )

    @contextlib.contextmanager
    def server(port: int = 80):
        yield SimpleNamespace(put=lambda token, value: None, tokens={})

    monkeypatch.setattr(acme_module, "challenge_server", server)
    return FakeClient


def _issuer(settings: Settings) -> AcmeIssuer:
    return AcmeIssuer(settings, SecretStore.from_data_dir(settings.data_dir))


def test_issue_success(settings: Settings, fake_acme) -> None:
    fullchain, key = _issuer(settings)._issue_sync("Example.COM", 30)
    assert fullchain.startswith("-----BEGIN CERTIFICATE")
    assert "PRIVATE KEY" in key
    assert fake_acme.instances[0].answered[0].chall.token == "tok"


def test_issue_suppresses_conflict(settings: Settings, fake_acme) -> None:
    fake_acme.conflict = True
    fullchain, _key = _issuer(settings)._issue_sync("example.com", 30)
    assert fullchain


def test_issue_requires_domain(settings: Settings, fake_acme) -> None:
    with pytest.raises(AcmeError):
        _issuer(settings)._issue_sync("   ", 30)


def test_issue_without_http01_challenge(settings: Settings, fake_acme) -> None:
    fake_acme.offer_http = False
    with pytest.raises(AcmeError, match="did not offer HTTP-01"):
        _issuer(settings)._issue_sync("example.com", 30)


def test_issue_without_fullchain(settings: Settings, fake_acme) -> None:
    fake_acme.fullchain = ""
    with pytest.raises(AcmeError, match="did not return a certificate chain"):
        _issuer(settings)._issue_sync("example.com", 30)


def test_issue_runtime_error(settings: Settings, fake_acme) -> None:
    fake_acme.fail_order = True
    fake_acme.error = RuntimeError("boom")
    with pytest.raises(AcmeError, match="issuance failed"):
        _issuer(settings)._issue_sync("example.com", 30)


def test_issue_acme_error(settings: Settings, fake_acme) -> None:
    fake_acme.fail_order = True
    fake_acme.error = errors.Error("acme broke")
    with pytest.raises(AcmeError, match="ACME request failed"):
        _issuer(settings)._issue_sync("example.com", 30)


def test_async_issue_delegates(settings: Settings, fake_acme) -> None:
    import asyncio

    fullchain, key = asyncio.run(_issuer(settings).issue("example.com"))
    assert fullchain and key


def test_challenge_server_bind_failure(monkeypatch) -> None:
    class Broken:
        def __init__(self, *args, **kwargs) -> None:
            raise OSError("port in use")

    monkeypatch.setattr(acme_module, "ThreadingHTTPServer", Broken)
    with pytest.raises(AcmeError) as excinfo, challenge_server(port=18081):
        pass
    assert excinfo.value.code == "port_80_unavailable"


def test_challenge_server_rejects_unknown_token_and_query() -> None:
    with challenge_server(port=18082) as store:
        store.put("known", "value")
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(
                "http://127.0.0.1:18082/.well-known/acme-challenge/unknown", timeout=5
            )
        assert missing.value.code == 404

        with urllib.request.urlopen(
            "http://127.0.0.1:18082/.well-known/acme-challenge/known?x=1", timeout=5
        ) as response:
            assert response.read() == b"value"
