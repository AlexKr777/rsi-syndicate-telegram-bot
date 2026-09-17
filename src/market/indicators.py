from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    values = close.astype(float).to_numpy()
    rsi = np.full(len(values), np.nan, dtype=float)
    if len(values) <= length:
        return pd.Series(rsi, index=close.index)

    delta = np.diff(values)
    gains = np.where(delta > 0.0, delta, 0.0)
    losses = np.where(delta < 0.0, -delta, 0.0)

    avg_gain = float(np.mean(gains[:length]))
    avg_loss = float(np.mean(losses[:length]))
    rsi[length] = _rsi_from_averages(avg_gain, avg_loss)

    for idx in range(length + 1, len(values)):
        gain = float(gains[idx - 1])
        loss = float(losses[idx - 1])
        avg_gain = ((avg_gain * (length - 1)) + gain) / length
        avg_loss = ((avg_loss * (length - 1)) + loss) / length
        rsi[idx] = _rsi_from_averages(avg_gain, avg_loss)

    return pd.Series(rsi, index=close.index)


def calculate_atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr_values = tr.astype(float).to_numpy()
    atr = np.full(len(tr_values), np.nan, dtype=float)
    if len(tr_values) < length:
        return pd.Series(atr, index=frame.index)

    avg_tr = float(np.mean(tr_values[:length]))
    atr[length - 1] = avg_tr

    for idx in range(length, len(tr_values)):
        avg_tr = ((avg_tr * (length - 1)) + float(tr_values[idx])) / length
        atr[idx] = avg_tr

    return pd.Series(atr, index=frame.index)


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_live_rsi(close: pd.Series, live_price: float, length: int = 14) -> float | None:
    if close.empty:
        return None
    last_index = close.index[-1]
    if hasattr(last_index, "tzinfo"):
        next_index = last_index + pd.Timedelta(microseconds=1)
    else:
        next_index = len(close)
    live_series = pd.concat(
        [
            close.astype(float),
            pd.Series([float(live_price)], index=[next_index], dtype=float),
        ]
    )
    live_rsi = calculate_rsi(live_series, length=length).iloc[-1]
    return float(live_rsi) if pd.notna(live_rsi) else None


def calculate_bollinger_bands(
    close: pd.Series,
    *,
    length: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    rolling_mean = close.rolling(length).mean()
    rolling_std = close.rolling(length).std(ddof=0)
    upper_band = rolling_mean + (rolling_std * num_std)
    lower_band = rolling_mean - (rolling_std * num_std)
    return rolling_mean, upper_band, lower_band


def calculate_intraday_vwap(frame: pd.DataFrame) -> pd.Series:
    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    weighted_price = typical_price * frame["volume"]
    cumulative_volume = frame["volume"].cumsum().replace(0.0, np.nan)
    return weighted_price.cumsum() / cumulative_volume


def enrich_klines(frame: pd.DataFrame, rsi_length: int) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["rsi"] = calculate_rsi(enriched["close"], length=rsi_length)
    enriched["atr"] = calculate_atr(enriched, length=rsi_length)
    enriched["atr_pct"] = (enriched["atr"] / enriched["close"]).fillna(0.0)
    enriched["ema20"] = enriched["close"].ewm(span=20, adjust=False).mean()
    enriched["ema50"] = enriched["close"].ewm(span=50, adjust=False).mean()
    bb_mid, bb_upper, bb_lower = calculate_bollinger_bands(enriched["close"], length=20, num_std=2.0)
    enriched["bb_mid"] = bb_mid
    enriched["bb_upper"] = bb_upper
    enriched["bb_lower"] = bb_lower
    enriched["bb_width"] = (bb_upper - bb_lower).fillna(0.0)
    enriched["avg_volume_20"] = enriched["volume"].rolling(20).mean()
    enriched["volume_ratio"] = (enriched["volume"] / enriched["avg_volume_20"]).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    return enriched
