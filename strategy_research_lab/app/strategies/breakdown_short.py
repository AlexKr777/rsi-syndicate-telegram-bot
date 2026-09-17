from __future__ import annotations

from typing import Any

import pandas as pd


STRATEGY_NAME = "breakdown_short"


def generate_signals(frame: pd.DataFrame, metadata: pd.Series, config: dict[str, Any]) -> pd.DataFrame:
    params = config["strategies"][STRATEGY_NAME]
    lookback = int(params["breakdown_lookback_bars"])
    body_pct_min = float(params["body_pct_min"])
    volume_ratio_min = float(params["volume_ratio_min"])
    atr_pct_min = float(params["atr_pct_min"])
    close_distance_limit = float(params["max_close_distance_from_low_pct_of_range"])
    require_ema_trend = bool(params.get("require_ema_trend", True))
    min_liquidity = float(params.get("min_liquidity_24h", 0.0))

    signals: list[dict[str, Any]] = []
    rolling_low = frame["low"].rolling(lookback).min().shift(1)
    for idx in range(lookback, len(frame)):
        row = frame.iloc[idx]
        previous_low = rolling_low.iloc[idx]
        if pd.isna(previous_low):
            continue
        if require_ema_trend and not (float(row["close"]) < float(row["ema20"]) < float(row["ema50"])):
            continue
        if float(row.get("body_pct", 0.0) or 0.0) < body_pct_min:
            continue
        if float(row.get("volume_ratio", 0.0) or 0.0) < volume_ratio_min:
            continue
        if float(row.get("atr_pct", 0.0) or 0.0) < atr_pct_min:
            continue
        if float(row.get("rolling_quote_volume_24h", 0.0) or 0.0) < min_liquidity:
            continue
        if float(row["close"]) >= float(previous_low):
            continue
        close_position = float(row.get("close_position_in_range", 0.5) or 0.5)
        if close_position > close_distance_limit:
            continue
        signal_id = f"{row['symbol']}|{STRATEGY_NAME}|{row['open_time_utc']}"
        signals.append(
            {
                "strategy_name": STRATEGY_NAME,
                "signal_id": signal_id,
                "symbol": row["symbol"],
                "side": "SHORT",
                "signal_index": idx,
                "entry_index": idx,
                "signal_time": row["close_time_utc"],
                "entry_time": row["close_time_utc"],
                "entry_price": float(row["close"]),
                "signal_high": float(row["high"]),
                "signal_low": float(row["low"]),
                "lookback_low_price": float(previous_low),
                "structural_stop_anchor_price": float(row["high"]),
            }
        )
    return pd.DataFrame(signals)
