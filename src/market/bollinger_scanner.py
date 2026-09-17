from __future__ import annotations

import asyncio
import logging

import pandas as pd

from src.core.config import Settings
from src.core.models import AlertSignal
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


class BollingerScanner:
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
        symbols = [
            symbol
            for symbol in await self.binance_client.get_active_usdt_symbols()
            if str(symbol or "").strip().upper() != self.settings.gold_symbol.strip().upper()
        ]
        ticker_map = await self.binance_client.get_all_ticker_stats()
        semaphore = asyncio.Semaphore(self.settings.scan_concurrency)

        async def _bounded_scan(symbol: str) -> AlertSignal | None:
            async with semaphore:
                return await self._scan_symbol(symbol, ticker_map.get(symbol))

        results = await asyncio.gather(
            *(_bounded_scan(symbol) for symbol in symbols),
            return_exceptions=True,
        )
        alerts: list[AlertSignal] = []
        errors = 0
        for result in results:
            if isinstance(result, Exception):
                errors += 1
                LOGGER.warning("Bollinger scan failed: %s", result)
                continue
            if result is not None:
                alerts.append(result)
        LOGGER.info(
            "Bollinger scan cycle complete: %s alerts, %s symbols, %s errors",
            len(alerts),
            len(symbols),
            errors,
        )
        return alerts

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 2:
            return None

        previous_row = enriched.iloc[-2]
        current_row = enriched.iloc[-1]
        direction = self._classify_reentry(previous_row, current_row)
        if direction is None:
            return None

        signal = self._build_signal(symbol, enriched, ticker, direction=direction)
        if signal is None:
            return None

        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction=direction,
            strategy_key="bollinger",
            timeframe=self.settings.scan_timeframe,
            candle_open_time=signal.candle_open_time,
        ):
            return None
        return signal

    def _classify_reentry(self, previous_row: pd.Series, current_row: pd.Series) -> str | None:
        previous_close = float(previous_row["close"])
        current_close = float(current_row["close"])
        previous_low = float(previous_row.get("low", previous_close))
        previous_high = float(previous_row.get("high", previous_close))
        current_low = float(current_row.get("low", current_close))
        current_high = float(current_row.get("high", current_close))
        previous_lower = float(previous_row["bb_lower"])
        previous_upper = float(previous_row["bb_upper"])
        current_lower = float(current_row["bb_lower"])
        current_upper = float(current_row["bb_upper"])
        previous_outside_lower = previous_close < previous_lower or previous_low < previous_lower
        previous_outside_upper = previous_close > previous_upper or previous_high > previous_upper
        current_lower_rejection = current_low < current_lower and current_close > current_lower and self._rejection_strength(current_row, direction="long") >= 0.5
        current_upper_rejection = current_high > current_upper and current_close < current_upper and self._rejection_strength(current_row, direction="short") >= 0.5
        if previous_outside_lower and current_close > current_lower:
            return "long"
        if previous_outside_upper and current_close < current_upper:
            return "short"
        if current_lower_rejection:
            return "long"
        if current_upper_rejection:
            return "short"
        return None

    def _rejection_strength(self, row: pd.Series, *, direction: str) -> float:
        candle_high = float(row.get("high", row["close"]))
        candle_low = float(row.get("low", row["close"]))
        candle_close = float(row["close"])
        candle_range = max(candle_high - candle_low, candle_close * 0.003, 1e-9)
        if direction == "long":
            return (candle_close - candle_low) / candle_range
        return (candle_high - candle_close) / candle_range

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
    ) -> AlertSignal | None:
        previous_row = frame.iloc[-2]
        current_row = frame.iloc[-1]
        current_close = float(current_row["close"])
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else current_close
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(previous_row, current_row, direction=direction)
        explanation = self._build_explanation(direction, timeframe=self.settings.scan_timeframe)

        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=current_row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=current_close,
            rsi=float(current_row["rsi"]),
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(current_row["volume"]),
            avg_volume_20=float(current_row["avg_volume_20"]) if pd.notna(current_row["avg_volume_20"]) else 0.0,
            atr=float(current_row["atr"]) if pd.notna(current_row["atr"]) else 0.0,
            atr_pct=float(current_row["atr_pct"]) if pd.notna(current_row["atr_pct"]) else 0.0,
            ema20=float(current_row["ema20"]),
            ema50=float(current_row["ema50"]),
            score=score,
            explanation=explanation,
            metadata={
                "asset_class": "crypto",
                "strategy_key": "bollinger",
                "signal_model": "bollinger_reentry",
                "bb_mid": float(current_row["bb_mid"]),
                "bb_upper": float(current_row["bb_upper"]),
                "bb_lower": float(current_row["bb_lower"]),
                "previous_close": float(previous_row["close"]),
                "previous_bb_upper": float(previous_row["bb_upper"]),
                "previous_bb_lower": float(previous_row["bb_lower"]),
                "volume_ratio": float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else None,
                "live_price": live_price,
                "live_rsi": live_rsi,
                "signal_close_price": current_close,
                "signal_candle_close_time": candle_close_time.isoformat(),
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
            },
        )

    def _build_explanation(self, direction: str, *, timeframe: str) -> str:
        if direction == "long":
            return (
                f"Price closed back inside the lower Bollinger Band on {timeframe} after trading outside it. "
                "This is a mean-reversion long setup, not proof of a lasting bottom."
            )
        return (
            f"Price closed back inside the upper Bollinger Band on {timeframe} after trading outside it. "
            "This is a mean-reversion short setup, not proof of a lasting top."
        )

    def _score_signal(self, previous_row: pd.Series, current_row: pd.Series, *, direction: str) -> int:
        band_width = max(float(current_row["bb_width"]), float(current_row["close"]) * 0.006, 1e-9)
        previous_close = float(previous_row["close"])
        current_close = float(current_row["close"])
        previous_low = float(previous_row.get("low", previous_close))
        previous_high = float(previous_row.get("high", previous_close))
        current_low = float(current_row.get("low", current_close))
        current_high = float(current_row.get("high", current_close))
        if direction == "long":
            exit_severity = max(
                float(previous_row["bb_lower"]) - min(previous_close, previous_low),
                float(current_row["bb_lower"]) - current_low,
                0.0,
            ) / band_width
            reentry_strength = max(float(current_row["close"]) - float(current_row["bb_lower"]), 0.0) / band_width
            stretch = max((float(current_row["ema20"]) - float(current_row["close"])) / float(current_row["close"]), 0.0)
            trend_score = 10 if current_row["close"] < current_row["ema20"] < current_row["ema50"] else 5
            rsi_confirmation = max(35.0 - min(float(previous_row["rsi"]), float(current_row["rsi"])), 0.0)
            rejection_score = self._rejection_strength(current_row, direction="long")
        else:
            exit_severity = max(
                max(previous_close, previous_high) - float(previous_row["bb_upper"]),
                current_high - float(current_row["bb_upper"]),
                0.0,
            ) / band_width
            reentry_strength = max(float(current_row["bb_upper"]) - float(current_row["close"]), 0.0) / band_width
            stretch = max((float(current_row["close"]) - float(current_row["ema20"])) / float(current_row["close"]), 0.0)
            trend_score = 10 if current_row["close"] > current_row["ema20"] > current_row["ema50"] else 5
            rsi_confirmation = max(max(float(previous_row["rsi"]), float(current_row["rsi"])) - 65.0, 0.0)
            rejection_score = self._rejection_strength(current_row, direction="short")

        exit_score = min(exit_severity * 24.0, 34.0)
        reentry_score = min(reentry_strength * 20.0, 22.0)
        rejection_component = min(rejection_score * 10.0, 10.0)
        rsi_component = min(rsi_confirmation * 1.3, 10.0)
        volume_ratio = float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16.0, 16.0)
        volatility_score = min(float(current_row["atr_pct"]) * 600.0, 12.0)
        stretch_score = min(stretch * 4500.0, 10.0)
        total = exit_score + reentry_score + rejection_component + rsi_component + volume_score + volatility_score + trend_score + stretch_score
        return int(max(0, min(round(total), 100)))
