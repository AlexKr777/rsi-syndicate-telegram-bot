from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.utils import realized_side_return_pct


def global_entry_filters_pass(entry_row: pd.Series, config: dict[str, Any]) -> bool:
    filters = config.get("filters", {})
    liquidity = float(entry_row.get("rolling_quote_volume_24h", 0.0) or 0.0)
    if liquidity < float(filters.get("min_liquidity_24h", 0.0)):
        return False

    allowed_map = {
        "allowed_rsi_buckets": "rsi_bucket",
        "allowed_atr_buckets": "atr_bucket",
        "allowed_volume_buckets": "volume_bucket",
        "allowed_liquidity_buckets": "liquidity_bucket",
        "allowed_score_buckets": "score_bucket",
    }
    for config_key, row_key in allowed_map.items():
        allowed = filters.get(config_key) or []
        if allowed and str(entry_row.get(row_key)) not in {str(item) for item in allowed}:
            return False
    return True


def build_trade_levels(signal_row: pd.Series, entry_row: pd.Series, scenario, side: str) -> tuple[float, float] | None:
    entry_price = float(signal_row["entry_price"])
    atr_value = float(entry_row.get("atr", np.nan)) if pd.notna(entry_row.get("atr")) else np.nan
    structure_anchor = signal_row.get("structural_stop_anchor_price")
    structure_anchor = float(structure_anchor) if structure_anchor is not None and pd.notna(structure_anchor) else None
    measured_move_price = signal_row.get("measured_move_price")
    measured_move_price = float(measured_move_price) if measured_move_price is not None and pd.notna(measured_move_price) else None

    if scenario.mode == "fixed_pct":
        stop_pct = float(scenario.stop_pct or 0.0)
        take_pct = float(scenario.take_pct or 0.0)
        if side == "LONG":
            return entry_price * (1.0 - stop_pct / 100.0), entry_price * (1.0 + take_pct / 100.0)
        return entry_price * (1.0 + stop_pct / 100.0), entry_price * (1.0 - take_pct / 100.0)

    if scenario.mode == "atr_r":
        if not np.isfinite(atr_value) or atr_value <= 0.0:
            return None
        risk_distance = atr_value * float(scenario.stop_atr_multiple or 0.0)
        if risk_distance <= 0.0:
            return None
        if side == "LONG":
            stop_price = entry_price - risk_distance
            take_price = entry_price + risk_distance * float(scenario.take_r_multiple or 0.0)
        else:
            stop_price = entry_price + risk_distance
            take_price = entry_price - risk_distance * float(scenario.take_r_multiple or 0.0)
        return stop_price, take_price

    if scenario.mode in {"structural_rr", "measured_move"}:
        if structure_anchor is None:
            return None
        atr_buffer = float(scenario.atr_buffer or 0.0)
        buffer_distance = (atr_value * atr_buffer) if np.isfinite(atr_value) and atr_value > 0.0 else 0.0
        if side == "LONG":
            stop_price = structure_anchor - buffer_distance
            risk_distance = entry_price - stop_price
        else:
            stop_price = structure_anchor + buffer_distance
            risk_distance = stop_price - entry_price
        if risk_distance <= 0.0:
            return None
        if scenario.mode == "structural_rr":
            if side == "LONG":
                take_price = entry_price + risk_distance * float(scenario.take_r_multiple or 0.0)
            else:
                take_price = entry_price - risk_distance * float(scenario.take_r_multiple or 0.0)
            return stop_price, take_price
        if side == "LONG":
            if measured_move_price is not None and measured_move_price > entry_price:
                take_price = measured_move_price
            else:
                take_price = entry_price + risk_distance * float(scenario.fallback_take_r_multiple or 2.0)
        else:
            if measured_move_price is not None and measured_move_price < entry_price:
                take_price = measured_move_price
            else:
                take_price = entry_price - risk_distance * float(scenario.fallback_take_r_multiple or 2.0)
        return stop_price, take_price

    return None


