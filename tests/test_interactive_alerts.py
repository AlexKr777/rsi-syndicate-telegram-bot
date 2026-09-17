from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from src.bot.interactive_alerts import InteractiveAlertService
from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult
from src.storage.models import AlertRecord, InteractiveAlertState


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.answers: list[dict[str, object]] = []

    async def answer_callback_query(self, **kwargs):
        self.answers.append(kwargs)
        return {"ok": True}


class InteractiveAlertCompareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.telegram = _FakeTelegramClient()
        self.service = InteractiveAlertService(
            settings=get_settings(),
            repository=SimpleNamespace(),
            telegram_client=self.telegram,
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            prepared_feature_service=SimpleNamespace(),
        )

    async def test_followup_compare_uses_original_alert_as_reference(self) -> None:
        now = datetime.now(timezone.utc)
        alert = AlertRecord(
            id=101,
            symbol="INXUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            alert_price=0.013136,
            alert_rsi=74.0,
            day_change_pct=None,
            day_volume=7_600_000.0,
            score=88,
            alert_sent_at=now,
            followup_due_at=now + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"quote_volume": 7_600_000.0, "strategy_key": "rsi"},
            strategy_key="rsi",
        )
        followup = FollowUpResult(
            alert_id=101,
            symbol="INXUSDT",
            direction="overbought",
            timeframe="15m",
            alert_price=0.013136,
            current_price=0.012333,
            alert_rsi=74.0,
            current_rsi=61.5,
            move_pct=-6.11,
            summary="Price corrected lower.",
            score=88,
            observed_at=now + timedelta(hours=2),
            stage="2h",
            favorable_move_pct=6.11,
            adverse_move_pct=0.0,
            thesis_result_state="favorable",
            metadata={"live_rsi": 60.9},
        )
        reference_signal = AlertSignal(
            symbol="INXUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            price=0.013136,
            rsi=74.0,
            day_change_pct=None,
            day_volume=7_600_000.0,
            quote_volume=7_600_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=88,
            explanation="",
            metadata={"strategy_key": "rsi"},
        )
        state = InteractiveAlertState(
            id=1,
            chat_id="777001",
            message_id=55,
            alert_id=101,
            destination_kind="private",
            symbol="INXUSDT",
            original_timeframe="15m",
            displayed_timeframe="15m",
            direction="overbought",
            is_preview=False,
            created_at=now,
            updated_at=now,
            metadata={
                "message_kind": "followup",
                "followup_stage": "2h",
                "telegram_chat_id": "777001",
                "language_code": "en",
            },
        )

        captured: dict[str, object] = {}

        async def _resolve_alert_record_for_state(_state: InteractiveAlertState) -> AlertRecord:
            return alert

        async def _build_followup_snapshot(**kwargs):
            del kwargs
            return followup, pd.DataFrame(), reference_signal

        async def _build_compare_passed_lines(**kwargs):
            del kwargs
            return ["Score cleared your floor: 88/82"]

        async def _send_detail_card(*, state, text, reply_markup=None):
            del state, reply_markup
            captured["text"] = text

        async def _safe_answer(query_id: str, *, text: str | None = None) -> None:
            del query_id, text

        self.service._resolve_alert_record_for_state = _resolve_alert_record_for_state  # type: ignore[method-assign]
        self.service._build_followup_snapshot = _build_followup_snapshot  # type: ignore[method-assign]
        self.service._build_compare_passed_lines = _build_compare_passed_lines  # type: ignore[method-assign]
        self.service._send_detail_card = _send_detail_card  # type: ignore[method-assign]
        self.service._safe_answer = _safe_answer  # type: ignore[method-assign]

        await self.service._handle_signal_compare("cb-1", state)

        text = str(captured.get("text") or "")
        self.assertIn("vs original signal", text)
        self.assertIn("What changed", text)
        self.assertIn("RSI moved from 74.00 to 61.50", text)
        self.assertNotIn("No useful comparison point is available yet.", text)

    async def test_regular_compare_uses_original_alert_and_live_snapshot(self) -> None:
        now = datetime.now(timezone.utc)
        alert = AlertRecord(
            id=202,
            symbol="SIRENUSDT",
            direction="overbought",
            timeframe="5m",
            candle_open_time=now - timedelta(minutes=5),
            candle_close_time=now,
            alert_price=0.0051,
            alert_rsi=72.0,
            day_change_pct=None,
            day_volume=6_200_000.0,
            score=76,
            alert_sent_at=now,
            followup_due_at=now + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"quote_volume": 6_200_000.0, "strategy_key": "rsi"},
            strategy_key="rsi",
        )
        live_signal = AlertSignal(
            symbol="SIRENUSDT",
            direction="short",
            timeframe="5m",
            candle_open_time=now,
            candle_close_time=now + timedelta(minutes=5),
            price=0.0049,
            rsi=64.0,
            day_change_pct=None,
            day_volume=7_900_000.0,
            quote_volume=7_900_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=83,
            explanation="",
            metadata={"strategy_key": "rsi"},
        )
        state = InteractiveAlertState(
            id=2,
            chat_id="777001",
            message_id=56,
            alert_id=202,
            destination_kind="private",
            symbol="SIRENUSDT",
            original_timeframe="5m",
            displayed_timeframe="5m",
            direction="overbought",
            is_preview=False,
            created_at=now,
            updated_at=now,
            metadata={
                "message_kind": "alert",
                "telegram_chat_id": "777001",
                "language_code": "en",
            },
        )

        captured: dict[str, object] = {}

        async def _resolve_alert_record_for_state(_state: InteractiveAlertState) -> AlertRecord:
            return alert

        async def _build_snapshot(symbol: str, timeframe: str, **kwargs):
            del symbol, timeframe, kwargs
            return SimpleNamespace(signal=live_signal, frame=pd.DataFrame())

        async def _build_compare_passed_lines(**kwargs):
            del kwargs
            return ["Score cleared your floor: 83/76"]

        async def _send_detail_card(*, state, text, reply_markup=None):
            del state, reply_markup
            captured["text"] = text

        async def _safe_answer(query_id: str, *, text: str | None = None) -> None:
            del query_id, text

        self.service._resolve_alert_record_for_state = _resolve_alert_record_for_state  # type: ignore[method-assign]
        self.service._build_snapshot = _build_snapshot  # type: ignore[method-assign]
        self.service._build_compare_passed_lines = _build_compare_passed_lines  # type: ignore[method-assign]
        self.service._send_detail_card = _send_detail_card  # type: ignore[method-assign]
        self.service._safe_answer = _safe_answer  # type: ignore[method-assign]

        await self.service._handle_signal_compare("cb-2", state)

        text = str(captured.get("text") or "")
        self.assertIn("vs original signal", text)
        self.assertIn("What changed", text)
        self.assertIn("The setup looks stronger now", text)
        self.assertIn("RSI moved from 72.00 to 64.00", text)
        self.assertNotIn("No useful comparison point is available yet.", text)


if __name__ == "__main__":
    unittest.main()
