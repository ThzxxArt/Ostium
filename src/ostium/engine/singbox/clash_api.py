"""Clash API client for connections, live traffic and proxy health."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class ClashApi:
    def __init__(self, secret_path: Path, base_url: str = "http://127.0.0.1:19090") -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_path = secret_path

    def _headers(self) -> dict[str, str]:
        try:
            secret = self.secret_path.read_text(encoding="utf-8").strip()
        except OSError:
            secret = ""
        return {"Authorization": f"Bearer {secret}"} if secret else {}

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(f"{self.base_url}{path}", headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def connections(self) -> dict[str, Any]:
        try:
            return dict(await self._get("/connections"))
        except Exception:
            return {"downloadTotal": 0, "uploadTotal": 0, "connections": [], "unavailable": True}

    async def close_connection(self, connection_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                response = await client.delete(
                    f"{self.base_url}/connections/{connection_id}", headers=self._headers()
                )
            return response.status_code < 300
        except httpx.HTTPError:
            return False

    async def version(self) -> dict[str, Any] | None:
        try:
            return dict(await self._get("/version"))
        except Exception:
            return None

    async def proxies(self) -> dict[str, Any]:
        try:
            return dict(await self._get("/proxies"))
        except Exception:
            return {}

    async def close_all(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                response = await client.delete(
                    f"{self.base_url}/connections", headers=self._headers()
                )
            return response.status_code < 300
        except httpx.HTTPError:
            return False
