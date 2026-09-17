from __future__ import annotations

import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Sequence

import aiosqlite

from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost, TwitterDraft
from src.core.strategy_keys import PREMIUM_STRATEGY_KEY_SET
from src.core.utils import utc_now
from src.storage.models import (
    AlertRecord,
    CachedAnalysisRecord,
    ChatMemberRosterRecord,
    CryptoPayInvoiceRecord,
    CryptoPayWebhookEventRecord,
    DeliveredSignalRecord,
    FollowUpResultRecord,
    FollowUpTaskRecord,
    InteractiveAlertState,
    OnboardingStateRecord,
    OnboardingCampaignRecord,
    PreparedFeatureCardRecord,
    PrivateBotUserRecord,
    PremiumStrategySettingsRecord,
    ReferralRecord,
    ReferralCycleStatRecord,
    ReferralRewardGrantRecord,
    ScheduledGeneratedPostRecord,
    SignalCandleRecord,
    SignalEventRecord,
    SignalLifecycleRecord,
    SymbolState,
    StrategyStatsSnapshotRecord,
    UserSavedSetupRecord,
    UserAccessRecord,
    UserSettingsRecord,
    UserStyleProfileRecord,
    WatchlistThemeRecord,
    WatchlistEntry,
)


def _to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _to_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _to_strategy_keys(value: str | None) -> tuple[str, ...]:
    try:
        raw = json.loads(value or "[]")
    except json.JSONDecodeError:
        raw = []
    if not isinstance(raw, list):
        return ()
    normalized: list[str] = []
    for item in raw:
        key = str(item or "").strip().lower()
        if key in PREMIUM_STRATEGY_KEY_SET and key not in normalized:
            normalized.append(key)
    return tuple(normalized)


