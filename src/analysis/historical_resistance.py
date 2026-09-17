from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.market.indicators import enrich_klines


@dataclass(frozen=True, slots=True)
class HistoricalResistanceTouch:
    timeframe: str
    price: float
    impulse_pct: float
    rejection_pct: float
    tolerance: float
    timeframe_weight: float
    touched_at: datetime


@dataclass(frozen=True, slots=True)
class HistoricalResistanceZone:
    zone_low: float
    zone_high: float
    zone_price: float
    distance_pct: float
    touch_count: int
    strong_rejections: int
    avg_rejection_pct: float
    avg_impulse_pct: float
    confidence: int
    quality: str
    timeframes: tuple[str, ...]
    latest_touch_at: datetime | None
    highest_peak_price: float | None
    highest_peak_timeframe: str | None
    highest_peak_distance_pct: float | None
    highest_peak_touched_at: datetime | None


@dataclass(frozen=True, slots=True)
class HistoricalResistanceAnalysis:
    zone: HistoricalResistanceZone | None
    highest_peak_touch: HistoricalResistanceTouch | None


_TIMEFRAME_CONFIG: dict[str, dict[str, float]] = {
    "1h": {
        "pivot_window": 2,
        "impulse_lookback": 6,
        "rejection_lookahead": 8,
        "min_impulse_pct": 2.4,
        "min_rejection_pct": 1.8,
        "min_close_break_atr": 0.75,
        "zone_pct": 0.0028,
        "weight": 1.0,
    },
    "4h": {
        "pivot_window": 2,
        "impulse_lookback": 5,
        "rejection_lookahead": 6,
        "min_impulse_pct": 3.0,
        "min_rejection_pct": 2.4,
        "min_close_break_atr": 0.85,
        "zone_pct": 0.0035,
        "weight": 1.4,
    },
}
_TIMEFRAME_ORDER = {"4h": 0, "1h": 1}


def find_historical_resistance_zone(
    frames_by_timeframe: dict[str, pd.DataFrame],
    *,
    current_price: float,
    rsi_length: int,
) -> HistoricalResistanceZone | None:
    return analyze_historical_resistance(
        frames_by_timeframe,
        current_price=current_price,
        rsi_length=rsi_length,
    ).zone


def analyze_historical_resistance(
    frames_by_timeframe: dict[str, pd.DataFrame],
    *,
    current_price: float,
    rsi_length: int,
) -> HistoricalResistanceAnalysis:
    if current_price <= 0.0:
        return HistoricalResistanceAnalysis(zone=None, highest_peak_touch=None)

    prepared_frames: dict[str, pd.DataFrame] = {}
    current_atr: float | None = None
    anchor_time: datetime | None = None
    for timeframe, raw_frame in frames_by_timeframe.items():
        config = _TIMEFRAME_CONFIG.get(timeframe)
        if config is None or raw_frame.empty:
            continue
        enriched = enrich_klines(raw_frame, rsi_length).dropna().copy()
        min_rows = int(config["impulse_lookback"] + config["rejection_lookahead"] + (config["pivot_window"] * 2) + 8)
        if len(enriched) < min_rows:
            continue
        prepared_frames[timeframe] = enriched
        latest_row = enriched.iloc[-1]
        latest_atr = float(latest_row["atr"]) if pd.notna(latest_row["atr"]) else 0.0
        if timeframe == "1h" and latest_atr > 0.0:
            current_atr = latest_atr
        latest_close_time = _to_datetime(latest_row.get("close_time"))
        if latest_close_time is not None and (anchor_time is None or latest_close_time > anchor_time):
            anchor_time = latest_close_time

    if not prepared_frames:
        return HistoricalResistanceAnalysis(zone=None, highest_peak_touch=None)

    if current_atr is None:
        for prepared in prepared_frames.values():
            latest_atr = float(prepared.iloc[-1]["atr"]) if pd.notna(prepared.iloc[-1]["atr"]) else 0.0
            if latest_atr > 0.0:
                current_atr = latest_atr
                break
    current_atr = max(float(current_atr or 0.0), current_price * 0.006)
    current_atr_pct = (current_atr / current_price) * 100.0

    touches: list[HistoricalResistanceTouch] = []
    for timeframe, prepared in prepared_frames.items():
        touches.extend(
            _extract_resistance_touches(
                prepared,
                timeframe=timeframe,
                current_price=current_price,
                current_atr=current_atr,
            )
        )
    highest_peak_touch = _select_highest_peak_touch(touches)
    if not touches:
        return HistoricalResistanceAnalysis(zone=None, highest_peak_touch=highest_peak_touch)

    clusters = _cluster_touches(touches, current_atr=current_atr, current_price=current_price)
    best_zone: HistoricalResistanceZone | None = None
    best_key: tuple[float, float, float] | None = None
    for cluster in clusters:
        zone = _build_zone(
            cluster,
            current_price=current_price,
            current_atr=current_atr,
            current_atr_pct=current_atr_pct,
            anchor_time=anchor_time,
        )
        if zone is None:
            continue
        ranking = (
            float(zone.confidence),
            float(zone.touch_count),
            -abs(zone.distance_pct),
        )
        if best_key is None or ranking > best_key:
            best_zone = zone
            best_key = ranking
    return HistoricalResistanceAnalysis(zone=best_zone, highest_peak_touch=highest_peak_touch)


