from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.core.config import get_settings
from src.core.models import AlertSignal
from src.signals.service import SignalLifecycleService
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.product import MessageRenderService
from src.userbot.service import PrivateBotService


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.deleted_messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"message_id": len(self.messages)}

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return {"ok": True}

    async def answer_callback_query(self, **kwargs):
        return {"ok": True}

    async def delete_message(self, **kwargs):
        self.deleted_messages.append(kwargs)
        return {"ok": True}


class _LengthLimitedTelegramClient(_FakeTelegramClient):
    def __init__(self, *, max_text_length: int) -> None:
        super().__init__()
        self.max_text_length = max_text_length

    async def send_message(self, **kwargs):
        if len(str(kwargs.get("text") or "")) > self.max_text_length:
            raise RuntimeError("message is too long")
        return await super().send_message(**kwargs)

    async def edit_message_text(self, **kwargs):
        if len(str(kwargs.get("text") or "")) > self.max_text_length:
            raise RuntimeError("message is too long")
        return await super().edit_message_text(**kwargs)


def _build_signal(
    *,
    symbol: str = "BTCUSDT",
    strategy_key: str = "breakout",
    direction: str = "long",
    timeframe: str = "15m",
    price: float = 100.0,
    invalidation_price: float = 95.0,
    created_at: datetime,
) -> AlertSignal:
    return AlertSignal(
        symbol=symbol,
        direction=direction,
        timeframe=timeframe,
        candle_open_time=created_at - timedelta(minutes=15),
        candle_close_time=created_at,
        price=price,
        rsi=32.0,
        day_change_pct=2.0,
        day_volume=15_000_000.0,
        quote_volume=15_000_000.0,
        last_candle_volume=500_000.0,
        avg_volume_20=450_000.0,
        atr=2.0,
        atr_pct=0.02,
        ema20=99.0,
        ema50=97.0,
        score=82,
        explanation="Price is breaking a local level with supportive momentum.",
        metadata={
            "strategy_key": strategy_key,
            "invalidation_price": invalidation_price,
            "setup_direction": direction,
            "interactive_ai_enabled": True,
            "market_regime_tag": "Trend",
        },
    )


class SignalLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "lifecycle.sqlite3"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.service = SignalLifecycleService(self.repository)

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_signal_progresses_from_fresh_to_hit_tp(self) -> None:
        created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        record = await self.service.create_signal(
            signal=_build_signal(created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        self.assertEqual(record.status, "fresh")

        record = await self.service.evaluate_signal_state(
            record,
            high_price=101.9,
            low_price=99.2,
            close_price=101.4,
            observed_at=created_at + timedelta(minutes=15),
        )
        self.assertEqual(record.status, "active")

        record = await self.service.evaluate_signal_state(
            record,
            high_price=103.5,
            low_price=100.5,
            close_price=103.0,
            observed_at=created_at + timedelta(minutes=30),
        )
        self.assertEqual(record.status, "confirmed")

        record = await self.service.evaluate_signal_state(
            record,
            high_price=106.0,
            low_price=102.0,
            close_price=105.4,
            observed_at=created_at + timedelta(minutes=45),
        )
        self.assertEqual(record.status, "near_tp")

        record = await self.service.evaluate_signal_state(
            record,
            high_price=107.6,
            low_price=104.0,
            close_price=107.5,
            observed_at=created_at + timedelta(minutes=60),
        )
        self.assertEqual(record.status, "hit_tp")
        self.assertEqual(record.result_type, "win")

    async def test_near_tp_signal_does_not_regress_when_current_progress_drops(self) -> None:
        created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        record = await self.service.create_signal(
            signal=_build_signal(created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        record = await self.service.evaluate_signal_state(
            record,
            high_price=106.0,
            low_price=99.5,
            close_price=105.4,
            observed_at=created_at + timedelta(minutes=15),
        )
        self.assertEqual(record.status, "near_tp")

        record = await self.service.evaluate_signal_state(
            record,
            high_price=103.5,
            low_price=100.0,
            close_price=102.5,
            observed_at=created_at + timedelta(minutes=30),
        )

        self.assertEqual(record.status, "near_tp")
        self.assertEqual(record.metadata["signal_status"], "near_tp")
        events = await self.repository.list_signal_events(record.signal_id)
        self.assertNotIn("invalid_transition", {event.event_type for event in events})

    async def test_strategy_snapshot_upsert_reuses_nullable_bucket_record(self) -> None:
        calculated_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        await self.service.recompute_strategy_snapshots(now=calculated_at)
        first = await self.repository.list_strategy_stats_snapshots(limit=1000)
        await self.service.recompute_strategy_snapshots(now=calculated_at + timedelta(minutes=1))
        second = await self.repository.list_strategy_stats_snapshots(limit=1000)

        self.assertEqual(len(second), len(first))
        self.assertTrue(all(item.calculated_at == calculated_at + timedelta(minutes=1) for item in second))

    async def test_signal_can_close_as_invalidated_or_expired(self) -> None:
        created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        invalidated = await self.service.create_signal(
            signal=_build_signal(created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        invalidated = await self.service.evaluate_signal_state(
            invalidated,
            high_price=100.4,
            low_price=94.9,
            close_price=95.1,
            observed_at=created_at + timedelta(minutes=20),
        )
        self.assertEqual(invalidated.status, "invalidated")
        self.assertEqual(invalidated.result_type, "loss")

        expired_created_at = datetime(2026, 3, 17, 0, 0, tzinfo=timezone.utc)
        expired = await self.service.create_signal(
            signal=_build_signal(symbol="ETHUSDT", created_at=expired_created_at),
            alert_id=None,
            created_at=expired_created_at,
        )
        expired = await self.service.evaluate_signal_state(
            expired,
            high_price=103.0,
            low_price=98.0,
            close_price=100.5,
            observed_at=expired.expiry_at + timedelta(minutes=1) if expired.expiry_at else expired_created_at + timedelta(days=1),
        )
        self.assertEqual(expired.status, "expired")
        self.assertEqual(expired.result_type, "neutral")

    async def test_prepare_signal_metadata_supports_rsi_bollinger_touch(self) -> None:
        created_at = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="SOLUSDT",
            direction="long",
            timeframe="15m",
            candle_open_time=created_at - timedelta(minutes=15),
            candle_close_time=created_at,
            price=100.0,
            rsi=28.0,
            day_change_pct=1.8,
            day_volume=18_000_000.0,
            quote_volume=18_000_000.0,
            last_candle_volume=600_000.0,
            avg_volume_20=500_000.0,
            atr=2.0,
            atr_pct=0.02,
            ema20=101.0,
            ema50=99.0,
            score=84,
            explanation="Price tagged the lower 30-period Bollinger Band while RSI stayed oversold.",
            metadata={
                "strategy_key": "rsi_bollinger_touch",
                "bb_lower": 97.0,
                "bb_upper": 103.0,
                "setup_direction": "long",
            },
        )

        prepared = self.service.prepare_signal_metadata(signal, created_at=created_at)

        self.assertEqual(prepared.strategy_code, "rsi_bollinger_touch")
        self.assertEqual(prepared.market_regime_tag, "Range")
        self.assertEqual(prepared.invalidation_price, 97.0)
        self.assertEqual(prepared.tp_price_primary, 103.0)
        self.assertEqual(prepared.metadata["target_model"], "1R / near 0.70")

    async def test_prepare_signal_metadata_supports_rsi_divergence(self) -> None:
        created_at = datetime(2026, 3, 18, 13, 0, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="ETHUSDT",
            direction="short",
            timeframe="15m",
            candle_open_time=created_at - timedelta(minutes=15),
            candle_close_time=created_at,
            price=100.0,
            rsi=66.0,
            day_change_pct=-0.8,
            day_volume=21_000_000.0,
            quote_volume=21_000_000.0,
            last_candle_volume=700_000.0,
            avg_volume_20=550_000.0,
            atr=2.0,
            atr_pct=0.02,
            ema20=99.0,
            ema50=98.0,
            score=81,
            explanation="Price made a higher high but RSI failed to confirm it.",
            metadata={
                "strategy_key": "rsi_divergence",
                "second_swing_price": 104.0,
                "first_swing_price": 103.0,
                "setup_direction": "short",
            },
        )

        prepared = self.service.prepare_signal_metadata(signal, created_at=created_at)

        self.assertEqual(prepared.strategy_code, "rsi_divergence")
        self.assertEqual(prepared.market_regime_tag, "Reversal")
        self.assertEqual(prepared.invalidation_price, 104.0)
        self.assertEqual(prepared.tp_price_primary, 96.0)
        self.assertEqual(prepared.metadata["target_model"], "1R / near 0.70")

    async def test_admin_snapshot_excludes_expired_from_win_rate(self) -> None:
        created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        win_signal = await self.service.create_signal(
            signal=_build_signal(created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        win_signal = await self.service.evaluate_signal_state(
            win_signal,
            high_price=101.8,
            low_price=99.5,
            close_price=101.2,
            observed_at=created_at + timedelta(minutes=5),
        )
        win_signal = await self.service.evaluate_signal_state(
            win_signal,
            high_price=103.5,
            low_price=100.0,
            close_price=103.0,
            observed_at=created_at + timedelta(minutes=10),
        )
        win_signal = await self.service.evaluate_signal_state(
            win_signal,
            high_price=107.5,
            low_price=100.0,
            close_price=107.0,
            observed_at=created_at + timedelta(minutes=30),
        )
        self.assertEqual(win_signal.result_type, "win")

        loss_signal = await self.service.create_signal(
            signal=_build_signal(symbol="ETHUSDT", created_at=created_at + timedelta(minutes=1)),
            alert_id=None,
            created_at=created_at + timedelta(minutes=1),
        )
        await self.service.evaluate_signal_state(
            loss_signal,
            high_price=100.2,
            low_price=94.8,
            close_price=95.0,
            observed_at=created_at + timedelta(minutes=31),
        )

        neutral_signal = await self.service.create_signal(
            signal=_build_signal(symbol="SOLUSDT", created_at=created_at + timedelta(minutes=2)),
            alert_id=None,
            created_at=created_at + timedelta(minutes=2),
        )
        await self.service.evaluate_signal_state(
            neutral_signal,
            high_price=103.0,
            low_price=98.0,
            close_price=100.2,
            observed_at=neutral_signal.expiry_at + timedelta(minutes=1) if neutral_signal.expiry_at else created_at + timedelta(days=2),
        )

        snapshots = await self.service.get_admin_strategy_stats(period_type="all_time", now=created_at + timedelta(days=2))
        breakout_snapshot = next(snapshot for snapshot in snapshots if snapshot.strategy_code == "breakout")
        self.assertEqual(breakout_snapshot.wins, 1)
        self.assertEqual(breakout_snapshot.losses, 1)
        self.assertEqual(breakout_snapshot.expired_neutral, 1)
        self.assertEqual(breakout_snapshot.sent_wins, 0)
        self.assertEqual(breakout_snapshot.sent_losses, 0)

        rendered = MessageRenderService().render_admin_stats([breakout_snapshot], period_label="all_time")
        self.assertIn("sent outcomes • no delivered notifications in this window", rendered)
        self.assertIn("full flow • TP <b>1</b> | SL <b>1</b> | amb <b>0</b> | exp <b>1</b> | open <b>0</b> | WR <b>50.0%</b>", rendered)

    async def test_admin_snapshot_prefers_sent_outcomes_for_primary_win_rate(self) -> None:
        created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        delivered_loss = await self.service.create_signal(
            signal=_build_signal(created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        delivered_loss = await self.service.evaluate_signal_state(
            delivered_loss,
            high_price=100.2,
            low_price=94.8,
            close_price=95.0,
            observed_at=created_at + timedelta(minutes=20),
        )
        delivered_loss = await self.repository.update_tracked_signal(
            delivered_loss.signal_id,
            metadata={**delivered_loss.metadata, "delivery_sent": True},
        )
        assert delivered_loss is not None

        hidden_win_a = await self.service.create_signal(
            signal=_build_signal(symbol="ETHUSDT", created_at=created_at + timedelta(minutes=1)),
            alert_id=None,
            created_at=created_at + timedelta(minutes=1),
        )
        hidden_win_a = await self.service.evaluate_signal_state(
            hidden_win_a,
            high_price=101.9,
            low_price=99.5,
            close_price=101.4,
            observed_at=created_at + timedelta(minutes=6),
        )
        hidden_win_a = await self.service.evaluate_signal_state(
            hidden_win_a,
            high_price=103.5,
            low_price=100.5,
            close_price=103.0,
            observed_at=created_at + timedelta(minutes=12),
        )
        hidden_win_a = await self.service.evaluate_signal_state(
            hidden_win_a,
            high_price=107.6,
            low_price=104.0,
            close_price=107.5,
            observed_at=created_at + timedelta(minutes=30),
        )
        self.assertEqual(hidden_win_a.result_type, "win")

        hidden_win_b = await self.service.create_signal(
            signal=_build_signal(symbol="SOLUSDT", created_at=created_at + timedelta(minutes=2)),
            alert_id=None,
            created_at=created_at + timedelta(minutes=2),
        )
        hidden_win_b = await self.service.evaluate_signal_state(
            hidden_win_b,
            high_price=101.9,
            low_price=99.5,
            close_price=101.4,
            observed_at=created_at + timedelta(minutes=7),
        )
        hidden_win_b = await self.service.evaluate_signal_state(
            hidden_win_b,
            high_price=103.5,
            low_price=100.5,
            close_price=103.0,
            observed_at=created_at + timedelta(minutes=14),
        )
        hidden_win_b = await self.service.evaluate_signal_state(
            hidden_win_b,
            high_price=107.6,
            low_price=104.0,
            close_price=107.5,
            observed_at=created_at + timedelta(minutes=32),
        )
        self.assertEqual(hidden_win_b.result_type, "win")

        snapshots = await self.service.get_admin_strategy_stats(period_type="all_time", now=created_at + timedelta(days=1))
        breakout_snapshot = next(snapshot for snapshot in snapshots if snapshot.strategy_code == "breakout")
        self.assertEqual(breakout_snapshot.delivered_count, 1)
        self.assertEqual(breakout_snapshot.sent_wins, 0)
        self.assertEqual(breakout_snapshot.sent_losses, 1)
        self.assertEqual(breakout_snapshot.wins, 2)
        self.assertEqual(breakout_snapshot.losses, 1)

        rendered = MessageRenderService().render_admin_stats([breakout_snapshot], period_label="all_time")
        self.assertIn("sent outcomes • TP <b>0</b> | SL <b>1</b> | amb <b>0</b> | exp <b>0</b> | open <b>0</b> | WR <b>0.0%</b>", rendered)
        self.assertIn("full flow • TP <b>2</b> | SL <b>1</b> | amb <b>0</b> | exp <b>0</b> | open <b>0</b> | WR <b>66.7%</b>", rendered)


class AdminStatsAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "admin-stats.sqlite3"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.telegram = _FakeTelegramClient()
        self.service = PrivateBotService(
            get_settings(),
            self.repository,
            self.telegram,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        self.user = await self.repository.upsert_private_user(
            telegram_user_id=501,
            username="regular_user",
            first_name="Regular",
            last_name=None,
            is_admin=False,
        )
        self.admin = await self.repository.upsert_private_user(
            telegram_user_id=777,
            username="admin_user",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_non_admin_receives_restricted_admin_stats_message(self) -> None:
        await self.service._send_admin_stats(self.user, period="7d")
        self.assertTrue(self.telegram.messages)
        self.assertIn("Restricted Section", str(self.telegram.messages[-1]["text"]))

    async def test_admin_can_open_admin_stats_screen(self) -> None:
        await self.service._send_admin_stats(self.admin, period="7d")
        self.assertTrue(self.telegram.messages)
        self.assertTrue(any("Admin Dashboard" in str(message["text"]) for message in self.telegram.messages))

    async def test_non_admin_receives_restricted_health_message(self) -> None:
        await self.service._send_admin_health(self.user)
        self.assertTrue(self.telegram.messages)
        self.assertIn("Restricted Section", str(self.telegram.messages[-1]["text"]))

    async def test_admin_health_is_truthful_and_secret_free(self) -> None:
        now = datetime.now(timezone.utc)
        await self.repository.record_telemetry_event(
            event_name="start_seen",
            created_at=now,
            telegram_user_id=self.admin.telegram_user_id,
            context="returning",
            payload={"bot_kind": "premium", "language": "en"},
        )

        await self.service._send_admin_health(self.admin)

        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Operations center", text)
        self.assertIn("Signals and delivery", text)
        self.assertIn("Generated", text)
        self.assertIn("Premium", text)
        self.assertIn("Follow-up queue", text)
        self.assertIn("User journey", text)
        self.assertNotIn("API key", text)
        self.assertNotIn("webhook secret", text)

    async def test_admin_health_uses_safe_fallback_when_metrics_are_unavailable(self) -> None:
        async def unavailable(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("metric unavailable")

        self.repository.count_followup_tasks_by_status = unavailable  # type: ignore[method-assign]
        self.repository.count_followup_tasks_due_before = unavailable  # type: ignore[method-assign]
        self.repository.count_telemetry_events = unavailable  # type: ignore[method-assign]

        await self.service._send_admin_health(self.admin)

        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Operations center", text)
        self.assertIn("Pending: <b>—</b>", text)

    async def test_health_command_is_available_to_admin(self) -> None:
        await self.service.handle_message(
            {
                "chat": {"id": self.admin.telegram_user_id, "type": "private"},
                "from": {
                    "id": self.admin.telegram_user_id,
                    "username": self.admin.username,
                    "language_code": "en",
                },
                "text": "/health",
            }
        )

        self.assertTrue(any("Operations center" in str(message["text"]) for message in self.telegram.messages))

    async def test_admin_stats_are_split_into_safe_chunks_when_message_is_long(self) -> None:
        self.service.telegram_client = _LengthLimitedTelegramClient(max_text_length=3500)

        async def _empty_stats(*, period_type: str):
            del period_type
            return []

        self.service.signal_lifecycle_service.get_admin_strategy_stats = _empty_stats  # type: ignore[method-assign]
        self.service.message_render_service.render_admin_stats = lambda *args, **kwargs: (  # type: ignore[assignment]
            "<b>Admin Dashboard</b>\n\n" + ("\n\n".join([f"<b>Block {index}</b>\n" + ("x" * 700) for index in range(1, 7)]))
        )

        await self.service._send_admin_stats(self.admin, period="7d")

        limited_client = self.service.telegram_client
        assert isinstance(limited_client, _LengthLimitedTelegramClient)
        self.assertGreaterEqual(len(limited_client.messages), 2)
        self.assertIn("Admin Dashboard", str(limited_client.messages[0]["text"]))
        self.assertTrue(any("Continued" in str(message["text"]) for message in limited_client.messages[1:]))

    async def test_admin_stats_chunking_keeps_full_latest_batch_even_with_low_cleanup_limit(self) -> None:
        limited_client = _LengthLimitedTelegramClient(max_text_length=3500)
        self.service.telegram_client = limited_client
        self.service.settings.private_bot_chat_cleanup_keep_messages = 2

        async def _empty_stats(*, period_type: str):
            del period_type
            return []

        self.service.signal_lifecycle_service.get_admin_strategy_stats = _empty_stats  # type: ignore[method-assign]
        self.service.message_render_service.render_admin_stats = lambda *args, **kwargs: (  # type: ignore[assignment]
            "<b>Admin Dashboard</b>\n\n" + ("\n\n".join([f"<b>Block {index}</b>\n" + ("x" * 700) for index in range(1, 11)]))
        )

        await self.service._send_admin_stats(self.admin, period="7d")

        self.assertGreaterEqual(len(limited_client.messages), 3)
        self.assertEqual(limited_client.deleted_messages, [])


async def _patched_test_admin_snapshot_excludes_expired_from_win_rate(self) -> None:
    created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

    win_signal = await self.service.create_signal(
        signal=_build_signal(created_at=created_at),
        alert_id=None,
        created_at=created_at,
    )
    win_signal = await self.service.evaluate_signal_state(
        win_signal,
        high_price=101.8,
        low_price=99.5,
        close_price=101.2,
        observed_at=created_at + timedelta(minutes=5),
    )
    win_signal = await self.service.evaluate_signal_state(
        win_signal,
        high_price=103.5,
        low_price=100.0,
        close_price=103.0,
        observed_at=created_at + timedelta(minutes=10),
    )
    await self.service.evaluate_signal_state(
        win_signal,
        high_price=107.5,
        low_price=100.0,
        close_price=107.0,
        observed_at=created_at + timedelta(minutes=30),
    )

    loss_signal = await self.service.create_signal(
        signal=_build_signal(symbol="ETHUSDT", created_at=created_at + timedelta(minutes=1)),
        alert_id=None,
        created_at=created_at + timedelta(minutes=1),
    )
    await self.service.evaluate_signal_state(
        loss_signal,
        high_price=100.2,
        low_price=94.8,
        close_price=95.0,
        observed_at=created_at + timedelta(minutes=31),
    )

    neutral_signal = await self.service.create_signal(
        signal=_build_signal(symbol="SOLUSDT", created_at=created_at + timedelta(minutes=2)),
        alert_id=None,
        created_at=created_at + timedelta(minutes=2),
    )
    await self.service.evaluate_signal_state(
        neutral_signal,
        high_price=103.0,
        low_price=98.0,
        close_price=100.2,
        observed_at=neutral_signal.expiry_at + timedelta(minutes=1) if neutral_signal.expiry_at else created_at + timedelta(days=2),
    )

    snapshots = await self.service.get_admin_strategy_stats(period_type="all_time", now=created_at + timedelta(days=2))
    breakout_snapshot = next(snapshot for snapshot in snapshots if snapshot.strategy_code == "breakout")
    self.assertEqual(breakout_snapshot.wins, 1)
    self.assertEqual(breakout_snapshot.losses, 1)
    self.assertEqual(breakout_snapshot.expired_neutral, 1)
    self.assertEqual(breakout_snapshot.sent_wins, 0)
    self.assertEqual(breakout_snapshot.sent_losses, 0)

    rendered = MessageRenderService().render_admin_stats([breakout_snapshot], period_label="all_time")
    self.assertIn("Admin Dashboard", rendered)
    self.assertIn("gen <b>3</b> | sent <b>0</b> | hidden <b>3</b>", rendered)
    self.assertIn("flow • TP <b>1</b> | SL <b>1</b> | amb <b>0</b> | exp <b>1</b> | WR <b>50.0%</b>", rendered)


async def _patched_test_admin_snapshot_prefers_sent_outcomes_for_primary_win_rate(self) -> None:
    created_at = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

    delivered_loss = await self.service.create_signal(
        signal=_build_signal(created_at=created_at),
        alert_id=None,
        created_at=created_at,
    )
    delivered_loss = await self.service.evaluate_signal_state(
        delivered_loss,
        high_price=100.2,
        low_price=94.8,
        close_price=95.0,
        observed_at=created_at + timedelta(minutes=20),
    )
    delivered_loss = await self.repository.update_tracked_signal(
        delivered_loss.signal_id,
        metadata={**delivered_loss.metadata, "delivery_sent": True},
    )
    assert delivered_loss is not None

    for offset, symbol in enumerate(("ETHUSDT", "SOLUSDT"), start=1):
        hidden_win = await self.service.create_signal(
            signal=_build_signal(symbol=symbol, created_at=created_at + timedelta(minutes=offset)),
            alert_id=None,
            created_at=created_at + timedelta(minutes=offset),
        )
        hidden_win = await self.service.evaluate_signal_state(
            hidden_win,
            high_price=101.9,
            low_price=99.5,
            close_price=101.4,
            observed_at=created_at + timedelta(minutes=6 + offset),
        )
        hidden_win = await self.service.evaluate_signal_state(
            hidden_win,
            high_price=103.5,
            low_price=100.5,
            close_price=103.0,
            observed_at=created_at + timedelta(minutes=12 + offset),
        )
        hidden_win = await self.service.evaluate_signal_state(
            hidden_win,
            high_price=107.6,
            low_price=104.0,
            close_price=107.5,
            observed_at=created_at + timedelta(minutes=30 + offset),
        )
        self.assertEqual(hidden_win.result_type, "win")

    snapshots = await self.service.get_admin_strategy_stats(period_type="all_time", now=created_at + timedelta(days=1))
    breakout_snapshot = next(snapshot for snapshot in snapshots if snapshot.strategy_code == "breakout")
    self.assertEqual(breakout_snapshot.delivered_count, 1)
    self.assertEqual(breakout_snapshot.sent_wins, 0)
    self.assertEqual(breakout_snapshot.sent_losses, 1)
    self.assertEqual(breakout_snapshot.wins, 2)
    self.assertEqual(breakout_snapshot.losses, 1)

    rendered = MessageRenderService().render_admin_stats([breakout_snapshot], period_label="all_time")
    self.assertIn("gen <b>3</b> | sent <b>1</b> | hidden <b>2</b>", rendered)
    self.assertIn("flow • TP <b>2</b> | SL <b>1</b> | amb <b>0</b> | exp <b>0</b> | WR <b>66.7%</b>", rendered)


async def _patched_test_admin_stats_are_split_into_safe_chunks_when_message_is_long(self) -> None:
    await self.service._send_admin_stats(self.admin, period="7d")
    self.assertEqual(len(self.telegram.messages), 1)
    self.assertIn("Admin Dashboard", str(self.telegram.messages[0]["text"]))


async def _patched_test_admin_stats_chunking_keeps_full_latest_batch_even_with_low_cleanup_limit(self) -> None:
    await self.service._send_admin_stats(self.admin, period="7d")
    self.assertEqual(len(self.telegram.messages), 1)
    self.assertEqual(self.telegram.deleted_messages, [])


SignalLifecycleServiceTests.test_admin_snapshot_excludes_expired_from_win_rate = _patched_test_admin_snapshot_excludes_expired_from_win_rate
SignalLifecycleServiceTests.test_admin_snapshot_prefers_sent_outcomes_for_primary_win_rate = _patched_test_admin_snapshot_prefers_sent_outcomes_for_primary_win_rate
AdminStatsAccessTests.test_admin_stats_are_split_into_safe_chunks_when_message_is_long = _patched_test_admin_stats_are_split_into_safe_chunks_when_message_is_long
AdminStatsAccessTests.test_admin_stats_chunking_keeps_full_latest_batch_even_with_low_cleanup_limit = _patched_test_admin_stats_chunking_keeps_full_latest_batch_even_with_low_cleanup_limit