class Repository:
    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = sqlite_path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    def _row_to_user_settings(self, row: aiosqlite.Row | None) -> UserSettingsRecord | None:
        if row is None:
            return None
        updated_at_raw = row["updated_at"] if "updated_at" in row.keys() else row["settings_updated_at"]
        return UserSettingsRecord(
            telegram_user_id=row["telegram_user_id"],
            bot_kind=row["bot_kind"],
            direct_signal_delivery_enabled=bool(row["direct_signal_delivery_enabled"]),
            followup_delivery_enabled=bool(row["followup_delivery_enabled"]),
            gold_alerts_enabled=bool(row["gold_alerts_enabled"]),
            language_code=str(row["language_code"] or "en"),
            signal_profile=str(row["signal_profile"] or "balanced"),
            base_signal_profile=str(row["base_signal_profile"] or "balanced"),
            preferred_min_score=row["preferred_min_score"],
            min_quote_volume=row["min_quote_volume"],
            rsi_oversold=row["rsi_oversold"],
            rsi_overbought=row["rsi_overbought"],
            direction_filter=str(row["direction_filter"] or "both"),
            watchlist_only=bool(row["watchlist_only"]),
            menu_collapsed=bool(row["menu_collapsed"]),
            delivery_mode=str(row["delivery_mode"] or "instant"),
            delivery_mode_changed_at=_to_dt(row["delivery_mode_changed_at"]),
            quiet_hours_start_minute=row["quiet_hours_start_minute"],
            quiet_hours_end_minute=row["quiet_hours_end_minute"],
            snooze_until=_to_dt(row["snooze_until"]),
            snooze_started_at=_to_dt(row["snooze_started_at"]),
            snooze_label=row["snooze_label"],
            last_resume_summary_at=_to_dt(row["last_resume_summary_at"]),
            last_digest_sent_at=_to_dt(row["last_digest_sent_at"]),
            last_daily_recap_at=_to_dt(row["last_daily_recap_at"]),
            last_weekly_recap_at=_to_dt(row["last_weekly_recap_at"]),
            active_watchlist_theme=str(row["active_watchlist_theme"] or "custom"),
            active_custom_theme_name=row["active_custom_theme_name"],
            onboarding_completed_at=_to_dt(row["onboarding_completed_at"]),
            updated_at=datetime.fromisoformat(updated_at_raw),
            enabled_strategy_keys=_to_strategy_keys(row["enabled_strategy_keys_json"] if "enabled_strategy_keys_json" in row.keys() else None),
            active_strategy_key=row["active_strategy_key"] if "active_strategy_key" in row.keys() else None,
            strategy_selector_completed_at=_to_dt(
                row["strategy_selector_completed_at"] if "strategy_selector_completed_at" in row.keys() else None
            ),
            current_context=row["current_context"] if "current_context" in row.keys() else None,
            current_strategy_context=row["current_strategy_context"] if "current_strategy_context" in row.keys() else None,
            current_set_id=row["current_set_id"] if "current_set_id" in row.keys() else None,
            timezone_name=row["timezone_name"] if "timezone_name" in row.keys() else None,
            display_mode=str(row["display_mode"] or "pro") if "display_mode" in row.keys() else "pro",
            active_workspace=row["active_workspace"] if "active_workspace" in row.keys() else None,
            saved_workspace_payload=json.loads(
                (row["saved_workspace_payload_json"] if "saved_workspace_payload_json" in row.keys() else "{}") or "{}"
            ),
            strategy_preferences=json.loads(
                (row["strategy_preferences_json"] if "strategy_preferences_json" in row.keys() else "{}") or "{}"
            ),
            personalization=json.loads(
                (row["personalization_json"] if "personalization_json" in row.keys() else "{}") or "{}"
            ),
            delivery_rules=json.loads(
                (row["delivery_rules_json"] if "delivery_rules_json" in row.keys() else "{}") or "{}"
            ),
        )

    def _row_to_user_saved_setup(self, row: aiosqlite.Row | None) -> UserSavedSetupRecord | None:
        if row is None:
            return None
        return UserSavedSetupRecord(
            id=int(row["id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            bot_kind=str(row["bot_kind"] or "premium"),
            name=str(row["name"] or "Setup"),
            is_default=bool(row["is_default"]),
            is_pinned=bool(row["is_pinned"]),
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_used_at=_to_dt(row["last_used_at"]),
        )

    def _row_to_user_style_profile(self, row: aiosqlite.Row | None) -> UserStyleProfileRecord | None:
        if row is None:
            return None
        return UserStyleProfileRecord(
            telegram_user_id=int(row["telegram_user_id"]),
            bot_kind=str(row["bot_kind"] or "premium"),
            title=str(row["title"] or "Balanced Trader"),
            summary=row["summary"],
            preferences=json.loads(row["preferences_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_chat_member_roster_record(self, row: aiosqlite.Row | None) -> ChatMemberRosterRecord | None:
        if row is None:
            return None
        return ChatMemberRosterRecord(
            chat_id=str(row["chat_id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_bot=bool(row["is_bot"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )

    def _row_to_signal_lifecycle_record(self, row: aiosqlite.Row | None) -> SignalLifecycleRecord | None:
        if row is None:
            return None
        return SignalLifecycleRecord(
            signal_id=row["signal_id"],
            alert_id=row["alert_id"],
            source_signal_key=row["source_signal_key"],
            strategy_code=row["strategy_code"],
            symbol=row["symbol"],
            asset_type=row["asset_type"],
            direction=row["direction"],
            timeframe=row["timeframe"],
            status=row["status"],
            result_type=row["result_type"],
            entry_price=row["entry_price"],
            entry_zone_low=row["entry_zone_low"],
            entry_zone_high=row["entry_zone_high"],
            invalidation_price=row["invalidation_price"],
            tp_price_primary=row["tp_price_primary"],
            tp_price_secondary=row["tp_price_secondary"],
            benchmark_win_percent=float(row["benchmark_win_percent"] or 0.0),
            created_at=datetime.fromisoformat(row["created_at"]),
            activated_at=_to_dt(row["activated_at"]),
            confirmed_at=_to_dt(row["confirmed_at"]),
            near_tp_at=_to_dt(row["near_tp_at"]),
            hit_tp_at=_to_dt(row["hit_tp_at"]),
            invalidated_at=_to_dt(row["invalidated_at"]),
            expired_at=_to_dt(row["expired_at"]),
            closed_at=_to_dt(row["closed_at"]),
            expiry_at=_to_dt(row["expiry_at"]),
            last_price=row["last_price"],
            last_price_at=_to_dt(row["last_price_at"]),
            mfe_percent=float(row["mfe_percent"] or 0.0),
            mae_percent=float(row["mae_percent"] or 0.0),
            market_regime_tag=row["market_regime_tag"],
            liquidity_tag=row["liquidity_tag"],
            confidence_score=row["confidence_score"],
            setup_quality=row["setup_quality"],
            explanation_short=row["explanation_short"],
            explanation_full=row["explanation_full"],
            ai_analysis_available=bool(row["ai_analysis_available"]),
            parent_alert_message_id=row["parent_alert_message_id"],
            source_type=row["source_type"],
            is_gold=bool(row["is_gold"]),
            ambiguous_resolution=bool(row["ambiguous_resolution"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _row_to_signal_event_record(self, row: aiosqlite.Row | None) -> SignalEventRecord | None:
        if row is None:
            return None
        return SignalEventRecord(
            event_id=row["event_id"],
            signal_id=row["signal_id"],
            event_type=row["event_type"],
            old_status=row["old_status"],
            new_status=row["new_status"],
            event_payload=json.loads(row["event_payload_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
        )

    def _row_to_signal_candle_record(self, row: aiosqlite.Row | None) -> SignalCandleRecord | None:
        if row is None:
            return None
        return SignalCandleRecord(
            id=int(row["id"]),
            signal_id=int(row["signal_id"]),
            alert_id=row["alert_id"],
            symbol=str(row["symbol"] or ""),
            timeframe=str(row["timeframe"] or ""),
            candle_open_time=datetime.fromisoformat(row["candle_open_time"]),
            candle_close_time=datetime.fromisoformat(row["candle_close_time"]),
            open_price=float(row["open_price"]),
            high_price=float(row["high_price"]),
            low_price=float(row["low_price"]),
            close_price=float(row["close_price"]),
            volume=float(row["volume"]) if row["volume"] is not None else None,
            quote_volume=float(row["quote_volume"]) if row["quote_volume"] is not None else None,
            source=str(row["source"] or "rest_backfill"),
            collected_at=datetime.fromisoformat(row["collected_at"]),
            processed_at=_to_dt(row["processed_at"]),
        )

    def _row_to_strategy_stats_snapshot_record(
        self,
        row: aiosqlite.Row | None,
    ) -> StrategyStatsSnapshotRecord | None:
        if row is None:
            return None
        return StrategyStatsSnapshotRecord(
            snapshot_id=row["snapshot_id"],
            strategy_code=row["strategy_code"],
            timeframe_bucket=row["timeframe_bucket"],
            market_regime_bucket=row["market_regime_bucket"],
            asset_cluster_bucket=row["asset_cluster_bucket"],
            period_type=row["period_type"],
            total_signals=int(row["total_signals"] or 0),
            wins=int(row["wins"] or 0),
            losses=int(row["losses"] or 0),
            expired_neutral=int(row["expired_neutral"] or 0),
            invalidated_count=int(row["invalidated_count"] or 0),
            avg_rr=row["avg_rr"],
            avg_time_to_win_minutes=row["avg_time_to_win_minutes"],
            avg_time_to_invalidation_minutes=row["avg_time_to_invalidation_minutes"],
            signals_per_day=row["signals_per_day"],
            best_tf=row["best_tf"],
            best_assets=row["best_assets"],
            best_regime=row["best_regime"],
            drawdown_profile=row["drawdown_profile"],
            calculated_at=datetime.fromisoformat(row["calculated_at"]),
            delivered_count=int(row["delivered_count"] or 0),
            suppressed_count=int(row["suppressed_count"] or 0),
            ambiguous_count=int(row["ambiguous_count"] or 0),
            sent_wins=int(row["sent_wins"] or 0),
            sent_losses=int(row["sent_losses"] or 0),
            sent_expired_neutral=int(row["sent_expired_neutral"] or 0),
            sent_ambiguous_count=int(row["sent_ambiguous_count"] or 0),
            sent_avg_rr=row["sent_avg_rr"],
            sent_signals_per_day=row["sent_signals_per_day"],
            sent_best_tf=row["sent_best_tf"],
            sent_best_assets=row["sent_best_assets"],
            sent_best_regime=row["sent_best_regime"],
        )

    def _row_to_premium_strategy_settings(
        self,
        row: aiosqlite.Row | None,
    ) -> PremiumStrategySettingsRecord | None:
        if row is None:
            return None
        return PremiumStrategySettingsRecord(
            telegram_user_id=row["telegram_user_id"],
            bot_kind=str(row["bot_kind"] or "premium"),
            strategy_key=str(row["strategy_key"] or "rsi"),
            direct_signal_delivery_enabled=bool(row["direct_signal_delivery_enabled"]),
            followup_delivery_enabled=bool(row["followup_delivery_enabled"]),
            signal_profile=str(row["signal_profile"] or "balanced"),
            base_signal_profile=str(row["base_signal_profile"] or "balanced"),
            preferred_min_score=row["preferred_min_score"],
            min_quote_volume=row["min_quote_volume"],
            rsi_oversold=row["rsi_oversold"],
            rsi_overbought=row["rsi_overbought"],
            direction_filter=str(row["direction_filter"] or "both"),
            watchlist_only=bool(row["watchlist_only"]),
            delivery_mode=str(row["delivery_mode"] or "instant"),
            delivery_mode_changed_at=_to_dt(row["delivery_mode_changed_at"]),
            quiet_hours_start_minute=row["quiet_hours_start_minute"],
            quiet_hours_end_minute=row["quiet_hours_end_minute"],
            snooze_until=_to_dt(row["snooze_until"]),
            snooze_started_at=_to_dt(row["snooze_started_at"]),
            snooze_label=row["snooze_label"],
            last_resume_summary_at=_to_dt(row["last_resume_summary_at"]),
            last_digest_sent_at=_to_dt(row["last_digest_sent_at"]),
            last_daily_recap_at=_to_dt(row["last_daily_recap_at"]),
            last_weekly_recap_at=_to_dt(row["last_weekly_recap_at"]),
            active_watchlist_theme=str(row["active_watchlist_theme"] or "custom"),
            active_custom_theme_name=row["active_custom_theme_name"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
            strategy_preferences=json.loads(row["strategy_preferences_json"] or "{}"),
        )

    def _row_to_alert_record(self, row: aiosqlite.Row | None) -> AlertRecord | None:
        if row is None:
            return None
        return AlertRecord(
            id=row["id"],
            symbol=row["symbol"],
            direction=row["direction"],
            timeframe=row["timeframe"],
            candle_open_time=datetime.fromisoformat(row["candle_open_time"]),
            candle_close_time=datetime.fromisoformat(row["candle_close_time"]),
            alert_price=row["alert_price"],
            alert_rsi=row["alert_rsi"],
            day_change_pct=row["day_change_pct"],
            day_volume=row["day_volume"],
            score=row["score"],
            alert_sent_at=datetime.fromisoformat(row["alert_sent_at"]),
            followup_due_at=datetime.fromisoformat(row["followup_due_at"]),
            followup_sent_at=_to_dt(row["followup_sent_at"]),
            lab_message_id=row["lab_message_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            strategy_key=str(row["strategy_key"] or "rsi") if "strategy_key" in row.keys() else "rsi",
        )

    def _row_to_followup_result_record(
        self,
        row: aiosqlite.Row | None,
    ) -> FollowUpResultRecord | None:
        if row is None:
            return None
        return FollowUpResultRecord(
            alert_id=row["alert_id"],
            stage=row["stage"] if "stage" in row.keys() else "2h",
            symbol=row["symbol"],
            direction=row["direction"],
            timeframe=row["timeframe"],
            alert_price=row["alert_price"],
            alert_rsi=row["alert_rsi"],
            score=row["score"],
            current_price=row["current_price"],
            current_rsi=row["current_rsi"],
            move_pct=row["move_pct"],
            summary=row["summary"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    async def _connect(self) -> aiosqlite.Connection:
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.sqlite_path, timeout=5.0)
            self._connection.row_factory = aiosqlite.Row
            # Keep SQLite responsive under concurrent bot traffic.
            await self._connection.execute("PRAGMA journal_mode = WAL")
            await self._connection.execute("PRAGMA synchronous = NORMAL")
            await self._connection.execute("PRAGMA temp_store = MEMORY")
            await self._connection.execute("PRAGMA cache_size = -20000")
            await self._connection.execute("PRAGMA mmap_size = 268435456")
            await self._connection.execute("PRAGMA wal_autocheckpoint = 1000")
            await self._connection.execute("PRAGMA busy_timeout = 5000")
            await self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    async def connect(self) -> None:
        await self._connect()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def get_symbol_state(self, symbol: str) -> SymbolState | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM symbol_state
                WHERE symbol = ?
                """,
                (symbol,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return SymbolState(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                last_rsi=row["last_rsi"],
                zone=row["zone"],
                oversold_active=bool(row["oversold_active"]),
                overbought_active=bool(row["overbought_active"]),
                oversold_last_alert_at=_to_dt(row["oversold_last_alert_at"]),
                overbought_last_alert_at=_to_dt(row["overbought_last_alert_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    async def upsert_symbol_state(
        self,
        *,
        symbol: str,
        timeframe: str,
        last_rsi: float,
        zone: str,
        oversold_active: bool,
        overbought_active: bool,
        oversold_last_alert_at: datetime | None,
        overbought_last_alert_at: datetime | None,
        updated_at: datetime | None = None,
    ) -> None:
        timestamp = (updated_at or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO symbol_state (
                    symbol,
                    timeframe,
                    last_rsi,
                    zone,
                    oversold_active,
                    overbought_active,
                    oversold_last_alert_at,
                    overbought_last_alert_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    timeframe = excluded.timeframe,
                    last_rsi = excluded.last_rsi,
                    zone = excluded.zone,
                    oversold_active = excluded.oversold_active,
                    overbought_active = excluded.overbought_active,
                    oversold_last_alert_at = excluded.oversold_last_alert_at,
                    overbought_last_alert_at = excluded.overbought_last_alert_at,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    timeframe,
                    last_rsi,
                    zone,
                    int(oversold_active),
                    int(overbought_active),
                    oversold_last_alert_at.isoformat() if oversold_last_alert_at else None,
                    overbought_last_alert_at.isoformat() if overbought_last_alert_at else None,
                    timestamp,
                ),
            )
            await connection.commit()

    async def alert_exists_for_candle(
        self,
        *,
        symbol: str,
        direction: str,
        strategy_key: str,
        timeframe: str,
        candle_open_time: datetime,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT 1
                FROM alerts
                WHERE symbol = ?
                  AND direction = ?
                  AND strategy_key = ?
                  AND timeframe = ?
                  AND candle_open_time = ?
                LIMIT 1
                """,
                (symbol, direction, strategy_key, timeframe, candle_open_time.isoformat()),
            )
            return await cursor.fetchone() is not None

    async def create_alert(
        self,
        signal: AlertSignal,
        *,
        sent_at: datetime,
        followup_due_at: datetime,
        lab_message_id: int | None,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                INSERT INTO alerts (
                    symbol,
                    direction,
                    strategy_key,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    alert_price,
                    alert_rsi,
                    day_change_pct,
                    day_volume,
                    score,
                    alert_sent_at,
                    followup_due_at,
                    lab_message_id,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.symbol,
                    signal.direction,
                    str(signal.metadata.get("strategy_key") or "rsi"),
                    signal.timeframe,
                    signal.candle_open_time.isoformat(),
                    signal.candle_close_time.isoformat(),
                    signal.price,
                    signal.rsi,
                    signal.day_change_pct,
                    signal.day_volume,
                    signal.score,
                    sent_at.isoformat(),
                    followup_due_at.isoformat(),
                    lab_message_id,
                    _to_json(
                        {
                            **signal.metadata,
                            "explanation": signal.explanation,
                            "quote_volume": signal.quote_volume,
                            "atr_pct": signal.atr_pct,
                        }
                    ),
                ),
            )
            alert_id = cursor.lastrowid
            for stage_label, stage_delay_seconds in self._followup_stages():
                due_at = sent_at + timedelta(seconds=stage_delay_seconds)
                await connection.execute(
                    """
                    INSERT INTO followup_stage_tasks (
                        alert_id,
                        symbol,
                        direction,
                        stage,
                        due_at,
                        status,
                        attempts,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)
                    """,
                    (
                        alert_id,
                        signal.symbol,
                        signal.direction,
                        stage_label,
                        due_at.isoformat(),
                        sent_at.isoformat(),
                    ),
                )
            await connection.commit()
            return int(alert_id)

    async def get_alert(self, alert_id: int) -> AlertRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE id = ?
                """,
                (alert_id,),
            )
            return self._row_to_alert_record(await cursor.fetchone())

    async def list_alerts_by_ids(self, alert_ids: Sequence[int]) -> list[AlertRecord]:
        normalized_ids = sorted({int(alert_id) for alert_id in alert_ids if int(alert_id) > 0})
        if not normalized_ids:
            return []
        async with self._lock:
            connection = await self._connect()
            placeholders = ", ".join("?" for _ in normalized_ids)
            cursor = await connection.execute(
                f"""
                SELECT *
                FROM alerts
                WHERE id IN ({placeholders})
                """,
                normalized_ids,
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_alert_record(row)) is not None]

    async def list_recent_alerts_for_symbol(self, symbol: str, *, limit: int = 12) -> list[AlertRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE symbol = ?
                ORDER BY alert_sent_at DESC
                LIMIT ?
                """,
                (symbol, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_alert_record(row)) is not None]

    async def update_alert_lab_message_id(self, alert_id: int, lab_message_id: int | None) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE alerts
                SET lab_message_id = ?
                WHERE id = ?
                """,
                (lab_message_id, alert_id),
            )
            await connection.commit()

    async def get_followup_result(self, alert_id: int) -> FollowUpResultRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM followup_stage_results
                WHERE alert_id = ?
                ORDER BY observed_at DESC
                LIMIT 1
                """,
                (alert_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute(
                    """
                    SELECT *
                    FROM followup_results
                    WHERE alert_id = ?
                    """,
                    (alert_id,),
                )
                row = await cursor.fetchone()
            return self._row_to_followup_result_record(row)

    async def list_latest_followup_results_for_alert_ids(self, alert_ids: Sequence[int]) -> list[FollowUpResultRecord]:
        normalized_ids = sorted({int(alert_id) for alert_id in alert_ids if int(alert_id) > 0})
        if not normalized_ids:
            return []
        async with self._lock:
            connection = await self._connect()
            placeholders = ", ".join("?" for _ in normalized_ids)
            cursor = await connection.execute(
                f"""
                SELECT * FROM (
                    SELECT
                        result.*,
                        ROW_NUMBER() OVER (PARTITION BY result.alert_id ORDER BY result.observed_at DESC) AS latest_rank
                    FROM followup_stage_results AS result
                    WHERE result.alert_id IN ({placeholders})
                )
                WHERE latest_rank = 1
                ORDER BY alert_id ASC
                """,
                normalized_ids,
            )
            rows = await cursor.fetchall()
            if not rows:
                cursor = await connection.execute(
                    f"""
                    SELECT *,
                           '2h' AS stage
                    FROM followup_results
                    WHERE alert_id IN ({placeholders})
                    ORDER BY alert_id ASC, observed_at DESC
                    """,
                    normalized_ids,
                )
                rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_followup_result_record(row)) is not None]

    async def get_next_due_followup(self) -> FollowUpTaskRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM followup_stage_tasks
                WHERE status = 'pending'
                ORDER BY due_at ASC
                LIMIT 1
                """,
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute(
                    """
                    SELECT *,
                           '2h' AS stage
                    FROM followup_tasks
                    WHERE status = 'pending'
                    ORDER BY due_at ASC
                    LIMIT 1
                    """,
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
            return FollowUpTaskRecord(
                id=row["id"],
                alert_id=row["alert_id"],
                symbol=row["symbol"],
                direction=row["direction"],
                stage=row["stage"],
                due_at=datetime.fromisoformat(row["due_at"]),
                status=row["status"],
                attempts=row["attempts"],
                last_error=row["last_error"],
                created_at=datetime.fromisoformat(row["created_at"]),
                executed_at=_to_dt(row["executed_at"]),
            )

    async def get_due_followups(self, now: datetime | None = None) -> list[FollowUpTaskRecord]:
        effective_now = (now or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM followup_stage_tasks
                WHERE status = 'pending'
                  AND due_at <= ?
                ORDER BY due_at ASC
                """,
                (effective_now,),
            )
            rows = await cursor.fetchall()
            if not rows:
                cursor = await connection.execute(
                    """
                    SELECT *,
                           '2h' AS stage
                    FROM followup_tasks
                    WHERE status = 'pending'
                      AND due_at <= ?
                    ORDER BY due_at ASC
                    """,
                    (effective_now,),
                )
                rows = await cursor.fetchall()
            return [
                FollowUpTaskRecord(
                    id=row["id"],
                    alert_id=row["alert_id"],
                    symbol=row["symbol"],
                    direction=row["direction"],
                    stage=row["stage"],
                    due_at=datetime.fromisoformat(row["due_at"]),
                    status=row["status"],
                    attempts=row["attempts"],
                    last_error=row["last_error"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    executed_at=_to_dt(row["executed_at"]),
                )
                for row in rows
            ]

    async def mark_followup_processing(self, task_id: int, attempts: int) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE followup_stage_tasks
                SET status = 'processing',
                    attempts = ?
                WHERE id = ?
                """,
                (attempts, task_id),
            )
            await connection.commit()

    async def mark_followup_pending(self, task_id: int, error: str) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE followup_stage_tasks
                SET status = 'pending',
                    last_error = ?
                WHERE id = ?
                """,
                (error[:500], task_id),
            )
            await connection.commit()

    async def reschedule_followup(
        self,
        task_id: int,
        next_due_at: datetime,
        error: str,
        attempts: int,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE followup_stage_tasks
                SET status = 'pending',
                    due_at = ?,
                    last_error = ?,
                    attempts = ?
                WHERE id = ?
                """,
                (next_due_at.isoformat(), error[:500], attempts, task_id),
            )
            await connection.commit()

    async def mark_followup_complete(self, task_id: int, alert_id: int, executed_at: datetime) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE followup_stage_tasks
                SET status = 'completed',
                    executed_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                (executed_at.isoformat(), task_id),
            )
            await connection.execute(
                """
                UPDATE alerts
                SET followup_sent_at = ?
                WHERE id = ?
                """,
                (executed_at.isoformat(), alert_id),
            )
            await connection.commit()

    async def mark_followup_skipped(self, task_id: int, reason: str, executed_at: datetime) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE followup_stage_tasks
                SET status = 'skipped',
                    executed_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (executed_at.isoformat(), reason[:500], task_id),
            )
            await connection.commit()

    async def create_scheduled_generated_post(
        self,
        *,
        post: GeneratedPost,
        due_at: datetime,
        created_at: datetime | None = None,
    ) -> int:
        timestamp = created_at or utc_now()
        payload = {
            "channel_kind": post.channel_kind,
            "destination": post.destination,
            "content_type": post.content_type,
            "generated_text": post.generated_text,
            "delivery_text": post.delivery_text,
            "status": post.status,
            "chart_path": str(post.chart_path) if post.chart_path is not None else None,
            "ai_model": post.ai_model,
            "source_symbol": post.source_symbol,
            "related_alert_id": post.related_alert_id,
            "force_autopost": post.force_autopost,
            "send_lab_copy": post.send_lab_copy,
            "bundle_in_lab_review": post.bundle_in_lab_review,
            "metadata": post.metadata,
        }
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                INSERT INTO scheduled_generated_posts (
                    channel_kind,
                    destination,
                    content_type,
                    payload_json,
                    due_at,
                    status,
                    attempts,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    post.channel_kind,
                    post.destination,
                    post.content_type,
                    _to_json(payload),
                    due_at.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            await connection.commit()
            return int(cursor.lastrowid)

    async def get_next_due_scheduled_generated_post(self) -> ScheduledGeneratedPostRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM scheduled_generated_posts
                WHERE status = 'pending'
                ORDER BY due_at ASC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return ScheduledGeneratedPostRecord(
                id=row["id"],
                channel_kind=row["channel_kind"],
                destination=row["destination"],
                content_type=row["content_type"],
                payload=json.loads(row["payload_json"] or "{}"),
                due_at=datetime.fromisoformat(row["due_at"]),
                status=row["status"],
                attempts=row["attempts"],
                last_error=row["last_error"],
                created_at=datetime.fromisoformat(row["created_at"]),
                sent_at=_to_dt(row["sent_at"]),
            )

    async def get_due_scheduled_generated_posts(
        self,
        now: datetime | None = None,
    ) -> list[ScheduledGeneratedPostRecord]:
        effective_now = (now or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM scheduled_generated_posts
                WHERE status = 'pending'
                  AND due_at <= ?
                ORDER BY due_at ASC
                """,
                (effective_now,),
            )
            rows = await cursor.fetchall()
            return [
                ScheduledGeneratedPostRecord(
                    id=row["id"],
                    channel_kind=row["channel_kind"],
                    destination=row["destination"],
                    content_type=row["content_type"],
                    payload=json.loads(row["payload_json"] or "{}"),
                    due_at=datetime.fromisoformat(row["due_at"]),
                    status=row["status"],
                    attempts=row["attempts"],
                    last_error=row["last_error"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    sent_at=_to_dt(row["sent_at"]),
                )
                for row in rows
            ]

    async def mark_scheduled_generated_post_processing(self, task_id: int, attempts: int) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE scheduled_generated_posts
                SET status = 'processing',
                    attempts = ?
                WHERE id = ?
                """,
                (attempts, task_id),
            )
            await connection.commit()

    async def reschedule_scheduled_generated_post(
        self,
        task_id: int,
        next_due_at: datetime,
        error: str,
        attempts: int,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE scheduled_generated_posts
                SET status = 'pending',
                    due_at = ?,
                    last_error = ?,
                    attempts = ?
                WHERE id = ?
                """,
                (next_due_at.isoformat(), error[:500], attempts, task_id),
            )
            await connection.commit()

    async def mark_scheduled_generated_post_sent(self, task_id: int, sent_at: datetime) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE scheduled_generated_posts
                SET status = 'sent',
                    sent_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                (sent_at.isoformat(), task_id),
            )
            await connection.commit()

    async def mark_scheduled_generated_post_skipped(self, task_id: int, reason: str, sent_at: datetime) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE scheduled_generated_posts
                SET status = 'skipped',
                    sent_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (sent_at.isoformat(), reason[:500], task_id),
            )
            await connection.commit()

    async def save_generated_post(
        self,
        *,
        post: GeneratedPost,
        created_at: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        timestamp = created_at or utc_now()
        content_value = post.delivery_text or post.generated_text
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO posts_history (
                    alert_id,
                    related_alert_id,
                    source_symbol,
                    channel_kind,
                    destination,
                    content_type,
                    content,
                    generated_text,
                    short_variant,
                    reply_variant,
                    status,
                    ai_model,
                    model_name,
                    created_at,
                    sent_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.related_alert_id,
                    post.related_alert_id,
                    post.source_symbol,
                    post.channel_kind,
                    post.destination,
                    post.content_type,
                    content_value,
                    post.generated_text,
                    None,
                    None,
                    post.status,
                    post.ai_model,
                    post.ai_model,
                    timestamp.isoformat(),
                    sent_at.isoformat() if sent_at else None,
                    _to_json({**post.metadata, "chart_attached": bool(post.chart_path)}),
                ),
            )
            await connection.commit()

    async def save_twitter_draft(
        self,
        *,
        draft: TwitterDraft,
        created_at: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        timestamp = created_at or utc_now()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO posts_history (
                    alert_id,
                    related_alert_id,
                    source_symbol,
                    channel_kind,
                    destination,
                    content_type,
                    content,
                    generated_text,
                    short_variant,
                    reply_variant,
                    status,
                    ai_model,
                    model_name,
                    created_at,
                    sent_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.related_alert_id,
                    draft.related_alert_id,
                    draft.source_symbol,
                    "twitter_drafts",
                    "twitter_drafts",
                    draft.content_type,
                    draft.main_text,
                    draft.main_text,
                    draft.short_variant,
                    draft.reply_variant,
                    draft.status,
                    draft.writer_model,
                    draft.writer_model,
                    timestamp.isoformat(),
                    sent_at.isoformat() if sent_at else None,
                    _to_json(
                        {
                            **draft.metadata,
                            "mode": draft.mode,
                            "angle": draft.angle,
                            "value_types": list(draft.value_types),
                            "similarity_score": draft.similarity_score,
                            "rewritten_for_similarity": draft.rewritten_for_similarity,
                            "preview_mode": draft.preview_mode,
                            "skipped_reason": draft.skipped_reason,
                            "telegram_destination": draft.destination,
                            "analysis_model": draft.analysis_model,
                            "writer_model": draft.writer_model,
                            "chart_attached": bool(draft.chart_path),
                        }
                    ),
                ),
            )
            await connection.commit()

    async def save_followup_result(self, result: FollowUpResult) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO followup_stage_results (
                    alert_id,
                    stage,
                    symbol,
                    direction,
                    timeframe,
                    alert_price,
                    alert_rsi,
                    score,
                    current_price,
                    current_rsi,
                    move_pct,
                    summary,
                    observed_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id, stage) DO UPDATE SET
                    symbol = excluded.symbol,
                    direction = excluded.direction,
                    timeframe = excluded.timeframe,
                    alert_price = excluded.alert_price,
                    alert_rsi = excluded.alert_rsi,
                    score = excluded.score,
                    current_price = excluded.current_price,
                    current_rsi = excluded.current_rsi,
                    move_pct = excluded.move_pct,
                    summary = excluded.summary,
                    observed_at = excluded.observed_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    result.alert_id,
                    result.stage,
                    result.symbol,
                    result.direction,
                    result.timeframe,
                    result.alert_price,
                    result.alert_rsi,
                    result.score,
                    result.current_price,
                    result.current_rsi,
                    result.move_pct,
                    result.summary,
                    result.observed_at.isoformat(),
                    _to_json(result.metadata),
                ),
            )
            await connection.execute(
                """
                INSERT INTO followup_results (
                    alert_id,
                    symbol,
                    direction,
                    timeframe,
                    alert_price,
                    alert_rsi,
                    score,
                    current_price,
                    current_rsi,
                    move_pct,
                    summary,
                    observed_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    direction = excluded.direction,
                    timeframe = excluded.timeframe,
                    alert_price = excluded.alert_price,
                    alert_rsi = excluded.alert_rsi,
                    score = excluded.score,
                    current_price = excluded.current_price,
                    current_rsi = excluded.current_rsi,
                    move_pct = excluded.move_pct,
                    summary = excluded.summary,
                    observed_at = excluded.observed_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    result.alert_id,
                    result.symbol,
                    result.direction,
                    result.timeframe,
                    result.alert_price,
                    result.alert_rsi,
                    result.score,
                    result.current_price,
                    result.current_rsi,
                    result.move_pct,
                    result.summary,
                    result.observed_at.isoformat(),
                    _to_json({**result.metadata, "stage": result.stage}),
                ),
            )
            await connection.commit()

    async def upsert_interactive_alert_state(
        self,
        *,
        chat_id: str,
        message_id: int,
        alert_id: int | None,
        destination_kind: str,
        symbol: str,
        original_timeframe: str,
        displayed_timeframe: str,
        direction: str,
        is_preview: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timestamp = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO interactive_alerts (
                    chat_id,
                    message_id,
                    alert_id,
                    destination_kind,
                    symbol,
                    original_timeframe,
                    displayed_timeframe,
                    direction,
                    is_preview,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    alert_id = excluded.alert_id,
                    destination_kind = excluded.destination_kind,
                    symbol = excluded.symbol,
                    original_timeframe = excluded.original_timeframe,
                    displayed_timeframe = excluded.displayed_timeframe,
                    direction = excluded.direction,
                    is_preview = excluded.is_preview,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    chat_id,
                    message_id,
                    alert_id,
                    destination_kind,
                    symbol,
                    original_timeframe,
                    displayed_timeframe,
                    direction,
                    int(is_preview),
                    timestamp,
                    timestamp,
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()

    async def get_interactive_alert_state(
        self,
        *,
        chat_id: str,
        message_id: int,
    ) -> InteractiveAlertState | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM interactive_alerts
                WHERE chat_id = ?
                  AND message_id = ?
                """,
                (chat_id, message_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return InteractiveAlertState(
                id=row["id"],
                chat_id=row["chat_id"],
                message_id=row["message_id"],
                alert_id=row["alert_id"],
                destination_kind=row["destination_kind"],
                symbol=row["symbol"],
                original_timeframe=row["original_timeframe"],
                displayed_timeframe=row["displayed_timeframe"],
                direction=row["direction"],
                is_preview=bool(row["is_preview"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def get_interactive_alert_state_by_message_id(
        self,
        *,
        message_id: int,
        symbol: str | None = None,
        chat_id_prefix: str | None = None,
    ) -> InteractiveAlertState | None:
        async with self._lock:
            connection = await self._connect()
            prefix_filter = ""
            parameters: list[Any]
            if symbol:
                query = """
                    SELECT *
                    FROM interactive_alerts
                    WHERE message_id = ?
                      AND symbol = ?
                """
                parameters = [message_id, symbol]
            else:
                query = """
                    SELECT *
                    FROM interactive_alerts
                    WHERE message_id = ?
                """
                parameters = [message_id]
            if chat_id_prefix:
                query += "\n  AND chat_id LIKE ?"
                parameters.append(f"{chat_id_prefix}:%")
            query += "\n ORDER BY updated_at DESC LIMIT 1"
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            if row is None:
                return None
            return InteractiveAlertState(
                id=row["id"],
                chat_id=row["chat_id"],
                message_id=row["message_id"],
                alert_id=row["alert_id"],
                destination_kind=row["destination_kind"],
                symbol=row["symbol"],
                original_timeframe=row["original_timeframe"],
                displayed_timeframe=row["displayed_timeframe"],
                direction=row["direction"],
                is_preview=bool(row["is_preview"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def update_interactive_alert_display(
        self,
        *,
        state_id: int,
        displayed_timeframe: str,
        direction: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timestamp = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE interactive_alerts
                SET displayed_timeframe = ?,
                    direction = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    displayed_timeframe,
                    direction,
                    timestamp,
                    _to_json(metadata or {}),
                    state_id,
                ),
            )
            await connection.commit()

    async def rebind_interactive_alert_message(
        self,
        *,
        state_id: int,
        chat_id: str,
        message_id: int,
        displayed_timeframe: str,
        direction: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timestamp = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE interactive_alerts
                SET chat_id = ?,
                    message_id = ?,
                    displayed_timeframe = ?,
                    direction = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    chat_id,
                    message_id,
                    displayed_timeframe,
                    direction,
                    timestamp,
                    _to_json(metadata or {}),
                    state_id,
                ),
            )
            await connection.commit()

    async def update_interactive_alert_binding(
        self,
        *,
        state_id: int,
        alert_id: int,
        symbol: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timestamp = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE interactive_alerts
                SET alert_id = ?,
                    symbol = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    alert_id,
                    symbol,
                    timestamp,
                    _to_json(metadata or {}),
                    state_id,
                ),
            )
            await connection.commit()

    async def get_cached_analysis(
        self,
        *,
        symbol: str,
        timeframe: str,
        analysis_type: str,
        alert_id: int | None,
        now: datetime | None = None,
    ) -> CachedAnalysisRecord | None:
        effective_now = (now or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            if alert_id is None:
                cursor = await connection.execute(
                    """
                    SELECT *
                    FROM analysis_cache
                    WHERE symbol = ?
                      AND timeframe = ?
                      AND analysis_type = ?
                      AND alert_id IS NULL
                      AND expires_at > ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (symbol, timeframe, analysis_type, effective_now),
                )
            else:
                cursor = await connection.execute(
                    """
                    SELECT *
                    FROM analysis_cache
                    WHERE symbol = ?
                      AND timeframe = ?
                      AND analysis_type = ?
                      AND (alert_id = ? OR alert_id IS NULL)
                      AND expires_at > ?
                    ORDER BY CASE WHEN alert_id = ? THEN 0 ELSE 1 END, created_at DESC
                    LIMIT 1
                    """,
                    (symbol, timeframe, analysis_type, alert_id, effective_now, alert_id),
                )
            row = await cursor.fetchone()
            if row is None:
                return None
            return CachedAnalysisRecord(
                id=row["id"],
                alert_id=row["alert_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                analysis_type=row["analysis_type"],
                content=row["content"],
                model_name=row["model_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def save_cached_analysis(
        self,
        *,
        symbol: str,
        timeframe: str,
        analysis_type: str,
        content: str,
        model_name: str | None,
        alert_id: int | None,
        expires_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        created_at = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO analysis_cache (
                    alert_id,
                    symbol,
                    timeframe,
                    analysis_type,
                    content,
                    model_name,
                    created_at,
                    expires_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    symbol,
                    timeframe,
                    analysis_type,
                    content,
                    model_name,
                    created_at,
                    expires_at.isoformat(),
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()

    async def get_prepared_feature_card(
        self,
        *,
        symbol: str,
        timeframe: str,
        content_type: str,
        source_data_hash: str,
        alert_id: int | None,
        ready_only: bool = True,
    ) -> PreparedFeatureCardRecord | None:
        async with self._lock:
            connection = await self._connect()
            if alert_id is None:
                query = """
                    SELECT *
                    FROM prepared_feature_cards
                    WHERE symbol = ?
                      AND timeframe = ?
                      AND content_type = ?
                      AND source_data_hash = ?
                      AND alert_id IS NULL
                """
                parameters: list[Any] = [symbol, timeframe, content_type, source_data_hash]
            else:
                query = """
                    SELECT *
                    FROM prepared_feature_cards
                    WHERE symbol = ?
                      AND timeframe = ?
                      AND content_type = ?
                      AND source_data_hash = ?
                      AND (alert_id = ? OR alert_id IS NULL)
                """
                parameters = [symbol, timeframe, content_type, source_data_hash, alert_id]
            if ready_only:
                query += "\n  AND is_ready = 1"
            query += "\nORDER BY CASE WHEN alert_id = ? THEN 0 ELSE 1 END, updated_at DESC LIMIT 1"
            parameters.append(alert_id if alert_id is not None else -1)
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            if row is None:
                return None
            return PreparedFeatureCardRecord(
                id=row["id"],
                alert_id=row["alert_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                content_type=row["content_type"],
                source_data_hash=row["source_data_hash"],
                text_payload=row["text_payload"] or "",
                json_payload=json.loads(row["json_payload"] or "{}"),
                model_name=row["model_name"],
                is_ready=bool(row["is_ready"]),
                generated_at=datetime.fromisoformat(row["generated_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def save_prepared_feature_card(
        self,
        *,
        symbol: str,
        timeframe: str,
        content_type: str,
        source_data_hash: str,
        alert_id: int | None,
        text_payload: str,
        json_payload: dict[str, Any] | None,
        model_name: str | None,
        is_ready: bool,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now().isoformat()
        existing = await self.get_prepared_feature_card(
            symbol=symbol,
            timeframe=timeframe,
            content_type=content_type,
            source_data_hash=source_data_hash,
            alert_id=alert_id,
            ready_only=False,
        )
        async with self._lock:
            connection = await self._connect()
            if existing is None:
                cursor = await connection.execute(
                    """
                    INSERT INTO prepared_feature_cards (
                        alert_id,
                        symbol,
                        timeframe,
                        content_type,
                        source_data_hash,
                        text_payload,
                        json_payload,
                        model_name,
                        is_ready,
                        generated_at,
                        updated_at,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert_id,
                        symbol,
                        timeframe,
                        content_type,
                        source_data_hash,
                        text_payload,
                        _to_json(json_payload or {}),
                        model_name,
                        int(is_ready),
                        now,
                        now,
                        _to_json(metadata or {}),
                    ),
                )
                await connection.commit()
                return int(cursor.lastrowid)

            await connection.execute(
                """
                UPDATE prepared_feature_cards
                SET text_payload = ?,
                    json_payload = ?,
                    model_name = ?,
                    is_ready = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    text_payload,
                    _to_json(json_payload or {}),
                    model_name,
                    int(is_ready),
                    now,
                    _to_json(metadata or {}),
                    existing.id,
                ),
            )
            await connection.commit()
            return existing.id

    async def upsert_private_user(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_active: bool = True,
        is_admin: bool | None = None,
        referred_by_user_id: int | None = None,
    ) -> PrivateBotUserRecord:
        now = utc_now().isoformat()
        effective_is_admin = bool(is_admin)
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO bot_users (
                    telegram_user_id,
                    username,
                    first_name,
                    last_name,
                    first_seen_at,
                    last_seen_at,
                    is_active,
                    access_level,
                    access_status,
                    is_admin,
                    referred_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, bot_users.username),
                    first_name = COALESCE(excluded.first_name, bot_users.first_name),
                    last_name = COALESCE(excluded.last_name, bot_users.last_name),
                    last_seen_at = excluded.last_seen_at,
                    is_active = excluded.is_active,
                    is_admin = CASE
                        WHEN excluded.is_admin = 1 THEN 1
                        ELSE bot_users.is_admin
                    END,
                    access_level = CASE
                        WHEN excluded.is_admin = 1 THEN 'admin'
                        ELSE bot_users.access_level
                    END,
                    access_status = CASE
                        WHEN excluded.is_admin = 1 THEN 'admin'
                        ELSE bot_users.access_status
                    END,
                    referred_by_user_id = COALESCE(bot_users.referred_by_user_id, excluded.referred_by_user_id)
                """,
                (
                    telegram_user_id,
                    username,
                    first_name,
                    last_name,
                    now,
                    now,
                    int(is_active),
                    "admin" if effective_is_admin else "free",
                    "admin" if effective_is_admin else "free",
                    int(effective_is_admin),
                    referred_by_user_id,
                ),
            )
            await connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_user_id,
                    direct_signal_delivery_enabled,
                    followup_delivery_enabled,
                    gold_alerts_enabled,
                    preferred_min_score,
                    updated_at
                )
                VALUES (?, 0, ?, 0, NULL, ?)
                ON CONFLICT(telegram_user_id) DO NOTHING
                """,
                (
                    telegram_user_id,
                    int(get_settings().private_bot_followups_default),
                    now,
                ),
            )
            await connection.commit()

        user = await self.get_private_user(telegram_user_id)
        assert user is not None
        return user

    async def get_private_user(self, telegram_user_id: int) -> PrivateBotUserRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM bot_users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return PrivateBotUserRecord(
                telegram_user_id=row["telegram_user_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
                is_active=bool(row["is_active"]),
                access_level=row["access_level"],
                access_status=row["access_status"],
                is_admin=bool(row["is_admin"]),
                referral_code=row["referral_code"],
                referred_by_user_id=row["referred_by_user_id"],
            )

    async def upsert_chat_member_roster(
        self,
        *,
        chat_id: str,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_bot: bool,
        seen_at: datetime | None = None,
    ) -> ChatMemberRosterRecord:
        timestamp = (seen_at or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO chat_member_roster (
                    chat_id,
                    telegram_user_id,
                    username,
                    first_name,
                    last_name,
                    is_bot,
                    created_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, telegram_user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, chat_member_roster.username),
                    first_name = COALESCE(excluded.first_name, chat_member_roster.first_name),
                    last_name = COALESCE(excluded.last_name, chat_member_roster.last_name),
                    is_bot = excluded.is_bot,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    str(chat_id),
                    int(telegram_user_id),
                    username,
                    first_name,
                    last_name,
                    int(bool(is_bot)),
                    timestamp,
                    timestamp,
                ),
            )
            await connection.commit()
            cursor = await connection.execute(
                """
                SELECT *
                FROM chat_member_roster
                WHERE chat_id = ? AND telegram_user_id = ?
                """,
                (str(chat_id), int(telegram_user_id)),
            )
            return self._row_to_chat_member_roster_record(await cursor.fetchone())  # type: ignore[return-value]

    async def list_chat_member_roster(
        self,
        chat_id: str,
        *,
        limit: int = 50,
        include_bots: bool = False,
    ) -> list[ChatMemberRosterRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                f"""
                SELECT *
                FROM chat_member_roster
                WHERE chat_id = ?
                  {" " if include_bots else "AND is_bot = 0"}
                ORDER BY last_seen_at DESC, telegram_user_id DESC
                LIMIT ?
                """,
                (str(chat_id), max(1, int(limit))),
            )
            rows = await cursor.fetchall()
            return [
                record
                for row in rows
                if (record := self._row_to_chat_member_roster_record(row)) is not None
            ]

    async def get_private_user_by_referral_code(self, referral_code: str) -> PrivateBotUserRecord | None:
        normalized_code = str(referral_code or "").strip()
        if not normalized_code:
            return None
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM bot_users
                WHERE referral_code = ?
                LIMIT 1
                """,
                (normalized_code,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return PrivateBotUserRecord(
                telegram_user_id=row["telegram_user_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
                is_active=bool(row["is_active"]),
                access_level=row["access_level"],
                access_status=row["access_status"],
                is_admin=bool(row["is_admin"]),
                referral_code=row["referral_code"],
                referred_by_user_id=row["referred_by_user_id"],
            )

    async def set_private_user_referral_code(
        self,
        *,
        telegram_user_id: int,
        referral_code: str,
    ) -> None:
        normalized_code = str(referral_code or "").strip()
        if not normalized_code:
            return
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE bot_users
                SET referral_code = COALESCE(referral_code, ?),
                    last_seen_at = ?
                WHERE telegram_user_id = ?
                """,
                (
                    normalized_code,
                    utc_now().isoformat(),
                    telegram_user_id,
                ),
            )
            await connection.commit()

    async def get_user_settings(self, telegram_user_id: int, *, bot_kind: str = "premium") -> UserSettingsRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_bot_settings
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            row = await cursor.fetchone()
            return self._row_to_user_settings(row)

    async def upsert_user_settings(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        direct_signal_delivery_enabled: bool,
        followup_delivery_enabled: bool | None = None,
        gold_alerts_enabled: bool | None = None,
        language_code: str | None = None,
        signal_profile: str | None = None,
        base_signal_profile: str | None = None,
        preferred_min_score: int | None = None,
        min_quote_volume: float | None = None,
        rsi_oversold: float | None = None,
        rsi_overbought: float | None = None,
        direction_filter: str | None = None,
        watchlist_only: bool | None = None,
        menu_collapsed: bool | None = None,
        delivery_mode: str | None = None,
        delivery_mode_changed_at=...,
        quiet_hours_start_minute=...,
        quiet_hours_end_minute=...,
        snooze_until=...,
        snooze_started_at=...,
        snooze_label=...,
        last_resume_summary_at=...,
        last_digest_sent_at=...,
        last_daily_recap_at=...,
        last_weekly_recap_at=...,
        active_watchlist_theme: str | None = None,
        active_custom_theme_name=...,
        onboarding_completed_at=...,
        enabled_strategy_keys: Sequence[str] | None = None,
        active_strategy_key=...,
        strategy_selector_completed_at=...,
        current_context=...,
        current_strategy_context=...,
        current_set_id=...,
        timezone_name=...,
        display_mode: str | None = None,
        active_workspace=...,
        saved_workspace_payload: dict[str, Any] | None = None,
        strategy_preferences: dict[str, Any] | None = None,
        personalization: dict[str, Any] | None = None,
        delivery_rules: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT
                    followup_delivery_enabled,
                    gold_alerts_enabled,
                    language_code,
                    signal_profile,
                    base_signal_profile,
                    preferred_min_score,
                    min_quote_volume,
                    rsi_oversold,
                    rsi_overbought,
                    direction_filter,
                    watchlist_only,
                    menu_collapsed,
                    delivery_mode,
                    delivery_mode_changed_at,
                    quiet_hours_start_minute,
                    quiet_hours_end_minute,
                    snooze_until,
                    snooze_started_at,
                    snooze_label,
                    last_resume_summary_at,
                    last_digest_sent_at,
                    last_daily_recap_at,
                    last_weekly_recap_at,
                    active_watchlist_theme,
                    active_custom_theme_name,
                    onboarding_completed_at,
                    enabled_strategy_keys_json,
                    active_strategy_key,
                    strategy_selector_completed_at,
                    current_context,
                    current_strategy_context,
                    current_set_id,
                    timezone_name,
                    display_mode,
                    active_workspace,
                    saved_workspace_payload_json,
                    strategy_preferences_json,
                    personalization_json,
                    delivery_rules_json
                FROM user_bot_settings
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            existing = await cursor.fetchone()
            await cursor.close()
            default_followup = (
                get_settings().private_bot_followups_default
                if bot_kind == "premium"
                else get_settings().classic_bot_followups_default
            )
            default_gold = (
                get_settings().private_bot_gold_alerts_default
                if bot_kind == "premium"
                else False
            )
            effective_followup = (
                bool(existing["followup_delivery_enabled"])
                if followup_delivery_enabled is None and existing is not None
                else default_followup if followup_delivery_enabled is None
                else followup_delivery_enabled
            )
            effective_gold = (
                bool(existing["gold_alerts_enabled"])
                if gold_alerts_enabled is None and existing is not None
                else default_gold if gold_alerts_enabled is None
                else gold_alerts_enabled
            )
            effective_language_code = (
                str(existing["language_code"] or "en")
                if language_code is None and existing is not None
                else str(language_code or "en")
            )
            effective_profile = (
                str(existing["signal_profile"] or "balanced")
                if signal_profile is None and existing is not None
                else str(signal_profile or "balanced")
            )
            effective_base_profile = (
                str(existing["base_signal_profile"] or "balanced")
                if base_signal_profile is None and existing is not None
                else str(
                    base_signal_profile
                    or (signal_profile if str(signal_profile or "").strip().lower() in {"conservative", "balanced", "aggressive"} else "balanced")
                    or "balanced"
                )
            )
            effective_min_score = (
                existing["preferred_min_score"]
                if preferred_min_score is None and existing is not None
                else preferred_min_score
            )
            effective_min_quote_volume = (
                existing["min_quote_volume"]
                if min_quote_volume is None and existing is not None
                else min_quote_volume
            )
            effective_rsi_oversold = (
                existing["rsi_oversold"]
                if rsi_oversold is None and existing is not None
                else rsi_oversold
            )
            effective_rsi_overbought = (
                existing["rsi_overbought"]
                if rsi_overbought is None and existing is not None
                else rsi_overbought
            )
            effective_direction_filter = (
                str(existing["direction_filter"] or "both")
                if direction_filter is None and existing is not None
                else str(direction_filter or "both")
            )
            effective_watchlist_only = (
                bool(existing["watchlist_only"])
                if watchlist_only is None and existing is not None
                else False if watchlist_only is None
                else watchlist_only
            )
            effective_menu_collapsed = (
                bool(existing["menu_collapsed"])
                if menu_collapsed is None and existing is not None
                else False if menu_collapsed is None
                else menu_collapsed
            )
            effective_delivery_mode = (
                str(existing["delivery_mode"] or "instant")
                if delivery_mode is None and existing is not None
                else str(delivery_mode or "instant")
            )
            effective_delivery_mode_changed_at = (
                existing["delivery_mode_changed_at"]
                if delivery_mode_changed_at is Ellipsis and existing is not None
                else delivery_mode_changed_at.isoformat() if isinstance(delivery_mode_changed_at, datetime) else None
            )
            effective_quiet_hours_start = (
                existing["quiet_hours_start_minute"]
                if quiet_hours_start_minute is Ellipsis and existing is not None
                else None if quiet_hours_start_minute is Ellipsis
                else quiet_hours_start_minute
            )
            effective_quiet_hours_end = (
                existing["quiet_hours_end_minute"]
                if quiet_hours_end_minute is Ellipsis and existing is not None
                else None if quiet_hours_end_minute is Ellipsis
                else quiet_hours_end_minute
            )
            effective_snooze_until = (
                existing["snooze_until"]
                if snooze_until is Ellipsis and existing is not None
                else snooze_until.isoformat() if isinstance(snooze_until, datetime) else None
            )
            effective_snooze_started_at = (
                existing["snooze_started_at"]
                if snooze_started_at is Ellipsis and existing is not None
                else snooze_started_at.isoformat() if isinstance(snooze_started_at, datetime) else None
            )
            effective_snooze_label = (
                existing["snooze_label"]
                if snooze_label is Ellipsis and existing is not None
                else None if snooze_label is Ellipsis
                else snooze_label
            )
            effective_last_resume_summary_at = (
                existing["last_resume_summary_at"]
                if last_resume_summary_at is Ellipsis and existing is not None
                else last_resume_summary_at.isoformat() if isinstance(last_resume_summary_at, datetime) else None
            )
            effective_last_digest_sent_at = (
                existing["last_digest_sent_at"]
                if last_digest_sent_at is Ellipsis and existing is not None
                else last_digest_sent_at.isoformat() if isinstance(last_digest_sent_at, datetime) else None
            )
            effective_last_daily_recap_at = (
                existing["last_daily_recap_at"]
                if last_daily_recap_at is Ellipsis and existing is not None
                else last_daily_recap_at.isoformat() if isinstance(last_daily_recap_at, datetime) else None
            )
            effective_last_weekly_recap_at = (
                existing["last_weekly_recap_at"]
                if last_weekly_recap_at is Ellipsis and existing is not None
                else last_weekly_recap_at.isoformat() if isinstance(last_weekly_recap_at, datetime) else None
            )
            effective_active_watchlist_theme = (
                str(existing["active_watchlist_theme"] or "custom")
                if active_watchlist_theme is None and existing is not None
                else str(active_watchlist_theme or "custom")
            )
            effective_active_custom_theme_name = (
                existing["active_custom_theme_name"]
                if active_custom_theme_name is Ellipsis and existing is not None
                else None if active_custom_theme_name is Ellipsis
                else active_custom_theme_name
            )
            effective_onboarding_completed_at = (
                existing["onboarding_completed_at"]
                if onboarding_completed_at is Ellipsis and existing is not None
                else onboarding_completed_at.isoformat() if isinstance(onboarding_completed_at, datetime) else None
            )
            effective_enabled_strategy_keys = (
                _to_strategy_keys(existing["enabled_strategy_keys_json"])
                if enabled_strategy_keys is None and existing is not None
                else tuple(
                    key
                    for key in (
                        str(item or "").strip().lower()
                        for item in (enabled_strategy_keys or ())
                    )
                    if key in PREMIUM_STRATEGY_KEY_SET
                )
            )
            effective_active_strategy_key = (
                existing["active_strategy_key"]
                if active_strategy_key is Ellipsis and existing is not None
                else None if active_strategy_key is Ellipsis
                else str(active_strategy_key or "").strip().lower() or None
            )
            effective_strategy_selector_completed_at = (
                existing["strategy_selector_completed_at"]
                if strategy_selector_completed_at is Ellipsis and existing is not None
                else (
                    strategy_selector_completed_at.isoformat()
                    if isinstance(strategy_selector_completed_at, datetime)
                    else None
                )
            )
            effective_current_context = (
                existing["current_context"]
                if current_context is Ellipsis and existing is not None
                else None if current_context is Ellipsis
                else str(current_context or "").strip() or None
            )
            effective_current_strategy_context = (
                existing["current_strategy_context"]
                if current_strategy_context is Ellipsis and existing is not None
                else None if current_strategy_context is Ellipsis
                else str(current_strategy_context or "").strip() or None
            )
            effective_current_set_id = (
                existing["current_set_id"]
                if current_set_id is Ellipsis and existing is not None
                else None if current_set_id is Ellipsis
                else current_set_id
            )
            effective_timezone_name = (
                existing["timezone_name"]
                if timezone_name is Ellipsis and existing is not None
                else None if timezone_name is Ellipsis
                else str(timezone_name or "").strip() or None
            )
            effective_display_mode = (
                str(existing["display_mode"] or "pro")
                if display_mode is None and existing is not None
                else str(display_mode or "pro").strip().lower() or "pro"
            )
            if effective_display_mode not in {"simple", "pro"}:
                effective_display_mode = "pro"
            effective_active_workspace = (
                existing["active_workspace"]
                if active_workspace is Ellipsis and existing is not None
                else None if active_workspace is Ellipsis
                else str(active_workspace or "").strip().lower() or None
            )
            effective_saved_workspace_payload = (
                json.loads(existing["saved_workspace_payload_json"] or "{}")
                if saved_workspace_payload is None and existing is not None
                else saved_workspace_payload or {}
            )
            effective_strategy_preferences = (
                json.loads(existing["strategy_preferences_json"] or "{}")
                if strategy_preferences is None and existing is not None
                else strategy_preferences or {}
            )
            effective_personalization = (
                json.loads(existing["personalization_json"] or "{}")
                if personalization is None and existing is not None
                else personalization or {}
            )
            effective_delivery_rules = (
                json.loads(existing["delivery_rules_json"] or "{}")
                if delivery_rules is None and existing is not None
                else delivery_rules or {}
            )
            await connection.execute(
                """
                INSERT INTO user_bot_settings (
                    telegram_user_id,
                    bot_kind,
                    direct_signal_delivery_enabled,
                    followup_delivery_enabled,
                    gold_alerts_enabled,
                    language_code,
                    signal_profile,
                    base_signal_profile,
                    preferred_min_score,
                    min_quote_volume,
                    rsi_oversold,
                    rsi_overbought,
                    direction_filter,
                    watchlist_only,
                    menu_collapsed,
                    delivery_mode,
                    delivery_mode_changed_at,
                    quiet_hours_start_minute,
                    quiet_hours_end_minute,
                    snooze_until,
                    snooze_started_at,
                    snooze_label,
                    last_resume_summary_at,
                    last_digest_sent_at,
                    last_daily_recap_at,
                    last_weekly_recap_at,
                    active_watchlist_theme,
                    active_custom_theme_name,
                    onboarding_completed_at,
                    enabled_strategy_keys_json,
                    active_strategy_key,
                    strategy_selector_completed_at,
                    current_context,
                    current_strategy_context,
                    current_set_id,
                    timezone_name,
                    display_mode,
                    active_workspace,
                    saved_workspace_payload_json,
                    strategy_preferences_json,
                    personalization_json,
                    delivery_rules_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind) DO UPDATE SET
                    direct_signal_delivery_enabled = excluded.direct_signal_delivery_enabled,
                    followup_delivery_enabled = excluded.followup_delivery_enabled,
                    gold_alerts_enabled = excluded.gold_alerts_enabled,
                    language_code = excluded.language_code,
                    signal_profile = excluded.signal_profile,
                    base_signal_profile = excluded.base_signal_profile,
                    preferred_min_score = excluded.preferred_min_score,
                    min_quote_volume = excluded.min_quote_volume,
                    rsi_oversold = excluded.rsi_oversold,
                    rsi_overbought = excluded.rsi_overbought,
                    direction_filter = excluded.direction_filter,
                    watchlist_only = excluded.watchlist_only,
                    menu_collapsed = excluded.menu_collapsed,
                    delivery_mode = excluded.delivery_mode,
                    delivery_mode_changed_at = excluded.delivery_mode_changed_at,
                    quiet_hours_start_minute = excluded.quiet_hours_start_minute,
                    quiet_hours_end_minute = excluded.quiet_hours_end_minute,
                    snooze_until = excluded.snooze_until,
                    snooze_started_at = excluded.snooze_started_at,
                    snooze_label = excluded.snooze_label,
                    last_resume_summary_at = excluded.last_resume_summary_at,
                    last_digest_sent_at = excluded.last_digest_sent_at,
                    last_daily_recap_at = excluded.last_daily_recap_at,
                    last_weekly_recap_at = excluded.last_weekly_recap_at,
                    active_watchlist_theme = excluded.active_watchlist_theme,
                    active_custom_theme_name = excluded.active_custom_theme_name,
                    onboarding_completed_at = excluded.onboarding_completed_at,
                    enabled_strategy_keys_json = excluded.enabled_strategy_keys_json,
                    active_strategy_key = excluded.active_strategy_key,
                    strategy_selector_completed_at = excluded.strategy_selector_completed_at,
                    current_context = excluded.current_context,
                    current_strategy_context = excluded.current_strategy_context,
                    current_set_id = excluded.current_set_id,
                    timezone_name = excluded.timezone_name,
                    display_mode = excluded.display_mode,
                    active_workspace = excluded.active_workspace,
                    saved_workspace_payload_json = excluded.saved_workspace_payload_json,
                    strategy_preferences_json = excluded.strategy_preferences_json,
                    personalization_json = excluded.personalization_json,
                    delivery_rules_json = excluded.delivery_rules_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    int(direct_signal_delivery_enabled),
                    int(effective_followup),
                    int(effective_gold),
                    effective_language_code,
                    effective_profile,
                    effective_base_profile,
                    effective_min_score,
                    effective_min_quote_volume,
                    effective_rsi_oversold,
                    effective_rsi_overbought,
                    effective_direction_filter,
                    int(effective_watchlist_only),
                    int(effective_menu_collapsed),
                    effective_delivery_mode,
                    effective_delivery_mode_changed_at,
                    effective_quiet_hours_start,
                    effective_quiet_hours_end,
                    effective_snooze_until,
                    effective_snooze_started_at,
                    effective_snooze_label,
                    effective_last_resume_summary_at,
                    effective_last_digest_sent_at,
                    effective_last_daily_recap_at,
                    effective_last_weekly_recap_at,
                    effective_active_watchlist_theme,
                    effective_active_custom_theme_name,
                    effective_onboarding_completed_at,
                    json.dumps(list(dict.fromkeys(effective_enabled_strategy_keys)), ensure_ascii=True, separators=(",", ":")),
                    effective_active_strategy_key,
                    effective_strategy_selector_completed_at,
                    effective_current_context,
                    effective_current_strategy_context,
                    effective_current_set_id,
                    effective_timezone_name,
                    effective_display_mode,
                    effective_active_workspace,
                    _to_json(effective_saved_workspace_payload),
                    _to_json(effective_strategy_preferences),
                    _to_json(effective_personalization),
                    _to_json(effective_delivery_rules),
                    now,
                ),
            )
            await connection.commit()

    async def get_premium_strategy_settings(
        self,
        telegram_user_id: int,
        *,
        strategy_key: str,
        bot_kind: str = "premium",
    ) -> PremiumStrategySettingsRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM premium_strategy_settings
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                """,
                (telegram_user_id, bot_kind, strategy_key),
            )
            return self._row_to_premium_strategy_settings(await cursor.fetchone())

    async def list_premium_strategy_settings(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> list[PremiumStrategySettingsRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM premium_strategy_settings
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                ORDER BY strategy_key ASC
                """,
                (telegram_user_id, bot_kind),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_premium_strategy_settings(row)) is not None]

    async def upsert_premium_strategy_settings(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        bot_kind: str = "premium",
        direct_signal_delivery_enabled: bool,
        followup_delivery_enabled: bool | None = None,
        signal_profile: str | None = None,
        base_signal_profile: str | None = None,
        preferred_min_score: int | None = None,
        min_quote_volume: float | None = None,
        rsi_oversold: float | None = None,
        rsi_overbought: float | None = None,
        direction_filter: str | None = None,
        watchlist_only: bool | None = None,
        delivery_mode: str | None = None,
        delivery_mode_changed_at=...,
        quiet_hours_start_minute=...,
        quiet_hours_end_minute=...,
        snooze_until=...,
        snooze_started_at=...,
        snooze_label=...,
        last_resume_summary_at=...,
        last_digest_sent_at=...,
        last_daily_recap_at=...,
        last_weekly_recap_at=...,
        active_watchlist_theme: str | None = None,
        active_custom_theme_name=...,
        strategy_preferences: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT
                    followup_delivery_enabled,
                    signal_profile,
                    base_signal_profile,
                    preferred_min_score,
                    min_quote_volume,
                    rsi_oversold,
                    rsi_overbought,
                    direction_filter,
                    watchlist_only,
                    delivery_mode,
                    delivery_mode_changed_at,
                    quiet_hours_start_minute,
                    quiet_hours_end_minute,
                    snooze_until,
                    snooze_started_at,
                    snooze_label,
                    last_resume_summary_at,
                    last_digest_sent_at,
                    last_daily_recap_at,
                    last_weekly_recap_at,
                    active_watchlist_theme,
                    active_custom_theme_name,
                    strategy_preferences_json
                FROM premium_strategy_settings
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                """,
                (telegram_user_id, bot_kind, strategy_key),
            )
            existing = await cursor.fetchone()
            await cursor.close()
            default_followup = get_settings().private_bot_followups_default
            effective_followup = (
                bool(existing["followup_delivery_enabled"])
                if followup_delivery_enabled is None and existing is not None
                else default_followup if followup_delivery_enabled is None
                else followup_delivery_enabled
            )
            effective_profile = (
                str(existing["signal_profile"] or "balanced")
                if signal_profile is None and existing is not None
                else str(signal_profile or "balanced")
            )
            effective_base_profile = (
                str(existing["base_signal_profile"] or "balanced")
                if base_signal_profile is None and existing is not None
                else str(
                    base_signal_profile
                    or (signal_profile if str(signal_profile or "").strip().lower() in {"conservative", "balanced", "aggressive"} else "balanced")
                    or "balanced"
                )
            )
            effective_min_score = (
                existing["preferred_min_score"]
                if preferred_min_score is None and existing is not None
                else preferred_min_score
            )
            effective_min_quote_volume = (
                existing["min_quote_volume"]
                if min_quote_volume is None and existing is not None
                else min_quote_volume
            )
            effective_rsi_oversold = (
                existing["rsi_oversold"]
                if rsi_oversold is None and existing is not None
                else rsi_oversold
            )
            effective_rsi_overbought = (
                existing["rsi_overbought"]
                if rsi_overbought is None and existing is not None
                else rsi_overbought
            )
            effective_direction_filter = (
                str(existing["direction_filter"] or "both")
                if direction_filter is None and existing is not None
                else str(direction_filter or "both")
            )
            effective_watchlist_only = (
                bool(existing["watchlist_only"])
                if watchlist_only is None and existing is not None
                else False if watchlist_only is None
                else watchlist_only
            )
            effective_delivery_mode = (
                str(existing["delivery_mode"] or "instant")
                if delivery_mode is None and existing is not None
                else str(delivery_mode or "instant")
            )
            effective_delivery_mode_changed_at = (
                existing["delivery_mode_changed_at"]
                if delivery_mode_changed_at is Ellipsis and existing is not None
                else delivery_mode_changed_at.isoformat() if isinstance(delivery_mode_changed_at, datetime) else None
            )
            effective_quiet_hours_start = (
                existing["quiet_hours_start_minute"]
                if quiet_hours_start_minute is Ellipsis and existing is not None
                else None if quiet_hours_start_minute is Ellipsis
                else quiet_hours_start_minute
            )
            effective_quiet_hours_end = (
                existing["quiet_hours_end_minute"]
                if quiet_hours_end_minute is Ellipsis and existing is not None
                else None if quiet_hours_end_minute is Ellipsis
                else quiet_hours_end_minute
            )
            effective_snooze_until = (
                existing["snooze_until"]
                if snooze_until is Ellipsis and existing is not None
                else snooze_until.isoformat() if isinstance(snooze_until, datetime) else None
            )
            effective_snooze_started_at = (
                existing["snooze_started_at"]
                if snooze_started_at is Ellipsis and existing is not None
                else snooze_started_at.isoformat() if isinstance(snooze_started_at, datetime) else None
            )
            effective_snooze_label = (
                existing["snooze_label"]
                if snooze_label is Ellipsis and existing is not None
                else None if snooze_label is Ellipsis
                else snooze_label
            )
            effective_last_resume_summary_at = (
                existing["last_resume_summary_at"]
                if last_resume_summary_at is Ellipsis and existing is not None
                else last_resume_summary_at.isoformat() if isinstance(last_resume_summary_at, datetime) else None
            )
            effective_last_digest_sent_at = (
                existing["last_digest_sent_at"]
                if last_digest_sent_at is Ellipsis and existing is not None
                else last_digest_sent_at.isoformat() if isinstance(last_digest_sent_at, datetime) else None
            )
            effective_last_daily_recap_at = (
                existing["last_daily_recap_at"]
                if last_daily_recap_at is Ellipsis and existing is not None
                else last_daily_recap_at.isoformat() if isinstance(last_daily_recap_at, datetime) else None
            )
            effective_last_weekly_recap_at = (
                existing["last_weekly_recap_at"]
                if last_weekly_recap_at is Ellipsis and existing is not None
                else last_weekly_recap_at.isoformat() if isinstance(last_weekly_recap_at, datetime) else None
            )
            effective_active_watchlist_theme = (
                str(existing["active_watchlist_theme"] or "custom")
                if active_watchlist_theme is None and existing is not None
                else str(active_watchlist_theme or "custom")
            )
            effective_active_custom_theme_name = (
                existing["active_custom_theme_name"]
                if active_custom_theme_name is Ellipsis and existing is not None
                else None if active_custom_theme_name is Ellipsis
                else active_custom_theme_name
            )
            effective_strategy_preferences = (
                json.loads(existing["strategy_preferences_json"] or "{}")
                if strategy_preferences is None and existing is not None
                else strategy_preferences or {}
            )
            await connection.execute(
                """
                INSERT INTO premium_strategy_settings (
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    direct_signal_delivery_enabled,
                    followup_delivery_enabled,
                    signal_profile,
                    base_signal_profile,
                    preferred_min_score,
                    min_quote_volume,
                    rsi_oversold,
                    rsi_overbought,
                    direction_filter,
                    watchlist_only,
                    delivery_mode,
                    delivery_mode_changed_at,
                    quiet_hours_start_minute,
                    quiet_hours_end_minute,
                    snooze_until,
                    snooze_started_at,
                    snooze_label,
                    last_resume_summary_at,
                    last_digest_sent_at,
                    last_daily_recap_at,
                    last_weekly_recap_at,
                    active_watchlist_theme,
                    active_custom_theme_name,
                    strategy_preferences_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind, strategy_key) DO UPDATE SET
                    direct_signal_delivery_enabled = excluded.direct_signal_delivery_enabled,
                    followup_delivery_enabled = excluded.followup_delivery_enabled,
                    signal_profile = excluded.signal_profile,
                    base_signal_profile = excluded.base_signal_profile,
                    preferred_min_score = excluded.preferred_min_score,
                    min_quote_volume = excluded.min_quote_volume,
                    rsi_oversold = excluded.rsi_oversold,
                    rsi_overbought = excluded.rsi_overbought,
                    direction_filter = excluded.direction_filter,
                    watchlist_only = excluded.watchlist_only,
                    delivery_mode = excluded.delivery_mode,
                    delivery_mode_changed_at = excluded.delivery_mode_changed_at,
                    quiet_hours_start_minute = excluded.quiet_hours_start_minute,
                    quiet_hours_end_minute = excluded.quiet_hours_end_minute,
                    snooze_until = excluded.snooze_until,
                    snooze_started_at = excluded.snooze_started_at,
                    snooze_label = excluded.snooze_label,
                    last_resume_summary_at = excluded.last_resume_summary_at,
                    last_digest_sent_at = excluded.last_digest_sent_at,
                    last_daily_recap_at = excluded.last_daily_recap_at,
                    last_weekly_recap_at = excluded.last_weekly_recap_at,
                    active_watchlist_theme = excluded.active_watchlist_theme,
                    active_custom_theme_name = excluded.active_custom_theme_name,
                    strategy_preferences_json = excluded.strategy_preferences_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    int(direct_signal_delivery_enabled),
                    int(effective_followup),
                    effective_profile,
                    effective_base_profile,
                    effective_min_score,
                    effective_min_quote_volume,
                    effective_rsi_oversold,
                    effective_rsi_overbought,
                    effective_direction_filter,
                    int(effective_watchlist_only),
                    effective_delivery_mode,
                    effective_delivery_mode_changed_at,
                    effective_quiet_hours_start,
                    effective_quiet_hours_end,
                    effective_snooze_until,
                    effective_snooze_started_at,
                    effective_snooze_label,
                    effective_last_resume_summary_at,
                    effective_last_digest_sent_at,
                    effective_last_daily_recap_at,
                    effective_last_weekly_recap_at,
                    effective_active_watchlist_theme,
                    effective_active_custom_theme_name,
                    _to_json(effective_strategy_preferences),
                    now,
                ),
            )
            await connection.commit()

    async def list_premium_strategy_watchlist(
        self,
        telegram_user_id: int,
        *,
        strategy_key: str,
        bot_kind: str = "premium",
    ) -> list[WatchlistEntry]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT symbol, created_at
                FROM premium_strategy_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                ORDER BY created_at ASC, symbol ASC
                """,
                (telegram_user_id, bot_kind, strategy_key),
            )
            rows = await cursor.fetchall()
            return [
                WatchlistEntry(
                    telegram_user_id=telegram_user_id,
                    bot_kind=bot_kind,
                    symbol=row["symbol"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    async def add_premium_strategy_watchlist_symbol(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        symbol: str,
        bot_kind: str = "premium",
    ) -> bool:
        created_at = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO premium_strategy_watchlist (
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    symbol,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_user_id, bot_kind, strategy_key, symbol, created_at),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def remove_premium_strategy_watchlist_symbol(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        symbol: str,
        bot_kind: str = "premium",
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                DELETE FROM premium_strategy_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                  AND symbol = ?
                """,
                (telegram_user_id, bot_kind, strategy_key, symbol),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def replace_premium_strategy_watchlist_symbols(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        symbols: Sequence[str],
        bot_kind: str = "premium",
    ) -> None:
        created_at = utc_now().isoformat()
        normalized_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                DELETE FROM premium_strategy_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                """,
                (telegram_user_id, bot_kind, strategy_key),
            )
            if normalized_symbols:
                await connection.executemany(
                    """
                    INSERT INTO premium_strategy_watchlist (
                        telegram_user_id,
                        bot_kind,
                        strategy_key,
                        symbol,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (telegram_user_id, bot_kind, strategy_key, symbol, created_at)
                        for symbol in normalized_symbols
                    ],
                )
            await connection.commit()

    async def list_premium_strategy_watchlist_themes(
        self,
        telegram_user_id: int,
        *,
        strategy_key: str,
        bot_kind: str = "premium",
    ) -> list[WatchlistThemeRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM premium_strategy_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                ORDER BY updated_at DESC, theme_name COLLATE NOCASE ASC
                """,
                (telegram_user_id, bot_kind, strategy_key),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_watchlist_theme(row)) is not None]

    async def get_premium_strategy_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        theme_name: str,
        bot_kind: str = "premium",
    ) -> WatchlistThemeRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM premium_strategy_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, strategy_key, theme_name),
            )
            return self._row_to_watchlist_theme(await cursor.fetchone())

    async def save_premium_strategy_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        theme_name: str,
        symbols: Sequence[str],
        metadata: dict[str, Any] | None = None,
        bot_kind: str = "premium",
    ) -> WatchlistThemeRecord:
        now = utc_now().isoformat()
        normalized_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO premium_strategy_watchlist_themes (
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    theme_name,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind, strategy_key, theme_name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    theme_name,
                    now,
                    now,
                    _to_json(metadata or {}),
                ),
            )
            cursor = await connection.execute(
                """
                SELECT id
                FROM premium_strategy_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, strategy_key, theme_name),
            )
            row = await cursor.fetchone()
            assert row is not None
            theme_id = int(row["id"])
            await connection.execute(
                """
                DELETE FROM premium_strategy_watchlist_theme_symbols
                WHERE theme_id = ?
                """,
                (theme_id,),
            )
            if normalized_symbols:
                await connection.executemany(
                    """
                    INSERT INTO premium_strategy_watchlist_theme_symbols (
                        theme_id,
                        symbol,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    [(theme_id, symbol, now) for symbol in normalized_symbols],
                )
            await connection.commit()
        record = await self.get_premium_strategy_watchlist_theme(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            strategy_key=strategy_key,
            theme_name=theme_name,
        )
        assert record is not None
        return record

    async def list_premium_strategy_watchlist_theme_symbols(self, theme_id: int) -> list[str]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT symbol
                FROM premium_strategy_watchlist_theme_symbols
                WHERE theme_id = ?
                ORDER BY created_at ASC, symbol ASC
                """,
                (theme_id,),
            )
            rows = await cursor.fetchall()
            return [str(row["symbol"]) for row in rows]

    async def rename_premium_strategy_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        old_name: str,
        new_name: str,
        bot_kind: str = "premium",
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                UPDATE premium_strategy_watchlist_themes
                SET theme_name = ?,
                    updated_at = ?
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                  AND theme_name = ?
                """,
                (
                    new_name,
                    utc_now().isoformat(),
                    telegram_user_id,
                    bot_kind,
                    strategy_key,
                    old_name,
                ),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def delete_premium_strategy_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        strategy_key: str,
        theme_name: str,
        bot_kind: str = "premium",
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                DELETE FROM premium_strategy_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND strategy_key = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, strategy_key, theme_name),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def list_user_watchlist(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> list[WatchlistEntry]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                ORDER BY created_at ASC, symbol ASC
                """,
                (telegram_user_id, bot_kind),
            )
            rows = await cursor.fetchall()
            return [
                WatchlistEntry(
                    telegram_user_id=row["telegram_user_id"],
                    bot_kind=row["bot_kind"],
                    symbol=row["symbol"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    async def add_user_watchlist_symbol(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        symbol: str,
    ) -> bool:
        created_at = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO user_watchlist (
                    telegram_user_id,
                    bot_kind,
                    symbol,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (telegram_user_id, bot_kind, symbol, created_at),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def remove_user_watchlist_symbol(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        symbol: str,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                DELETE FROM user_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND symbol = ?
                """,
                (telegram_user_id, bot_kind, symbol),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def user_watchlist_contains(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        symbol: str,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT 1
                FROM user_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND symbol = ?
                LIMIT 1
                """,
                (telegram_user_id, bot_kind, symbol),
            )
            return await cursor.fetchone() is not None

    async def replace_user_watchlist_symbols(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        symbols: Sequence[str],
    ) -> None:
        created_at = utc_now().isoformat()
        normalized_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                DELETE FROM user_watchlist
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            if normalized_symbols:
                await connection.executemany(
                    """
                    INSERT INTO user_watchlist (
                        telegram_user_id,
                        bot_kind,
                        symbol,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (telegram_user_id, bot_kind, symbol, created_at)
                        for symbol in normalized_symbols
                    ],
                )
            await connection.commit()

    async def get_user_onboarding_state(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> OnboardingStateRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_onboarding_state
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return OnboardingStateRecord(
                telegram_user_id=row["telegram_user_id"],
                bot_kind=row["bot_kind"],
                step=row["step"],
                draft=json.loads(row["draft_json"] or "{}"),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                completed_at=_to_dt(row["completed_at"]),
            )

    async def upsert_user_onboarding_state(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        step: str,
        draft: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO user_onboarding_state (
                    telegram_user_id,
                    bot_kind,
                    step,
                    draft_json,
                    updated_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind) DO UPDATE SET
                    step = excluded.step,
                    draft_json = excluded.draft_json,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    step,
                    _to_json(draft or {}),
                    now,
                    completed_at.isoformat() if completed_at is not None else None,
                ),
            )
            await connection.commit()

    async def delete_user_onboarding_state(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                DELETE FROM user_onboarding_state
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            await connection.commit()

    def _row_to_watchlist_theme(self, row: aiosqlite.Row | None) -> WatchlistThemeRecord | None:
        if row is None:
            return None
        return WatchlistThemeRecord(
            id=row["id"],
            telegram_user_id=row["telegram_user_id"],
            bot_kind=row["bot_kind"],
            theme_name=row["theme_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    async def list_user_watchlist_themes(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> list[WatchlistThemeRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                ORDER BY updated_at DESC, theme_name COLLATE NOCASE ASC
                """,
                (telegram_user_id, bot_kind),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_watchlist_theme(row)) is not None]

    async def get_user_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        theme_name: str,
    ) -> WatchlistThemeRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, theme_name),
            )
            row = await cursor.fetchone()
            return self._row_to_watchlist_theme(row)

    async def save_user_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        theme_name: str,
        symbols: Sequence[str],
        metadata: dict[str, Any] | None = None,
    ) -> WatchlistThemeRecord:
        now = utc_now().isoformat()
        normalized_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO user_watchlist_themes (
                    telegram_user_id,
                    bot_kind,
                    theme_name,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind, theme_name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    theme_name,
                    now,
                    now,
                    _to_json(metadata or {}),
                ),
            )
            cursor = await connection.execute(
                """
                SELECT id
                FROM user_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, theme_name),
            )
            row = await cursor.fetchone()
            assert row is not None
            theme_id = int(row["id"])
            await connection.execute(
                """
                DELETE FROM user_watchlist_theme_symbols
                WHERE theme_id = ?
                """,
                (theme_id,),
            )
            if normalized_symbols:
                await connection.executemany(
                    """
                    INSERT INTO user_watchlist_theme_symbols (
                        theme_id,
                        symbol,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    [(theme_id, symbol, now) for symbol in normalized_symbols],
                )
            await connection.commit()
        record = await self.get_user_watchlist_theme(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            theme_name=theme_name,
        )
        assert record is not None
        return record

    async def list_user_watchlist_theme_symbols(self, theme_id: int) -> list[str]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT symbol
                FROM user_watchlist_theme_symbols
                WHERE theme_id = ?
                ORDER BY created_at ASC, symbol ASC
                """,
                (theme_id,),
            )
            rows = await cursor.fetchall()
            return [str(row["symbol"]) for row in rows]

    async def rename_user_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        old_name: str,
        new_name: str,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                UPDATE user_watchlist_themes
                SET theme_name = ?,
                    updated_at = ?
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND theme_name = ?
                """,
                (
                    new_name,
                    utc_now().isoformat(),
                    telegram_user_id,
                    bot_kind,
                    old_name,
                ),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def delete_user_watchlist_theme(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        theme_name: str,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                DELETE FROM user_watchlist_themes
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND theme_name = ?
                """,
                (telegram_user_id, bot_kind, theme_name),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def list_user_saved_setups(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> list[UserSavedSetupRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_saved_setups
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                ORDER BY is_pinned DESC, is_default DESC, updated_at DESC, name COLLATE NOCASE ASC
                """,
                (telegram_user_id, bot_kind),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_user_saved_setup(row)) is not None]

    async def get_user_saved_setup(
        self,
        setup_id: int,
        *,
        telegram_user_id: int | None = None,
        bot_kind: str = "premium",
    ) -> UserSavedSetupRecord | None:
        query = """
            SELECT *
            FROM user_saved_setups
            WHERE id = ?
              AND bot_kind = ?
        """
        parameters: list[Any] = [setup_id, bot_kind]
        if telegram_user_id is not None:
            query += "\n  AND telegram_user_id = ?"
            parameters.append(telegram_user_id)
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            return self._row_to_user_saved_setup(await cursor.fetchone())

    async def create_user_saved_setup(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        name: str,
        payload: dict[str, Any],
        is_default: bool = False,
        is_pinned: bool = False,
    ) -> UserSavedSetupRecord:
        now = utc_now().isoformat()
        normalized_name = str(name or "").strip() or "Setup"
        async with self._lock:
            connection = await self._connect()
            if is_default:
                await connection.execute(
                    """
                    UPDATE user_saved_setups
                    SET is_default = 0,
                        updated_at = ?
                    WHERE telegram_user_id = ?
                      AND bot_kind = ?
                    """,
                    (now, telegram_user_id, bot_kind),
                )
            insert = await connection.execute(
                """
                INSERT INTO user_saved_setups (
                    telegram_user_id,
                    bot_kind,
                    name,
                    is_default,
                    is_pinned,
                    payload_json,
                    created_at,
                    updated_at,
                    last_used_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    normalized_name,
                    int(is_default),
                    int(is_pinned),
                    _to_json(payload or {}),
                    now,
                    now,
                    None,
                ),
            )
            setup_id = int(insert.lastrowid)
            await connection.commit()
        created = await self.get_user_saved_setup(setup_id, telegram_user_id=telegram_user_id, bot_kind=bot_kind)
        assert created is not None
        return created

    async def update_user_saved_setup(
        self,
        setup_id: int,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        name: str | None = None,
        payload: dict[str, Any] | None = None,
        is_default: bool | None = None,
        is_pinned: bool | None = None,
        last_used_at: datetime | None | object = ...,
    ) -> UserSavedSetupRecord | None:
        existing = await self.get_user_saved_setup(setup_id, telegram_user_id=telegram_user_id, bot_kind=bot_kind)
        if existing is None:
            return None
        now = utc_now().isoformat()
        effective_name = str(name or existing.name).strip() or existing.name
        effective_payload = existing.payload if payload is None else payload
        effective_default = existing.is_default if is_default is None else bool(is_default)
        effective_pinned = existing.is_pinned if is_pinned is None else bool(is_pinned)
        effective_last_used_at = existing.last_used_at if last_used_at is Ellipsis else last_used_at
        async with self._lock:
            connection = await self._connect()
            if effective_default:
                await connection.execute(
                    """
                    UPDATE user_saved_setups
                    SET is_default = 0,
                        updated_at = ?
                    WHERE telegram_user_id = ?
                      AND bot_kind = ?
                      AND id != ?
                    """,
                    (now, telegram_user_id, bot_kind, setup_id),
                )
            await connection.execute(
                """
                UPDATE user_saved_setups
                SET name = ?,
                    is_default = ?,
                    is_pinned = ?,
                    payload_json = ?,
                    updated_at = ?,
                    last_used_at = ?
                WHERE id = ?
                  AND telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (
                    effective_name,
                    int(effective_default),
                    int(effective_pinned),
                    _to_json(effective_payload or {}),
                    now,
                    effective_last_used_at.isoformat() if isinstance(effective_last_used_at, datetime) else None,
                    setup_id,
                    telegram_user_id,
                    bot_kind,
                ),
            )
            await connection.commit()
        return await self.get_user_saved_setup(setup_id, telegram_user_id=telegram_user_id, bot_kind=bot_kind)

    async def delete_user_saved_setup(
        self,
        setup_id: int,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                DELETE FROM user_saved_setups
                WHERE id = ?
                  AND telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (setup_id, telegram_user_id, bot_kind),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def get_user_style_profile(
        self,
        telegram_user_id: int,
        *,
        bot_kind: str = "premium",
    ) -> UserStyleProfileRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_style_profiles
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                """,
                (telegram_user_id, bot_kind),
            )
            return self._row_to_user_style_profile(await cursor.fetchone())

    async def upsert_user_style_profile(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        title: str,
        summary: str | None,
        preferences: dict[str, Any],
    ) -> UserStyleProfileRecord:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO user_style_profiles (
                    telegram_user_id,
                    bot_kind,
                    title,
                    summary,
                    preferences_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    preferences_json = excluded.preferences_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    str(title or "Balanced Trader").strip() or "Balanced Trader",
                    summary,
                    _to_json(preferences or {}),
                    now,
                    now,
                ),
            )
            await connection.commit()
        profile = await self.get_user_style_profile(telegram_user_id, bot_kind=bot_kind)
        assert profile is not None
        return profile

    async def set_user_access_level(
        self,
        *,
        telegram_user_id: int,
        access_level: str,
        status: str = "active",
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        user_access_status: str | None = None,
        is_admin: bool | None = None,
    ) -> None:
        now = utc_now()
        effective_starts_at = starts_at or now
        effective_access_status = (user_access_status or access_level).strip() or "free"
        is_admin_value = None if is_admin is None else int(is_admin)
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE bot_users
                SET access_level = ?,
                    access_status = ?,
                    is_admin = CASE
                        WHEN ? IS NULL THEN is_admin
                        ELSE ?
                    END,
                    last_seen_at = ?
                WHERE telegram_user_id = ?
                """,
                (
                    access_level,
                    effective_access_status,
                    is_admin_value,
                    is_admin_value,
                    now.isoformat(),
                    telegram_user_id,
                ),
            )
            await connection.execute(
                """
                INSERT INTO user_access (
                    telegram_user_id,
                    access_level,
                    status,
                    starts_at,
                    ends_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    access_level,
                    status,
                    effective_starts_at.isoformat(),
                    ends_at.isoformat() if ends_at is not None else None,
                    now.isoformat(),
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()

    async def get_latest_user_access(self, telegram_user_id: int) -> UserAccessRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM user_access
                WHERE telegram_user_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (telegram_user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return UserAccessRecord(
                id=row["id"],
                telegram_user_id=row["telegram_user_id"],
                access_level=row["access_level"],
                status=row["status"],
                starts_at=datetime.fromisoformat(row["starts_at"]),
                ends_at=_to_dt(row["ends_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def upsert_crypto_pay_invoice(
        self,
        *,
        invoice_id: int,
        invoice_hash: str | None,
        telegram_user_id: int | None,
        bot_kind: str,
        target_access_level: str,
        target_duration_days: int,
        amount: str | None,
        asset: str | None,
        currency_type: str | None,
        description: str | None,
        status: str,
        pay_url: str | None,
        custom_payload: str | None,
        created_at: datetime,
        paid_at: datetime | None,
        activated_at: datetime | None,
        metadata: dict[str, Any] | None = None,
    ) -> CryptoPayInvoiceRecord:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO crypto_pay_invoices (
                    invoice_id,
                    invoice_hash,
                    telegram_user_id,
                    bot_kind,
                    target_access_level,
                    target_duration_days,
                    amount,
                    asset,
                    currency_type,
                    description,
                    status,
                    pay_url,
                    custom_payload,
                    created_at,
                    paid_at,
                    activated_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(invoice_id) DO UPDATE SET
                    invoice_hash = COALESCE(excluded.invoice_hash, crypto_pay_invoices.invoice_hash),
                    telegram_user_id = COALESCE(excluded.telegram_user_id, crypto_pay_invoices.telegram_user_id),
                    bot_kind = excluded.bot_kind,
                    target_access_level = excluded.target_access_level,
                    target_duration_days = excluded.target_duration_days,
                    amount = COALESCE(excluded.amount, crypto_pay_invoices.amount),
                    asset = COALESCE(excluded.asset, crypto_pay_invoices.asset),
                    currency_type = COALESCE(excluded.currency_type, crypto_pay_invoices.currency_type),
                    description = COALESCE(excluded.description, crypto_pay_invoices.description),
                    status = excluded.status,
                    pay_url = COALESCE(excluded.pay_url, crypto_pay_invoices.pay_url),
                    custom_payload = COALESCE(excluded.custom_payload, crypto_pay_invoices.custom_payload),
                    paid_at = COALESCE(excluded.paid_at, crypto_pay_invoices.paid_at),
                    activated_at = COALESCE(excluded.activated_at, crypto_pay_invoices.activated_at),
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    invoice_id,
                    invoice_hash,
                    telegram_user_id,
                    bot_kind,
                    target_access_level,
                    target_duration_days,
                    amount,
                    asset,
                    currency_type,
                    description,
                    status,
                    pay_url,
                    custom_payload,
                    created_at.isoformat(),
                    paid_at.isoformat() if paid_at is not None else None,
                    activated_at.isoformat() if activated_at is not None else None,
                    now,
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()
        record = await self.get_crypto_pay_invoice(invoice_id=invoice_id)
        assert record is not None
        return record

    async def get_crypto_pay_invoice(
        self,
        *,
        invoice_id: int | None = None,
        invoice_hash: str | None = None,
    ) -> CryptoPayInvoiceRecord | None:
        if invoice_id is None and not invoice_hash:
            return None
        async with self._lock:
            connection = await self._connect()
            if invoice_id is not None:
                cursor = await connection.execute(
                    "SELECT * FROM crypto_pay_invoices WHERE invoice_id = ?",
                    (invoice_id,),
                )
            else:
                cursor = await connection.execute(
                    "SELECT * FROM crypto_pay_invoices WHERE invoice_hash = ?",
                    (invoice_hash,),
                )
            row = await cursor.fetchone()
            if row is None:
                return None
            return CryptoPayInvoiceRecord(
                invoice_id=row["invoice_id"],
                invoice_hash=row["invoice_hash"],
                telegram_user_id=row["telegram_user_id"],
                bot_kind=row["bot_kind"],
                target_access_level=row["target_access_level"],
                target_duration_days=row["target_duration_days"],
                amount=row["amount"],
                asset=row["asset"],
                currency_type=row["currency_type"],
                description=row["description"],
                status=row["status"],
                pay_url=row["pay_url"],
                custom_payload=row["custom_payload"],
                created_at=datetime.fromisoformat(row["created_at"]),
                paid_at=_to_dt(row["paid_at"]),
                activated_at=_to_dt(row["activated_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def mark_crypto_pay_invoice_activated(
        self,
        *,
        invoice_id: int,
        activated_at: datetime,
        status: str = "paid",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE crypto_pay_invoices
                SET status = ?,
                    activated_at = ?,
                    updated_at = ?,
                    metadata_json = CASE
                        WHEN ? IS NULL THEN metadata_json
                        ELSE ?
                    END
                WHERE invoice_id = ?
                """,
                (
                    status,
                    activated_at.isoformat(),
                    now,
                    None if metadata is None else 1,
                    _to_json(metadata or {}),
                    invoice_id,
                ),
            )
            await connection.commit()

    async def record_crypto_pay_webhook_event(
        self,
        *,
        event_hash: str,
        update_type: str,
        invoice_id: int | None,
        request_date: datetime | None,
        status: str,
        raw_payload: dict[str, Any],
        last_error: str | None = None,
    ) -> bool:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO crypto_pay_webhook_events (
                    event_hash,
                    update_type,
                    invoice_id,
                    request_date,
                    status,
                    processed_at,
                    last_error,
                    raw_payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_hash,
                    update_type,
                    invoice_id,
                    request_date.isoformat() if request_date is not None else None,
                    status,
                    utc_now().isoformat(),
                    last_error,
                    _to_json(raw_payload),
                ),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def update_crypto_pay_webhook_event_status(
        self,
        *,
        event_hash: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE crypto_pay_webhook_events
                SET status = ?,
                    processed_at = ?,
                    last_error = ?
                WHERE event_hash = ?
                """,
                (status, utc_now().isoformat(), last_error, event_hash),
            )
            await connection.commit()

    async def upsert_onboarding_payment_campaign(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str,
        campaign_type: str,
        first_contact_at: datetime,
        trial_started_at: datetime | None,
        trial_ends_at: datetime | None,
        referred_by_user_id: int | None,
        invoice_id: int | None,
        offer_sent_at: datetime | None,
        status: str,
        attempt_count: int = 0,
        next_retry_at: datetime | None = None,
        last_error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OnboardingCampaignRecord:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO onboarding_payment_campaigns (
                    telegram_user_id,
                    bot_kind,
                    campaign_type,
                    first_contact_at,
                    trial_started_at,
                    trial_ends_at,
                    referred_by_user_id,
                    invoice_id,
                    offer_sent_at,
                    status,
                    attempt_count,
                    next_retry_at,
                    last_error,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, bot_kind, campaign_type) DO UPDATE SET
                    first_contact_at = onboarding_payment_campaigns.first_contact_at,
                    trial_started_at = COALESCE(excluded.trial_started_at, onboarding_payment_campaigns.trial_started_at),
                    trial_ends_at = COALESCE(excluded.trial_ends_at, onboarding_payment_campaigns.trial_ends_at),
                    referred_by_user_id = COALESCE(onboarding_payment_campaigns.referred_by_user_id, excluded.referred_by_user_id),
                    invoice_id = COALESCE(excluded.invoice_id, onboarding_payment_campaigns.invoice_id),
                    offer_sent_at = COALESCE(excluded.offer_sent_at, onboarding_payment_campaigns.offer_sent_at),
                    status = excluded.status,
                    attempt_count = excluded.attempt_count,
                    next_retry_at = excluded.next_retry_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    campaign_type,
                    first_contact_at.isoformat(),
                    trial_started_at.isoformat() if trial_started_at is not None else None,
                    trial_ends_at.isoformat() if trial_ends_at is not None else None,
                    referred_by_user_id,
                    invoice_id,
                    offer_sent_at.isoformat() if offer_sent_at is not None else None,
                    status,
                    attempt_count,
                    next_retry_at.isoformat() if next_retry_at is not None else None,
                    last_error,
                    now,
                    now,
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()
        record = await self.get_onboarding_payment_campaign(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            campaign_type=campaign_type,
        )
        assert record is not None
        return record

    async def get_onboarding_payment_campaign(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str,
        campaign_type: str = "trial_48h",
    ) -> OnboardingCampaignRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM onboarding_payment_campaigns
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND campaign_type = ?
                """,
                (telegram_user_id, bot_kind, campaign_type),
            )
            row = await cursor.fetchone()
            return self._row_to_onboarding_campaign(row)

    async def get_onboarding_payment_campaign_by_invoice(
        self,
        *,
        invoice_id: int,
    ) -> OnboardingCampaignRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM onboarding_payment_campaigns
                WHERE invoice_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (invoice_id,),
            )
            row = await cursor.fetchone()
            return self._row_to_onboarding_campaign(row)

    async def update_onboarding_payment_campaign(
        self,
        campaign_id: int,
        *,
        first_contact_at: datetime | None = None,
        status: str | None = None,
        invoice_id: int | None = None,
        offer_sent_at: datetime | None = None,
        attempt_count: int | None = None,
        next_retry_at: datetime | None = None,
        last_error: str | None = None,
        trial_started_at: datetime | None = None,
        trial_ends_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now().isoformat()]
        if first_contact_at is not None:
            assignments.append("first_contact_at = ?")
            values.append(first_contact_at.isoformat())
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if invoice_id is not None:
            assignments.append("invoice_id = ?")
            values.append(invoice_id)
        if offer_sent_at is not None:
            assignments.append("offer_sent_at = ?")
            values.append(offer_sent_at.isoformat())
        if attempt_count is not None:
            assignments.append("attempt_count = ?")
            values.append(attempt_count)
        if next_retry_at is not None:
            assignments.append("next_retry_at = ?")
            values.append(next_retry_at.isoformat())
        elif next_retry_at is None and status in {"offer_sent", "converted", "skipped_admin", "skipped_paid", "expired_no_payment", "delivery_unreachable"}:
            assignments.append("next_retry_at = NULL")
        if last_error is not None:
            assignments.append("last_error = ?")
            values.append(last_error)
        elif status in {"offer_sent", "converted", "skipped_admin", "skipped_paid", "expired_no_payment"}:
            assignments.append("last_error = NULL")
        if trial_started_at is not None:
            assignments.append("trial_started_at = ?")
            values.append(trial_started_at.isoformat())
        if trial_ends_at is not None:
            assignments.append("trial_ends_at = ?")
            values.append(trial_ends_at.isoformat())
        if metadata is not None:
            assignments.append("metadata_json = ?")
            values.append(_to_json(metadata))
        values.append(campaign_id)
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                f"""
                UPDATE onboarding_payment_campaigns
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                tuple(values),
            )
            await connection.commit()

    async def get_next_due_onboarding_payment_campaign(self) -> OnboardingCampaignRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *,
                       COALESCE(next_retry_at, trial_ends_at) AS due_at
                FROM onboarding_payment_campaigns
                WHERE status IN ('trial_active', 'invoice_ready', 'send_retry')
                ORDER BY due_at ASC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            return self._row_to_onboarding_campaign(row)

    async def get_due_onboarding_payment_campaigns(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[OnboardingCampaignRecord]:
        effective_now = (now or utc_now()).isoformat()
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM onboarding_payment_campaigns
                WHERE status IN ('trial_active', 'invoice_ready', 'send_retry')
                  AND COALESCE(next_retry_at, trial_ends_at) IS NOT NULL
                  AND COALESCE(next_retry_at, trial_ends_at) <= ?
                ORDER BY COALESCE(next_retry_at, trial_ends_at) ASC
                LIMIT ?
                """,
                (effective_now, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_onboarding_campaign(row)) is not None]

    async def upsert_referral(
        self,
        *,
        referrer_user_id: int,
        referred_user_id: int,
        bot_kind: str,
        source_payload: str | None,
        status: str = "registered",
        metadata: dict[str, Any] | None = None,
    ) -> ReferralRecord:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO referrals (
                    referrer_user_id,
                    referred_user_id,
                    bot_kind,
                    status,
                    source_payload,
                    created_at,
                    converted_at,
                    first_paid_conversion_at,
                    counted_as_paid_referral,
                    conversion_invoice_id,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, ?)
                ON CONFLICT(referred_user_id) DO UPDATE SET
                    referrer_user_id = referrals.referrer_user_id,
                    bot_kind = COALESCE(referrals.bot_kind, excluded.bot_kind),
                    status = CASE
                        WHEN referrals.counted_as_paid_referral = 1 THEN referrals.status
                        ELSE excluded.status
                    END,
                    source_payload = COALESCE(referrals.source_payload, excluded.source_payload),
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    referrer_user_id,
                    referred_user_id,
                    bot_kind,
                    status,
                    source_payload,
                    now,
                    now,
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()
        record = await self.get_referral(referred_user_id=referred_user_id)
        assert record is not None
        return record

    async def get_referral(self, *, referred_user_id: int) -> ReferralRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM referrals
                WHERE referred_user_id = ?
                LIMIT 1
                """,
                (referred_user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return ReferralRecord(
                id=row["id"],
                referrer_user_id=row["referrer_user_id"],
                referred_user_id=row["referred_user_id"],
                bot_kind=row["bot_kind"],
                status=row["status"],
                source_payload=row["source_payload"],
                created_at=datetime.fromisoformat(row["created_at"]),
                converted_at=_to_dt(row["converted_at"]),
                first_paid_conversion_at=_to_dt(row["first_paid_conversion_at"]),
                counted_as_paid_referral=bool(row["counted_as_paid_referral"]),
                conversion_invoice_id=row["conversion_invoice_id"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )

    async def mark_referral_converted(
        self,
        *,
        referred_user_id: int,
        invoice_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE referrals
                SET status = 'converted',
                    converted_at = COALESCE(converted_at, ?),
                    first_paid_conversion_at = COALESCE(first_paid_conversion_at, ?),
                    counted_as_paid_referral = 1,
                    conversion_invoice_id = COALESCE(conversion_invoice_id, ?),
                    updated_at = ?,
                    metadata_json = CASE
                        WHEN ? IS NULL THEN metadata_json
                        ELSE ?
                    END
                WHERE referred_user_id = ?
                """,
                (
                    now,
                    now,
                    invoice_id,
                    now,
                    None if metadata is None else 1,
                    _to_json(metadata or {}),
                    referred_user_id,
                ),
            )
            await connection.commit()

    async def get_referral_cycle_stats(
        self,
        *,
        referrer_user_id: int,
    ) -> ReferralCycleStatRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM referral_cycle_stats
                WHERE referrer_user_id = ?
                LIMIT 1
                """,
                (referrer_user_id,),
            )
            row = await cursor.fetchone()
            return self._row_to_referral_cycle_stats(row)

    async def list_referral_reward_grants(
        self,
        *,
        referrer_user_id: int,
        limit: int = 20,
    ) -> list[ReferralRewardGrantRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM referral_reward_grants
                WHERE referrer_user_id = ?
                ORDER BY granted_at DESC, id DESC
                LIMIT ?
                """,
                (referrer_user_id, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_referral_reward_grant(row)) is not None]

    async def count_referrals_for_referrer(
        self,
        *,
        referrer_user_id: int,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT COUNT(*)
                FROM referrals
                WHERE referrer_user_id = ?
                """,
                (referrer_user_id,),
            )
            row = await cursor.fetchone()
            return int(row[0] or 0) if row is not None else 0

    async def process_paid_referral_conversion(
        self,
        *,
        referred_user_id: int,
        invoice_id: int,
        converted_at: datetime,
        reward_days_by_milestone: dict[int, int],
    ) -> dict[str, Any]:
        timestamp = converted_at.isoformat()
        milestones = sorted(
            (int(count), max(int(days), 0))
            for count, days in reward_days_by_milestone.items()
            if int(count) > 0 and int(days) > 0
        )
        terminal_milestone = milestones[-1][0] if milestones else 0
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT r.*,
                       referrer.is_admin AS referrer_is_admin
                FROM referrals r
                JOIN bot_users referrer
                  ON referrer.telegram_user_id = r.referrer_user_id
                WHERE r.referred_user_id = ?
                LIMIT 1
                """,
                (referred_user_id,),
            )
            referral_row = await cursor.fetchone()
            if referral_row is None:
                return {"status": "no_referral", "counted": False}
            if int(referral_row["referrer_user_id"]) == int(referred_user_id):
                return {"status": "self_referral_blocked", "counted": False}
            if bool(referral_row["counted_as_paid_referral"]):
                stats_cursor = await connection.execute(
                    """
                    SELECT *
                    FROM referral_cycle_stats
                    WHERE referrer_user_id = ?
                    LIMIT 1
                    """,
                    (referral_row["referrer_user_id"],),
                )
                stats_row = await stats_cursor.fetchone()
                return {
                    "status": "already_counted",
                    "counted": False,
                    "referrer_user_id": int(referral_row["referrer_user_id"]),
                    "stats": self._row_to_referral_cycle_stats(stats_row),
                }

            now = utc_now()
            await connection.execute(
                """
                UPDATE referrals
                SET status = 'converted',
                    converted_at = COALESCE(converted_at, ?),
                    first_paid_conversion_at = COALESCE(first_paid_conversion_at, ?),
                    counted_as_paid_referral = 1,
                    conversion_invoice_id = COALESCE(conversion_invoice_id, ?),
                    updated_at = ?,
                    metadata_json = ?
                WHERE referred_user_id = ?
                  AND counted_as_paid_referral = 0
                """,
                (
                    timestamp,
                    timestamp,
                    invoice_id,
                    now.isoformat(),
                    _to_json(
                        {
                            "counted_invoice_id": invoice_id,
                            "counted_at": timestamp,
                        }
                    ),
                    referred_user_id,
                ),
            )

            stats_cursor = await connection.execute(
                """
                SELECT *
                FROM referral_cycle_stats
                WHERE referrer_user_id = ?
                LIMIT 1
                """,
                (referral_row["referrer_user_id"],),
            )
            existing_stats_row = await stats_cursor.fetchone()
            current_active = int(existing_stats_row["active_cycle_paid_referrals_count"]) if existing_stats_row is not None else 0
            current_lifetime = int(existing_stats_row["lifetime_paid_referrals_count"]) if existing_stats_row is not None else 0
            current_cycle_number = int(existing_stats_row["current_cycle_number"]) if existing_stats_row is not None else 1
            next_active_count = current_active + 1
            next_lifetime_count = current_lifetime + 1

            milestone_trigger: int | None = None
            reward_days = 0
            for milestone_count, milestone_reward_days in milestones:
                if next_active_count == milestone_count:
                    milestone_trigger = milestone_count
                    reward_days = milestone_reward_days
                    break

            referrer_is_admin = bool(referral_row["referrer_is_admin"])
            reward_granted = False
            access_extension_from: datetime | None = None
            access_extension_to: datetime | None = None
            if milestone_trigger is not None:
                reward_insert = await connection.execute(
                    """
                    INSERT OR IGNORE INTO referral_reward_grants (
                        referrer_user_id,
                        referred_user_id,
                        reward_type,
                        reward_days,
                        milestone_trigger,
                        cycle_number,
                        granted_at,
                        access_extension_from,
                        access_extension_to,
                        metadata_json
                    )
                    VALUES (?, ?, 'premium_days', ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        referral_row["referrer_user_id"],
                        referred_user_id,
                        reward_days,
                        milestone_trigger,
                        current_cycle_number,
                        timestamp,
                        _to_json(
                            {
                                "invoice_id": invoice_id,
                                "counted_at": timestamp,
                                "referred_user_id": referred_user_id,
                            }
                        ),
                    ),
                )
                reward_granted = reward_insert.rowcount > 0
                if reward_granted and not referrer_is_admin:
                    latest_cursor = await connection.execute(
                        """
                        SELECT *
                        FROM user_access
                        WHERE telegram_user_id = ?
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (referral_row["referrer_user_id"],),
                    )
                    latest_access = await latest_cursor.fetchone()
                    access_extension_from = converted_at
                    if (
                        latest_access is not None
                        and latest_access["ends_at"] is not None
                        and str(latest_access["status"] or "").strip().lower() in {"paid_active", "trial_active"}
                    ):
                        latest_end = _to_dt(latest_access["ends_at"])
                        if latest_end is not None and latest_end > converted_at:
                            access_extension_from = latest_end
                    access_extension_to = access_extension_from + timedelta(days=reward_days)
                    await connection.execute(
                        """
                        UPDATE bot_users
                        SET access_level = 'pro',
                            access_status = 'paid',
                            last_seen_at = ?
                        WHERE telegram_user_id = ?
                        """,
                        (
                            now.isoformat(),
                            referral_row["referrer_user_id"],
                        ),
                    )
                    await connection.execute(
                        """
                        INSERT INTO user_access (
                            telegram_user_id,
                            access_level,
                            status,
                            starts_at,
                            ends_at,
                            updated_at,
                            metadata_json
                        )
                        VALUES (?, 'pro', 'paid_active', ?, ?, ?, ?)
                        """,
                        (
                            referral_row["referrer_user_id"],
                            converted_at.isoformat(),
                            access_extension_to.isoformat(),
                            now.isoformat(),
                            _to_json(
                                {
                                    "source": "referral_reward",
                                    "reward_days": reward_days,
                                    "milestone_trigger": milestone_trigger,
                                    "cycle_number": current_cycle_number,
                                    "referred_user_id": referred_user_id,
                                    "invoice_id": invoice_id,
                                    "extension_anchor": access_extension_from.isoformat(),
                                }
                            ),
                        ),
                    )
                    await connection.execute(
                        """
                        UPDATE referral_reward_grants
                        SET access_extension_from = ?,
                            access_extension_to = ?,
                            metadata_json = ?
                        WHERE referrer_user_id = ?
                          AND cycle_number = ?
                          AND milestone_trigger = ?
                        """,
                        (
                            access_extension_from.isoformat(),
                            access_extension_to.isoformat(),
                            _to_json(
                                {
                                    "invoice_id": invoice_id,
                                    "counted_at": timestamp,
                                    "referred_user_id": referred_user_id,
                                    "extension_anchor": access_extension_from.isoformat(),
                                    "access_extension_to": access_extension_to.isoformat(),
                                }
                            ),
                            referral_row["referrer_user_id"],
                            current_cycle_number,
                            milestone_trigger,
                        ),
                    )

            cycle_reset = milestone_trigger is not None and terminal_milestone and milestone_trigger >= terminal_milestone
            post_action_active_count = 0 if cycle_reset else next_active_count
            current_cycle_after = current_cycle_number + 1 if cycle_reset else current_cycle_number
            last_reward_milestone_reached = 0 if cycle_reset else (milestone_trigger or (int(existing_stats_row["last_reward_milestone_reached"]) if existing_stats_row is not None else 0))
            await connection.execute(
                """
                INSERT INTO referral_cycle_stats (
                    referrer_user_id,
                    active_cycle_paid_referrals_count,
                    lifetime_paid_referrals_count,
                    current_cycle_number,
                    last_reward_milestone_reached,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(referrer_user_id) DO UPDATE SET
                    active_cycle_paid_referrals_count = excluded.active_cycle_paid_referrals_count,
                    lifetime_paid_referrals_count = excluded.lifetime_paid_referrals_count,
                    current_cycle_number = excluded.current_cycle_number,
                    last_reward_milestone_reached = excluded.last_reward_milestone_reached,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    referral_row["referrer_user_id"],
                    post_action_active_count,
                    next_lifetime_count,
                    current_cycle_after,
                    last_reward_milestone_reached,
                    now.isoformat(),
                    _to_json(
                        {
                            "last_referred_user_id": referred_user_id,
                            "last_invoice_id": invoice_id,
                            "last_counted_at": timestamp,
                            "cycle_reset": cycle_reset,
                        }
                    ),
                ),
            )
            await connection.commit()

            stats = ReferralCycleStatRecord(
                referrer_user_id=int(referral_row["referrer_user_id"]),
                active_cycle_paid_referrals_count=post_action_active_count,
                lifetime_paid_referrals_count=next_lifetime_count,
                current_cycle_number=current_cycle_after,
                last_reward_milestone_reached=last_reward_milestone_reached,
                updated_at=now,
                metadata={
                    "last_referred_user_id": referred_user_id,
                    "last_invoice_id": invoice_id,
                    "cycle_reset": cycle_reset,
                },
            )
            return {
                "status": "counted",
                "counted": True,
                "referrer_user_id": int(referral_row["referrer_user_id"]),
                "referred_user_id": referred_user_id,
                "cycle_progress_before_reset": next_active_count,
                "cycle_progress_after": post_action_active_count,
                "cycle_number_triggered": current_cycle_number,
                "cycle_number_after": current_cycle_after,
                "lifetime_paid_referrals_count": next_lifetime_count,
                "milestone_trigger": milestone_trigger,
                "reward_days_granted": reward_days if reward_granted else 0,
                "reward_granted": reward_granted,
                "cycle_reset": cycle_reset,
                "access_extension_from": access_extension_from,
                "access_extension_to": access_extension_to,
                "referrer_is_admin": referrer_is_admin,
                "stats": stats,
            }

    def _row_to_onboarding_campaign(self, row: aiosqlite.Row | None) -> OnboardingCampaignRecord | None:
        if row is None:
            return None
        return OnboardingCampaignRecord(
            id=row["id"],
            telegram_user_id=row["telegram_user_id"],
            bot_kind=row["bot_kind"],
            campaign_type=row["campaign_type"],
            first_contact_at=datetime.fromisoformat(row["first_contact_at"]),
            trial_started_at=_to_dt(row["trial_started_at"]),
            trial_ends_at=_to_dt(row["trial_ends_at"]),
            referred_by_user_id=row["referred_by_user_id"],
            invoice_id=row["invoice_id"],
            offer_sent_at=_to_dt(row["offer_sent_at"]),
            status=row["status"],
            attempt_count=row["attempt_count"],
            next_retry_at=_to_dt(row["next_retry_at"]),
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _row_to_referral_cycle_stats(
        self,
        row: aiosqlite.Row | None,
    ) -> ReferralCycleStatRecord | None:
        if row is None:
            return None
        return ReferralCycleStatRecord(
            referrer_user_id=row["referrer_user_id"],
            active_cycle_paid_referrals_count=int(row["active_cycle_paid_referrals_count"] or 0),
            lifetime_paid_referrals_count=int(row["lifetime_paid_referrals_count"] or 0),
            current_cycle_number=int(row["current_cycle_number"] or 1),
            last_reward_milestone_reached=int(row["last_reward_milestone_reached"] or 0),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _row_to_referral_reward_grant(
        self,
        row: aiosqlite.Row | None,
    ) -> ReferralRewardGrantRecord | None:
        if row is None:
            return None
        return ReferralRewardGrantRecord(
            id=row["id"],
            referrer_user_id=row["referrer_user_id"],
            referred_user_id=row["referred_user_id"],
            reward_type=row["reward_type"],
            reward_days=int(row["reward_days"] or 0),
            milestone_trigger=int(row["milestone_trigger"] or 0),
            cycle_number=int(row["cycle_number"] or 1),
            granted_at=datetime.fromisoformat(row["granted_at"]),
            access_extension_from=_to_dt(row["access_extension_from"]),
            access_extension_to=_to_dt(row["access_extension_to"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    async def list_private_signal_recipients(
        self,
        *,
        bot_kind: str = "premium",
        access_levels: Sequence[str] = ("free", "pro", "admin"),
        require_direct_enabled: bool = True,
    ) -> list[tuple[PrivateBotUserRecord, UserSettingsRecord | None]]:
        placeholders = ", ".join("?" for _ in access_levels)
        async with self._lock:
            connection = await self._connect()
            direct_enabled_filter = "\n                  AND COALESCE(s.direct_signal_delivery_enabled, 0) = 1" if require_direct_enabled else ""
            cursor = await connection.execute(
                f"""
                SELECT
                    u.*,
                    s.bot_kind,
                    s.direct_signal_delivery_enabled,
                    s.followup_delivery_enabled,
                    s.gold_alerts_enabled,
                    s.language_code,
                    s.signal_profile,
                    s.base_signal_profile,
                    s.preferred_min_score,
                    s.min_quote_volume,
                    s.rsi_oversold,
                    s.rsi_overbought,
                    s.direction_filter,
                    s.watchlist_only,
                    s.menu_collapsed,
                    s.delivery_mode,
                    s.delivery_mode_changed_at,
                    s.quiet_hours_start_minute,
                    s.quiet_hours_end_minute,
                    s.snooze_until,
                    s.snooze_started_at,
                    s.snooze_label,
                    s.last_resume_summary_at,
                    s.last_digest_sent_at,
                    s.last_daily_recap_at,
                    s.last_weekly_recap_at,
                    s.active_watchlist_theme,
                    s.active_custom_theme_name,
                    s.onboarding_completed_at,
                    s.enabled_strategy_keys_json,
                    s.active_strategy_key,
                    s.strategy_selector_completed_at,
                    s.current_context,
                    s.current_strategy_context,
                    s.current_set_id,
                    s.timezone_name,
                    s.display_mode,
                    s.active_workspace,
                    s.saved_workspace_payload_json,
                    s.strategy_preferences_json,
                    s.personalization_json,
                    s.delivery_rules_json,
                    s.updated_at AS settings_updated_at
                FROM bot_users u
                LEFT JOIN user_bot_settings s
                  ON s.telegram_user_id = u.telegram_user_id
                 AND s.bot_kind = ?
                WHERE u.is_active = 1
                  AND u.access_level IN ({placeholders})
                {direct_enabled_filter}
                ORDER BY u.last_seen_at DESC
                """,
                (bot_kind, *tuple(access_levels)),
            )
            rows = await cursor.fetchall()
            recipients: list[tuple[PrivateBotUserRecord, UserSettingsRecord | None]] = []
            for row in rows:
                user = PrivateBotUserRecord(
                    telegram_user_id=row["telegram_user_id"],
                    username=row["username"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                    last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
                    is_active=bool(row["is_active"]),
                    access_level=row["access_level"],
                    access_status=row["access_status"],
                    is_admin=bool(row["is_admin"]),
                    referral_code=row["referral_code"],
                    referred_by_user_id=row["referred_by_user_id"],
                )
                settings = None
                if row["settings_updated_at"] is not None:
                    settings = self._row_to_user_settings(row)
                recipients.append((user, settings))
            return recipients

    async def delivered_signal_exists(
        self,
        *,
        telegram_user_id: int,
        alert_id: int | None,
        bot_kind: str = "premium",
        content_kind: str,
        message_kind: str,
    ) -> bool:
        if alert_id is None:
            return False
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT 1
                FROM delivered_bot_signals
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
                  AND alert_id = ?
                  AND content_kind = ?
                  AND message_kind = ?
                LIMIT 1
                """,
                (telegram_user_id, bot_kind, alert_id, content_kind, message_kind),
            )
            return await cursor.fetchone() is not None

    async def list_delivered_signals(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        content_kind: str | None = None,
        alert_id: int | None = None,
        message_kind_prefix: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[DeliveredSignalRecord]:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT *
                FROM delivered_bot_signals
                WHERE telegram_user_id = ?
                  AND bot_kind = ?
            """
            parameters: list[Any] = [telegram_user_id, bot_kind]
            if content_kind is not None:
                query += "\n  AND content_kind = ?"
                parameters.append(content_kind)
            if alert_id is not None:
                query += "\n  AND alert_id = ?"
                parameters.append(alert_id)
            if message_kind_prefix is not None:
                query += "\n  AND message_kind LIKE ?"
                parameters.append(f"{message_kind_prefix}%")
            if since is not None:
                query += "\n  AND delivered_at >= ?"
                parameters.append(since.isoformat())
            query += "\n ORDER BY delivered_at DESC, id DESC LIMIT ?"
            parameters.append(limit)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [
                DeliveredSignalRecord(
                    id=row["id"],
                    telegram_user_id=row["telegram_user_id"],
                    bot_kind=row["bot_kind"],
                    alert_id=row["alert_id"],
                    content_kind=row["content_kind"],
                    message_kind=row["message_kind"],
                    telegram_message_id=row["telegram_message_id"],
                    delivered_at=datetime.fromisoformat(row["delivered_at"]),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
                for row in rows
            ]

    async def record_delivered_signal(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        alert_id: int | None,
        content_kind: str,
        message_kind: str,
        telegram_message_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT OR IGNORE INTO delivered_bot_signals (
                    telegram_user_id,
                    bot_kind,
                    alert_id,
                    content_kind,
                    message_kind,
                    telegram_message_id,
                    delivered_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    bot_kind,
                    alert_id,
                    content_kind,
                    message_kind,
                    telegram_message_id,
                    utc_now().isoformat(),
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()

    async def delete_delivered_signal_records(self, record_ids: Sequence[int]) -> None:
        normalized_ids = sorted({int(record_id) for record_id in record_ids if int(record_id) > 0})
        if not normalized_ids:
            return
        async with self._lock:
            connection = await self._connect()
            placeholders = ", ".join("?" for _ in normalized_ids)
            await connection.execute(
                f"""
                DELETE FROM delivered_bot_signals
                WHERE id IN ({placeholders})
                """,
                normalized_ids,
            )
            await connection.commit()

    async def count_sent_messages_since(
        self,
        destination: str,
        since: datetime,
        *,
        message_types: Sequence[str] | None = None,
        message_type_prefixes: Sequence[str] | None = None,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT COUNT(1) AS total
                FROM message_log
                WHERE destination = ?
                  AND status = 'sent'
                  AND created_at >= ?
            """
            parameters: list[Any] = [destination, since.isoformat()]
            filters: list[str] = []

            if message_types:
                placeholders = ", ".join("?" for _ in message_types)
                filters.append(f"message_type IN ({placeholders})")
                parameters.extend(message_types)

            if message_type_prefixes:
                prefix_filters = ["message_type LIKE ?" for _ in message_type_prefixes]
                filters.append(f"({' OR '.join(prefix_filters)})")
                parameters.extend(f"{prefix}%" for prefix in message_type_prefixes)

            if filters:
                query = f"{query}\n AND ({' OR '.join(filters)})"

            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def list_recent_twitter_drafts(
        self,
        *,
        limit: int = 20,
        statuses: Sequence[str] | None = ("sent", "generated", "rewritten"),
        preview_mode: bool | None = False,
    ) -> list[TwitterDraft]:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT *
                FROM posts_history
                WHERE channel_kind = 'twitter_drafts'
            """
            parameters: list[Any] = []
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                query += f"\n AND status IN ({placeholders})"
                parameters.extend(statuses)
            if preview_mode is not None:
                query += "\n AND COALESCE(json_extract(metadata_json, '$.preview_mode'), 0) = ?"
                parameters.append(int(preview_mode))
            query += "\n ORDER BY created_at DESC LIMIT ?"
            parameters.append(limit)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            drafts: list[TwitterDraft] = []
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                drafts.append(
                    TwitterDraft(
                        destination=str(metadata.get("telegram_destination", "twitter_drafts")),
                        content_type=row["content_type"],
                        main_text=row["generated_text"] or row["content"],
                        mode=str(metadata.get("mode", "NORMAL")),
                        angle=str(metadata.get("angle", "")),
                        value_types=tuple(metadata.get("value_types", [])),
                        short_variant=row["short_variant"],
                        reply_variant=row["reply_variant"],
                        source_symbol=row["source_symbol"],
                        related_alert_id=row["related_alert_id"],
                        status=row["status"],
                        similarity_score=metadata.get("similarity_score"),
                        rewritten_for_similarity=bool(metadata.get("rewritten_for_similarity", False)),
                        preview_mode=bool(metadata.get("preview_mode", False)),
                        skipped_reason=metadata.get("skipped_reason"),
                        writer_model=metadata.get("writer_model") or row["model_name"],
                        analysis_model=metadata.get("analysis_model"),
                        metadata={
                            **metadata,
                            "created_at": row["created_at"],
                            "sent_at": row["sent_at"],
                        },
                    )
                )
            return drafts

    async def list_recent_post_texts(
        self,
        *,
        destination: str,
        channel_kind: str,
        limit: int = 8,
        content_types: Sequence[str] | None = None,
    ) -> list[str]:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT generated_text, content
                FROM posts_history
                WHERE destination = ?
                  AND channel_kind = ?
                  AND status IN ('generated', 'sent', 'rewritten', 'batched')
            """
            parameters: list[Any] = [destination, channel_kind]
            if content_types:
                placeholders = ", ".join("?" for _ in content_types)
                query += f"\n AND content_type IN ({placeholders})"
                parameters.extend(content_types)
            query += "\n ORDER BY created_at DESC LIMIT ?"
            parameters.append(limit)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [str(row["generated_text"] or row["content"] or "").strip() for row in rows if (row["generated_text"] or row["content"])]

    async def list_generated_posts_history(
        self,
        *,
        destination: str,
        channel_kind: str,
        related_alert_id: int | None = None,
        content_types: Sequence[str] | None = None,
        statuses: Sequence[str] | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT *
                FROM posts_history
                WHERE destination = ?
                  AND channel_kind = ?
            """
            parameters: list[Any] = [destination, channel_kind]
            if related_alert_id is not None:
                query += "\n AND related_alert_id = ?"
                parameters.append(related_alert_id)
            if content_types:
                placeholders = ", ".join("?" for _ in content_types)
                query += f"\n AND content_type IN ({placeholders})"
                parameters.extend(content_types)
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                query += f"\n AND status IN ({placeholders})"
                parameters.extend(statuses)
            if since is not None:
                query += "\n AND created_at >= ?"
                parameters.append(since.isoformat())
            query += "\n ORDER BY created_at DESC LIMIT ?"
            parameters.append(limit)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                items.append(
                    {
                        "destination": row["destination"],
                        "channel_kind": row["channel_kind"],
                        "status": row["status"],
                        "content_type": row["content_type"],
                        "related_alert_id": row["related_alert_id"],
                        "source_symbol": row["source_symbol"],
                        "created_at": row["created_at"],
                        "sent_at": row["sent_at"],
                        "metadata": metadata,
                    }
                )
            return items

    async def count_posts_history_since(
        self,
        *,
        destination: str,
        since: datetime,
        channel_kind: str | None = None,
        content_types: Sequence[str] | None = None,
        statuses: Sequence[str] | None = None,
        preview_mode: bool | None = None,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT COUNT(1) AS total
                FROM posts_history
                WHERE destination = ?
                  AND created_at >= ?
            """
            parameters: list[Any] = [destination, since.isoformat()]
            if channel_kind is not None:
                query += "\n AND channel_kind = ?"
                parameters.append(channel_kind)
            if content_types:
                placeholders = ", ".join("?" for _ in content_types)
                query += f"\n AND content_type IN ({placeholders})"
                parameters.extend(content_types)
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                query += f"\n AND status IN ({placeholders})"
                parameters.extend(statuses)
            if preview_mode is not None:
                query += "\n AND COALESCE(json_extract(metadata_json, '$.preview_mode'), 0) = ?"
                parameters.append(int(preview_mode))
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def count_scheduled_generated_posts_since(
        self,
        *,
        destination: str,
        since: datetime,
        channel_kind: str | None = None,
        content_types: Sequence[str] | None = None,
        statuses: Sequence[str] | None = ("pending", "processing"),
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            query = """
                SELECT COUNT(1) AS total
                FROM scheduled_generated_posts
                WHERE destination = ?
                  AND created_at >= ?
            """
            parameters: list[Any] = [destination, since.isoformat()]
            if channel_kind is not None:
                query += "\n AND channel_kind = ?"
                parameters.append(channel_kind)
            if content_types:
                placeholders = ", ".join("?" for _ in content_types)
                query += f"\n AND content_type IN ({placeholders})"
                parameters.extend(content_types)
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                query += f"\n AND status IN ({placeholders})"
                parameters.extend(statuses)
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def list_alerts_between(
        self,
        *,
        start: datetime,
        end: datetime,
        min_score: int = 0,
        min_quote_volume: float = 0.0,
        limit: int = 100,
    ) -> list[AlertRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE alert_sent_at >= ?
                  AND alert_sent_at < ?
                  AND score >= ?
                  AND COALESCE(json_extract(metadata_json, '$.quote_volume'), 0) >= ?
                ORDER BY score DESC, alert_sent_at DESC
                LIMIT ?
                """,
                (start.isoformat(), end.isoformat(), min_score, min_quote_volume, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_alert_record(row)) is not None]

    async def list_recent_alerts(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int,
        min_score: int = 0,
        min_quote_volume: float = 0.0,
    ) -> list[AlertRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE alert_sent_at >= ?
                  AND alert_sent_at < ?
                  AND score >= ?
                  AND COALESCE(json_extract(metadata_json, '$.quote_volume'), 0) >= ?
                ORDER BY alert_sent_at DESC
                LIMIT ?
                """,
                (start.isoformat(), end.isoformat(), min_score, min_quote_volume, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_alert_record(row)) is not None]

    async def count_alerts_between(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT COUNT(1) AS total
                FROM alerts
                WHERE alert_sent_at >= ?
                  AND alert_sent_at < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def list_followup_results_between(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[FollowUpResultRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM followup_stage_results
                WHERE observed_at >= ?
                  AND observed_at < ?
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                (start.isoformat(), end.isoformat(), limit),
            )
            rows = await cursor.fetchall()
            if not rows:
                cursor = await connection.execute(
                    """
                    SELECT *,
                           '2h' AS stage
                    FROM followup_results
                    WHERE observed_at >= ?
                      AND observed_at < ?
                    ORDER BY observed_at DESC
                    LIMIT ?
                    """,
                    (start.isoformat(), end.isoformat(), limit),
                )
                rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_followup_result_record(row)) is not None]

    async def list_followup_results_missing_lifecycle(self, *, limit: int = 500) -> list[FollowUpResultRecord]:
        """Return historical follow-ups whose original alert has no lifecycle row yet."""

        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT f.*
                FROM followup_stage_results f
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM tracked_signals s
                    WHERE s.alert_id = f.alert_id
                )
                ORDER BY f.observed_at ASC
                LIMIT ?
                """,
                (max(int(limit), 1),),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_followup_result_record(row)) is not None]

    async def count_followup_results_between(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> int:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT COUNT(1) AS total
                FROM followup_stage_results
                WHERE observed_at >= ?
                  AND observed_at < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            row = await cursor.fetchone()
            total = int(row["total"] if row is not None else 0)
            if total:
                return total
            cursor = await connection.execute(
                """
                SELECT COUNT(1) AS total
                FROM followup_results
                WHERE observed_at >= ?
                  AND observed_at < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def count_followup_tasks_by_status(self, status: str) -> int:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT COUNT(1) AS total
                FROM followup_stage_tasks
                WHERE status = ?
                """,
                (status,),
            )
            row = await cursor.fetchone()
            total = int(row["total"] if row is not None else 0)
            if total:
                return total
            cursor = await connection.execute(
                """
                SELECT COUNT(1) AS total
                FROM followup_tasks
                WHERE status = ?
                """,
                (status,),
            )
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def count_followup_tasks_due_before(
        self,
        *,
        before: datetime,
        statuses: Sequence[str] = ("pending", "processing"),
    ) -> int:
        normalized_statuses = tuple(
            dict.fromkeys(str(status or "").strip().lower() for status in statuses if str(status or "").strip())
        )
        if not normalized_statuses:
            return 0
        placeholders = ", ".join("?" for _ in normalized_statuses)
        parameters = [*normalized_statuses, before.isoformat()]
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                f"""
                SELECT COUNT(1) AS total
                FROM followup_stage_tasks
                WHERE status IN ({placeholders})
                  AND due_at < ?
                """,
                parameters,
            )
            row = await cursor.fetchone()
            total = int(row["total"] if row is not None else 0)
            if total:
                return total
            cursor = await connection.execute(
                f"""
                SELECT COUNT(1) AS total
                FROM followup_tasks
                WHERE status IN ({placeholders})
                  AND due_at < ?
                """,
                parameters,
            )
            row = await cursor.fetchone()
            return int(row["total"] if row is not None else 0)

    async def get_results_diagnostics(
        self,
        *,
        stale_before: datetime,
        error_since: datetime | None = None,
    ) -> dict[str, int | float | str | None]:
        """Return persisted Results integrity and job-health facts for administrators."""

        async with self._lock:
            connection = await self._connect()
            queries = {
                "signals": "SELECT COUNT(1) AS total FROM tracked_signals",
                "signals_without_lifecycle": "SELECT COUNT(1) AS total FROM alerts a WHERE NOT EXISTS (SELECT 1 FROM tracked_signals s WHERE s.alert_id = a.id)",
                "signals_without_followup": "SELECT COUNT(1) AS total FROM tracked_signals s WHERE s.alert_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM followup_stage_results f WHERE f.alert_id = s.alert_id)",
                "orphan_followups": "SELECT COUNT(1) AS total FROM followup_stage_results f WHERE NOT EXISTS (SELECT 1 FROM tracked_signals s WHERE s.alert_id = f.alert_id)",
                "duplicate_followups": "SELECT COUNT(1) AS total FROM (SELECT alert_id, stage FROM followup_stage_results GROUP BY alert_id, stage HAVING COUNT(1) > 1)",
                "results_without_signal": "SELECT COUNT(1) AS total FROM followup_stage_results f WHERE NOT EXISTS (SELECT 1 FROM tracked_signals s WHERE s.alert_id = f.alert_id)",
                "stale_active": "SELECT COUNT(1) AS total FROM tracked_signals WHERE status IN ('fresh', 'active', 'confirmed', 'near_tp') AND created_at < ?",
            }
            result: dict[str, int | float | str | None] = {}
            for name, query in queries.items():
                cursor = await connection.execute(query, (stale_before.isoformat(),) if name == "stale_active" else ())
                row = await cursor.fetchone()
                result[name] = int(row["total"] if row is not None else 0)
            cursor = await connection.execute(
                """
                SELECT created_at, payload_json
                FROM telemetry_events
                WHERE event_name = 'lifecycle_maintenance_completed'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            latest_lifecycle = await cursor.fetchone()
            if latest_lifecycle is None:
                result["last_lifecycle_job_at"] = None
                result["last_lifecycle_duration_ms"] = None
            else:
                try:
                    payload = json.loads(str(latest_lifecycle["payload_json"] or "{}"))
                except json.JSONDecodeError:
                    payload = {}
                duration = payload.get("duration_ms") if isinstance(payload, dict) else None
                result["last_lifecycle_job_at"] = str(latest_lifecycle["created_at"])
                result["last_lifecycle_duration_ms"] = float(duration) if isinstance(duration, (int, float)) else None
            cursor = await connection.execute("SELECT MAX(last_price_at) AS value FROM tracked_signals")
            row = await cursor.fetchone()
            result["last_market_update_at"] = str(row["value"]) if row is not None and row["value"] else None
            if error_since is not None:
                cursor = await connection.execute(
                    """
                    SELECT COUNT(1) AS total
                    FROM telemetry_events
                    WHERE event_name = 'lifecycle_market_error'
                      AND created_at >= ?
                    """,
                    (error_since.isoformat(),),
                )
                row = await cursor.fetchone()
                result["market_errors_24h"] = int(row["total"] if row is not None else 0)
            return result

    async def get_tracked_signal(self, signal_id: int) -> SignalLifecycleRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE signal_id = ?
                """,
                (signal_id,),
            )
            return self._row_to_signal_lifecycle_record(await cursor.fetchone())

    async def get_tracked_signal_by_alert_id(self, alert_id: int) -> SignalLifecycleRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE alert_id = ?
                """,
                (alert_id,),
            )
            return self._row_to_signal_lifecycle_record(await cursor.fetchone())

    async def get_tracked_signal_by_source_key(self, source_signal_key: str) -> SignalLifecycleRecord | None:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE source_signal_key = ?
                """,
                (source_signal_key,),
            )
            return self._row_to_signal_lifecycle_record(await cursor.fetchone())

    async def create_tracked_signal(
        self,
        *,
        alert_id: int | None,
        source_signal_key: str,
        strategy_code: str,
        symbol: str,
        asset_type: str,
        direction: str,
        timeframe: str,
        status: str,
        result_type: str,
        entry_price: float,
        entry_zone_low: float | None,
        entry_zone_high: float | None,
        invalidation_price: float | None,
        tp_price_primary: float | None,
        tp_price_secondary: float | None,
        benchmark_win_percent: float,
        created_at: datetime,
        activated_at: datetime | None = None,
        confirmed_at: datetime | None = None,
        near_tp_at: datetime | None = None,
        hit_tp_at: datetime | None = None,
        invalidated_at: datetime | None = None,
        expired_at: datetime | None = None,
        closed_at: datetime | None = None,
        expiry_at: datetime | None = None,
        last_price: float | None = None,
        last_price_at: datetime | None = None,
        mfe_percent: float = 0.0,
        mae_percent: float = 0.0,
        market_regime_tag: str | None = None,
        liquidity_tag: str | None = None,
        confidence_score: float | None = None,
        setup_quality: str | None = None,
        explanation_short: str | None = None,
        explanation_full: str | None = None,
        ai_analysis_available: bool = False,
        parent_alert_message_id: int | None = None,
        source_type: str = "strategy_stream",
        is_gold: bool = False,
        ambiguous_resolution: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> SignalLifecycleRecord:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE source_signal_key = ?
                """,
                (source_signal_key,),
            )
            existing = self._row_to_signal_lifecycle_record(await cursor.fetchone())
            if existing is not None:
                if existing.alert_id is None and alert_id is not None:
                    await connection.execute(
                        """
                        UPDATE tracked_signals
                        SET alert_id = ?
                        WHERE signal_id = ?
                        """,
                        (alert_id, existing.signal_id),
                    )
                    await connection.commit()
                    existing.alert_id = alert_id
                    return existing
                return existing
            insert = await connection.execute(
                """
                INSERT INTO tracked_signals (
                    alert_id,
                    source_signal_key,
                    strategy_code,
                    symbol,
                    asset_type,
                    direction,
                    timeframe,
                    status,
                    result_type,
                    entry_price,
                    entry_zone_low,
                    entry_zone_high,
                    invalidation_price,
                    tp_price_primary,
                    tp_price_secondary,
                    benchmark_win_percent,
                    created_at,
                    activated_at,
                    confirmed_at,
                    near_tp_at,
                    hit_tp_at,
                    invalidated_at,
                    expired_at,
                    closed_at,
                    expiry_at,
                    last_price,
                    last_price_at,
                    mfe_percent,
                    mae_percent,
                    market_regime_tag,
                    liquidity_tag,
                    confidence_score,
                    setup_quality,
                    explanation_short,
                    explanation_full,
                    ai_analysis_available,
                    parent_alert_message_id,
                    source_type,
                    is_gold,
                    ambiguous_resolution,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    source_signal_key,
                    strategy_code,
                    symbol,
                    asset_type,
                    direction,
                    timeframe,
                    status,
                    result_type,
                    entry_price,
                    entry_zone_low,
                    entry_zone_high,
                    invalidation_price,
                    tp_price_primary,
                    tp_price_secondary,
                    benchmark_win_percent,
                    created_at.isoformat(),
                    activated_at.isoformat() if activated_at else None,
                    confirmed_at.isoformat() if confirmed_at else None,
                    near_tp_at.isoformat() if near_tp_at else None,
                    hit_tp_at.isoformat() if hit_tp_at else None,
                    invalidated_at.isoformat() if invalidated_at else None,
                    expired_at.isoformat() if expired_at else None,
                    closed_at.isoformat() if closed_at else None,
                    expiry_at.isoformat() if expiry_at else None,
                    last_price,
                    last_price_at.isoformat() if last_price_at else None,
                    float(mfe_percent),
                    float(mae_percent),
                    market_regime_tag,
                    liquidity_tag,
                    confidence_score,
                    setup_quality,
                    explanation_short,
                    explanation_full,
                    int(ai_analysis_available),
                    parent_alert_message_id,
                    source_type,
                    int(is_gold),
                    int(ambiguous_resolution),
                    _to_json(metadata or {}),
                ),
            )
            signal_id = int(insert.lastrowid)
            await connection.commit()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE signal_id = ?
                """,
                (signal_id,),
            )
            created = self._row_to_signal_lifecycle_record(await cursor.fetchone())
            assert created is not None
            return created

    async def update_tracked_signal(
        self,
        signal_id: int,
        **changes: Any,
    ) -> SignalLifecycleRecord | None:
        if not changes:
            return await self.get_tracked_signal(signal_id)
        allowed = {
            "alert_id",
            "status",
            "result_type",
            "entry_zone_low",
            "entry_zone_high",
            "invalidation_price",
            "tp_price_primary",
            "tp_price_secondary",
            "activated_at",
            "confirmed_at",
            "near_tp_at",
            "hit_tp_at",
            "invalidated_at",
            "expired_at",
            "closed_at",
            "expiry_at",
            "last_price",
            "last_price_at",
            "mfe_percent",
            "mae_percent",
            "market_regime_tag",
            "liquidity_tag",
            "confidence_score",
            "setup_quality",
            "explanation_short",
            "explanation_full",
            "ai_analysis_available",
            "parent_alert_message_id",
            "source_type",
            "is_gold",
            "ambiguous_resolution",
            "metadata",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = "metadata_json" if key == "metadata" else key
            if key in {
                "activated_at",
                "confirmed_at",
                "near_tp_at",
                "hit_tp_at",
                "invalidated_at",
                "expired_at",
                "closed_at",
                "expiry_at",
                "last_price_at",
            }:
                serialized = value.isoformat() if isinstance(value, datetime) else None
            elif key in {"ai_analysis_available", "is_gold", "ambiguous_resolution"}:
                serialized = int(bool(value))
            elif key == "metadata":
                serialized = _to_json(value or {})
            else:
                serialized = value
            assignments.append(f"{column} = ?")
            parameters.append(serialized)
        if not assignments:
            return await self.get_tracked_signal(signal_id)
        parameters.append(signal_id)
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                f"""
                UPDATE tracked_signals
                SET {", ".join(assignments)}
                WHERE signal_id = ?
                """,
                parameters,
            )
            await connection.commit()
        return await self.get_tracked_signal(signal_id)

    async def list_tracked_signals(
        self,
        *,
        statuses: Sequence[str] | None = None,
        result_types: Sequence[str] | None = None,
        strategy_code: str | None = None,
        limit: int = 50,
    ) -> list[SignalLifecycleRecord]:
        query = "SELECT * FROM tracked_signals WHERE 1 = 1"
        parameters: list[Any] = []
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            parameters.extend(statuses)
        if result_types:
            placeholders = ", ".join("?" for _ in result_types)
            query += f" AND result_type IN ({placeholders})"
            parameters.extend(result_types)
        if strategy_code:
            query += " AND strategy_code = ?"
            parameters.append(strategy_code)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(limit)
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_lifecycle_record(row)) is not None]

    async def list_tracked_signals_for_maintenance(
        self,
        *,
        now: datetime,
        limit: int = 1_000,
    ) -> list[SignalLifecycleRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE status IN ('fresh', 'active', 'confirmed', 'near_tp')
                  AND (expiry_at IS NULL OR expiry_at > ?)
                ORDER BY COALESCE(last_price_at, created_at) ASC, signal_id ASC
                LIMIT ?
                """,
                (now.isoformat(), max(int(limit), 1)),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_lifecycle_record(row)) is not None]

    async def expire_due_tracked_signals(
        self,
        *,
        now: datetime,
        batch_size: int = 5_000,
    ) -> int:
        effective_batch_size = max(int(batch_size), 1)
        now_iso = now.isoformat()
        async with self._lock:
            connection = await self._connect()
            before_changes = connection.total_changes
            await connection.execute(
                """
                UPDATE tracked_signals
                SET status = 'expired',
                    result_type = 'neutral',
                    expired_at = COALESCE(expired_at, ?),
                    closed_at = COALESCE(closed_at, ?),
                    metadata_json = json_set(
                        CASE
                            WHEN json_valid(metadata_json) THEN metadata_json
                            ELSE '{}'
                        END,
                        '$.signal_status',
                        'expired',
                        '$.result_type',
                        'neutral'
                    )
                WHERE signal_id IN (
                    SELECT signal_id
                    FROM tracked_signals
                    WHERE status IN ('fresh', 'active', 'confirmed', 'near_tp')
                      AND expiry_at IS NOT NULL
                      AND expiry_at <= ?
                    ORDER BY expiry_at ASC, signal_id ASC
                    LIMIT ?
                )
                """,
                (now_iso, now_iso, now_iso, effective_batch_size),
            )
            expired_count = max(connection.total_changes - before_changes, 0)
            await connection.commit()
            return expired_count

    async def list_recent_tracked_signals(
        self,
        *,
        since: datetime,
        strategy_code: str | None = None,
        limit: int = 300,
    ) -> list[SignalLifecycleRecord]:
        query = """
            SELECT *
            FROM tracked_signals
            WHERE (
                created_at >= ?
                OR activated_at >= ?
                OR confirmed_at >= ?
                OR near_tp_at >= ?
                OR hit_tp_at >= ?
                OR invalidated_at >= ?
                OR expired_at >= ?
                OR closed_at >= ?
                OR last_price_at >= ?
            )
        """
        parameters: list[Any] = [since.isoformat()] * 9
        if strategy_code:
            query += "\n  AND strategy_code = ?"
            parameters.append(strategy_code)
        query += "\n ORDER BY COALESCE(closed_at, hit_tp_at, invalidated_at, expired_at, near_tp_at, confirmed_at, activated_at, last_price_at, created_at) DESC LIMIT ?"
        parameters.append(limit)
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_lifecycle_record(row)) is not None]

    async def summarize_recent_tracked_signals(
        self,
        *,
        since: datetime,
        strategy_code: str | None = None,
    ) -> dict[str, int | str | None]:
        """Aggregate the Results hub directly in SQLite.

        Results means signals created in the selected period. This is both the
        user-facing period definition and an indexable lifecycle boundary.
        The hub needs counts and timestamps, not hundreds of hydrated rows.
        """

        period_clause = "created_at >= ?"
        period_params: list[Any] = [since.isoformat()]
        strategy_clause = ""
        if strategy_code:
            strategy_clause = " AND strategy_code = ?"
            period_params.append(strategy_code)
        aggregate_query = f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status IN ('confirmed', 'near_tp', 'hit_tp') THEN 1 ELSE 0 END) AS confirmed,
                SUM(CASE WHEN status = 'invalidated' THEN 1 ELSE 0 END) AS broken,
                SUM(CASE WHEN status IN ('fresh', 'active', 'confirmed', 'near_tp') THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN status = 'expired' AND json_valid(metadata_json) AND COALESCE(json_extract(metadata_json, '$.tracking_unavailable'), 0) THEN 1 ELSE 0 END) AS insufficient,
                MAX(COALESCE(closed_at, hit_tp_at, invalidated_at, expired_at, near_tp_at, confirmed_at, activated_at, last_price_at, created_at)) AS updated_at
            FROM tracked_signals
            WHERE {period_clause}{strategy_clause}
        """
        relevant_alerts_cte = f"""
            WITH relevant_alerts AS (
                SELECT alert_id
                FROM tracked_signals
                WHERE {period_clause}{strategy_clause}
                  AND alert_id IS NOT NULL
            )
        """
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(aggregate_query, period_params)
            aggregate = await cursor.fetchone()
            cursor = await connection.execute(
                relevant_alerts_cte
                + """
                    SELECT
                        COUNT(latest_observed_at) AS total,
                        MAX(latest_observed_at) AS updated_at
                    FROM (
                        SELECT (
                            SELECT result.observed_at
                            FROM followup_stage_results AS result
                            WHERE result.alert_id = signal.alert_id
                            ORDER BY result.observed_at DESC
                            LIMIT 1
                        ) AS latest_observed_at
                        FROM relevant_alerts AS signal
                    )
                """,
                period_params,
            )
            followup_aggregate = await cursor.fetchone()
            followups = int(followup_aggregate["total"] or 0) if followup_aggregate is not None else 0
            followup_updated_at = followup_aggregate["updated_at"] if followup_aggregate is not None else None
            if followups == 0:
                cursor = await connection.execute(
                    relevant_alerts_cte
                    + """
                        SELECT COUNT(*) AS total, MAX(result.observed_at) AS updated_at
                        FROM followup_results AS result
                        INNER JOIN relevant_alerts AS signal ON signal.alert_id = result.alert_id
                    """,
                    period_params,
                )
                fallback = await cursor.fetchone()
                followups = int(fallback["total"] or 0) if fallback is not None else 0
                followup_updated_at = fallback["updated_at"] if fallback is not None else None
            return {
                "total": int(aggregate["total"] or 0),
                "confirmed": int(aggregate["confirmed"] or 0),
                "broken": int(aggregate["broken"] or 0),
                "open": int(aggregate["open_count"] or 0),
                "insufficient": int(aggregate["insufficient"] or 0),
                "followups": followups,
                "updated_at": max(
                    (item for item in (aggregate["updated_at"], followup_updated_at) if item),
                    default=None,
                ),
            }

    async def list_results_tracked_signals(
        self,
        *,
        since: datetime,
        strategy_code: str | None = None,
        limit: int = 300,
    ) -> list[SignalLifecycleRecord]:
        """Read lifecycle rows for Results using its indexable creation period."""

        query = "SELECT * FROM tracked_signals WHERE created_at >= ?"
        parameters: list[Any] = [since.isoformat()]
        if strategy_code:
            query += " AND strategy_code = ?"
            parameters.append(strategy_code)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(limit)
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_lifecycle_record(row)) is not None]

    async def list_signals_for_candle_archive(
        self,
        *,
        since: datetime,
        limit: int = 200,
    ) -> list[SignalLifecycleRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM tracked_signals
                WHERE created_at >= ?
                  AND status IN ('fresh', 'active', 'confirmed', 'near_tp')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (since.isoformat(), int(limit)),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_lifecycle_record(row)) is not None]

    async def save_tracked_signal_candles(
        self,
        *,
        signal_id: int,
        alert_id: int | None,
        symbol: str,
        timeframe: str,
        candles: Sequence[dict[str, Any]],
    ) -> int:
        if not candles:
            return 0
        async with self._lock:
            connection = await self._connect()
            before_changes = connection.total_changes
            await connection.executemany(
                """
                INSERT OR IGNORE INTO tracked_signal_candles (
                    signal_id,
                    alert_id,
                    symbol,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    quote_volume,
                    source,
                    collected_at,
                    processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(signal_id),
                        alert_id,
                        str(symbol),
                        str(timeframe),
                        str(item["candle_open_time"]),
                        str(item["candle_close_time"]),
                        float(item["open_price"]),
                        float(item["high_price"]),
                        float(item["low_price"]),
                        float(item["close_price"]),
                        float(item["volume"]) if item.get("volume") is not None else None,
                        float(item["quote_volume"]) if item.get("quote_volume") is not None else None,
                        str(item.get("source") or "rest_backfill"),
                        str(item["collected_at"]),
                        item.get("processed_at"),
                    )
                    for item in candles
                ],
            )
            await connection.commit()
            return max(connection.total_changes - before_changes, 0)

    async def list_signal_candles(
        self,
        signal_id: int,
        *,
        only_unprocessed: bool = False,
        limit: int = 200,
    ) -> list[SignalCandleRecord]:
        query = """
            SELECT *
            FROM tracked_signal_candles
            WHERE signal_id = ?
        """
        parameters: list[Any] = [int(signal_id)]
        if only_unprocessed:
            query += "\n  AND processed_at IS NULL"
        query += "\n ORDER BY candle_close_time ASC LIMIT ?"
        parameters.append(int(limit))
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_candle_record(row)) is not None]

    async def mark_signal_candle_processed(
        self,
        candle_id: int,
        *,
        processed_at: datetime,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                UPDATE tracked_signal_candles
                SET processed_at = COALESCE(processed_at, ?)
                WHERE id = ?
                """,
                (processed_at.isoformat(), int(candle_id)),
            )
            await connection.commit()

    async def append_signal_event(
        self,
        *,
        signal_id: int,
        event_type: str,
        old_status: str | None,
        new_status: str | None,
        event_payload: dict[str, Any] | None = None,
        created_at: datetime,
        created_by: str | None = None,
    ) -> SignalEventRecord:
        async with self._lock:
            connection = await self._connect()
            insert = await connection.execute(
                """
                INSERT INTO signal_events (
                    signal_id,
                    event_type,
                    old_status,
                    new_status,
                    event_payload_json,
                    created_at,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    event_type,
                    old_status,
                    new_status,
                    _to_json(event_payload or {}),
                    created_at.isoformat(),
                    created_by,
                ),
            )
            event_id = int(insert.lastrowid)
            await connection.commit()
            cursor = await connection.execute(
                """
                SELECT *
                FROM signal_events
                WHERE event_id = ?
                """,
                (event_id,),
            )
            event = self._row_to_signal_event_record(await cursor.fetchone())
            assert event is not None
            return event

    async def list_signal_events(self, signal_id: int, *, limit: int = 50) -> list[SignalEventRecord]:
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(
                """
                SELECT *
                FROM signal_events
                WHERE signal_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (signal_id, limit),
            )
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_signal_event_record(row)) is not None]

    async def upsert_strategy_stats_snapshot(
        self,
        *,
        strategy_code: str,
        timeframe_bucket: str | None,
        market_regime_bucket: str | None,
        asset_cluster_bucket: str | None,
        period_type: str,
        total_signals: int,
        wins: int,
        losses: int,
        expired_neutral: int,
        invalidated_count: int,
        avg_rr: float | None,
        avg_time_to_win_minutes: float | None,
        avg_time_to_invalidation_minutes: float | None,
        signals_per_day: float | None,
        best_tf: str | None,
        best_assets: str | None,
        best_regime: str | None,
        drawdown_profile: str | None,
        calculated_at: datetime,
        delivered_count: int = 0,
        suppressed_count: int = 0,
        ambiguous_count: int = 0,
        sent_wins: int = 0,
        sent_losses: int = 0,
        sent_expired_neutral: int = 0,
        sent_ambiguous_count: int = 0,
        sent_avg_rr: float | None = None,
        sent_signals_per_day: float | None = None,
        sent_best_tf: str | None = None,
        sent_best_assets: str | None = None,
        sent_best_regime: str | None = None,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            existing_cursor = await connection.execute(
                """
                SELECT snapshot_id
                FROM strategy_stats_snapshots
                WHERE strategy_code = ?
                  AND timeframe_bucket IS ?
                  AND market_regime_bucket IS ?
                  AND asset_cluster_bucket IS ?
                  AND period_type = ?
                ORDER BY snapshot_id DESC
                LIMIT 1
                """,
                (
                    strategy_code,
                    timeframe_bucket,
                    market_regime_bucket,
                    asset_cluster_bucket,
                    period_type,
                ),
            )
            existing = await existing_cursor.fetchone()
            if existing is not None:
                await connection.execute(
                    """
                    UPDATE strategy_stats_snapshots
                    SET total_signals = ?,
                        wins = ?,
                        losses = ?,
                        expired_neutral = ?,
                        invalidated_count = ?,
                        avg_rr = ?,
                        avg_time_to_win_minutes = ?,
                        avg_time_to_invalidation_minutes = ?,
                        signals_per_day = ?,
                        best_tf = ?,
                        best_assets = ?,
                        best_regime = ?,
                        drawdown_profile = ?,
                        delivered_count = ?,
                        suppressed_count = ?,
                        ambiguous_count = ?,
                        sent_wins = ?,
                        sent_losses = ?,
                        sent_expired_neutral = ?,
                        sent_ambiguous_count = ?,
                        sent_avg_rr = ?,
                        sent_signals_per_day = ?,
                        sent_best_tf = ?,
                        sent_best_assets = ?,
                        sent_best_regime = ?,
                        calculated_at = ?
                    WHERE snapshot_id = ?
                    """,
                    (
                        total_signals,
                        wins,
                        losses,
                        expired_neutral,
                        invalidated_count,
                        avg_rr,
                        avg_time_to_win_minutes,
                        avg_time_to_invalidation_minutes,
                        signals_per_day,
                        best_tf,
                        best_assets,
                        best_regime,
                        drawdown_profile,
                        delivered_count,
                        suppressed_count,
                        ambiguous_count,
                        sent_wins,
                        sent_losses,
                        sent_expired_neutral,
                        sent_ambiguous_count,
                        sent_avg_rr,
                        sent_signals_per_day,
                        sent_best_tf,
                        sent_best_assets,
                        sent_best_regime,
                        calculated_at.isoformat(),
                        int(existing["snapshot_id"]),
                    ),
                )
                await connection.commit()
                return
            await connection.execute(
                """
                INSERT INTO strategy_stats_snapshots (
                    strategy_code,
                    timeframe_bucket,
                    market_regime_bucket,
                    asset_cluster_bucket,
                    period_type,
                    total_signals,
                    wins,
                    losses,
                    expired_neutral,
                    invalidated_count,
                    avg_rr,
                    avg_time_to_win_minutes,
                    avg_time_to_invalidation_minutes,
                    signals_per_day,
                    best_tf,
                    best_assets,
                    best_regime,
                    drawdown_profile,
                    delivered_count,
                    suppressed_count,
                    ambiguous_count,
                    sent_wins,
                    sent_losses,
                    sent_expired_neutral,
                    sent_ambiguous_count,
                    sent_avg_rr,
                    sent_signals_per_day,
                    sent_best_tf,
                    sent_best_assets,
                    sent_best_regime,
                    calculated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_code, timeframe_bucket, market_regime_bucket, asset_cluster_bucket, period_type)
                DO UPDATE SET
                    total_signals = excluded.total_signals,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    expired_neutral = excluded.expired_neutral,
                    invalidated_count = excluded.invalidated_count,
                    avg_rr = excluded.avg_rr,
                    avg_time_to_win_minutes = excluded.avg_time_to_win_minutes,
                    avg_time_to_invalidation_minutes = excluded.avg_time_to_invalidation_minutes,
                    signals_per_day = excluded.signals_per_day,
                    best_tf = excluded.best_tf,
                    best_assets = excluded.best_assets,
                    best_regime = excluded.best_regime,
                    drawdown_profile = excluded.drawdown_profile,
                    delivered_count = excluded.delivered_count,
                    suppressed_count = excluded.suppressed_count,
                    ambiguous_count = excluded.ambiguous_count,
                    sent_wins = excluded.sent_wins,
                    sent_losses = excluded.sent_losses,
                    sent_expired_neutral = excluded.sent_expired_neutral,
                    sent_ambiguous_count = excluded.sent_ambiguous_count,
                    sent_avg_rr = excluded.sent_avg_rr,
                    sent_signals_per_day = excluded.sent_signals_per_day,
                    sent_best_tf = excluded.sent_best_tf,
                    sent_best_assets = excluded.sent_best_assets,
                    sent_best_regime = excluded.sent_best_regime,
                    calculated_at = excluded.calculated_at
                """,
                (
                    strategy_code,
                    timeframe_bucket,
                    market_regime_bucket,
                    asset_cluster_bucket,
                    period_type,
                    total_signals,
                    wins,
                    losses,
                    expired_neutral,
                    invalidated_count,
                    avg_rr,
                    avg_time_to_win_minutes,
                    avg_time_to_invalidation_minutes,
                    signals_per_day,
                    best_tf,
                    best_assets,
                    best_regime,
                    drawdown_profile,
                    delivered_count,
                    suppressed_count,
                    ambiguous_count,
                    sent_wins,
                    sent_losses,
                    sent_expired_neutral,
                    sent_ambiguous_count,
                    sent_avg_rr,
                    sent_signals_per_day,
                    sent_best_tf,
                    sent_best_assets,
                    sent_best_regime,
                    calculated_at.isoformat(),
                ),
            )
            await connection.commit()

    async def prune_operational_history(
        self,
        *,
        candle_before: datetime,
        telemetry_before: datetime,
        snapshot_before: datetime,
        batch_size: int = 5_000,
    ) -> dict[str, int]:
        effective_batch_size = max(int(batch_size), 1)
        statements = (
            (
                "tracked_signal_candles",
                """
                DELETE FROM tracked_signal_candles
                WHERE id IN (
                    SELECT id
                    FROM tracked_signal_candles
                    WHERE collected_at < ?
                    ORDER BY id ASC
                    LIMIT ?
                )
                """,
                candle_before.isoformat(),
            ),
            (
                "telemetry_events",
                """
                DELETE FROM telemetry_events
                WHERE event_id IN (
                    SELECT event_id
                    FROM telemetry_events
                    WHERE created_at < ?
                    ORDER BY event_id ASC
                    LIMIT ?
                )
                """,
                telemetry_before.isoformat(),
            ),
            (
                "strategy_stats_snapshots",
                """
                DELETE FROM strategy_stats_snapshots
                WHERE snapshot_id IN (
                    SELECT snapshot_id
                    FROM strategy_stats_snapshots
                    WHERE calculated_at < ?
                    ORDER BY snapshot_id ASC
                    LIMIT ?
                )
                """,
                snapshot_before.isoformat(),
            ),
        )
        deleted: dict[str, int] = {}
        async with self._lock:
            connection = await self._connect()
            for table_name, statement, cutoff in statements:
                before_changes = connection.total_changes
                await connection.execute(statement, (cutoff, effective_batch_size))
                deleted[table_name] = max(connection.total_changes - before_changes, 0)
            await connection.commit()
        return deleted

    async def list_strategy_stats_snapshots(
        self,
        *,
        strategy_code: str | None = None,
        period_type: str | None = None,
        limit: int = 100,
    ) -> list[StrategyStatsSnapshotRecord]:
        query = "SELECT * FROM strategy_stats_snapshots WHERE 1 = 1"
        parameters: list[Any] = []
        if strategy_code:
            query += " AND strategy_code = ?"
            parameters.append(strategy_code)
        if period_type:
            query += " AND period_type = ?"
            parameters.append(period_type)
        query += " ORDER BY calculated_at DESC LIMIT ?"
        parameters.append(limit)
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return [record for row in rows if (record := self._row_to_strategy_stats_snapshot_record(row)) is not None]

    async def record_telemetry_event(
        self,
        *,
        event_name: str,
        created_at: datetime,
        telegram_user_id: int | None = None,
        context: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO telemetry_events (
                    event_name,
                    telegram_user_id,
                    context,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_name,
                    telegram_user_id,
                    context,
                    _to_json(payload or {}),
                    created_at.isoformat(),
                ),
            )
            await connection.commit()

    async def count_telemetry_events(
        self,
        *,
        start: datetime,
        end: datetime,
        event_names: Sequence[str] | None = None,
        telegram_user_id: int | None = None,
    ) -> dict[str, int]:
        normalized_names = tuple(
            dict.fromkeys(str(event_name or "").strip() for event_name in (event_names or ()) if str(event_name or "").strip())
        )
        if event_names is not None and not normalized_names:
            return {}
        query = """
            SELECT event_name, COUNT(1) AS total
            FROM telemetry_events
            WHERE created_at >= ?
              AND created_at < ?
        """
        parameters: list[Any] = [start.isoformat(), end.isoformat()]
        if normalized_names:
            placeholders = ", ".join("?" for _ in normalized_names)
            query += f"\n AND event_name IN ({placeholders})"
            parameters.extend(normalized_names)
        if telegram_user_id is not None:
            query += "\n AND telegram_user_id = ?"
            parameters.append(telegram_user_id)
        query += "\n GROUP BY event_name ORDER BY event_name ASC"
        async with self._lock:
            connection = await self._connect()
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            return {str(row["event_name"]): int(row["total"]) for row in rows}

    def _followup_stages(self) -> tuple[tuple[str, int], ...]:
        return get_settings().followup_stage_definitions

    async def record_message_event(
        self,
        *,
        destination: str,
        message_type: str,
        status: str,
        created_at: datetime,
        telegram_message_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            connection = await self._connect()
            await connection.execute(
                """
                INSERT INTO message_log (
                    destination,
                    message_type,
                    status,
                    telegram_message_id,
                    created_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    destination,
                    message_type,
                    status,
                    telegram_message_id,
                    created_at.isoformat(),
                    _to_json(metadata or {}),
                ),
            )
            await connection.commit()
