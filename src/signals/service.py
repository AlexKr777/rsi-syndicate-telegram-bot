from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Iterable

from src.core.models import AlertSignal
from src.core.utils import normalize_symbol, utc_now
from src.signals.domain import (
    DEFAULT_BENCHMARK_WIN_PERCENT,
    DEFAULT_CONFIRM_PROGRESS,
    DEFAULT_NEAR_TP_PROGRESS,
    EvaluationSnapshot,
    build_source_signal_key,
    default_expiry_for_timeframe,
    is_terminal_signal_status,
    is_transition_allowed,
    market_regime_from_metadata,
    normalize_signal_status,
    resolve_asset_cluster_tag,
    resolve_asset_type,
    resolve_trade_direction,
    resolve_strategy_code,
)
from src.storage.models import SignalLifecycleRecord, StrategyStatsSnapshotRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)

_STRATEGY_ORDER = (
    "breakout",
    "trend_pullback",
    "rsi_bollinger_mr",
    "rsi_bollinger_touch",
    "daily_rsi_80",
    "vwap",
    "false_breakout",
    "rsi",
    "rsi_divergence",
    "bollinger",
    "ekek",
    "gold",
    "gold_breakout",
    "gold_pullback",
    "gold_liquidity",
)

_PROGRESSION_ORDER = ("fresh", "active", "confirmed", "near_tp", "hit_tp")
_TARGET_MODELS: dict[str, tuple[float, float]] = {
    "breakout": (1.5, 0.8),
    "trend_pullback": (1.5, 0.8),
    "vwap": (1.5, 0.8),
    "gold_breakout": (1.5, 0.8),
    "gold_pullback": (1.5, 0.8),
    "false_breakout": (1.0, 0.7),
    "rsi_bollinger_mr": (1.0, 0.7),
    "rsi_bollinger_touch": (1.0, 0.7),
    "daily_rsi_80": (0.75, 0.5),
    "bollinger": (1.0, 0.7),
    "rsi_divergence": (1.0, 0.7),
    "ekek": (1.0, 0.7),
    "gold_liquidity": (1.0, 0.7),
    "rsi": (0.75, 0.5),
    "gold": (0.75, 0.5),
}


def _target_model(strategy_code: str) -> tuple[float, float]:
    return _TARGET_MODELS.get(str(strategy_code or "").strip().lower(), (1.0, DEFAULT_NEAR_TP_PROGRESS))


def _target_model_label(strategy_code: str) -> str:
    tp_rr, near_tp_progress = _target_model(strategy_code)
    return f"{tp_rr:.2f}R / near {near_tp_progress:.2f}".replace(".00", "")


class InvalidSignalPayloadError(ValueError):
    """Raised when a signal cannot safely be delivered as a trade scenario."""


@dataclass(frozen=True, slots=True)
class PreparedSignalLifecycle:
    source_signal_key: str
    strategy_code: str
    trade_direction: str
    asset_type: str
    asset_cluster_tag: str
    market_regime_tag: str
    invalidation_price: float | None
    tp_price_primary: float | None
    tp_price_secondary: float | None
    benchmark_win_percent: float
    expiry_at: datetime
    entry_zone_low: float | None
    entry_zone_high: float | None
    liquidity_tag: str | None
    confidence_score: float | None
    setup_quality: str | None
    explanation_short: str | None
    explanation_full: str | None
    ai_analysis_available: bool
    source_type: str
    is_gold: bool
    metadata: dict[str, Any]


