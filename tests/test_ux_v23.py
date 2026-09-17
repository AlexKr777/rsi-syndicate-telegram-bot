from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.bot.formatters import format_alert_message, format_followup_message
from src.core.models import AlertSignal, FollowUpResult
from src.signals.domain import resolve_trade_direction
from src.signals.service import InvalidSignalPayloadError, SignalLifecycleService, StrategyRuleEngine
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.results_service import ResultsService
from src.userbot.access_view import build_access_view_model
from src.userbot.formatters import format_admin_health_message
from src.userbot.ux_v2 import format_results_message
from src.userbot.ux_v2 import (
    build_home_keyboard,
    build_market_keyboard,
    build_market_sets_keyboard,
    build_strategies_keyboard,
    format_flow_message,
)


def _callbacks(markup: dict[str, object]) -> list[str]:
    return [
        str(button["callback_data"])
        for row in markup["inline_keyboard"]
        for button in row
    ]


def _oversold_signal(*, invalidation_price: float = 2.8753) -> AlertSignal:
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    return AlertSignal(
        symbol="TESTUSDT",
        direction="oversold",
        timeframe="15m",
        candle_open_time=now - timedelta(minutes=15),
        candle_close_time=now,
        price=2.949,
        rsi=27.4,
        day_change_pct=-2.1,
        day_volume=10_000_000.0,
        quote_volume=10_000_000.0,
        last_candle_volume=100_000.0,
        avg_volume_20=90_000.0,
        atr=0.04,
        atr_pct=0.013,
        ema20=2.96,
        ema50=3.01,
        score=78,
        explanation="RSI entered the oversold area after a controlled pullback.",
        metadata={
            "strategy_key": "rsi",
            "invalidation_price": invalidation_price,
        },
    )


class UXV23NavigationSurfaceTests(unittest.TestCase):
    def test_pro_home_uses_the_same_signal_setup_entry_as_simple_home(self) -> None:
        markup = build_home_keyboard(language_code="ru", is_pro=True, include_gold=False)
        callbacks = _callbacks(markup)
        labels = [button["text"] for row in markup["inline_keyboard"] for button in row]

        self.assertIn("v2:flow:hub", callbacks)
        self.assertNotIn("v2:flows:hub", callbacks)
        self.assertIn("🎛 Настроить сигналы", labels)
        self.assertNotIn("🧩 Профили сигналов", labels)

    def test_strategy_list_does_not_repeat_signal_setup(self) -> None:
        callbacks = _callbacks(
            build_strategies_keyboard(
                language_code="ru",
                strategies=[("rsi", "RSI", True, False)],
            )
        )
        self.assertNotIn("v2:flow:hub", callbacks)

    def test_market_opens_real_watchlist_management_directly(self) -> None:
        callbacks = _callbacks(build_market_keyboard(language_code="ru", include_gold=False))
        self.assertIn("v2:watchlist:manage", callbacks)
        self.assertNotIn("v2:watchlist:hub", callbacks)

    def test_market_sets_do_not_mix_in_watchlist_management(self) -> None:
        callbacks = _callbacks(
            build_market_sets_keyboard(
                language_code="ru",
                builtin_sets=[("majors", "Крупные монеты")],
                saved_sets=[(1, "Мой набор")],
            )
        )
        self.assertIn("v2:market:set:tracked", callbacks)
        self.assertNotIn("v2:watchlist:manage", callbacks)

    def test_signal_setup_does_not_expose_an_internal_profile_as_the_main_state(self) -> None:
        text = format_flow_message(
            language_code="ru",
            flow_name="Мой поток",
            summary="Сигналы: сбалансированный режим.",
        )
        self.assertIn("Выберите, какие торговые ситуации отслеживать", text)
        self.assertNotIn("Активный профиль", text)

    def test_admin_access_uses_product_and_control_sections(self) -> None:
        text = build_access_view_model(
            access_state=SimpleNamespace(is_admin=True, access_status="paid", has_premium_access=True, ends_at=None),
            is_gold_enabled=True,
            profile_label="Не используется",
            delivery_label="Сразу",
            language_code="ru",
        ).render(language_code="ru")
        self.assertIn("Панель администратора", text)
        self.assertIn("<b>Продукт</b>", text)
        self.assertIn("<b>Контроль</b>", text)
        self.assertNotIn("Доступно сейчас", text)

    def test_admin_operations_screen_has_clear_sections_without_placeholder_noise(self) -> None:
        text = format_admin_health_message(
            generated_at_label="2026-07-27 14:00 UTC",
            signals_generated=None,
            premium_delivery_records=4,
            classic_delivery_records=2,
            pending_followups=3,
            processing_followups=1,
            stale_followups=0,
            database_size_label="24 GB",
            funnel_counts={"start_seen": 10},
            language_code="ru",
        )
        self.assertIn("Операционный центр", text)
        self.assertIn("<b>Состояние</b>", text)
        self.assertIn("<b>Сигналы и доставка</b>", text)
        self.assertNotIn("Не отслеживается", text)

    def test_results_period_matches_selected_day_range(self) -> None:
        text = format_results_message(
            language_code="ru",
            total=1,
            confirmed=0,
            broken=0,
            open_count=1,
            insufficient=0,
            followups=0,
            updated_at="12:00",
            days=1,
        )
        self.assertIn("Период: сегодня", text)


