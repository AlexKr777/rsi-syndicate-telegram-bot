from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.config import Settings
from src.core.utils import retry_async

LOGGER = logging.getLogger(__name__)


class CryptoPayClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get_me(self) -> dict[str, Any]:
        result = await self._request("getMe")
        return result if isinstance(result, dict) else {}

    async def create_invoice(
        self,
        *,
        amount: str,
        asset: str,
        description: str,
        payload: str,
        paid_btn_url: str | None = None,
    ) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
            "amount": amount,
            "asset": asset,
            "description": description,
            "payload": payload,
        }
        if paid_btn_url:
            request_payload["paid_btn_name"] = "openBot"
            request_payload["paid_btn_url"] = paid_btn_url
        result = await self._request("createInvoice", payload=request_payload)
        return result if isinstance(result, dict) else {}

    async def get_invoices(self, *, invoice_ids: list[int] | None = None) -> list[dict[str, Any]]:
        request_payload: dict[str, Any] = {}
        if invoice_ids:
            request_payload["invoice_ids"] = ",".join(str(item) for item in invoice_ids)
        result = await self._request("getInvoices", payload=request_payload if request_payload else None)
        if isinstance(result, dict):
            items = result.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    async def _request(
        self,
        method: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        session = await self._ensure_session()
        url = f"{self.settings.crypto_pay_api_base_url.rstrip('/')}/{method.lstrip('/')}"
        headers = {
            "Crypto-Pay-API-Token": self.settings.crypto_pay_api_token.strip(),
        }

        async def _send() -> Any:
            async with session.post(url, json=payload or {}, headers=headers) as response:
                response_text = await response.text()
                try:
                    response_json = await response.json(content_type=None)
                except Exception:
                    response_json = None
                if response.status >= 400:
                    raise RuntimeError(
                        f"Crypto Pay {method} failed: status={response.status}, response={response_text[:300]}"
                    )
                if not isinstance(response_json, dict):
                    raise RuntimeError(f"Crypto Pay {method} returned a non-JSON payload")
                if not response_json.get("ok", False):
                    raise RuntimeError(f"Crypto Pay {method} returned ok=false: {response_json}")
                return response_json.get("result")

        return await retry_async(
            _send,
            retries=max(self.settings.http_max_retries, 1),
            base_delay=1.0,
            operation_name=f"Crypto Pay {method}",
        )
