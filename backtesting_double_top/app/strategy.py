from __future__ import annotations

import pandas as pd

from app.utils import atr_bucket, liquidity_bucket, short_rsi_bucket, volume_ratio_bucket


def entry_filters_pass(entry_row: pd.Series, config: dict) -> bool:
    filters = config["filters"]
    volume_ratio = float(entry_row.get("volume_ratio", 0.0) or 0.0)
    rsi = float(entry_row.get("rsi", 0.0) or 0.0)
    atr_pct = float(entry_row.get("atr_pct", 0.0) or 0.0)
    liquidity = float(entry_row.get("rolling_quote_volume_24h", 0.0) or 0.0)

    if bool(filters.get("use_volume_filter")) and volume_ratio < float(filters["min_volume_ratio"]):
        return False
    if bool(filters.get("use_rsi_filter")) and rsi < float(filters["min_rsi_for_short"]):
        return False
    if atr_pct < float(filters.get("atr_filter_min", 0.0)):
        return False
    if liquidity < float(filters.get("liquidity_filter_min", 0.0)):
        return False
    if bool(filters.get("use_ema_filter")):
        if bool(filters.get("require_close_below_ema20")) and not (float(entry_row["close"]) < float(entry_row["ema20"])):
            return False
        if bool(filters.get("require_ema20_above_ema50")) and not (float(entry_row["ema20"]) > float(entry_row["ema50"])):
            return False
    return True


def _simulate_short_trade(
    frame: pd.DataFrame,
    *,
    entry_index: int,
    entry_price: float,
    stop_pct: float,
    take_pct: float,
    ambiguous_policy: str,
    interval_minutes: int,
) -> dict:
    stop_price = entry_price * (1.0 + stop_pct / 100.0)
    take_price = entry_price * (1.0 - take_pct / 100.0)
    future = frame.iloc[entry_index + 1 :].copy()
    if future.empty:
        return {
            "outcome": "OPEN",
            "exit_time": None,
            "exit_price": None,
            "bars_to_outcome": None,
            "minutes_to_outcome": None,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "max_adverse_price": entry_price,
            "max_favorable_price": entry_price,
            "ambiguous_hit": False,
        }

    max_favorable_price = float(future["low"].min())
    max_adverse_price = float(future["high"].max())
    mfe_pct = max((entry_price - max_favorable_price) / entry_price * 100.0, 0.0)
    mae_pct = max((max_adverse_price - entry_price) / entry_price * 100.0, 0.0)

    for offset, row in enumerate(future.itertuples(index=False), start=1):
        take_hit = float(row.low) <= take_price
        stop_hit = float(row.high) >= stop_price
        ambiguous_hit = take_hit and stop_hit
        outcome = None
        exit_price = None
        if ambiguous_hit:
            if ambiguous_policy == "optimistic":
                outcome = "TAKE"
                exit_price = take_price
            elif ambiguous_policy == "skip_ambiguous":
                outcome = "AMBIGUOUS"
            else:
                outcome = "STOP"
                exit_price = stop_price
        elif take_hit:
            outcome = "TAKE"
            exit_price = take_price
        elif stop_hit:
            outcome = "STOP"
            exit_price = stop_price
        if outcome is None:
            continue
        return {
            "outcome": outcome,
            "exit_time": row.close_time_utc,
            "exit_price": exit_price,
            "bars_to_outcome": offset,
            "minutes_to_outcome": offset * interval_minutes,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "max_adverse_price": max_adverse_price,
            "max_favorable_price": max_favorable_price,
            "ambiguous_hit": ambiguous_hit,
        }

    return {
        "outcome": "OPEN",
        "exit_time": None,
        "exit_price": None,
        "bars_to_outcome": None,
        "minutes_to_outcome": None,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "max_adverse_price": max_adverse_price,
        "max_favorable_price": max_favorable_price,
        "ambiguous_hit": False,
    }