class UXV23SignalIntegrityTests(unittest.TestCase):
    def test_oversold_is_normalized_to_long_before_levels_and_storage(self) -> None:
        signal = _oversold_signal()
        prepared = StrategyRuleEngine().prepare(
            signal,
            created_at=signal.candle_close_time,
            source_type="test",
        )

        self.assertEqual(resolve_trade_direction("oversold"), "long")
        self.assertEqual(prepared.trade_direction, "long")
        self.assertLess(float(prepared.invalidation_price), signal.price)
        self.assertGreater(float(prepared.tp_price_primary), signal.price)
        self.assertEqual(prepared.metadata["setup_direction"], "long")
        self.assertEqual(prepared.metadata["rsi_status"], "oversold")

    def test_bad_short_invalidation_is_rejected_instead_of_being_corrected(self) -> None:
        signal = _oversold_signal(invalidation_price=2.80)
        signal.direction = "overbought"
        signal.rsi = 73.0
        with self.assertRaisesRegex(InvalidSignalPayloadError, "invalidation"):
            StrategyRuleEngine().prepare(
                signal,
                created_at=signal.candle_close_time,
                source_type="test",
            )

    def test_unknown_or_conflicting_direction_is_rejected(self) -> None:
        unknown = _oversold_signal()
        unknown.direction = "sideways"
        unknown.metadata.pop("setup_direction", None)
        with self.assertRaisesRegex(InvalidSignalPayloadError, "direction"):
            StrategyRuleEngine().prepare(
                unknown,
                created_at=unknown.candle_close_time,
                source_type="test",
            )

        conflicting = _oversold_signal()
        conflicting.direction = "short"
        conflicting.metadata["setup_direction"] = "long"
        with self.assertRaisesRegex(InvalidSignalPayloadError, "conflicts"):
            StrategyRuleEngine().prepare(
                conflicting,
                created_at=conflicting.candle_close_time,
                source_type="test",
            )

    def test_v23_card_shows_rsi_separately_from_setup_score_and_uses_long(self) -> None:
        signal = _oversold_signal()
        prepared = StrategyRuleEngine().prepare(
            signal,
            created_at=signal.candle_close_time,
            source_type="test",
        )
        signal.metadata = {**signal.metadata, **prepared.metadata, "text_layout": "v2_3_signal"}

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")

        self.assertIn("ЛОНГ", text)
        self.assertIn("RSI(14): <b>27.40</b>", text)
        self.assertIn("Оценка сетапа: <b>78/100</b>", text)
        self.assertIn("Почему появился сигнал", text)
        self.assertNotIn("⭐", text)

    def test_v23_followup_normalizes_oversold_to_long(self) -> None:
        signal = _oversold_signal()
        text = format_followup_message(
            FollowUpResult(
                alert_id=1,
                symbol=signal.symbol,
                direction="oversold",
                timeframe=signal.timeframe,
                alert_price=signal.price,
                current_price=3.0,
                alert_rsi=signal.rsi,
                current_rsi=38.0,
                move_pct=1.7,
                score=signal.score,
                observed_at=signal.candle_close_time + timedelta(hours=2),
                stage="2h",
                summary="Сценарий удерживается.",
                metadata={"text_layout": "v2_3_signal"},
            ),
            timezone.utc,
            language_code="ru",
        )
        self.assertIn("ЛОНГ", text)


class UXV23ResultsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "results.sqlite3"
        await initialize_database(str(self.path))
        self.repository = Repository(str(self.path))
        await self.repository.connect()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_fast_hub_summary_uses_persisted_lifecycle_and_latest_followup_only(self) -> None:
        signal = _oversold_signal()
        now = signal.candle_close_time
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now,
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        lifecycle = await SignalLifecycleService(self.repository).create_signal(
            signal=signal,
            alert_id=alert_id,
            created_at=now,
        )
        self.assertEqual(lifecycle.direction, "long")
        for stage, observed_at in (("2h", now + timedelta(hours=2)), ("4h", now + timedelta(hours=4))):
            await self.repository.save_followup_result(
                FollowUpResult(
                    alert_id=alert_id,
                    symbol=signal.symbol,
                    direction="long",
                    timeframe=signal.timeframe,
                    alert_price=signal.price,
                    current_price=3.02,
                    alert_rsi=signal.rsi,
                    current_rsi=40.0,
                    move_pct=2.4,
                    score=signal.score,
                    observed_at=observed_at,
                    stage=stage,
                    summary="Persisted follow-up.",
                )
            )

        summary = await ResultsService(self.repository).summary(
            days=7,
            now=now + timedelta(hours=5),
            include_records=False,
        )

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.followups, 1)
        self.assertEqual(summary.records, ())
        self.assertEqual(summary.followup_records, ())
