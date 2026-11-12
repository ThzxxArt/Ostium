from __future__ import annotations

import urllib.error
import urllib.request

from ostium.acme.client import AcmeIssuer, challenge_server
from ostium.config import Settings
from ostium.services.crypto import SecretStore


def test_challenge_server_serves_only_tokens() -> None:
    with challenge_server(port=18080) as store:
        store.put("token-abc", "key-authorization")
        with urllib.request.urlopen(
            "http://127.0.0.1:18080/.well-known/acme-challenge/token-abc", timeout=5
        ) as response:
            assert response.status == 200
            assert response.read() == b"key-authorization"
        try:
            urllib.request.urlopen("http://127.0.0.1:18080/other", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("unknown paths must be rejected")


def test_acme_account_key_is_persisted_and_encrypted(settings: Settings) -> None:
    store = SecretStore.from_data_dir(settings.data_dir)
    issuer = AcmeIssuer(settings, store)
    first = issuer._load_account_key()
    path = settings.data_dir / "acme" / "account.key.enc"
    assert path.is_file()
    assert path.read_text().startswith("v1.")
    second = issuer._load_account_key()
    assert first.private_numbers() == second.private_numbers()


def test_acme_staging_directory(settings: Settings) -> None:
    settings.acme_staging = True
    issuer = AcmeIssuer(settings, SecretStore.from_data_dir(settings.data_dir))
    assert "staging" in issuer._directory_url()
    settings.acme_staging = False
    assert "staging" not in issuer._directory_url()
