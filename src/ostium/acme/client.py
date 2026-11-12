"""Built-in ACME HTTP-01 client.

Only HTTP-01 is implemented by design (see PLAN.md §2.4).  The challenge server
binds port 80 for the duration of issuance and serves exactly the requested key
authorizations, then shuts down.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import josepy as jose
from acme import challenges, client, errors, messages
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ostium.config import Settings
from ostium.services.crypto import SecretStore


class AcmeError(Exception):
    def __init__(self, message: str, code: str = "acme_error", status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _ChallengeStore:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}
        self.lock = threading.Lock()

    def put(self, token: str, key_authorization: str) -> None:
        with self.lock:
            self.tokens[token] = key_authorization

    def get(self, token: str) -> str | None:
        with self.lock:
            return self.tokens.get(token)


def _handler(store: _ChallengeStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            prefix = "/.well-known/acme-challenge/"
            if not self.path.startswith(prefix):
                self.send_error(404)
                return
            token = self.path[len(prefix) :].split("?", 1)[0]
            value = store.get(token)
            if value is None:
                self.send_error(404)
                return
            body = value.encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return Handler


@contextlib.contextmanager
def challenge_server(port: int = 80) -> Iterator[_ChallengeStore]:
    store = _ChallengeStore()
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _handler(store))
    except OSError as exc:
        raise AcmeError(
            f"cannot bind port {port} for the ACME HTTP-01 challenge: {exc}", "port_80_unavailable"
        ) from exc
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="acme-http01", daemon=True)
    thread.start()
    try:
        yield store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class AcmeIssuer:
    def __init__(self, settings: Settings, store: SecretStore) -> None:
        self.settings = settings
        self.store = store

    def _directory_url(self) -> str:
        if self.settings.acme_staging:
            return "https://acme-staging-v02.api.letsencrypt.org/directory"
        return self.settings.acme_directory

    def _load_account_key(self) -> rsa.RSAPrivateKey:
        # The account key lives in a small file next to the master key; it is
        # encrypted at rest with the same master key.
        path = self.settings.data_dir / "acme" / "account.key.enc"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            pem = self.store.decrypt(
                path.read_text(encoding="utf-8"),
                table="settings",
                record_id="acme",
                field="account_key",
            )
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            assert isinstance(key, rsa.RSAPrivateKey)
            return key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        path.write_text(
            self.store.encrypt(pem, table="settings", record_id="acme", field="account_key"),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return key

    async def issue(self, domain: str, *, timeout_seconds: int = 180) -> tuple[str, str]:
        return await asyncio.to_thread(self._issue_sync, domain, timeout_seconds)

    def _issue_sync(self, domain: str, timeout_seconds: int) -> tuple[str, str]:
        domain = domain.strip().lower()
        if not domain:
            raise AcmeError("a domain is required for ACME")
        account_key = self._load_account_key()
        acme_key = jose.JWKRSA(key=account_key)  # type: ignore[attr-defined]
        net = client.ClientNetwork(
            acme_key,
            user_agent="Ostium/0.1 (+https://github.com/ThzxxArt/Ostium)",
            timeout=30,
        )
        try:
            directory = messages.Directory.from_json(net.get(self._directory_url()).json())
            acme_client = client.ClientV2(directory, net)
            with contextlib.suppress(errors.ConflictError):
                acme_client.new_account(
                    messages.NewRegistration.from_data(
                        email=self.settings.acme_email, terms_of_service_agreed=True
                    )
                )
            cert_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            csr = (
                x509.CertificateSigningRequestBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
                .sign(cert_key, hashes.SHA256())
            )
            order = acme_client.new_order(csr.public_bytes(serialization.Encoding.PEM))
            with challenge_server(80) as store:
                for authz in order.authorizations:
                    challenge = next(
                        (
                            item
                            for item in authz.body.challenges
                            if item.chall.typ == challenges.HTTP01.typ
                        ),
                        None,
                    )
                    if challenge is None:
                        raise AcmeError(
                            "the ACME server did not offer HTTP-01 for "
                            f"{authz.body.identifier.value}"
                        )
                    response, validation = challenge.response_and_validation(acme_client.net.key)
                    store.put(challenge.chall.token, validation)
                    acme_client.answer_challenge(challenge, response)
                deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=timeout_seconds)
                finalized = acme_client.poll_and_finalize(order, deadline=deadline)
            fullchain = finalized.fullchain_pem
            if not fullchain:
                raise AcmeError("ACME did not return a certificate chain")
            key_pem = cert_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
            return fullchain, key_pem
        except AcmeError:
            raise
        except errors.Error as exc:
            raise AcmeError(f"ACME request failed: {exc}") from exc
        except Exception as exc:
            raise AcmeError(f"ACME issuance failed: {exc}") from exc
