"""Loopback client for the sing-box Clash API."""

from __future__ import annotations

import httpx
from django.conf import settings

from .runtime import read_clash_secret


class ClashError(RuntimeError):
    pass


class ClashClient:
    def __init__(self, *, address: str | None = None, secret: str | None = None, timeout: float = 3.0) -> None:
        configured = address or settings.OSTIUM_SINGBOX_CLASH_URL or settings.OSTIUM_SINGBOX_CLASH_ADDRESS
        self.address = configured
        self.secret = secret if secret is not None else read_clash_secret()
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        return self.address if "://" in self.address else f"http://{self.address}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}"} if self.secret else {}

    def _request(self, method: str, path: str) -> dict:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, headers=self._headers()) as client:
                response = client.request(method, path)
                response.raise_for_status()
                if response.content:
                    return response.json()
                return {}
        except (httpx.HTTPError, ValueError) as exc:
            raise ClashError(str(exc)) from exc

    def version(self) -> dict:
        return self._request("GET", "/version")

    def connections(self) -> list[dict]:
        payload = self._request("GET", "/connections")
        result = []
        for item in payload.get("connections", []):
            metadata = item.get("metadata", {})
            result.append(
                {
                    "id": item.get("id"),
                    "user": metadata.get("user") or metadata.get("inboundUser") or "—",
                    "inbound": metadata.get("inboundName") or metadata.get("type") or "—",
                    "network": metadata.get("network") or "—",
                    "host": metadata.get("host") or metadata.get("destinationIP") or "—",
                    "destination": f"{metadata.get('destinationIP', '')}:{metadata.get('destinationPort', '')}".strip(
                        ":"
                    ),
                    "rule": item.get("rule") or "—",
                    "chains": item.get("chains") or [],
                    "upload": item.get("upload", 0),
                    "download": item.get("download", 0),
                    "start": item.get("start"),
                }
            )
        return result

    def close_connection(self, connection_id: str) -> None:
        self._request("DELETE", f"/connections/{connection_id}")

    def close_all(self) -> None:
        self._request("DELETE", "/connections")

    def traffic(self) -> dict:
        payload = self._request("GET", "/connections")
        return {
            "upload_total": payload.get("uploadTotal", 0),
            "download_total": payload.get("downloadTotal", 0),
            "connections": len(payload.get("connections", [])),
        }


__all__ = ["ClashClient", "ClashError"]