def build_trade_rows(
    *,
    frame: pd.DataFrame,
    symbol_metadata: pd.Series,
    patterns: pd.DataFrame,
    scenario_name: str,
    stop_pct: float,
    take_pct: float,
    config: dict,
    interval_minutes: int,
) -> list[dict]:
    trades: list[dict] = []
    ambiguous_policy = str(config["strategy"]["ambiguous_candle_policy"]).lower()
    one_open_trade = bool(config["strategy"].get("one_open_trade_per_symbol", True))
    next_entry_index = 0

    for pattern in patterns.itertuples(index=False):
        entry_index = int(pattern.entry_index)
        if one_open_trade and entry_index < next_entry_index:
            continue
        entry_row = frame.iloc[entry_index]
        if not entry_filters_pass(entry_row, config):
            continue
        entry_price = float(entry_row["close"])
        outcome_payload = _simulate_short_trade(
            frame,
            entry_index=entry_index,
            entry_price=entry_price,
            stop_pct=stop_pct,
            take_pct=take_pct,
            ambiguous_policy=ambiguous_policy,
            interval_minutes=interval_minutes,
        )
        if one_open_trade:
            if outcome_payload["bars_to_outcome"] is None:
                next_entry_index = len(frame) + 1
            else:
                next_entry_index = entry_index + int(outcome_payload["bars_to_outcome"]) + 1
        realized_return_pct = None
        if outcome_payload["outcome"] == "TAKE":
            realized_return_pct = take_pct
        elif outcome_payload["outcome"] == "STOP":
            realized_return_pct = -stop_pct
        trade_id = f"{scenario_name}|{pattern.pattern_id}"
        trades.append(
            {
                "trade_id": trade_id,
                "scenario_name": scenario_name,
                "symbol": entry_row["symbol"],
                "quote_asset": symbol_metadata.get("quote_asset"),
                "contract_type": symbol_metadata.get("contract_type"),
                "status": symbol_metadata.get("status"),
                "onboard_date_ms": symbol_metadata.get("onboard_date_ms"),
                "pattern_id": pattern.pattern_id,
                "first_peak_time": pattern.first_peak_time,
                "second_peak_time": pattern.second_peak_time,
                "valley_time": pattern.valley_time,
                "first_peak_price": float(pattern.first_peak_price),
                "second_peak_price": float(pattern.second_peak_price),
                "neckline_price": float(pattern.neckline_price),
                "breakout_time": pattern.breakout_time,
                "entry_time": pattern.entry_time,
                "entry_price": entry_price,
                "stop_pct": stop_pct,
                "take_pct": take_pct,
                "stop_price": entry_price * (1.0 + stop_pct / 100.0),
                "take_price": entry_price * (1.0 - take_pct / 100.0),
                "outcome": outcome_payload["outcome"],
                "exit_time": outcome_payload["exit_time"],
                "exit_price": outcome_payload["exit_price"],
                "bars_to_outcome": outcome_payload["bars_to_outcome"],
                "minutes_to_outcome": outcome_payload["minutes_to_outcome"],
                "mfe_pct": outcome_payload["mfe_pct"],
                "mae_pct": outcome_payload["mae_pct"],
                "max_adverse_price": outcome_payload["max_adverse_price"],
                "max_favorable_price": outcome_payload["max_favorable_price"],
                "peak_similarity_pct": float(pattern.peak_similarity_pct),
                "valley_depth_pct": float(pattern.valley_depth_pct),
                "rsi_at_entry": float(entry_row["rsi"]) if pd.notna(entry_row["rsi"]) else None,
                "score_at_entry": int(entry_row["score"]) if pd.notna(entry_row["score"]) else None,
                "atr_pct_at_entry": float(entry_row["atr_pct"]) if pd.notna(entry_row["atr_pct"]) else None,
                "volume_ratio_at_entry": float(entry_row["volume_ratio"]) if pd.notna(entry_row["volume_ratio"]) else None,
                "ema20_at_entry": float(entry_row["ema20"]) if pd.notna(entry_row["ema20"]) else None,
                "ema50_at_entry": float(entry_row["ema50"]) if pd.notna(entry_row["ema50"]) else None,
                "quote_volume_24h_at_entry": float(entry_row["rolling_quote_volume_24h"]) if pd.notna(entry_row["rolling_quote_volume_24h"]) else None,
                "rsi_bucket": short_rsi_bucket(entry_row.get("rsi")),
                "atr_bucket": atr_bucket(entry_row.get("atr_pct")),
                "volume_bucket": volume_ratio_bucket(entry_row.get("volume_ratio")),
                "liquidity_bucket": liquidity_bucket(entry_row.get("rolling_quote_volume_24h")),
                "realized_return_pct": realized_return_pct,
                "ambiguous_hit": outcome_payload["ambiguous_hit"],
                "ambiguous_policy": ambiguous_policy,
                "entry_index": entry_index,
                "first_peak_index": int(pattern.first_peak_index),
                "second_peak_index": int(pattern.second_peak_index),
                "valley_index": int(pattern.valley_index),
                "breakout_index": int(pattern.breakout_index),
                "interval": str(entry_row["interval"]),
            }
        )
    return trades
