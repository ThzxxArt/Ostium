"""HTTP client for the local ``ostium-core`` API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx

from ostium.config import Settings
from ostium.engine.singbox.supervisor import ensure_core_token


class CoreApiError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "core_error") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


class CoreClient:
    def __init__(self, settings: Settings, *, timeout: float = 5.0) -> None:
        self.settings = settings
        self.base_url = settings.core_url.rstrip("/")
        self.token_file: Path = settings.core_token_file
        self.timeout = timeout

    def _token(self) -> str:
        return ensure_core_token(self.token_file)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=1.5), trust_env=False
        ) as client:
            try:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
            except httpx.HTTPError as exc:
                raise CoreApiError(
                    503, f"core service is unreachable: {exc}", "core_unreachable"
                ) from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", response.text)
                code = payload.get("code", "core_error")
            except ValueError:
                detail = response.text or response.reason_phrase
                code = "core_error"
            raise CoreApiError(response.status_code, detail, code)
        if response.headers.get("content-type", "").startswith("application/json"):
            return cast(dict[str, Any], response.json())
        return response.text

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(2.0, connect=0.8), trust_env=False
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/v1/health")
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
            except httpx.HTTPError as exc:
                raise CoreApiError(
                    503, f"core service is unreachable: {exc}", "core_unreachable"
                ) from exc

    async def status(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/v1/status"))

    async def apply(self, config: dict[str, Any], sha256: str, role: str) -> dict[str, Any]:
        return dict(
            await self._request(
                "POST",
                "/v1/apply",
                json={"config": config, "sha256": sha256, "role": role},
            )
        )

    async def reload(self) -> dict[str, Any]:
        return dict(await self._request("POST", "/v1/reload", json={}))

    async def stop(self) -> dict[str, Any]:
        return dict(await self._request("POST", "/v1/stop", json={}))

    async def logs(self, tail: int = 500) -> str:
        return str(await self._request("GET", f"/v1/logs?tail={tail}"))

    async def config(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/v1/config"))