def _extract_resistance_touches(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    current_price: float,
    current_atr: float,
) -> list[HistoricalResistanceTouch]:
    config = _TIMEFRAME_CONFIG[timeframe]
    pivot_window = int(config["pivot_window"])
    impulse_lookback = int(config["impulse_lookback"])
    rejection_lookahead = int(config["rejection_lookahead"])
    highs = frame["high"].astype(float)
    lows = frame["low"].astype(float)
    closes = frame["close"].astype(float)
    touches: list[HistoricalResistanceTouch] = []
    for idx in range(impulse_lookback + pivot_window, len(frame) - rejection_lookahead - pivot_window):
        row = frame.iloc[idx]
        pivot_high = float(row["high"])
        if pivot_high <= 0.0:
            continue
        left_highs = highs.iloc[idx - pivot_window:idx]
        right_highs = highs.iloc[idx + 1:idx + 1 + pivot_window]
        if left_highs.empty or right_highs.empty:
            continue
        if pivot_high < float(left_highs.max()) or pivot_high < float(right_highs.max()):
            continue

        previous_lows = lows.iloc[idx - impulse_lookback:idx]
        next_lows = lows.iloc[idx + 1:idx + 1 + rejection_lookahead]
        next_closes = closes.iloc[idx + 1:idx + 1 + rejection_lookahead]
        if previous_lows.empty or next_lows.empty or next_closes.empty:
            continue
        impulse_base = float(previous_lows.min())
        rejection_low = float(next_lows.min())
        if impulse_base <= 0.0 or rejection_low <= 0.0:
            continue

        local_atr = float(row["atr"]) if pd.notna(row["atr"]) and float(row["atr"]) > 0.0 else current_atr
        local_atr = max(local_atr, current_price * 0.006)
        local_atr_pct = (local_atr / pivot_high) * 100.0
        impulse_pct = ((pivot_high - impulse_base) / impulse_base) * 100.0
        rejection_pct = ((pivot_high - rejection_low) / pivot_high) * 100.0
        min_impulse_pct = max(local_atr_pct * 1.6, float(config["min_impulse_pct"]))
        min_rejection_pct = max(local_atr_pct * 1.15, float(config["min_rejection_pct"]))
        if impulse_pct < min_impulse_pct or rejection_pct < min_rejection_pct:
            continue
        if float(next_closes.min()) > pivot_high - (local_atr * float(config["min_close_break_atr"])):
            continue

        touched_at = _to_datetime(row.get("close_time")) or _to_datetime(frame.index[idx])
        if touched_at is None:
            continue
        touches.append(
            HistoricalResistanceTouch(
                timeframe=timeframe,
                price=pivot_high,
                impulse_pct=impulse_pct,
                rejection_pct=rejection_pct,
                tolerance=max(local_atr * 0.65, pivot_high * float(config["zone_pct"])),
                timeframe_weight=float(config["weight"]),
                touched_at=touched_at,
            )
        )
    return touches


def _cluster_touches(
    touches: list[HistoricalResistanceTouch],
    *,
    current_atr: float,
    current_price: float,
) -> list[list[HistoricalResistanceTouch]]:
    clusters: list[dict[str, object]] = []
    base_tolerance = max(current_atr * 0.55, current_price * 0.003)
    for touch in sorted(touches, key=lambda item: item.price):
        matched: dict[str, object] | None = None
        for cluster in clusters:
            cluster_center = float(cluster["center"])
            cluster_tolerance = float(cluster["tolerance"])
            if abs(touch.price - cluster_center) <= max(base_tolerance, cluster_tolerance, touch.tolerance):
                matched = cluster
                break
        if matched is None:
            clusters.append(
                {
                    "center": touch.price,
                    "tolerance": max(base_tolerance, touch.tolerance),
                    "touches": [touch],
                }
            )
            continue
        cluster_touches = list(matched["touches"])
        cluster_touches.append(touch)
        matched["touches"] = cluster_touches
        matched["center"] = sum(item.price for item in cluster_touches) / len(cluster_touches)
        matched["tolerance"] = max(float(matched["tolerance"]), touch.tolerance, base_tolerance)
    return [list(cluster["touches"]) for cluster in clusters]


