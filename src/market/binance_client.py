from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import pandas as pd

from src.core.config import Settings
from src.core.utils import interval_to_timedelta, retry_async, utc_now
from src.market.symbols import TickerStats, is_active_usdt_perpetual

LOGGER = logging.getLogger(__name__)
_BANNED_UNTIL_PATTERN = re.compile(r"banned until (\d+)")


class BinanceApiError(RuntimeError):
    def __init__(
        self,
        status: int,
        response_text: str,
        *,
        retry_after: float | None = None,
        non_retryable: bool = False,
    ) -> None:
        self.status = int(status)
        self.response_text = str(response_text or "")[:300]
        self.retry_after = retry_after
        self.non_retryable = non_retryable
        super().__init__(f"Binance error {self.status}: {self.response_text}")


class BinanceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._symbols_cache: tuple[list[str], Any] | None = None
        self._ticker_cache: tuple[dict[str, TickerStats], datetime, datetime] | None = None
        self._ticker_inflight: asyncio.Task[dict[str, TickerStats]] | None = None
        self._klines_cache: dict[
            tuple[str, str, int, int | None],
            tuple[pd.DataFrame, datetime, datetime],
        ] = {}
        self._klines_inflight: dict[
            tuple[str, str, int, int | None],
            asyncio.Task[pd.DataFrame],
        ] = {}
        self._rate_limited_until: datetime | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "rsi-syndicate-bot/1.0"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _parse_retry_after_seconds(
        self,
        response: aiohttp.ClientResponse,
        response_text: str,
    ) -> float | None:
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header:
            try:
                return max(float(retry_after_header), 0.0)
            except ValueError:
                pass
        banned_until = self._parse_banned_until(response_text)
        if banned_until is None:
            return None
        return max((banned_until - utc_now()).total_seconds(), 0.0)

    def _parse_banned_until(self, response_text: str) -> datetime | None:
        match = _BANNED_UNTIL_PATTERN.search(str(response_text or ""))
        if not match:
            return None
        raw_value = int(match.group(1))
        if raw_value > 10_000_000_000:
            raw_value /= 1000
        return datetime.fromtimestamp(raw_value, tz=timezone.utc)

    def _get_rate_limit_retry_after(self) -> float | None:
        if self._rate_limited_until is None:
            return None
        retry_after = (self._rate_limited_until - utc_now()).total_seconds()
        if retry_after <= 0:
            self._rate_limited_until = None
            return None
        return retry_after

    def _set_rate_limit_window(self, until: datetime | None, retry_after: float | None) -> None:
        if until is not None:
            if self._rate_limited_until is None or until > self._rate_limited_until:
                self._rate_limited_until = until
            return
        if retry_after is not None and retry_after > 0:
            candidate = utc_now() + timedelta(seconds=retry_after)
            if self._rate_limited_until is None or candidate > self._rate_limited_until:
                self._rate_limited_until = candidate

    def _is_rate_limited_error(self, exc: Exception) -> bool:
        return isinstance(exc, BinanceApiError) and exc.status in {418, 429}

    def _ticker_force_refresh_cooldown(self) -> timedelta:
        return timedelta(seconds=5)

    def _ticker_cache_ttl(self) -> timedelta:
        return timedelta(seconds=20)

    def _kline_cache_ttl(self, interval: str, *, has_end_time: bool) -> timedelta:
        if has_end_time:
            return timedelta(minutes=10)
        try:
            interval_seconds = interval_to_timedelta(interval).total_seconds()
        except ValueError:
            interval_seconds = 60.0
        ttl_seconds = min(max(interval_seconds * 0.2, 5.0), 30.0)
        return timedelta(seconds=ttl_seconds)

    def _get_cached_ticker_map(
        self,
        *,
        now: datetime,
        force_refresh: bool,
        allow_stale: bool = False,
    ) -> tuple[dict[str, TickerStats], float] | None:
        if self._ticker_cache is None:
            return None
        ticker_map, expires_at, refreshed_at = self._ticker_cache
        age_seconds = max((now - refreshed_at).total_seconds(), 0.0)
        if now < expires_at:
            return dict(ticker_map), age_seconds
        if allow_stale:
            return dict(ticker_map), age_seconds
        if force_refresh and age_seconds <= self._ticker_force_refresh_cooldown().total_seconds():
            return dict(ticker_map), age_seconds
        return None

    def _get_cached_klines(
        self,
        key: tuple[str, str, int, int | None],
        *,
        now: datetime,
        allow_stale: bool = False,
    ) -> tuple[pd.DataFrame, float] | None:
        cached = self._klines_cache.get(key)
        if cached is None:
            return None
        frame, expires_at, refreshed_at = cached
        age_seconds = max((now - refreshed_at).total_seconds(), 0.0)
        if now < expires_at or allow_stale:
            return frame.copy(), age_seconds
        return None

    def _build_api_error(
        self,
        response: aiohttp.ClientResponse,
        response_text: str,
    ) -> BinanceApiError:
        retry_after = self._parse_retry_after_seconds(response, response_text)
        banned_until = self._parse_banned_until(response_text)
        if response.status in {418, 429}:
            self._set_rate_limit_window(banned_until, retry_after if retry_after is not None else 3.0)
        return BinanceApiError(
            response.status,
            response_text,
            retry_after=retry_after,
            non_retryable=response.status == 418,
        )

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        session = await self._ensure_session()
        url = f"{self.settings.binance_rest_base_url.rstrip('/')}{path}"

        async def _request() -> Any:
            retry_after = self._get_rate_limit_retry_after()
            if retry_after is not None:
                raise BinanceApiError(
                    418,
                    f"Rate limit cooldown active until {self._rate_limited_until.isoformat()}",
                    retry_after=retry_after,
                    non_retryable=True,
                )
            async with session.get(url, params=params) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise self._build_api_error(response, text)
                payload = await response.json()
                self._rate_limited_until = None
                return payload

        return await retry_async(
            _request,
            retries=self.settings.http_max_retries,
            operation_name=f"GET {path}",
        )

    async def get_active_usdt_symbols(self, force_refresh: bool = False) -> list[str]:
        now = utc_now()
        if not force_refresh and self._symbols_cache is not None:
            symbols, expires_at = self._symbols_cache
            if now < expires_at:
                return symbols

        payload = await self._get_json("/fapi/v1/exchangeInfo")
        symbols = sorted(
            item["symbol"]
            for item in payload.get("symbols", [])
            if is_active_usdt_perpetual(item)
        )
        expires_at = now + timedelta(minutes=self.settings.symbols_refresh_minutes)
        self._symbols_cache = (symbols, expires_at)
        LOGGER.info("Loaded %s active USDT-M futures symbols", len(symbols))
        return symbols

    async def get_all_ticker_stats(self, force_refresh: bool = False) -> dict[str, TickerStats]:
        now = utc_now()
        cached = self._get_cached_ticker_map(now=now, force_refresh=force_refresh)
        if cached is not None:
            ticker_map, _ = cached
            return ticker_map
        if self._ticker_inflight is not None:
            return dict(await asyncio.shield(self._ticker_inflight))

        async def _load() -> dict[str, TickerStats]:
            try:
                payload = await self._get_json("/fapi/v1/ticker/24hr")
            except Exception as exc:
                if self._is_rate_limited_error(exc):
                    stale = self._get_cached_ticker_map(now=utc_now(), force_refresh=force_refresh, allow_stale=True)
                    if stale is not None:
                        ticker_map, age_seconds = stale
                        LOGGER.warning(
                            "Binance ticker stats rate-limited; using cached snapshot from %.1fs ago",
                            age_seconds,
                        )
                        return ticker_map
                raise

            ticker_map: dict[str, TickerStats] = {}
            for item in payload:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                ticker_map[symbol] = TickerStats(
                    symbol=symbol,
                    last_price=float(item.get("lastPrice", 0.0)),
                    price_change_percent=float(item["priceChangePercent"])
                    if item.get("priceChangePercent") is not None
                    else None,
                    volume=float(item["volume"]) if item.get("volume") is not None else None,
                    quote_volume=float(item["quoteVolume"]) if item.get("quoteVolume") is not None else None,
                )
            refreshed_at = utc_now()
            self._ticker_cache = (
                ticker_map,
                refreshed_at + self._ticker_cache_ttl(),
                refreshed_at,
            )
            return ticker_map

        task = asyncio.create_task(_load())
        self._ticker_inflight = task
        try:
            return dict(await asyncio.shield(task))
        finally:
            if self._ticker_inflight is task:
                self._ticker_inflight = None

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        *,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        end_time_ms: int | None = None
        if end_time is not None:
            end_time_ms = int(end_time.timestamp() * 1000)
            params["endTime"] = end_time_ms
        key = (str(symbol).upper(), interval, int(limit), end_time_ms)
        cached = self._get_cached_klines(key, now=utc_now())
        if cached is not None:
            frame, _ = cached
            return frame
        inflight = self._klines_inflight.get(key)
        if inflight is not None:
            return (await asyncio.shield(inflight)).copy()

        async def _load() -> pd.DataFrame:
            try:
                payload = await self._get_json(
                    "/fapi/v1/klines",
                    params=params,
                )
            except Exception as exc:
                if self._is_rate_limited_error(exc):
                    stale = self._get_cached_klines(key, now=utc_now(), allow_stale=True)
                    if stale is not None:
                        frame, age_seconds = stale
                        LOGGER.warning(
                            "Binance klines rate-limited for %s %s limit=%s; using cached candles from %.1fs ago",
                            symbol,
                            interval,
                            limit,
                            age_seconds,
                        )
                        return frame
                raise

            frame = pd.DataFrame(
                payload,
                columns=[
                    "open_time_ms",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time_ms",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base_volume",
                    "taker_buy_quote_volume",
                    "ignore",
                ],
            )
            for column in ("open", "high", "low", "close", "volume", "quote_asset_volume"):
                frame[column] = frame[column].astype(float)

            frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
            frame["close_time"] = pd.to_datetime(frame["close_time_ms"], unit="ms", utc=True)
            frame = frame.set_index("open_time")

            cutoff_ms = end_time_ms if end_time_ms is not None else int(utc_now().timestamp() * 1000)
            closed_frame = frame.loc[frame["close_time_ms"] < cutoff_ms].copy()
            if closed_frame.empty:
                raise RuntimeError(f"No closed klines returned for {symbol}")
            refreshed_at = utc_now()
            self._klines_cache[key] = (
                closed_frame.copy(),
                refreshed_at + self._kline_cache_ttl(interval, has_end_time=end_time_ms is not None),
                refreshed_at,
            )
            return closed_frame

        task = asyncio.create_task(_load())
        self._klines_inflight[key] = task
        try:
            return (await asyncio.shield(task)).copy()
        finally:
            if self._klines_inflight.get(key) is task:
                self._klines_inflight.pop(key, None)
