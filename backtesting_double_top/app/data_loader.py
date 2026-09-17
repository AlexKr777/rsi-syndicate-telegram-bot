from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from app.utils import interval_to_minutes


def open_read_only_connection(sqlite_path: str | Path) -> sqlite3.Connection:
    path = Path(sqlite_path).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def fetch_symbol_catalog(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT symbol, quote_asset, contract_type, status, onboard_date_ms, raw_json, updated_at_utc
        FROM symbol_catalog
        ORDER BY symbol
        """,
        connection,
    )


def available_symbols(connection: sqlite3.Connection, interval: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT symbol
        FROM futures_klines
        WHERE interval = ?
        ORDER BY symbol
        """,
        (interval,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def load_symbol_klines(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    filters = ["symbol = ?", "interval = ?", "is_closed = 1"]
    params: list[object] = [symbol, interval]
    if start_date:
        filters.append("open_time_utc >= ?")
        params.append(start_date)
    if end_date:
        filters.append("open_time_utc <= ?")
        params.append(end_date)
    query = f"""
        SELECT
            symbol,
            interval,
            open_time_ms,
            open_time_utc,
            close_time_ms,
            close_time_utc,
            open,
            high,
            low,
            close,
            volume,
            quote_volume,
            trades,
            taker_base_volume,
            taker_quote_volume,
            is_closed,
            collected_at_utc
        FROM futures_klines
        WHERE {' AND '.join(filters)}
        ORDER BY open_time_ms
    """
    frame = pd.read_sql_query(query, connection, params=params)
    if frame.empty:
        return frame
    frame["open_time"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time_utc"], utc=True)
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trades",
        "taker_base_volume",
        "taker_quote_volume",
    ]
    frame[numeric_columns] = frame[numeric_columns].astype(float)
    return frame


def iter_symbol_frames(config: dict, connection: sqlite3.Connection) -> Iterator[tuple[pd.Series, pd.DataFrame]]:
    catalog = fetch_symbol_catalog(connection).set_index("symbol", drop=False)
    symbols = config.get("data_source", {}).get("symbols") or []
    interval = str(config["data_source"]["interval"])
    selected = [str(symbol).upper() for symbol in symbols] if symbols else available_symbols(connection, interval)
    max_symbols = config.get("data_source", {}).get("max_symbols")
    if max_symbols:
        selected = selected[: int(max_symbols)]
    for symbol in selected:
        frame = load_symbol_klines(
            connection,
            symbol=symbol,
            interval=interval,
            start_date=config["data_source"].get("start_date"),
            end_date=config["data_source"].get("end_date"),
        )
        if frame.empty:
            continue
        metadata = catalog.loc[symbol] if symbol in catalog.index else pd.Series({"symbol": symbol})
        yield metadata, frame


def rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    values = close.astype(float).to_numpy()
    rsi = np.full(len(values), np.nan, dtype=float)
    if len(values) <= length:
        return pd.Series(rsi, index=close.index)
    deltas = np.diff(values)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)
    avg_gain = float(np.mean(gains[:length]))
    avg_loss = float(np.mean(losses[:length]))
    rsi[length] = rsi_from_averages(avg_gain, avg_loss)
    for index in range(length + 1, len(values)):
        gain = float(gains[index - 1])
        loss = float(losses[index - 1])
        avg_gain = ((avg_gain * (length - 1)) + gain) / length
        avg_loss = ((avg_loss * (length - 1)) + loss) / length
        rsi[index] = rsi_from_averages(avg_gain, avg_loss)
    return pd.Series(rsi, index=close.index)


def calculate_atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    values = true_range.astype(float).to_numpy()
    atr = np.full(len(values), np.nan, dtype=float)
    if len(values) < length:
        return pd.Series(atr, index=frame.index)
    avg_tr = float(np.mean(values[:length]))
    atr[length - 1] = avg_tr
    for index in range(length, len(values)):
        avg_tr = ((avg_tr * (length - 1)) + float(values[index])) / length
        atr[index] = avg_tr
    return pd.Series(atr, index=frame.index)


def compute_bot_like_score(frame: pd.DataFrame) -> pd.Series:
    rsi = frame["rsi"].fillna(50.0).astype(float)
    close = frame["close"].replace(0, np.nan).ffill().bfill().astype(float)
    ema20 = frame["ema20"].fillna(close).astype(float)
    ema50 = frame["ema50"].fillna(close).astype(float)
    volume_ratio = frame["volume_ratio"].fillna(1.0).astype(float)
    atr_pct = (frame["atr_pct"] / 100.0).fillna(0.0).astype(float)

    threshold_distance = np.maximum(rsi - 70.0, 0.0)
    trend_score = np.where((close > ema20) & (ema20 > ema50), 12.0, 5.0)
    stretch = np.maximum((close - ema20) / close.replace(0, np.nan), 0.0).fillna(0.0)
    extremeness_score = np.minimum(threshold_distance * 4.2, 42.0)
    volume_score = np.minimum(np.maximum(volume_ratio - 1.0, 0.0) * 16.0, 18.0)
    volatility_score = np.minimum(atr_pct * 600.0, 16.0)
    stretch_score = np.minimum(stretch * 4000.0, 14.0)
    total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score
    return total.fillna(0.0).round().clip(lower=0, upper=100).astype(int)


def enrich_indicators(frame: pd.DataFrame, *, interval: str, rsi_length: int) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["rsi"] = calculate_rsi(enriched["close"], length=rsi_length)
    enriched["atr"] = calculate_atr(enriched, length=rsi_length)
    enriched["atr_pct"] = (enriched["atr"] / enriched["close"] * 100.0).replace([np.inf, -np.inf], np.nan)
    enriched["ema20"] = enriched["close"].ewm(span=20, adjust=False).mean()
    enriched["ema50"] = enriched["close"].ewm(span=50, adjust=False).mean()
    enriched["avg_volume_20"] = enriched["volume"].rolling(20).mean()
    enriched["volume_ratio"] = (enriched["volume"] / enriched["avg_volume_20"]).replace([np.inf, -np.inf], np.nan)
    candles_24h = max(1, int((24 * 60) / interval_to_minutes(interval)))
    enriched["rolling_quote_volume_24h"] = enriched["quote_volume"].rolling(candles_24h).sum()
    enriched["body_pct"] = ((enriched["close"] - enriched["open"]).abs() / enriched["open"] * 100.0).replace([np.inf, -np.inf], np.nan)
    enriched["upper_wick_pct"] = (
        (enriched["high"] - enriched[["open", "close"]].max(axis=1)) / enriched["open"] * 100.0
    ).clip(lower=0.0)
    enriched["lower_wick_pct"] = (
        (enriched[["open", "close"]].min(axis=1) - enriched["low"]) / enriched["open"] * 100.0
    ).clip(lower=0.0)
    enriched["score"] = compute_bot_like_score(enriched)
    return enriched


def load_candles_for_trade(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    start_time_utc: str,
    end_time_utc: str,
) -> pd.DataFrame:
    query = """
        SELECT
            symbol,
            interval,
            open_time_utc,
            close_time_utc,
            open,
            high,
            low,
            close,
            volume,
            quote_volume
        FROM futures_klines
        WHERE symbol = ?
          AND interval = ?
          AND open_time_utc >= ?
          AND open_time_utc <= ?
        ORDER BY open_time_utc
    """
    frame = pd.read_sql_query(query, connection, params=[symbol, interval, start_time_utc, end_time_utc])
    if frame.empty:
        return frame
    frame["open_time"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time_utc"], utc=True)
    for column in ["open", "high", "low", "close", "volume", "quote_volume"]:
        frame[column] = frame[column].astype(float)
    return frame