def _build_zone(
    touches: list[HistoricalResistanceTouch],
    *,
    current_price: float,
    current_atr: float,
    current_atr_pct: float,
    anchor_time: datetime | None,
) -> HistoricalResistanceZone | None:
    if not touches:
        return None
    prices = [touch.price for touch in touches]
    weights = [touch.timeframe_weight for touch in touches]
    weighted_sum = sum(price * weight for price, weight in zip(prices, weights, strict=False))
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return None
    zone_price = weighted_sum / total_weight
    zone_low = min(prices)
    zone_high = max(prices)
    zone_width_pct = ((zone_high - zone_low) / zone_price) * 100.0 if zone_price > 0.0 else 0.0
    if zone_width_pct > max(current_atr_pct * 1.8, 1.6):
        return None

    distance_pct = ((zone_price - current_price) / current_price) * 100.0
    zone_low_distance_pct = ((zone_low - current_price) / current_price) * 100.0
    zone_high_distance_pct = ((zone_high - current_price) / current_price) * 100.0
    if zone_high_distance_pct < -0.9:
        return None
    if zone_low_distance_pct > max(4.5, current_atr_pct * 4.8):
        return None

    avg_rejection_pct = sum(touch.rejection_pct for touch in touches) / len(touches)
    avg_impulse_pct = sum(touch.impulse_pct for touch in touches) / len(touches)
    strong_cutoff = max(3.0, current_atr_pct * 1.5)
    strong_rejections = sum(1 for touch in touches if touch.rejection_pct >= strong_cutoff)
    timeframes = tuple(sorted({touch.timeframe for touch in touches}, key=lambda value: _TIMEFRAME_ORDER.get(value, 99)))
    latest_touch_at = max((touch.touched_at for touch in touches), default=None)
    recency_bonus = 0.0
    if anchor_time is not None and latest_touch_at is not None:
        days_since_touch = max((anchor_time - latest_touch_at).total_seconds(), 0.0) / 86400.0
        if days_since_touch <= 10.0:
            recency_bonus = 8.0
        elif days_since_touch <= 24.0:
            recency_bonus = 4.0

    confidence = round(
        max(
            0.0,
            min(
                100.0,
                20.0
                + min(total_weight * 16.0, 36.0)
                + min(avg_rejection_pct * 4.2, 24.0)
                + min(avg_impulse_pct * 1.7, 18.0)
                + min((len(touches) - 1) * 8.0, 20.0)
                + (10.0 if "4h" in timeframes else 0.0)
                + (strong_rejections * 5.0)
                + recency_bonus
                - (max(distance_pct - 1.8, 0.0) * 6.0)
                - (max(-zone_high_distance_pct, 0.0) * 10.0),
            ),
        )
    )
    if confidence < 54:
        return None
    quality = "strong" if confidence >= 78 else "moderate" if confidence >= 60 else "weak"
    highest_peak_touch = _select_highest_peak_touch(touches)
    highest_peak_price = highest_peak_touch.price if highest_peak_touch is not None else None
    highest_peak_timeframe = highest_peak_touch.timeframe if highest_peak_touch is not None else None
    highest_peak_distance_pct = (
        ((highest_peak_price - current_price) / current_price) * 100.0
        if isinstance(highest_peak_price, float)
        else None
    )
    return HistoricalResistanceZone(
        zone_low=zone_low,
        zone_high=zone_high,
        zone_price=zone_price,
        distance_pct=distance_pct,
        touch_count=len(touches),
        strong_rejections=strong_rejections,
        avg_rejection_pct=avg_rejection_pct,
        avg_impulse_pct=avg_impulse_pct,
        confidence=confidence,
        quality=quality,
        timeframes=timeframes,
        latest_touch_at=latest_touch_at,
        highest_peak_price=highest_peak_price,
        highest_peak_timeframe=highest_peak_timeframe,
        highest_peak_distance_pct=highest_peak_distance_pct,
        highest_peak_touched_at=highest_peak_touch.touched_at if highest_peak_touch is not None else None,
    )


def _select_highest_peak_touch(
    touches: list[HistoricalResistanceTouch],
) -> HistoricalResistanceTouch | None:
    if not touches:
        return None
    return max(
        touches,
        key=lambda touch: (
            float(touch.price),
            float(touch.timeframe_weight),
            touch.touched_at.timestamp(),
        ),
    )


def _to_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return None
