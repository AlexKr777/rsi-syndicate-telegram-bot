from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import pandas as pd

from src.core.config import Settings
from src.core.utils import retry_async, utc_now
from src.market.symbols import TickerStats

LOGGER = logging.getLogger(__name__)


class YahooGoldClient:
    _INTERVAL_ALIASES = {
        "1m": "1m",
        "2m": "2m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "60m": "60m",
        "90m": "90m",
        "1d": "1d",
    }

    _INTERVAL_SECONDS = {
        "1m": 60,
        "2m": 120,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "60m": 3600,
        "90m": 5400,
        "1d": 86400,
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._ticker_cache: tuple[TickerStats, datetime] | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self.settings.gold_data_user_agent},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _provider_symbol(self) -> str:
        return self.settings.gold_provider_symbol.strip() or "GC=F"

    def _display_symbol(self) -> str:
        return self.settings.gold_symbol.strip() or "XAUUSD"

    def _normalize_interval(self, interval: str) -> str:
        normalized = str(interval or "").strip().lower()
        if normalized not in self._INTERVAL_ALIASES:
            raise RuntimeError(f"Unsupported gold timeframe: {interval}")
        return normalized

    def _interval_seconds(self, interval: str) -> int:
        normalized = self._normalize_interval(interval)
        return self._INTERVAL_SECONDS[normalized]

    def _chart_url(self) -> str:
        base = self.settings.gold_chart_api_base_url.rstrip("/")
        return f"{base}/{self._provider_symbol()}"

    def _fallback_range(self, interval: str, limit: int) -> str:
        normalized = self._normalize_interval(interval)
        desired_bars = max(int(limit) + 40, 180)
        if normalized in {"1m", "2m", "5m"}:
            return "5d" if desired_bars <= 1200 else "1mo"
        if normalized in {"15m", "30m"}:
            return "5d" if desired_bars <= 320 else "1mo"
        if normalized in {"1h", "60m"}:
            return "1mo" if desired_bars <= 620 else "3mo"
        if normalized == "90m":
            return "3mo"
        return "6mo" if desired_bars <= 180 else "1y"

    def _fetch_limit_candidates(self, limit: int) -> tuple[int, ...]:
        base_limit = max(int(limit), 1)
        candidates = [
            base_limit,
            max(base_limit * 3, base_limit + 120),
            max(base_limit * 6, base_limit + 240),
        ]
        deduped: list[int] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return tuple(deduped)

    async def _fetch_chart(
        self,
        *,
        interval: str,
        limit: int,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        provider_interval = self._INTERVAL_ALIASES[self._normalize_interval(interval)]
        interval_seconds = self._interval_seconds(interval)
        effective_end = end_time or utc_now()
        period2 = int(effective_end.timestamp())
        # Keep a small cushion so timeframe switches and follow-up snapshots still have enough bars.
        lookback_bars = max(int(limit) + 40, 180)
        period1 = period2 - (interval_seconds * lookback_bars)

        session = await self._ensure_session()
        params = {
            "interval": provider_interval,
            "period1": str(period1),
            "period2": str(period2),
            "includePrePost": "false",
            "events": "div,splits",
        }
        url = self._chart_url()

        async def _request(request_params: dict[str, str]) -> dict[str, Any]:
            async with session.get(url, params=request_params) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"Yahoo Gold error {response.status}: {text[:300]}")
                payload = await response.json()
                chart = payload.get("chart", {})
                results = chart.get("result") or []
                if not results:
                    error = chart.get("error")
                    raise RuntimeError(f"Yahoo Gold chart returned no result: {error}")
                return results[0]

        async def _fetch_with_params(request_params: dict[str, str], operation_name: str) -> dict[str, Any]:
            return await retry_async(
                lambda: _request(request_params),
                retries=self.settings.http_max_retries,
                operation_name=operation_name,
            )

        result = await _fetch_with_params(params, f"Yahoo Gold chart {provider_interval}")
        if result.get("timestamp"):
            return result

        if end_time is None:
            fallback_params = {
                "interval": provider_interval,
                "range": self._fallback_range(interval, limit),
                "includePrePost": "false",
                "events": "div,splits",
            }
            fallback_result = await _fetch_with_params(
                fallback_params,
                f"Yahoo Gold chart {provider_interval} fallback range",
            )
            if fallback_result.get("timestamp"):
                return fallback_result

        meta = result.get("meta") or {}
        market_time = meta.get("regularMarketTime")
        if isinstance(market_time, (int, float)) and market_time > 0:
            anchored_period2 = int(market_time)
            anchored_period1 = anchored_period2 - (interval_seconds * lookback_bars)
            anchored_params = {
                "interval": provider_interval,
                "period1": str(anchored_period1),
                "period2": str(anchored_period2),
                "includePrePost": "false",
                "events": "div,splits",
            }
            anchored_result = await _fetch_with_params(
                anchored_params,
                f"Yahoo Gold chart {provider_interval} anchored",
            )
            if anchored_result.get("timestamp"):
                return anchored_result

        return result

    def _frame_from_chart_result(
        self,
        result: dict[str, Any],
        *,
        interval: str,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        if not timestamps:
            raise RuntimeError("Yahoo Gold returned no timestamps")

        interval_seconds = self._interval_seconds(interval)
        rows: list[dict[str, Any]] = []
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        for idx, ts in enumerate(timestamps):
            close = closes[idx] if idx < len(closes) else None
            open_ = opens[idx] if idx < len(opens) else None
            high = highs[idx] if idx < len(highs) else None
            low = lows[idx] if idx < len(lows) else None
            volume = volumes[idx] if idx < len(volumes) else 0.0
            if close is None or open_ is None or high is None or low is None:
                continue
            open_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            close_time = open_time + timedelta(seconds=interval_seconds)
            rows.append(
                {
                    "open_time": open_time,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume or 0.0),
                    "quote_asset_volume": float(volume or 0.0) * float(close),
                    "close_time": close_time,
                    "close_time_ms": int(close_time.timestamp() * 1000),
                }
            )

        if not rows:
            raise RuntimeError("Yahoo Gold returned no complete OHLC rows")

        frame = pd.DataFrame(rows).set_index("open_time")
        cutoff = end_time or utc_now()
        closed_frame = frame.loc[frame["close_time"] < cutoff].copy()
        if closed_frame.empty:
            raise RuntimeError(f"No closed gold klines returned for {self._display_symbol()}")
        return closed_frame

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        *,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        if symbol.strip().upper() != self._display_symbol().upper():
            raise RuntimeError(f"YahooGoldClient does not serve symbol {symbol}")
        requested_limits = self._fetch_limit_candidates(limit)
        frame: pd.DataFrame | None = None
        for attempt, requested_limit in enumerate(requested_limits, start=1):
            result = await self._fetch_chart(interval=interval, limit=requested_limit, end_time=end_time)
            frame = self._frame_from_chart_result(result, interval=interval, end_time=end_time)
            if len(frame) >= limit:
                return frame.tail(limit).copy()
            if attempt < len(requested_limits):
                LOGGER.info(
                    "Gold klines underfilled for %s interval=%s requested_limit=%s closed_bars=%s target=%s; widening lookback",
                    self._display_symbol(),
                    interval,
                    requested_limit,
                    len(frame),
                    limit,
                )

        assert frame is not None
        return frame.tail(limit).copy()

    async def get_ticker_stats(self, force_refresh: bool = False) -> TickerStats:
        now = utc_now()
        if not force_refresh and self._ticker_cache is not None:
            cached, expires_at = self._ticker_cache
            if now < expires_at:
                return cached

        result = await self._fetch_chart(interval="15m", limit=160)
        frame = self._frame_from_chart_result(result, interval="15m")
        meta = result.get("meta") or {}
        last_price = float(meta.get("regularMarketPrice") or frame["close"].iloc[-1])
        previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        price_change_percent = None
        if previous_close not in (None, 0, 0.0):
            price_change_percent = ((last_price - float(previous_close)) / float(previous_close)) * 100.0
        volume = float(meta.get("regularMarketVolume") or frame["volume"].tail(96).sum() or 0.0)
        ticker = TickerStats(
            symbol=self._display_symbol(),
            last_price=last_price,
            price_change_percent=price_change_percent,
            volume=volume,
            quote_volume=volume * last_price if volume else None,
        )
        self._ticker_cache = (ticker, now + timedelta(seconds=20))
        return ticker
