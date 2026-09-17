from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from src.core.config import Settings
from src.core.utils import retry_async


LOGGER = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._cooldown_until_monotonic: float = 0.0
        self._cooldown_reason: str = ""

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.ollama_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def cooldown_remaining_seconds(self) -> float:
        remaining = self._cooldown_until_monotonic - time.monotonic()
        return max(0.0, remaining)

    def cooldown_reason(self) -> str:
        return self._cooldown_reason

    def is_cooling_down(self) -> bool:
        return self.cooldown_remaining_seconds() > 0

    async def generate(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        temperature: float = 0.7,
        timeout_seconds: float | None = None,
        retries: int | None = None,
        base_delay: float = 1.0,
    ) -> str:
        session = await self._ensure_session()
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"
        selected_model = (model_name or self.settings.ollama_model).strip()
        request_timeout = aiohttp.ClientTimeout(
            total=timeout_seconds if timeout_seconds is not None else self.settings.ollama_timeout_seconds
        )
        now_monotonic = time.monotonic()
        if now_monotonic < self._cooldown_until_monotonic:
            remaining = max(0.0, self._cooldown_until_monotonic - now_monotonic)
            reason = self._cooldown_reason or "recent Ollama failure"
            raise RuntimeError(
                f"Ollama temporarily cooled down for {remaining:.0f}s after {reason}"
            )

        async def _request() -> str:
            try:
                async with session.post(
                    url,
                    json={
                        "model": selected_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                        },
                    },
                    timeout=request_timeout,
                ) as response:
                    payload: dict[str, Any] = await response.json(content_type=None)
                    if response.status >= 400:
                        raise RuntimeError(f"Ollama returned {response.status}: {payload}")
                    return str(payload.get("response", "")).strip()
            except asyncio.TimeoutError as exc:
                self._activate_cooldown(f"timeout on model {selected_model}")
                raise RuntimeError(
                    f"Ollama request timed out for {self.settings.ollama_base_url} using model {selected_model}"
                ) from exc
            except aiohttp.ClientError as exc:
                self._activate_cooldown(f"connection error on model {selected_model}")
                raise RuntimeError(
                    f"Ollama request failed for {self.settings.ollama_base_url} using model "
                    f"{selected_model}: {exc}"
                ) from exc

        return await retry_async(
            _request,
            retries=retries if retries is not None else self.settings.http_max_retries,
            base_delay=base_delay,
            operation_name="Ollama generate",
        )

    def _activate_cooldown(self, reason: str) -> None:
        cooldown_seconds = max(1, int(self.settings.ollama_cooldown_seconds))
        until = time.monotonic() + cooldown_seconds
        if until <= self._cooldown_until_monotonic and reason == self._cooldown_reason:
            return
        self._cooldown_until_monotonic = until
        self._cooldown_reason = reason
        LOGGER.warning(
            "Ollama cooldown activated for %ss: %s",
            cooldown_seconds,
            reason,
        )
