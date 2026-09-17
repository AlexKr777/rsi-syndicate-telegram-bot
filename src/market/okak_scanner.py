from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class OkakScanner(BaseStrategyScanner):
    strategy_key = "okak"

    _PREFERRED_VOLUME_LOW = 5_000_000.0
    _PREFERRED_VOLUME_MID = 20_000_000.0
    _PREFERRED_VOLUME_HIGH = 50_000_000.0
    _RSI_GATE = 76.0
    _SCORE_GATE = 90

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            return None
        current_row = enriched.iloc[-1]
        closed_rsi = float(current_row["rsi"])
        if closed_rsi < float(self.settings.rsi_overbought):
            return None

        signal = self._build_signal(symbol, enriched, ticker)
        if signal is None:
            return None

        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction=signal.direction,
            strategy_key=self.strategy_key,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=signal.candle_open_time,
        ):
            return None
        return signal

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
    ) -> AlertSignal | None:
        row = frame.iloc[-1]
        candle_close_time = row["close_time"].to_pydatetime()
        quote_volume = float(ticker.quote_volume) if ticker is not None and ticker.quote_volume else None
        day_volume = (
            float(ticker.quote_volume)
            if ticker is not None and ticker.quote_volume
            else float(ticker.volume)
            if ticker is not None and ticker.volume
            else None
        )
        effective_volume = float(quote_volume or day_volume or 0.0)
        score = self._score_signal(row, direction="overbought")
        closed_rsi = float(row["rsi"])

        checks = {
            "preferred_volume_band": self._matches_preferred_volume_band(effective_volume),
            "rsi_76_plus": closed_rsi >= self._RSI_GATE,
            "score_90_plus": score >= self._SCORE_GATE,
        }
        passed_checks = sum(1 for passed in checks.values() if passed)
        if passed_checks < 2:
            return None

        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        explanation = self._build_explanation(closed_rsi=closed_rsi, score=score, quote_volume=effective_volume, checks=checks)
        criteria_summary = ", ".join(
            label
            for label, passed in (
                ("volume 5-20M / 50M+", checks["preferred_volume_band"]),
                ("RSI 76+", checks["rsi_76_plus"]),
                ("score 90+", checks["score_90_plus"]),
            )
            if passed
        ) or "none"
        return AlertSignal(
            symbol=symbol,
            direction="overbought",
            timeframe=self.settings.scan_timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(row["close"]),
            rsi=closed_rsi,
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=day_volume,
            quote_volume=quote_volume,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]) if pd.notna(row["avg_volume_20"]) else 0.0,
            atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=score,
            explanation=explanation,
            metadata={
                "asset_class": "crypto",
                "strategy_key": self.strategy_key,
                "signal_model": "okak_rsi_overbought",
                "setup_direction": "short",
                "closed_rsi": closed_rsi,
                "live_rsi": live_rsi,
                "live_price": live_price,
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "okak_checks": checks,
                "okak_checks_passed": passed_checks,
                "okak_criteria_summary": criteria_summary,
                "okak_volume_band_label": self._volume_band_label(effective_volume),
                "setup_quality": "OKAK shortlist",
                "explanation_short": f"OKAK shortlist: {criteria_summary}",
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _matches_preferred_volume_band(self, quote_volume: float) -> bool:
        return (
            self._PREFERRED_VOLUME_LOW <= quote_volume <= self._PREFERRED_VOLUME_MID
            or quote_volume >= self._PREFERRED_VOLUME_HIGH
        )

    def _volume_band_label(self, quote_volume: float) -> str:
        if self._PREFERRED_VOLUME_LOW <= quote_volume <= self._PREFERRED_VOLUME_MID:
            return "5-20M"
        if quote_volume >= self._PREFERRED_VOLUME_HIGH:
            return "50M+"
        if quote_volume <= 0.0:
            return "n/a"
        return "other"

    def _build_explanation(
        self,
        *,
        closed_rsi: float,
        score: int,
        quote_volume: float,
        checks: dict[str, bool],
    ) -> str:
        criteria_summary = ", ".join(
            label
            for label, passed in (
                ("preferred volume band", checks["preferred_volume_band"]),
                ("RSI 76+", checks["rsi_76_plus"]),
                ("score 90+", checks["score_90_plus"]),
            )
            if passed
        ) or "none"
        volume_band = self._volume_band_label(quote_volume)
        return (
            f"OKAK is a stricter RSI overbought shortlist on {self.settings.scan_timeframe}. "
            f"This alert only passes when at least 2 of 3 filters line up: preferred volume band, RSI 76+, score 90+. "
            f"Current snapshot: RSI {closed_rsi:.2f}, score {score}/100, quote volume {quote_volume / 1_000_000:.2f}M ({volume_band}), matched: {criteria_summary}."
        )

    def _score_signal(self, row: pd.Series, *, direction: str) -> int:
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