class StrategyRuleEngine:
    def prepare(
        self,
        signal: AlertSignal,
        *,
        created_at: datetime,
        source_type: str,
        benchmark_win_percent: float = DEFAULT_BENCHMARK_WIN_PERCENT,
    ) -> PreparedSignalLifecycle:
        strategy_code = resolve_strategy_code(signal)
        asset_type = resolve_asset_type(signal)
        is_gold = asset_type == "gold"
        metadata = dict(signal.metadata)
        entry_price = float(signal.price)
        atr_value = self._atr_value(signal)
        raw_direction = str(signal.direction or "").strip().lower()
        setup_direction_raw = str(metadata.get("setup_direction") or "").strip().lower()
        raw_trade_direction = resolve_trade_direction(raw_direction)
        setup_trade_direction = resolve_trade_direction(setup_direction_raw)
        if raw_direction and raw_trade_direction not in {"long", "short"}:
            raise InvalidSignalPayloadError(f"Invalid signal direction: {raw_direction}")
        if setup_direction_raw and setup_trade_direction not in {"long", "short"}:
            raise InvalidSignalPayloadError(f"Invalid setup direction: {setup_direction_raw}")
        if (
            raw_trade_direction in {"long", "short"}
            and setup_trade_direction in {"long", "short"}
            and raw_trade_direction != setup_trade_direction
        ):
            raise InvalidSignalPayloadError(
                f"Signal direction conflicts with setup_direction: {raw_direction} vs {setup_direction_raw}"
            )
        trade_direction = (
            setup_trade_direction
            if setup_trade_direction in {"long", "short"}
            else raw_trade_direction
        )
        if trade_direction not in {"long", "short"}:
            raise InvalidSignalPayloadError("Invalid signal direction: executable LONG or SHORT is required")
        direction_source = "scanner_or_strategy"
        invalidation_price, geometry_corrected = self._derive_invalidation(
            signal,
            strategy_code=strategy_code,
            direction=trade_direction,
            entry_price=entry_price,
            atr_value=atr_value,
        )
        if geometry_corrected:
            LOGGER.warning(
                "Corrected invalidation geometry for %s: direction=%s entry=%s invalidation=%s",
                signal.symbol,
                trade_direction,
                entry_price,
                invalidation_price,
            )
        target_rr, near_tp_progress = _target_model(strategy_code)
        tp_price_primary, tp_price_secondary = self._derive_targets(
            trade_direction,
            strategy_code=strategy_code,
            entry_price=entry_price,
            invalidation_price=invalidation_price,
            benchmark_win_percent=benchmark_win_percent,
        )
        effective_benchmark_win_percent = benchmark_win_percent
        if tp_price_primary is not None and entry_price > 0:
            effective_benchmark_win_percent = abs(float(tp_price_primary) - entry_price) / max(entry_price, 1e-9) * 100.0
        entry_zone_low, entry_zone_high = self._derive_entry_zone(
            signal,
            direction=trade_direction,
            entry_price=entry_price,
            atr_value=atr_value,
        )
        asset_cluster_tag = resolve_asset_cluster_tag(signal.symbol, is_gold=is_gold)
        market_regime_tag = market_regime_from_metadata(metadata, strategy_code=strategy_code)
        liquidity_tag = self._liquidity_tag(signal)
        confidence_score = float(signal.score)
        setup_quality = self._setup_quality(signal.score)
        explanation_short = self._short_explanation(signal.explanation)
        explanation_full = signal.explanation or explanation_short
        expiry_at = default_expiry_for_timeframe(signal.timeframe, created_at=created_at)
        source_signal_key = build_source_signal_key(
            strategy_code=strategy_code,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=trade_direction,
            candle_open_time=signal.candle_open_time,
        )
        derived_metadata = {
            **metadata,
            "signal_status": "fresh",
            "result_type": "open",
            "setup_direction": trade_direction,
            "rsi_status": str(metadata.get("rsi_status") or raw_direction or "neutral"),
            "trade_direction_source": direction_source,
            "geometry_corrected": geometry_corrected,
            "asset_cluster_tag": asset_cluster_tag,
            "market_regime_tag": market_regime_tag,
            "lifecycle_source_type": source_type,
            "benchmark_win_percent": effective_benchmark_win_percent,
            "expiry_at": expiry_at.isoformat(),
            "invalidation_price": invalidation_price,
            "tp_price_primary": tp_price_primary,
            "tp_price_secondary": tp_price_secondary,
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "liquidity_tag": liquidity_tag,
            "confidence_score": confidence_score,
            "setup_quality": setup_quality,
            "explanation_short": explanation_short,
            "invalidation_source": str(metadata.get("invalidation_source") or "fallback"),
            "target_model": _target_model_label(strategy_code),
            "target_rr": target_rr,
            "near_tp_progress": near_tp_progress,
        }
        return PreparedSignalLifecycle(
            source_signal_key=source_signal_key,
            strategy_code=strategy_code,
            trade_direction=trade_direction,
            asset_type=asset_type,
            asset_cluster_tag=asset_cluster_tag,
            market_regime_tag=market_regime_tag,
            invalidation_price=invalidation_price,
            tp_price_primary=tp_price_primary,
            tp_price_secondary=tp_price_secondary,
            benchmark_win_percent=effective_benchmark_win_percent,
            expiry_at=expiry_at,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            liquidity_tag=liquidity_tag,
            confidence_score=confidence_score,
            setup_quality=setup_quality,
            explanation_short=explanation_short,
            explanation_full=explanation_full,
            ai_analysis_available=bool(metadata.get("interactive_ai_enabled")),
            source_type=source_type,
            is_gold=is_gold,
            metadata=derived_metadata,
        )

    def _atr_value(self, signal: AlertSignal) -> float:
        atr = float(signal.atr or 0.0)
        if atr > 0:
            return atr
        atr_pct = float(signal.atr_pct or 0.0)
        if atr_pct > 0:
            return float(signal.price) * atr_pct
        return max(float(signal.price) * 0.01, 1e-8)

    def _derive_entry_zone(
        self,
        signal: AlertSignal,
        *,
        direction: str,
        entry_price: float,
        atr_value: float,
    ) -> tuple[float | None, float | None]:
        zone_size = max(atr_value * 0.2, entry_price * 0.0025)
        if direction == "short":
            return entry_price, entry_price + zone_size
        return entry_price - zone_size, entry_price

    def _derive_targets(
        self,
        direction: str,
        *,
        strategy_code: str,
        entry_price: float,
        invalidation_price: float | None,
        benchmark_win_percent: float,
    ) -> tuple[float, float]:
        tp_rr, _near_tp_progress = _target_model(strategy_code)
        risk_distance = abs(entry_price - float(invalidation_price)) if invalidation_price is not None else 0.0
        if risk_distance > 0:
            primary_distance = risk_distance * tp_rr
            secondary_distance = risk_distance * max(tp_rr + 0.5, tp_rr)
            if str(direction).strip().lower() == "short":
                return entry_price - primary_distance, entry_price - secondary_distance
            return entry_price + primary_distance, entry_price + secondary_distance
        win_ratio = benchmark_win_percent / 100.0
        extended_ratio = max((benchmark_win_percent + 3.0) / 100.0, win_ratio)
        if str(direction).strip().lower() == "short":
            return entry_price * (1.0 - win_ratio), entry_price * (1.0 - extended_ratio)
        return entry_price * (1.0 + win_ratio), entry_price * (1.0 + extended_ratio)

    def _derive_invalidation(
        self,
        signal: AlertSignal,
        *,
        strategy_code: str,
        direction: str,
        entry_price: float,
        atr_value: float,
    ) -> tuple[float | None, bool]:
        metadata = signal.metadata
        if isinstance(metadata.get("invalidation_price"), (int, float)):
            return self._normalize_invalidation(
                direction=direction,
                entry_price=entry_price,
                invalidation_price=float(metadata["invalidation_price"]),
                atr_value=atr_value,
            )
        trigger_level = float(metadata.get("trigger_level") or entry_price)
        range_low = float(metadata.get("range_low") or trigger_level)
        range_high = float(metadata.get("range_high") or trigger_level)
        sweep_level = float(metadata.get("sweep_level") or trigger_level)
        touched_ema = int(metadata.get("touched_ema") or 20)
        if strategy_code in {"breakout", "gold_breakout"}:
            candidate = max(range_high, trigger_level + atr_value * 0.4) if direction == "short" else min(range_low, trigger_level - atr_value * 0.4)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code in {"trend_pullback", "gold_pullback"}:
            multiplier = 0.7 if touched_ema == 50 else 0.6
            candidate = entry_price + atr_value * multiplier if direction == "short" else entry_price - atr_value * multiplier
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code == "vwap":
            candidate = trigger_level + atr_value * 0.35 if direction == "short" else trigger_level - atr_value * 0.35
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code in {"false_breakout", "gold_liquidity"}:
            candidate = max(sweep_level, entry_price + atr_value * 0.45) if direction == "short" else min(sweep_level, entry_price - atr_value * 0.45)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code in {"rsi_bollinger_mr", "rsi_bollinger_touch"}:
            bb_anchor = float(metadata.get("bb_upper" if direction == "short" else "bb_lower") or entry_price)
            candidate = max(bb_anchor, entry_price + atr_value * 0.5) if direction == "short" else min(bb_anchor, entry_price - atr_value * 0.5)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code == "rsi_divergence":
            swing_anchor = float(
                metadata.get("second_swing_price")
                or metadata.get("marker_price")
                or entry_price
            )
            candidate = max(swing_anchor, entry_price + atr_value * 0.45) if direction == "short" else min(swing_anchor, entry_price - atr_value * 0.45)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code == "ekek":
            impulse_anchor = float(
                metadata.get("marker_price")
                or metadata.get("signal_close_price")
                or entry_price
            )
            candidate = max(impulse_anchor, entry_price + atr_value * 0.5) if direction == "short" else min(impulse_anchor, entry_price - atr_value * 0.5)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code == "bollinger":
            bb_anchor = float(metadata.get("bb_upper" if direction == "short" else "bb_lower") or entry_price)
            candidate = max(bb_anchor, entry_price + atr_value * 0.45) if direction == "short" else min(bb_anchor, entry_price - atr_value * 0.45)
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        if strategy_code == "gold":
            padding = max(atr_value * 0.9, entry_price * 0.006)
            candidate = entry_price + padding if direction == "short" else entry_price - padding
            return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)
        padding = max(atr_value * 1.1, entry_price * 0.025)
        candidate = entry_price + padding if direction == "short" else entry_price - padding
        return self._normalize_invalidation(direction=direction, entry_price=entry_price, invalidation_price=candidate, atr_value=atr_value)

    @staticmethod
    def _normalize_invalidation(
        *,
        direction: str,
        entry_price: float,
        invalidation_price: float,
        atr_value: float,
    ) -> tuple[float, bool]:
        """Reject an invalidation on the wrong side before anything is delivered."""

        if direction == "short" and invalidation_price <= entry_price:
            raise InvalidSignalPayloadError(
                f"Invalid invalidation for SHORT: {invalidation_price} must be above entry {entry_price}"
            )
        if direction == "long" and invalidation_price >= entry_price:
            raise InvalidSignalPayloadError(
                f"Invalid invalidation for LONG: {invalidation_price} must be below entry {entry_price}"
            )
        return invalidation_price, False

    def _liquidity_tag(self, signal: AlertSignal) -> str | None:
        volume = float(signal.quote_volume or signal.day_volume or 0.0)
        if volume >= 25_000_000.0:
            return "high"
        if volume >= 8_000_000.0:
            return "medium"
        if volume > 0.0:
            return "low"
        return None

    def _setup_quality(self, score: int) -> str:
        if score >= 88:
            return "Conservative"
        if score >= 74:
            return "Balanced"
        return "Active"

    def _short_explanation(self, explanation: str | None) -> str:
        cleaned = str(explanation or "").strip().replace("\n", " ")
        if not cleaned:
            return "The setup matched the current strategy filters and market context."
        sentence = cleaned.split(".")[0].strip()
        return f"{sentence}." if sentence else cleaned[:180]


