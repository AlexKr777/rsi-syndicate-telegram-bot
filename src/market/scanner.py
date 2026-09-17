from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import pandas as pd

from src.core.config import Settings
from src.core.models import AlertSignal
from src.core.utils import utc_now
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


class MarketScanner:
    def __init__(
        self,
        settings: Settings,
        binance_client: BinanceClient,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.binance_client = binance_client
        self.repository = repository

    async def scan_once(self) -> list[AlertSignal]:
        symbols = await self.binance_client.get_active_usdt_symbols()
        ticker_map = await self.binance_client.get_all_ticker_stats()
        semaphore = asyncio.Semaphore(self.settings.scan_concurrency)

        async def _bounded_scan(symbol: str) -> AlertSignal | None:
            async with semaphore:
                ticker = ticker_map.get(symbol)
                return await self._scan_symbol(symbol, ticker)

        results = await asyncio.gather(
            *(_bounded_scan(symbol) for symbol in symbols),
            return_exceptions=True,
        )

        alerts: list[AlertSignal] = []
        errors = 0
        for result in results:
            if isinstance(result, Exception):
                errors += 1
                LOGGER.warning("Symbol scan failed: %s", result)
                continue
            if result is not None:
                alerts.append(result)

        LOGGER.info(
            "Scan cycle complete: %s alerts, %s symbols, %s errors",
            len(alerts),
            len(symbols),
            errors,
        )
        return alerts

    async def build_preview_signal(self, symbol: str = "BTCUSDT") -> AlertSignal:
        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=True)
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            raise RuntimeError(f"Unable to build preview signal for {symbol}")

        row = enriched.iloc[-1]
        if self._classify_zone(float(row["rsi"])) == "neutral":
            raise RuntimeError(f"No current closed RSI extreme available for {symbol}")

        preview_signal = self._build_signal(symbol, enriched, ticker_map.get(symbol), is_preview=True)
        if preview_signal is None:
            raise RuntimeError(f"Unable to build preview signal for {symbol}")
        return preview_signal

    async def build_preview_fallback_signal(self, symbol: str = "BTCUSDT") -> tuple[AlertSignal, pd.DataFrame]:
        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=True)
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            raise RuntimeError(f"Unable to build preview fallback signal for {symbol}")
        return self._build_preview_fallback(symbol, enriched, ticker_map.get(symbol)), enriched

    async def confirm_signal_sent(self, signal: AlertSignal, sent_at) -> None:
        state = await self.repository.get_symbol_state(signal.symbol)
        oversold_last_alert_at = state.oversold_last_alert_at if state else None
        overbought_last_alert_at = state.overbought_last_alert_at if state else None

        if signal.direction == "oversold":
            oversold_last_alert_at = sent_at
        else:
            overbought_last_alert_at = sent_at

        await self.repository.upsert_symbol_state(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            last_rsi=signal.rsi,
            zone=signal.direction,
            oversold_active=signal.direction == "oversold",
            overbought_active=signal.direction == "overbought",
            oversold_last_alert_at=oversold_last_alert_at,
            overbought_last_alert_at=overbought_last_alert_at,
            updated_at=sent_at,
        )

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            return None

        row = enriched.iloc[-1]
        rsi = float(row["rsi"])
        zone = self._classify_zone(rsi)
        now = utc_now()
        state = await self.repository.get_symbol_state(symbol)

        if zone == "neutral":
            await self.repository.upsert_symbol_state(
                symbol=symbol,
                timeframe=self.settings.scan_timeframe,
                last_rsi=rsi,
                zone="neutral",
                oversold_active=False,
                overbought_active=False,
                oversold_last_alert_at=state.oversold_last_alert_at if state else None,
                overbought_last_alert_at=state.overbought_last_alert_at if state else None,
                updated_at=now,
            )
            return None

        signal = self._build_signal(symbol, enriched, ticker)
        if signal is None:
            return None

        await self.repository.upsert_symbol_state(
            symbol=symbol,
            timeframe=self.settings.scan_timeframe,
            last_rsi=rsi,
            zone=zone,
            oversold_active=state.oversold_active if state else False,
            overbought_active=state.overbought_active if state else False,
            oversold_last_alert_at=state.oversold_last_alert_at if state else None,
            overbought_last_alert_at=state.overbought_last_alert_at if state else None,
            updated_at=now,
        )

        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction=zone,
            strategy_key=("gold" if symbol.strip().upper() == self.settings.gold_symbol.strip().upper() else "rsi"),
            timeframe=self.settings.scan_timeframe,
            candle_open_time=signal.candle_open_time,
        ):
            return None

        if state is None:
            return signal

        last_alert_at = (
            state.oversold_last_alert_at if zone == "oversold" else state.overbought_last_alert_at
        )
        is_active = state.oversold_active if zone == "oversold" else state.overbought_active
        cooldown_expired = (
            last_alert_at is None
            or (now - last_alert_at).total_seconds() >= self.settings.cooldown_seconds
        )
        return signal if (not is_active or cooldown_expired) else None

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        is_preview: bool = False,
    ) -> AlertSignal | None:
        row = frame.iloc[-1]
        rsi = float(row["rsi"])
        direction = self._classify_zone(rsi)
        if direction == "neutral" and not is_preview:
            return None

        if direction == "neutral":
            direction = "oversold" if rsi < 50 else "overbought"

        asset_class = "gold" if symbol.strip().upper() == self.settings.gold_symbol.strip().upper() else "crypto"
        strategy_key = "gold" if asset_class == "gold" else "rsi"
        explanation = self._build_explanation(direction, asset_class=asset_class, timeframe=self.settings.scan_timeframe)
        score = self._score_signal(row, direction)
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        candle_close_time = row["close_time"].to_pydatetime()
        LOGGER.debug(
            "RSI signal snapshot symbol=%s timeframe=%s mode=closed_trigger closed_rsi=%.2f live_rsi=%s candle_close=%s live_price=%.8f source=binance_futures_klines+wilder_rma",
            symbol,
            self.settings.scan_timeframe,
            rsi,
            f"{live_rsi:.2f}" if live_rsi is not None else "n/a",
            candle_close_time.isoformat(),
            live_price,
        )

        external_link_url = ""
        external_link_label = ""
        interactive_ai_enabled = True
        interactive_risk_enabled = True
        interactive_reason_enabled = True
        if asset_class == "gold":
            external_link_url = self.settings.gold_web_base_url
            external_link_label = "Open Gold Chart"
            interactive_ai_enabled = False
            interactive_risk_enabled = False
            interactive_reason_enabled = False

        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(row["close"]),
            rsi=rsi,
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]) if pd.notna(row["avg_volume_20"]) else 0.0,
            atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=score,
            explanation=explanation,
            metadata={
                "preview": is_preview,
                "asset_class": asset_class,
                "strategy_key": strategy_key,
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "rsi_mode": "closed_trigger",
                "rsi_source": "yahoo_gold_klines+wilder_rma" if asset_class == "gold" else "binance_futures_klines+wilder_rma",
                "closed_rsi": rsi,
                "live_rsi": live_rsi,
                "live_price": live_price,
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "external_link_label": external_link_label,
                "external_link_url": external_link_url,
                "interactive_ai_enabled": interactive_ai_enabled,
                "interactive_risk_enabled": interactive_risk_enabled,
                "interactive_reason_enabled": interactive_reason_enabled,
            },
        )

    def _build_preview_fallback(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
    ) -> AlertSignal:
        preview_signal = self._build_signal(symbol, frame, ticker, is_preview=True)
        assert preview_signal is not None
        return replace(
            preview_signal,
            explanation="Preview alert generated at startup so you can verify the Telegram formatting and chart design before live signals arrive.",
            metadata={**preview_signal.metadata, "sample_preview": True},
        )

    def _classify_zone(self, rsi: float) -> str:
        if rsi <= self.settings.rsi_oversold:
            return "oversold"
        if rsi >= self.settings.rsi_overbought:
            return "overbought"
        return "neutral"

    def _build_explanation(self, direction: str, *, asset_class: str, timeframe: str) -> str:
        market_label = "gold" if asset_class == "gold" else "the market"
        if direction == "oversold":
            return (
                f"RSI is below 30 on the {timeframe} chart. This can signal short-term downside exhaustion in {market_label}, "
                "but it is not proof of an immediate bounce."
            )
        return (
            f"RSI is above 70 on the {timeframe} chart. This can signal short-term upside exhaustion in {market_label}, "
            "but it is not proof of an immediate reversal."
        )

    def _score_signal(self, row: pd.Series, direction: str) -> int:
        if direction == "oversold":
            threshold_distance = max(self.settings.rsi_oversold - float(row["rsi"]), 0.0)
            trend_score = 12 if row["close"] < row["ema20"] < row["ema50"] else 5
            stretch = max((row["ema20"] - row["close"]) / row["close"], 0.0)
        else:
            threshold_distance = max(float(row["rsi"]) - self.settings.rsi_overbought, 0.0)
            trend_score = 12 if row["close"] > row["ema20"] > row["ema50"] else 5
            stretch = max((row["close"] - row["ema20"]) / row["close"], 0.0)

        extremeness_score = min(threshold_distance * 4.2, 42)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16, 18)
        volatility_score = min(float(row["atr_pct"]) * 600, 16)
        stretch_score = min(stretch * 4000, 14)
        total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score
        return int(max(0, min(round(total), 100)))
