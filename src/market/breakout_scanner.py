from __future__ import annotations

import logging

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats

LOGGER = logging.getLogger(__name__)


class BreakoutScanner(BaseStrategyScanner):
    strategy_key = "breakout"
    _BREAKOUT_PRIORITY = ("daily", "asia", "consolidation", "local")

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 24:
            return None
        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        current_row, breakout_type, direction, trigger_level, range_high, range_low, session_anchor = candidate
        candle_open_time = current_row.name.to_pydatetime()
        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction=direction,
            strategy_key=self.strategy_key,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=candle_open_time,
        ):
            return None
        return self._build_signal(
            symbol,
            enriched,
            ticker,
            breakout_type=breakout_type,
            direction=direction,
            trigger_level=trigger_level,
            range_high=range_high,
            range_low=range_low,
            session_anchor=session_anchor,
        )

    def _detect_candidate(
        self,
        frame: pd.DataFrame,
    ) -> tuple[pd.Series, str, str, float, float, float, str] | None:
        current_row = frame.iloc[-1]
        previous_row = frame.iloc[-2]
        previous_rows = frame.iloc[:-1]
        candidates: dict[str, tuple[pd.Series, str, str, float, float, float, str]] = {}
        current_close = float(current_row["close"])
        previous_close = float(previous_row["close"])

        local_rows = previous_rows.tail(20)
        if len(local_rows) == 20:
            local_high = float(local_rows["high"].max())
            local_low = float(local_rows["low"].min())
            if previous_close <= local_high and current_close > local_high:
                candidates["local"] = (current_row, "local", "long", local_high, local_high, local_low, "lookback_20")
            elif previous_close >= local_low and current_close < local_low:
                candidates["local"] = (current_row, "local", "short", local_low, local_high, local_low, "lookback_20")

        consolidation_rows = previous_rows.tail(12)
        if len(consolidation_rows) == 12:
            box_high = float(consolidation_rows["high"].max())
            box_low = float(consolidation_rows["low"].min())
            range_width = box_high - box_low
            atr_gate = max(float(current_row["atr"]) * 2.5, float(current_row["close"]) * 0.002)
            if range_width <= atr_gate:
                if previous_close <= box_high and current_close > box_high:
                    candidates["consolidation"] = (
                        current_row,
                        "consolidation",
                        "long",
                        box_high,
                        box_high,
                        box_low,
                        "lookback_12",
                    )
                elif previous_close >= box_low and current_close < box_low:
                    candidates["consolidation"] = (
                        current_row,
                        "consolidation",
                        "short",
                        box_low,
                        box_high,
                        box_low,
                        "lookback_12",
                    )

        close_times = frame["close_time"].dt.tz_convert("UTC")
        current_close_time = pd.Timestamp(current_row["close_time"]).tz_convert("UTC")
        current_day = current_close_time.date()
        previous_day = (current_close_time - pd.Timedelta(days=1)).date()
        previous_day_rows = frame.loc[close_times.dt.date == previous_day]
        if not previous_day_rows.empty:
            previous_day_high = float(previous_day_rows["high"].max())
            previous_day_low = float(previous_day_rows["low"].min())
            if previous_close <= previous_day_high and current_close > previous_day_high:
                candidates["daily"] = (
                    current_row,
                    "daily",
                    "long",
                    previous_day_high,
                    previous_day_high,
                    previous_day_low,
                    "utc_previous_day",
                )
            elif previous_close >= previous_day_low and current_close < previous_day_low:
                candidates["daily"] = (
                    current_row,
                    "daily",
                    "short",
                    previous_day_low,
                    previous_day_high,
                    previous_day_low,
                    "utc_previous_day",
                )

        session_end = current_close_time.normalize() + pd.Timedelta(hours=8)
        if current_close_time > session_end:
            asia_rows = frame.loc[
                (close_times.dt.date == current_day)
                & (close_times <= session_end)
            ]
            if not asia_rows.empty:
                asia_high = float(asia_rows["high"].max())
                asia_low = float(asia_rows["low"].min())
                if previous_close <= asia_high and current_close > asia_high:
                    candidates["asia"] = (
                        current_row,
                        "asia",
                        "long",
                        asia_high,
                        asia_high,
                        asia_low,
                        "utc_asia_0000_0800",
                    )
                elif previous_close >= asia_low and current_close < asia_low:
                    candidates["asia"] = (
                        current_row,
                        "asia",
                        "short",
                        asia_low,
                        asia_high,
                        asia_low,
                        "utc_asia_0000_0800",
                    )

        for breakout_type in self._BREAKOUT_PRIORITY:
            if breakout_type in candidates:
                return candidates[breakout_type]
        return None

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        breakout_type: str,
        direction: str,
        trigger_level: float,
        range_high: float,
        range_low: float,
        session_anchor: str,
    ) -> AlertSignal:
        current_row = frame.iloc[-1]
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(current_row, breakout_type=breakout_type, direction=direction, trigger_level=trigger_level)
        explanation = self._build_explanation(
            breakout_type=breakout_type,
            direction=direction,
            trigger_level=trigger_level,
            range_high=range_high,
            range_low=range_low,
        )
        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=current_row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(current_row["close"]),
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
                "strategy_key": self.strategy_key,
                "signal_model": "breakout_confirmed",
                "breakout_type": breakout_type,
                "trigger_level": trigger_level,
                "range_high": range_high,
                "range_low": range_low,
                "session_anchor": session_anchor,
                "marker_price": trigger_level,
                "marker_candle_close_time": candle_close_time.isoformat(),
                "volume_ratio": float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else None,
                "live_price": live_price,
                "live_rsi": live_rsi,
                "signal_close_price": float(current_row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _build_explanation(
        self,
        *,
        breakout_type: str,
        direction: str,
        trigger_level: float,
        range_high: float,
        range_low: float,
    ) -> str:
        trigger_text = f"{trigger_level:,.4f}".rstrip("0").rstrip(".")
        range_text = f"{range_low:,.4f}-{range_high:,.4f}".replace(",", "")
        direction_text = "long" if direction == "long" else "short"
        return (
            f"{breakout_type.title()} breakout confirmed on {self.settings.scan_timeframe}: price closed "
            f"{'above' if direction == 'long' else 'below'} {trigger_text}. "
            f"Range reference {range_text}; {direction_text} scenario stays valid while that range is not reclaimed."
        )

    def _score_signal(
        self,
        row: pd.Series,
        *,
        breakout_type: str,
        direction: str,
        trigger_level: float,
    ) -> int:
        atr_anchor = max(float(row["atr"]), float(row["close"]) * 0.003, 1e-9)
        close = float(row["close"])
        breakout_distance = abs(close - trigger_level) / atr_anchor
        breakout_score = min(breakout_distance * 22.0, 36.0)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 18.0, 18.0)
        volatility_score = min(float(row["atr_pct"]) * 600.0, 12.0)
        subtype_bonus = {
            "daily": 16.0,
            "asia": 13.0,
            "consolidation": 11.0,
            "local": 8.0,
        }.get(breakout_type, 8.0)
        if direction == "long":
            trend_score = 12.0 if close > float(row["ema20"]) > float(row["ema50"]) else 6.0
        else:
            trend_score = 12.0 if close < float(row["ema20"]) < float(row["ema50"]) else 6.0
        total = breakout_score + volume_score + volatility_score + subtype_bonus + trend_score
        return int(max(0, min(round(total), 100)))