def _simulate_trade(
    frame: pd.DataFrame,
    *,
    entry_index: int,
    entry_price: float,
    stop_price: float,
    take_price: float,
    side: str,
    ambiguous_policy: str,
    interval_minutes: int,
) -> dict[str, Any]:
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

    exit_offset: int | None = None
    outcome = "OPEN"
    exit_price = None
    ambiguous_hit = False

    for offset, row in enumerate(future.itertuples(index=False), start=1):
        if side == "LONG":
            take_hit = float(row.high) >= take_price
            stop_hit = float(row.low) <= stop_price
        else:
            take_hit = float(row.low) <= take_price
            stop_hit = float(row.high) >= stop_price

        ambiguous_hit = take_hit and stop_hit
        if ambiguous_hit:
            exit_offset = offset
            if ambiguous_policy == "optimistic":
                outcome = "TAKE"
                exit_price = take_price
            elif ambiguous_policy == "skip_ambiguous":
                outcome = "AMBIGUOUS"
                exit_price = None
            else:
                outcome = "STOP"
                exit_price = stop_price
            break
        if take_hit:
            exit_offset = offset
            outcome = "TAKE"
            exit_price = take_price
            break
        if stop_hit:
            exit_offset = offset
            outcome = "STOP"
            exit_price = stop_price
            break

    evaluation_subset = future.iloc[:exit_offset] if exit_offset is not None else future
    if side == "LONG":
        max_favorable_price = float(evaluation_subset["high"].max())
        max_adverse_price = float(evaluation_subset["low"].min())
        mfe_pct = max((max_favorable_price - entry_price) / entry_price * 100.0, 0.0)
        mae_pct = max((entry_price - max_adverse_price) / entry_price * 100.0, 0.0)
    else:
        max_favorable_price = float(evaluation_subset["low"].min())
        max_adverse_price = float(evaluation_subset["high"].max())
        mfe_pct = max((entry_price - max_favorable_price) / entry_price * 100.0, 0.0)
        mae_pct = max((max_adverse_price - entry_price) / entry_price * 100.0, 0.0)

    if exit_offset is None:
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

    exit_row = future.iloc[exit_offset - 1]
    return {
        "outcome": outcome,
        "exit_time": exit_row["close_time_utc"],
        "exit_price": exit_price,
        "bars_to_outcome": exit_offset,
        "minutes_to_outcome": exit_offset * interval_minutes,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "max_adverse_price": max_adverse_price,
        "max_favorable_price": max_favorable_price,
        "ambiguous_hit": ambiguous_hit,
    }


def _effective_prices(side: str, entry_price: float, exit_price: float, slippage_pct_per_side: float) -> tuple[float, float]:
    slip = slippage_pct_per_side / 100.0
    if side == "LONG":
        effective_entry = entry_price * (1.0 + slip)
        effective_exit = exit_price * (1.0 - slip)
    else:
        effective_entry = entry_price * (1.0 - slip)
        effective_exit = exit_price * (1.0 + slip)
    return effective_entry, effective_exit


def _money_metrics(outcome: str, side: str, entry_price: float, exit_price: float | None, config: dict[str, Any]) -> dict[str, float | None]:
    model = config["money_model"]
    stake = float(model.get("stake_per_trade_usd", 100.0))
    leverage = float(model.get("leverage", 1.0))
    fee_pct_per_side = float(model.get("fee_pct_per_side", 0.0))
    slippage_pct_per_side = float(model.get("slippage_pct_per_side", 0.0))
    if outcome not in {"TAKE", "STOP"} or exit_price is None:
        return {
            "gross_return_pct": None,
            "return_pct": None,
            "gross_pnl_usd": 0.0,
            "net_pnl_usd": 0.0,
            "fees_usd": 0.0,
        }

    effective_entry, effective_exit = _effective_prices(side, entry_price, exit_price, slippage_pct_per_side)
    gross_return_pct = realized_side_return_pct(side, effective_entry, effective_exit) * leverage
    gross_pnl_usd = stake * gross_return_pct / 100.0
    fees_usd = stake * leverage * (fee_pct_per_side / 100.0) * 2.0
    net_pnl_usd = gross_pnl_usd - fees_usd
    return {
        "gross_return_pct": gross_return_pct,
        "return_pct": net_pnl_usd / stake * 100.0 if stake > 0 else None,
        "gross_pnl_usd": gross_pnl_usd,
        "net_pnl_usd": net_pnl_usd,
        "fees_usd": fees_usd,
    }


