from __future__ import annotations

from typing import Any

import pandas as pd


STRATEGY_NAME = "trend_pullback_long"


def generate_signals(frame: pd.DataFrame, metadata: pd.Series, config: dict[str, Any]) -> pd.DataFrame:
    params = config["strategies"][STRATEGY_NAME]
    lookback = int(params["pullback_lookback_bars"])
    body_pct_min = float(params["body_pct_min"])
    volume_ratio_min = float(params["volume_ratio_min"])
    min_liquidity = float(params["min_liquidity_24h"])
    min_atr_pct = float(params["min_atr_pct"])
    rsi_min = float(params["rsi_min"])
    rsi_max = float(params["rsi_max"])
    zone_tolerance_pct = float(params["zone_tolerance_pct"]) / 100.0
    require_close_back_above_ema20 = bool(params.get("require_close_back_above_ema20", True))

    signals: list[dict[str, Any]] = []
    for idx in range(max(lookback, 1), len(frame)):
        row = frame.iloc[idx]
        if not (float(row["ema20"]) > float(row["ema50"])):
            continue
        if not (rsi_min <= float(row.get("rsi", 0.0) or 0.0) <= rsi_max):
            continue
        if float(row.get("body_pct", 0.0) or 0.0) < body_pct_min:
            continue
        if float(row.get("volume_ratio", 0.0) or 0.0) < volume_ratio_min:
            continue
        if float(row.get("rolling_quote_volume_24h", 0.0) or 0.0) < min_liquidity:
            continue
        if float(row.get("atr_pct", 0.0) or 0.0) < min_atr_pct:
            continue

        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        low_price = float(row["low"])
        close_price = float(row["close"])
        open_price = float(row["open"])
        in_pullback_zone = (low_price <= ema20 * (1.0 + zone_tolerance_pct)) and (low_price >= ema50 * (1.0 - zone_tolerance_pct))
        bullish_confirmation = close_price > open_price and close_price >= float(frame.iloc[idx - 1]["close"])
        if not in_pullback_zone or not bullish_confirmation:
            continue
        if require_close_back_above_ema20 and not (close_price >= ema20):
            continue

        swing_low = float(frame.iloc[max(0, idx - lookback) : idx + 1]["low"].min())
        signal_id = f"{row['symbol']}|{STRATEGY_NAME}|{row['open_time_utc']}"
        signals.append(
            {
                "strategy_name": STRATEGY_NAME,
                "signal_id": signal_id,
                "symbol": row["symbol"],
                "side": "LONG",
                "signal_index": idx,
                "entry_index": idx,
                "signal_time": row["close_time_utc"],
                "entry_time": row["close_time_utc"],
                "entry_price": close_price,
                "signal_high": float(row["high"]),
                "signal_low": low_price,
                "swing_low_price": swing_low,
                "structural_stop_anchor_price": swing_low,
            }
        )
    return pd.DataFrame(signals)
