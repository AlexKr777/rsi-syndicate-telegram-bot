from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.classicbot.service import ClassicBotService
from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult


class _FakeRepository:
    def __init__(self) -> None:
        self.alert_exists = False
        self.stage_exists = False
        self.recipients = [
            (
                SimpleNamespace(telegram_user_id=777001),
                SimpleNamespace(
                    direct_signal_delivery_enabled=True,
                    followup_delivery_enabled=True,
                    delivery_mode="instant",
                ),
            )
        ]

    async def list_private_signal_recipients(self, *, bot_kind: str):
        del bot_kind
        return list(self.recipients)

    async def delivered_signal_exists(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str,
        alert_id: int,
        content_kind: str,
        message_kind: str,
    ) -> bool:
        del telegram_user_id, bot_kind, alert_id, content_kind
        if message_kind == "alert":
            return self.alert_exists
        return self.stage_exists


class _FakeRouter:
    def __init__(self) -> None:
        self.alerts: list[dict[str, object]] = []
        self.followups: list[dict[str, object]] = []

    async def send_raw_alert_to_chat(self, signal, *, chat_id: str, destination_kind: str, preview: bool = False):
        self.alerts.append(
            {
                "signal": signal,
                "chat_id": chat_id,
                "destination_kind": destination_kind,
                "preview": preview,
            }
        )
        return SimpleNamespace(sent=True, telegram_message_id=1, metadata={"telegram_chat_id": chat_id})

    async def send_followup_to_chat(self, result, *, chat_id: str, destination_kind: str):
        self.followups.append(
            {
                "result": result,
                "chat_id": chat_id,
                "destination_kind": destination_kind,
            }
        )
        return SimpleNamespace(sent=True, telegram_message_id=2, metadata={"telegram_chat_id": chat_id})


class _FakeChartRenderer:
    def __init__(self) -> None:
        self.cleaned: list[object] = []

    def cleanup(self, path) -> None:
        self.cleaned.append(path)


class _FakeDraftGenerator:
    def _evaluate_public_best_setup(self, signal):
        del signal
        return SimpleNamespace(eligible=True, reason="strong_setup")

    def _evaluate_results_followup(self, signal, result):
        del signal, result
        return SimpleNamespace(eligible=True, reason="high_quality")

    async def _evaluate_results_stage_policy(self, result):
        del result
        return SimpleNamespace(eligible=True, reason="allowed_stage")


class ClassicBotServiceDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def _signal(self) -> AlertSignal:
        now = datetime.now(timezone.utc)
        return AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            price=100.0,
            rsi=28.0,
            day_change_pct=None,
            day_volume=12_000_000.0,
            quote_volume=12_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=88,
            explanation="",
            metadata={"strategy_key": "breakout", "language_code": "en"},
        )

    def _followup(self) -> FollowUpResult:
        now = datetime.now(timezone.utc)
        return FollowUpResult(
            alert_id=11,
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            current_price=103.0,
            alert_rsi=28.0,
            current_rsi=36.0,
            move_pct=3.0,
            summary="Follow-up improved.",
            score=90,
            observed_at=now,
            stage="2h",
            favorable_move_pct=3.0,
            adverse_move_pct=0.0,
            thesis_result_state="favorable",
            metadata={"strategy_key": "breakout", "language_code": "en"},
        )

    async def asyncSetUp(self) -> None:
        self.repository = _FakeRepository()
        self.router = _FakeRouter()
        self.chart_renderer = _FakeChartRenderer()
        settings = get_settings().model_copy(
            update={
                "telegram_classic_bot_token": "classic-test-token",
                "classic_bot_signal_delay_minutes": 0,
                "classic_bot_signal_delivery_enabled": True,
            }
        )
        self.service = ClassicBotService(
            settings=settings,
            repository=self.repository,  # type: ignore[arg-type]
            telegram_client=SimpleNamespace(),
            router=self.router,  # type: ignore[arg-type]
            binance_client=SimpleNamespace(),
            chart_renderer=self.chart_renderer,  # type: ignore[arg-type]
            interactive_alert_service=SimpleNamespace(),
            draft_generator=_FakeDraftGenerator(),  # type: ignore[arg-type]
        )
        self.service._watchlist_set = AsyncMock(return_value={"BTCUSDT"})  # type: ignore[method-assign]
        self.service._global_favorite_symbols = AsyncMock(return_value=["BTCUSDT"])  # type: ignore[method-assign]
        self.service._apply_user_preferences_to_signal = lambda signal, settings: signal  # type: ignore[method-assign]
        self.service._signal_matches_user_settings = lambda *args, **kwargs: (True, [])  # type: ignore[method-assign]
        self.service._register_private_delivery = AsyncMock()  # type: ignore[method-assign]
        self.service.render_delivery_chart = AsyncMock(return_value=Path("classic-chart.png"))  # type: ignore[method-assign]
        self.service._localize_followup_result = lambda result, settings: result  # type: ignore[method-assign]

    async def test_deliver_classic_alert_awaits_queue_reason_with_favorites_and_user(self) -> None:
        queue_reason = AsyncMock(return_value=None)
        self.service._live_delivery_queue_reason = queue_reason  # type: ignore[method-assign]

        await self.service.deliver_classic_alert(self._signal(), alert_id=11)

        queue_reason.assert_awaited_once()
        kwargs = queue_reason.await_args.kwargs
        self.assertEqual(kwargs["favorite_symbols"], {"BTCUSDT"})
        self.assertEqual(kwargs["telegram_user_id"], 777001)
        self.assertEqual(len(self.router.alerts), 1)

    async def test_deliver_classic_followup_awaits_queue_reason_with_favorites_and_user(self) -> None:
        self.repository.alert_exists = True
        queue_reason = AsyncMock(return_value=None)
        self.service._followup_delivery_queue_reason = queue_reason  # type: ignore[method-assign]

        await self.service.deliver_classic_followup(self._signal(), self._followup())

        queue_reason.assert_awaited_once()
        kwargs = queue_reason.await_args.kwargs
        self.assertEqual(kwargs["favorite_symbols"], {"BTCUSDT"})
        self.assertEqual(kwargs["telegram_user_id"], 777001)
        self.assertEqual(len(self.router.followups), 1)


class ClassicBotNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_uses_guided_first_run_and_compact_returning_copy(self) -> None:
        service = ClassicBotService.__new__(ClassicBotService)
        service.settings = get_settings().model_copy(
            update={
                "classic_bot_signal_delay_minutes": 30,
                "private_bot_trial_days": 2,
                "channels_folder_link": "",
            }
        )
        service._ensure_user_settings = AsyncMock(return_value=SimpleNamespace(language_code="en"))  # type: ignore[method-assign]
        service._language_code = lambda settings: "en"  # type: ignore[method-assign]
        service._send_chat_message = AsyncMock()  # type: ignore[method-assign]

        await service._send_start(777001, None, first_time=True)
        first_call = service._send_chat_message.await_args.kwargs
        self.assertIn("Welcome to Syndicate Classic", str(first_call["text"]))
        first_callbacks = [
            str(button["callback_data"])
            for row in first_call["reply_markup"].get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:welcome:example", first_callbacks)
        self.assertIn("ux:help:compare", first_callbacks)

        service._send_chat_message.reset_mock()
        await service._send_start(777001, None, first_time=False)
        returning_call = service._send_chat_message.await_args.kwargs
        self.assertIn("Welcome back", str(returning_call["text"]))
        self.assertNotIn("Welcome to Syndicate Classic", str(returning_call["text"]))
        self.assertEqual(returning_call["reply_markup"], first_call["reply_markup"])

    async def test_classic_language_confirmation_does_not_say_pro_plus(self) -> None:
        service = ClassicBotService.__new__(ClassicBotService)
        service.bot_kind = "classic"
        settings = SimpleNamespace(onboarding_completed_at=None)
        service._save_user_settings = AsyncMock(return_value=settings)  # type: ignore[method-assign]
        service._send_or_edit_text = AsyncMock()  # type: ignore[method-assign]
        service._record_funnel_event = AsyncMock()  # type: ignore[method-assign]
        service._send_start = AsyncMock()  # type: ignore[method-assign]

        await service._apply_language_choice(
            SimpleNamespace(telegram_user_id=777001),
            current_settings=settings,
            language_code="en",
            chat_id="777001",
            edit_message_id=12,
            context="welcome",
        )

        confirmation = str(service._send_or_edit_text.await_args.kwargs["text"])
        self.assertIn("Classic", confirmation)
        self.assertNotIn("PRO+", confirmation)
        service._send_start.assert_awaited_once_with(777001, None, first_time=True)


if __name__ == "__main__":
    unittest.main()