def build_trades_for_strategy(
    *,
    strategy_name: str,
    frame: pd.DataFrame,
    metadata: pd.Series,
    signals: pd.DataFrame,
    scenarios: dict[str, Any],
    config: dict[str, Any],
    interval_minutes: int,
) -> list[dict[str, Any]]:
    if signals.empty:
        return []
    trades: list[dict[str, Any]] = []
    ambiguous_policy = str(config["execution"]["ambiguous_candle_policy"]).lower()
    one_open_trade = bool(config["execution"].get("one_open_trade_per_symbol", True))
    enabled_scenarios = config["strategies"][strategy_name].get("enabled_scenarios", [])

    for scenario_name in enabled_scenarios:
        if scenario_name not in scenarios:
            continue
        scenario = scenarios[scenario_name]
        next_entry_index = 0
        for signal in signals.sort_values("entry_index").itertuples(index=False):
            entry_index = int(signal.entry_index)
            if one_open_trade and entry_index < next_entry_index:
                continue
            entry_row = frame.iloc[entry_index]
            if not global_entry_filters_pass(entry_row, config):
                continue
            levels = build_trade_levels(pd.Series(signal._asdict()), entry_row, scenario, str(signal.side))
            if levels is None:
                continue
            stop_price, take_price = levels
            outcome_payload = _simulate_trade(
                frame,
                entry_index=entry_index,
                entry_price=float(signal.entry_price),
                stop_price=stop_price,
                take_price=take_price,
                side=str(signal.side),
                ambiguous_policy=ambiguous_policy,
                interval_minutes=interval_minutes,
            )
            if one_open_trade:
                if outcome_payload["bars_to_outcome"] is None:
                    next_entry_index = len(frame) + 1
                else:
                    next_entry_index = entry_index + int(outcome_payload["bars_to_outcome"]) + 1
            money = _money_metrics(
                outcome_payload["outcome"],
                str(signal.side),
                float(signal.entry_price),
                outcome_payload["exit_price"],
                config,
            )
            signal_dict = signal._asdict()
            signal_dict.pop("Index", None)
            trade_id = f"{strategy_name}|{scenario.name}|{signal.signal_id}"
            trades.append(
                {
                    "trade_id": trade_id,
                    "strategy_name": strategy_name,
                    "scenario_name": scenario.name,
                    "scenario_mode": scenario.mode,
                    "symbol": signal.symbol,
                    "quote_asset": metadata.get("quote_asset"),
                    "contract_type": metadata.get("contract_type"),
                    "status": metadata.get("status"),
                    "onboard_date_ms": metadata.get("onboard_date_ms"),
                    "side": signal.side,
                    "signal_time": signal.signal_time,
                    "entry_time": signal.entry_time,
                    "entry_price": float(signal.entry_price),
                    "stop_price": float(stop_price),
                    "take_price": float(take_price),
                    "outcome": outcome_payload["outcome"],
                    "exit_time": outcome_payload["exit_time"],
                    "exit_price": outcome_payload["exit_price"],
                    "bars_to_outcome": outcome_payload["bars_to_outcome"],
                    "minutes_to_outcome": outcome_payload["minutes_to_outcome"],
                    "mfe_pct": outcome_payload["mfe_pct"],
                    "mae_pct": outcome_payload["mae_pct"],
                    "max_adverse_price": outcome_payload["max_adverse_price"],
                    "max_favorable_price": outcome_payload["max_favorable_price"],
                    "gross_pnl_usd": money["gross_pnl_usd"],
                    "net_pnl_usd": money["net_pnl_usd"],
                    "fees_usd": money["fees_usd"],
                    "gross_return_pct": money["gross_return_pct"],
                    "return_pct": money["return_pct"],
                    "rsi_at_entry": float(entry_row["rsi"]) if pd.notna(entry_row["rsi"]) else None,
                    "atr_at_entry": float(entry_row["atr"]) if pd.notna(entry_row["atr"]) else None,
                    "atr_pct_at_entry": float(entry_row["atr_pct"]) if pd.notna(entry_row["atr_pct"]) else None,
                    "volume_ratio_at_entry": float(entry_row["volume_ratio"]) if pd.notna(entry_row["volume_ratio"]) else None,
                    "ema20_at_entry": float(entry_row["ema20"]) if pd.notna(entry_row["ema20"]) else None,
                    "ema50_at_entry": float(entry_row["ema50"]) if pd.notna(entry_row["ema50"]) else None,
                    "liquidity_24h_at_entry": float(entry_row["rolling_quote_volume_24h"]) if pd.notna(entry_row["rolling_quote_volume_24h"]) else None,
                    "rsi_bucket_at_entry": entry_row.get("rsi_bucket"),
                    "atr_bucket_at_entry": entry_row.get("atr_bucket"),
                    "volume_bucket_at_entry": entry_row.get("volume_bucket"),
                    "liquidity_bucket_at_entry": entry_row.get("liquidity_bucket"),
                    "score_bucket_at_entry": entry_row.get("score_bucket"),
                    "bot_like_score_at_entry": int(entry_row["score"]) if pd.notna(entry_row["score"]) else None,
                    "ambiguous_hit": outcome_payload["ambiguous_hit"],
                    "ambiguous_policy": ambiguous_policy,
                    "interval": entry_row["interval"],
                    **signal_dict,
                }
            )
    return trades