class SignalLifecycleService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.rule_engine = StrategyRuleEngine()

    def prepare_signal_metadata(
        self,
        signal: AlertSignal,
        *,
        created_at: datetime | None = None,
        source_type: str = "strategy_stream",
        benchmark_win_percent: float = DEFAULT_BENCHMARK_WIN_PERCENT,
    ) -> PreparedSignalLifecycle:
        return self.rule_engine.prepare(
            signal,
            created_at=created_at or utc_now(),
            source_type=source_type,
            benchmark_win_percent=benchmark_win_percent,
        )

    def apply_prepared_metadata(self, signal: AlertSignal, prepared: PreparedSignalLifecycle) -> None:
        signal.metadata = {**signal.metadata, **prepared.metadata}

    async def create_signal(
        self,
        *,
        signal: AlertSignal,
        alert_id: int | None,
        created_at: datetime | None = None,
        parent_alert_message_id: int | None = None,
        source_type: str = "strategy_stream",
    ) -> SignalLifecycleRecord:
        effective_created_at = created_at or utc_now()
        prepared = self.prepare_signal_metadata(signal, created_at=effective_created_at, source_type=source_type)
        self.apply_prepared_metadata(signal, prepared)
        record = await self.repository.create_tracked_signal(
            alert_id=alert_id,
            source_signal_key=prepared.source_signal_key,
            strategy_code=prepared.strategy_code,
            symbol=normalize_symbol(signal.symbol),
            asset_type=prepared.asset_type,
            direction=prepared.trade_direction,
            timeframe=str(signal.timeframe).strip().lower(),
            status="fresh",
            result_type="open",
            entry_price=float(signal.price),
            entry_zone_low=prepared.entry_zone_low,
            entry_zone_high=prepared.entry_zone_high,
            invalidation_price=prepared.invalidation_price,
            tp_price_primary=prepared.tp_price_primary,
            tp_price_secondary=prepared.tp_price_secondary,
            benchmark_win_percent=prepared.benchmark_win_percent,
            created_at=effective_created_at,
            expiry_at=prepared.expiry_at,
            last_price=float(signal.metadata.get("live_price") or signal.price),
            last_price_at=effective_created_at,
            market_regime_tag=prepared.market_regime_tag,
            liquidity_tag=prepared.liquidity_tag,
            confidence_score=prepared.confidence_score,
            setup_quality=prepared.setup_quality,
            explanation_short=prepared.explanation_short,
            explanation_full=prepared.explanation_full,
            ai_analysis_available=prepared.ai_analysis_available,
            parent_alert_message_id=parent_alert_message_id,
            source_type=prepared.source_type,
            is_gold=prepared.is_gold,
            metadata=prepared.metadata,
        )
        await self.repository.append_signal_event(
            signal_id=record.signal_id,
            event_type="created",
            old_status=None,
            new_status=record.status,
            event_payload={"strategy_code": record.strategy_code, "symbol": record.symbol, "timeframe": record.timeframe},
            created_at=effective_created_at,
            created_by="system",
        )
        await self.repository.record_telemetry_event(
            event_name="signal_created",
            created_at=effective_created_at,
            context=record.strategy_code,
            payload={"signal_id": record.signal_id, "symbol": record.symbol, "status": record.status},
        )
        return record

    async def evaluate_signal_state(
        self,
        record: SignalLifecycleRecord,
        *,
        high_price: float,
        low_price: float,
        close_price: float,
        observed_at: datetime,
    ) -> SignalLifecycleRecord:
        if is_terminal_signal_status(record.status):
            return record
        evaluation = self._build_evaluation(
            record,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            observed_at=observed_at,
        )
        metadata = {
            **record.metadata,
            "signal_status": evaluation.status,
            "result_type": evaluation.result_type,
            "last_progress_to_target": round(evaluation.progress_to_target, 4),
            "ambiguous_resolution": evaluation.ambiguous_resolution,
        }
        updated = await self.repository.update_tracked_signal(
            record.signal_id,
            last_price=close_price,
            last_price_at=observed_at,
            mfe_percent=evaluation.mfe_percent,
            mae_percent=evaluation.mae_percent,
            ambiguous_resolution=evaluation.ambiguous_resolution or record.ambiguous_resolution,
            metadata=metadata,
        )
        assert updated is not None
        if evaluation.status == record.status:
            return updated
        transition_path = self._transition_path(record.status, evaluation.status)
        current = updated
        for next_status in transition_path:
            if next_status == "hit_tp":
                current = await self._transition(
                    current,
                    "hit_tp",
                    observed_at=observed_at,
                    event_type="hit_tp",
                    event_payload={"progress_to_target": evaluation.progress_to_target, "ambiguous_resolution": evaluation.ambiguous_resolution},
                )
                continue
            if next_status == "invalidated":
                current = await self._transition(
                    current,
                    "invalidated",
                    observed_at=observed_at,
                    event_type="invalidated",
                    event_payload={"ambiguous_resolution": evaluation.ambiguous_resolution},
                )
                continue
            if next_status == "expired":
                current = await self._transition(
                    current,
                    "expired",
                    observed_at=observed_at,
                    event_type="expired",
                    event_payload={"expired": True},
                )
                continue
            current = await self._transition(
                current,
                next_status,
                observed_at=observed_at,
                event_type=next_status,
                event_payload={"progress_to_target": evaluation.progress_to_target},
            )
        return current

    async def mark_signal_untrackable(
        self,
        record: SignalLifecycleRecord,
        *,
        observed_at: datetime,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> SignalLifecycleRecord:
        metadata = {
            **record.metadata,
            "tracking_unavailable": True,
            "tracking_unavailable_reason": str(reason or "unavailable"),
            "tracking_unavailable_at": observed_at.isoformat(),
        }
        if details:
            metadata["tracking_unavailable_details"] = details
        updated = await self.repository.update_tracked_signal(record.signal_id, metadata=metadata)
        assert updated is not None
        if is_terminal_signal_status(updated.status):
            await self.repository.append_signal_event(
                signal_id=updated.signal_id,
                event_type="tracking_unavailable",
                old_status=updated.status,
                new_status=updated.status,
                event_payload={"reason": reason, **(details or {})},
                created_at=observed_at,
                created_by="system",
            )
            await self.repository.record_telemetry_event(
                event_name="signal_tracking_unavailable",
                created_at=observed_at,
                context=updated.strategy_code,
                payload={"signal_id": updated.signal_id, "symbol": updated.symbol, "reason": reason},
            )
            return updated
        return await self._transition(
            updated,
            "expired",
            observed_at=observed_at,
            event_type="tracking_unavailable",
            event_payload={"reason": reason, **(details or {})},
        )

    async def list_lifecycle_signals(
        self,
        *,
        strategy_code: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[SignalLifecycleRecord]:
        return await self.repository.list_tracked_signals(
            strategy_code=strategy_code,
            statuses=tuple(statuses) if statuses is not None else None,
            limit=limit,
        )

    async def get_admin_strategy_stats(
        self,
        *,
        period_type: str = "7d",
        now: datetime | None = None,
    ) -> list[StrategyStatsSnapshotRecord]:
        effective_now = now or utc_now()
        return [
            await self._compute_strategy_snapshot(strategy_code, period_type=period_type, now=effective_now)
            for strategy_code in _STRATEGY_ORDER
        ]

    async def recompute_strategy_snapshots(self, *, now: datetime | None = None) -> None:
        effective_now = now or utc_now()
        for period_type in ("1d", "7d", "30d", "all_time"):
            for strategy_code in _STRATEGY_ORDER:
                snapshot = await self._compute_strategy_snapshot(strategy_code, period_type=period_type, now=effective_now)
                await self.repository.upsert_strategy_stats_snapshot(
                    strategy_code=snapshot.strategy_code,
                    timeframe_bucket=snapshot.timeframe_bucket,
                    market_regime_bucket=snapshot.market_regime_bucket,
                    asset_cluster_bucket=snapshot.asset_cluster_bucket,
                    period_type=snapshot.period_type,
                    total_signals=snapshot.total_signals,
                    wins=snapshot.wins,
                    losses=snapshot.losses,
                    expired_neutral=snapshot.expired_neutral,
                    invalidated_count=snapshot.invalidated_count,
                    avg_rr=snapshot.avg_rr,
                    avg_time_to_win_minutes=snapshot.avg_time_to_win_minutes,
                    avg_time_to_invalidation_minutes=snapshot.avg_time_to_invalidation_minutes,
                    signals_per_day=snapshot.signals_per_day,
                    best_tf=snapshot.best_tf,
                    best_assets=snapshot.best_assets,
                    best_regime=snapshot.best_regime,
                    drawdown_profile=snapshot.drawdown_profile,
                    calculated_at=snapshot.calculated_at,
                    delivered_count=snapshot.delivered_count,
                    suppressed_count=snapshot.suppressed_count,
                    ambiguous_count=snapshot.ambiguous_count,
                    sent_wins=snapshot.sent_wins,
                    sent_losses=snapshot.sent_losses,
                    sent_expired_neutral=snapshot.sent_expired_neutral,
                    sent_ambiguous_count=snapshot.sent_ambiguous_count,
                    sent_avg_rr=snapshot.sent_avg_rr,
                    sent_signals_per_day=snapshot.sent_signals_per_day,
                    sent_best_tf=snapshot.sent_best_tf,
                    sent_best_assets=snapshot.sent_best_assets,
                    sent_best_regime=snapshot.sent_best_regime,
                )

    def _build_evaluation(
        self,
        record: SignalLifecycleRecord,
        *,
        high_price: float,
        low_price: float,
        close_price: float,
        observed_at: datetime,
    ) -> EvaluationSnapshot:
        del close_price
        target_price = float(record.tp_price_primary or record.entry_price)
        direction = str(record.direction).strip().lower()
        benchmark_win_percent = max(float(record.benchmark_win_percent or DEFAULT_BENCHMARK_WIN_PERCENT), 0.001)
        near_tp_progress = float(record.metadata.get("near_tp_progress") or DEFAULT_NEAR_TP_PROGRESS)
        confirm_progress = min(float(record.metadata.get("confirm_progress") or DEFAULT_CONFIRM_PROGRESS), near_tp_progress)
        if direction == "short":
            favorable_move_percent = max((record.entry_price - low_price) / record.entry_price * 100.0, 0.0)
            adverse_move_percent = max((high_price - record.entry_price) / record.entry_price * 100.0, 0.0)
            hit_target = low_price <= target_price
            hit_invalidation = record.invalidation_price is not None and high_price >= float(record.invalidation_price)
        else:
            favorable_move_percent = max((high_price - record.entry_price) / record.entry_price * 100.0, 0.0)
            adverse_move_percent = max((record.entry_price - low_price) / record.entry_price * 100.0, 0.0)
            hit_target = high_price >= target_price
            hit_invalidation = record.invalidation_price is not None and low_price <= float(record.invalidation_price)
        mfe_percent = max(record.mfe_percent, favorable_move_percent)
        mae_percent = max(record.mae_percent, adverse_move_percent)
        progress_to_target = favorable_move_percent / benchmark_win_percent
        if hit_target and hit_invalidation:
            return EvaluationSnapshot("expired", "neutral", target_price, benchmark_win_percent, favorable_move_percent, adverse_move_percent, mfe_percent, mae_percent, progress_to_target, True, True, True)
        if hit_target:
            return EvaluationSnapshot("hit_tp", "win", target_price, benchmark_win_percent, favorable_move_percent, adverse_move_percent, mfe_percent, mae_percent, progress_to_target, True, False)
        if hit_invalidation:
            return EvaluationSnapshot("invalidated", "loss", target_price, benchmark_win_percent, favorable_move_percent, adverse_move_percent, mfe_percent, mae_percent, progress_to_target, False, True)
        if record.expiry_at is not None and observed_at >= record.expiry_at:
            return EvaluationSnapshot("expired", "neutral", target_price, benchmark_win_percent, favorable_move_percent, adverse_move_percent, mfe_percent, mae_percent, progress_to_target, False, False)
        current_status = normalize_signal_status(record.status)
        next_status = current_status
        if progress_to_target >= near_tp_progress:
            next_status = "near_tp"
        elif progress_to_target >= confirm_progress:
            next_status = "confirmed"
        elif next_status == "fresh":
            next_status = "active"
        if current_status in _PROGRESSION_ORDER and next_status in _PROGRESSION_ORDER:
            current_index = _PROGRESSION_ORDER.index(current_status)
            next_index = _PROGRESSION_ORDER.index(next_status)
            if next_index < current_index:
                next_status = current_status
        return EvaluationSnapshot(next_status, "open", target_price, benchmark_win_percent, favorable_move_percent, adverse_move_percent, mfe_percent, mae_percent, progress_to_target, False, False)

    async def _transition(
        self,
        record: SignalLifecycleRecord,
        new_status: str,
        *,
        observed_at: datetime,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
    ) -> SignalLifecycleRecord:
        old_status = normalize_signal_status(record.status)
        normalized_new_status = normalize_signal_status(new_status)
        if old_status == normalized_new_status:
            return record
        if not is_transition_allowed(old_status, normalized_new_status):
            LOGGER.warning(
                "Rejected invalid signal transition signal_id=%s old=%s new=%s",
                record.signal_id,
                old_status,
                normalized_new_status,
            )
            await self.repository.append_signal_event(
                signal_id=record.signal_id,
                event_type="invalid_transition",
                old_status=old_status,
                new_status=normalized_new_status,
                event_payload=event_payload or {},
                created_at=observed_at,
                created_by="system",
            )
            return record
        result_type = record.result_type
        updates: dict[str, Any] = {"status": normalized_new_status}
        if normalized_new_status == "active":
            updates["activated_at"] = record.activated_at or observed_at
        elif normalized_new_status == "confirmed":
            updates["confirmed_at"] = record.confirmed_at or observed_at
        elif normalized_new_status == "near_tp":
            updates["near_tp_at"] = record.near_tp_at or observed_at
        elif normalized_new_status == "hit_tp":
            result_type = "win"
            updates.update({"result_type": result_type, "hit_tp_at": record.hit_tp_at or observed_at, "closed_at": record.closed_at or observed_at})
        elif normalized_new_status == "invalidated":
            result_type = "loss"
            updates.update({"result_type": result_type, "invalidated_at": record.invalidated_at or observed_at, "closed_at": record.closed_at or observed_at})
        elif normalized_new_status == "expired":
            result_type = "neutral"
            updates.update({"result_type": result_type, "expired_at": record.expired_at or observed_at, "closed_at": record.closed_at or observed_at})
        updates["metadata"] = {**record.metadata, "signal_status": normalized_new_status, "result_type": result_type}
        updated = await self.repository.update_tracked_signal(record.signal_id, **updates)
        assert updated is not None
        await self.repository.append_signal_event(
            signal_id=record.signal_id,
            event_type=event_type,
            old_status=old_status,
            new_status=normalized_new_status,
            event_payload=event_payload or {},
            created_at=observed_at,
            created_by="system",
        )
        await self.repository.record_telemetry_event(
            event_name="signal_status_changed",
            created_at=observed_at,
            context=updated.strategy_code,
            payload={"signal_id": updated.signal_id, "old_status": old_status, "new_status": normalized_new_status},
        )
        return updated

    def _transition_path(self, old_status: str, new_status: str) -> list[str]:
        normalized_old = normalize_signal_status(old_status)
        normalized_new = normalize_signal_status(new_status)
        if normalized_old == normalized_new:
            return []
        if is_transition_allowed(normalized_old, normalized_new):
            return [normalized_new]
        if normalized_old in _PROGRESSION_ORDER and normalized_new in _PROGRESSION_ORDER:
            old_index = _PROGRESSION_ORDER.index(normalized_old)
            new_index = _PROGRESSION_ORDER.index(normalized_new)
            if new_index > old_index:
                return list(_PROGRESSION_ORDER[old_index + 1 : new_index + 1])
        return [normalized_new]

    async def _compute_strategy_snapshot(
        self,
        strategy_code: str,
        *,
        period_type: str,
        now: datetime,
    ) -> StrategyStatsSnapshotRecord:
        start = None
        if period_type == "1d":
            start = now - timedelta(days=1)
        elif period_type == "7d":
            start = now - timedelta(days=7)
        elif period_type == "30d":
            start = now - timedelta(days=30)
        records = await self.repository.list_tracked_signals(strategy_code=strategy_code, limit=5000)
        filtered = [record for record in records if start is None or record.created_at >= start]
        wins = [record for record in filtered if record.result_type == "win"]
        losses = [record for record in filtered if record.result_type == "loss"]
        ambiguous = [record for record in filtered if record.ambiguous_resolution]
        expired = [record for record in filtered if record.result_type == "neutral" and not record.ambiguous_resolution]
        delivered = [record for record in filtered if bool(record.metadata.get("delivery_sent"))]
        sent_wins = [record for record in delivered if record.result_type == "win"]
        sent_losses = [record for record in delivered if record.result_type == "loss"]
        sent_ambiguous = [record for record in delivered if record.ambiguous_resolution]
        sent_expired = [record for record in delivered if record.result_type == "neutral" and not record.ambiguous_resolution]
        grouped_tf = Counter(record.timeframe for record in wins)
        grouped_assets = Counter(str(record.metadata.get("asset_cluster_tag") or resolve_asset_cluster_tag(record.symbol, is_gold=record.is_gold)) for record in wins)
        grouped_regimes = Counter((record.market_regime_tag or "Mixed") for record in wins)
        sent_grouped_tf = Counter(record.timeframe for record in sent_wins)
        sent_grouped_assets = Counter(
            str(record.metadata.get("asset_cluster_tag") or resolve_asset_cluster_tag(record.symbol, is_gold=record.is_gold))
            for record in sent_wins
        )
        sent_grouped_regimes = Counter((record.market_regime_tag or "Mixed") for record in sent_wins)
        if start is not None:
            window_days = max((now - start).total_seconds() / 86400.0, 1.0)
        else:
            oldest_created_at = min((record.created_at for record in filtered), default=now)
            window_days = max((now - oldest_created_at).total_seconds() / 86400.0, 1.0)
        return StrategyStatsSnapshotRecord(
            snapshot_id=0,
            strategy_code=strategy_code,
            timeframe_bucket=None,
            market_regime_bucket=None,
            asset_cluster_bucket=None,
            period_type=period_type,
            total_signals=len(filtered),
            wins=len(wins),
            losses=len(losses),
            expired_neutral=len(expired),
            invalidated_count=len([record for record in filtered if record.status == "invalidated"]),
            avg_rr=self._average_rr(filtered),
            avg_time_to_win_minutes=self._average_minutes((record.hit_tp_at, record.created_at) for record in wins),
            avg_time_to_invalidation_minutes=self._average_minutes((record.invalidated_at, record.created_at) for record in losses),
            signals_per_day=round(len(filtered) / max(window_days, 1), 2),
            best_tf=grouped_tf.most_common(1)[0][0] if grouped_tf else None,
            best_assets=grouped_assets.most_common(1)[0][0] if grouped_assets else None,
            best_regime=grouped_regimes.most_common(1)[0][0] if grouped_regimes else None,
            drawdown_profile=self._drawdown_profile(filtered),
            calculated_at=now,
            delivered_count=len(delivered),
            suppressed_count=max(len(filtered) - len(delivered), 0),
            ambiguous_count=len(ambiguous),
            sent_wins=len(sent_wins),
            sent_losses=len(sent_losses),
            sent_expired_neutral=len(sent_expired),
            sent_ambiguous_count=len(sent_ambiguous),
            sent_avg_rr=self._average_rr(delivered),
            sent_signals_per_day=round(len(delivered) / max(window_days, 1), 2),
            sent_best_tf=sent_grouped_tf.most_common(1)[0][0] if sent_grouped_tf else None,
            sent_best_assets=sent_grouped_assets.most_common(1)[0][0] if sent_grouped_assets else None,
            sent_best_regime=sent_grouped_regimes.most_common(1)[0][0] if sent_grouped_regimes else None,
        )

    def _average_rr(self, records: list[SignalLifecycleRecord]) -> float | None:
        values: list[float] = []
        for record in records:
            if record.invalidation_price is None or record.tp_price_primary is None:
                continue
            risk = abs(record.entry_price - float(record.invalidation_price))
            reward = abs(float(record.tp_price_primary) - record.entry_price)
            if risk > 0:
                values.append(reward / risk)
        return round(mean(values), 2) if values else None

    def _average_minutes(self, pairs: Iterable[tuple[datetime | None, datetime | None]]) -> float | None:
        values = [
            max((end_at - start_at).total_seconds() / 60.0, 0.0)
            for end_at, start_at in pairs
            if end_at is not None and start_at is not None
        ]
        return round(mean(values), 1) if values else None

    def _drawdown_profile(self, records: list[SignalLifecycleRecord]) -> str | None:
        recent = [record for record in records if record.result_type in {"win", "loss"}][:12]
        if not recent:
            return None
        streak = 0
        worst = 0
        for record in recent:
            if record.result_type == "loss":
                streak += 1
                worst = max(worst, streak)
            else:
                streak = 0
        if worst >= 4:
            return "High"
        if worst >= 2:
            return "Medium"
        return "Low"
