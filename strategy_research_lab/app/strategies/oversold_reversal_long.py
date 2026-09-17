from __future__ import annotations

from typing import Any

import pandas as pd


STRATEGY_NAME = "oversold_reversal_long"


def generate_signals(frame: pd.DataFrame, metadata: pd.Series, config: dict[str, Any]) -> pd.DataFrame:
    params = config["strategies"][STRATEGY_NAME]
    rsi_threshold = float(params["rsi_threshold"])
    lower_wick_pct_min = float(params["lower_wick_pct_min"])
    body_pct_min = float(params["body_pct_min"])
    volume_ratio_min = float(params["volume_ratio_min"])
    min_liquidity = float(params["min_liquidity_24h"])
    min_atr_pct = float(params["min_atr_pct"])
    require_bullish_close = bool(params.get("require_bullish_close", True))

    signals: list[dict[str, Any]] = []
    for idx in range(1, len(frame)):
        row = frame.iloc[idx]
        if float(row.get("rsi", 100.0) or 100.0) > rsi_threshold:
            continue
        if float(row.get("lower_wick_pct", 0.0) or 0.0) < lower_wick_pct_min:
            continue
        if float(row.get("body_pct", 0.0) or 0.0) < body_pct_min:
            continue
        if float(row.get("volume_ratio", 0.0) or 0.0) < volume_ratio_min:
            continue
        if float(row.get("rolling_quote_volume_24h", 0.0) or 0.0) < min_liquidity:
            continue
        if float(row.get("atr_pct", 0.0) or 0.0) < min_atr_pct:
            continue
        if require_bullish_close and not (float(row["close"]) > float(row["open"])):
            continue
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
                "entry_price": float(row["close"]),
                "signal_high": float(row["high"]),
                "signal_low": float(row["low"]),
                "structural_stop_anchor_price": float(row["low"]),
            }
        )
    return pd.DataFrame(signals)
