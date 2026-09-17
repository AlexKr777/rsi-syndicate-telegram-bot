from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult
from src.localization import ui_text
from src.storage.db import initialize_database
from src.storage.models import AlertRecord, FollowUpResultRecord
from src.storage.repository import Repository
from src.userbot.experience import BUILTIN_WATCHLIST_THEMES
from src.userbot.callbacks import parse_userbot_callback_data
from src.userbot.service import PrivateBotService


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.answers: list[dict[str, object]] = []
        self.deleted: list[dict[str, object]] = []
        self.identity = {"id": 1, "username": "SyndicateProBot"}

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"message_id": len(self.messages)}

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return {"ok": True}

    async def answer_callback_query(self, **kwargs):
        self.answers.append(kwargs)
        return {"ok": True}

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return {"ok": True}

    async def get_me(self):
        return dict(self.identity)


class _FakeInteractiveAlertService:
    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.stopped: list[dict[str, object]] = []
        self.registered: list[dict[str, object]] = []

    async def start_chat_loading_indicator(self, **kwargs):
        self.started.append(kwargs)
        return {"id": len(self.started), **kwargs}

    async def stop_loading_indicator(self, handle, *, final_stage: str):
        self.stopped.append({"handle": handle, "final_stage": final_stage})

    async def register_alert_message(self, **kwargs):
        self.registered.append(kwargs)


class _FakeRouter:
    def __init__(self) -> None:
        self.alerts: list[dict[str, object]] = []

    async def send_raw_alert_to_chat(self, signal, *, chat_id: str, destination_kind: str, preview: bool = False):
        self.alerts.append(
            {
                "signal": signal,
                "chat_id": chat_id,
                "destination_kind": destination_kind,
                "preview": preview,
            }
        )
        return SimpleNamespace(
            sent=True,
            telegram_message_id=len(self.alerts),
            metadata={"telegram_chat_id": chat_id},
        )


class _FakeChartRenderer:
    def __init__(self) -> None:
        self.rendered: list[dict[str, object]] = []
        self.cleaned: list[object] = []

    async def render_alert_chart(self, frame, signal, preview: bool = False):
        self.rendered.append({"frame": frame, "signal": signal, "preview": preview})
        return Path("fake-chart.png")

    def cleanup(self, path) -> None:
        self.cleaned.append(path)


class _FakeBinanceClient:
    def __init__(self) -> None:
        self.symbols = {
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "DOGEUSDT",
            "PEPEUSDT",
            "XAUUSD",
        }

    async def get_active_usdt_symbols(self, force_refresh: bool = False):
        del force_refresh
        return sorted(self.symbols)

    async def get_all_ticker_stats(self, force_refresh: bool = False):
        del force_refresh
        return {
            symbol: SimpleNamespace(last_price=1.0, price_change_percent=2.5, quote_volume=1_500_000.0, volume=500_000.0)
            for symbol in self.symbols
        }

    async def get_klines(self, symbol: str, timeframe: str, limit: int):
        del symbol, timeframe, limit
        return pd.DataFrame()


class UserBotServiceBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = None
        self.temp_root = Path(".tmp_test_userbot")
        self.temp_root.mkdir(exist_ok=True)
        self.sqlite_path = self.temp_root / f"userbot_{uuid.uuid4().hex}.db"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.telegram = _FakeTelegramClient()
        self.interactive = _FakeInteractiveAlertService()
        self.router = _FakeRouter()
        self.chart_renderer = _FakeChartRenderer()
        self.service = PrivateBotService(
            settings=get_settings(),
            repository=self.repository,
            telegram_client=self.telegram,
            router=self.router,
            binance_client=_FakeBinanceClient(),
            chart_renderer=self.chart_renderer,
            interactive_alert_service=self.interactive,
            bot_kind="premium",
            destination_kind="private",
            content_kind="private_pro",
            onboarding_service=None,
        )
        self.service.settings.private_bot_chat_cleanup_keep_messages = 7
        self.service.settings.classic_bot_chat_cleanup_keep_messages = 7
        self.user = await self.repository.upsert_private_user(
            telegram_user_id=777001,
            username="tester",
            first_name="Test",
            last_name="User",
        )
        shell_settings = await self.service._ensure_user_settings(self.user.telegram_user_id, preferred_language="en")
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        if self.sqlite_path.exists():
            self.sqlite_path.unlink()

    def _make_signal(
        self,
        symbol: str,
        *,
        strategy_key: str = "rsi",
        direction: str = "oversold",
        score: int = 82,
        timeframe: str = "15m",
        atr_pct: float = 0.0,
        candle_close_time: datetime | None = None,
    ) -> AlertSignal:
        close_time = candle_close_time or datetime.now(timezone.utc)
        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            candle_open_time=close_time - timedelta(minutes=15),
            candle_close_time=close_time,
            price=100.0,
            rsi=34.0 if direction in {"long", "oversold"} else 66.0,
            day_change_pct=None,
            day_volume=25_000_000.0,
            quote_volume=25_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=atr_pct,
            ema20=0.0,
            ema50=0.0,
            score=score,
            explanation="",
            metadata={"strategy_key": strategy_key, "asset_class": "crypto", "atr_pct": atr_pct},
        )

    async def test_manual_watchlist_add_updates_favorites_without_overwriting_active_set(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            active_watchlist_theme="majors",
            active_custom_theme_name=None,
        )

        handled = await self.service._try_handle_watchlist_input(self.user, "+ADA")

        self.assertTrue(handled)
        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.active_watchlist_theme, "majors")
        symbols = await self.service._favorite_symbols(self.user.telegram_user_id)
        self.assertEqual(symbols, ["ADAUSDT"])
        active_scope = await self.service._watchlist_symbols(self.user.telegram_user_id)
        for symbol in BUILTIN_WATCHLIST_THEMES["majors"]:
            self.assertIn(symbol, active_scope)
        self.assertNotIn("ADAUSDT", active_scope)

    async def test_v22_strategy_settings_persist_and_change_delivery_filters(self) -> None:
        updated = await self.service._update_v2_strategy_settings(
            self.user,
            strategy_key="rsi",
            change="signals",
        )
        assert updated is not None
        self.assertTrue(updated.direct_signal_delivery_enabled)

        strict = await self.service._update_v2_strategy_settings(
            self.user,
            strategy_key="rsi",
            change="strict",
        )
        assert strict is not None
        self.assertEqual(strict.signal_profile, "conservative")
        self.assertGreaterEqual(strict.preferred_min_score, 80)

        stored = await self.repository.get_premium_strategy_settings(
            self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
        )
        assert stored is not None
        self.assertTrue(stored.direct_signal_delivery_enabled)
        self.assertEqual(stored.signal_profile, "conservative")
        self.assertGreaterEqual(stored.preferred_min_score, 80)

    async def test_v22_callback_smoke_keeps_strategy_back_on_its_own_message_stack(self) -> None:
        async def invoke(callback_data: str) -> None:
            action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(action, callback_data)
            assert action is not None
            await self.service._handle_v2_action(
                self.user,
                action=action,
                query_id=f"query:{callback_data}",
                chat_id=str(self.user.telegram_user_id),
                edit_message_id=4242,
            )

        await invoke("v2:home:simple")
        await invoke("v2:strategies:hub")
        await invoke("v2:strategies:open:rsi")
        await invoke("v2:strategies:settings:rsi")
        await invoke("v2:strategies:delivery:rsi:signals")
        await invoke("v2:nav:back")

        text = str(self.telegram.edits[-1]["text"])
        self.assertIn("RSI", text)
        callbacks = {
            button["callback_data"]
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertIn("v2:strategies:settings:rsi", callbacks)

    async def test_v22_market_set_switches_persisted_strategy_scope(self) -> None:
        action = parse_userbot_callback_data("v2:market:set:tracked")
        self.assertIsNotNone(action)
        assert action is not None
        await self.service._handle_v2_action(
            self.user,
            action=action,
            query_id="query:market-set",
            chat_id=str(self.user.telegram_user_id),
            edit_message_id=5151,
        )

        strategy_settings = await self.repository.get_premium_strategy_settings(
            self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
        )
        assert strategy_settings is not None
        self.assertTrue(strategy_settings.watchlist_only)
        self.assertEqual(strategy_settings.active_watchlist_theme, "watchlist")

    async def test_v23_market_back_never_falls_into_legacy_watchlist_or_themes(self) -> None:
        async def invoke(callback_data: str) -> None:
            action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(action, callback_data)
            assert action is not None
            await self.service._handle_v2_action(
                self.user,
                action=action,
                query_id=f"query:{callback_data}",
                chat_id=str(self.user.telegram_user_id),
                edit_message_id=6161,
            )

        async def assert_market_screen() -> None:
            markup = self.telegram.edits[-1]["reply_markup"]
            callbacks = {
                button["callback_data"]
                for row in markup["inline_keyboard"]
                for button in row
            }
            self.assertIn("v2:watchlist:manage", callbacks)
            self.assertIn("v2:market:sets", callbacks)
            self.assertFalse(any(callback.startswith("ux:") for callback in callbacks))

        await invoke("v2:home:simple")
        await invoke("v2:market:hub")
        await invoke("v2:watchlist:manage")
        await invoke("v2:nav:back")
        await assert_market_screen()

        await invoke("v2:market:sets")
        await invoke("v2:nav:back")
        await assert_market_screen()

    async def test_v23_saved_profiles_return_to_signal_setup(self) -> None:
        async def invoke(callback_data: str) -> None:
            action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(action, callback_data)
            assert action is not None
            await self.service._handle_v2_action(
                self.user,
                action=action,
                query_id=f"query:{callback_data}",
                chat_id=str(self.user.telegram_user_id),
                edit_message_id=6262,
            )

        await invoke("v2:home:simple")
        await invoke("v2:flow:hub")
        await invoke("v2:flows:list")
        callbacks = {
            button["callback_data"]
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertIn("v2:nav:back", callbacks)

        await invoke("v2:nav:back")
        self.assertIn("Signal setup", str(self.telegram.edits[-1]["text"]))

    async def test_okak_strategy_is_hidden_for_unauthorized_user(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None

        self.assertNotIn("okak", self.service._visible_strategy_keys(settings))

        await self.service._send_strategy_selector(self.user.telegram_user_id)
        markup = self.telegram.messages[-1]["reply_markup"]
        callbacks = {
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and button.get("callback_data")
        }
        self.assertNotIn("strategy:open:okak", callbacks)

    async def test_okak_strategy_is_available_for_allowed_user(self) -> None:
        allowed_user = await self.repository.upsert_private_user(
            telegram_user_id=5846358885,
            username="dordo_dordo",
            first_name="Dordo",
            last_name=None,
        )
        allowed_settings = await self.service._ensure_user_settings(allowed_user.telegram_user_id, preferred_language="ru")

        self.assertIn("okak", self.service._visible_strategy_keys(allowed_settings))

        await self.service._send_strategy_selector(allowed_user.telegram_user_id)
        markup = self.telegram.messages[-1]["reply_markup"]
        callbacks = {
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and button.get("callback_data")
        }
        self.assertIn("strategy:open:okak", callbacks)

    async def test_ekek_strategy_is_visible_for_regular_user_with_short_defaults(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None

        self.assertIn("ekek", self.service._visible_strategy_keys(settings))

        await self.service._send_strategy_selector(self.user.telegram_user_id)
        markup = self.telegram.messages[-1]["reply_markup"]
        callbacks = {
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and button.get("callback_data")
        }
        self.assertIn("strategy:open:ekek", callbacks)

        strategy_settings = await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key="ekek",
        )
        self.assertEqual(strategy_settings.preferred_min_score, 90)
        self.assertEqual(strategy_settings.direction_filter, "short")
        self.assertEqual(strategy_settings.rsi_overbought, 76.0)

    async def test_okak_historical_context_is_personalized_for_two_allowed_users(self) -> None:
        dordo_user = await self.repository.upsert_private_user(
            telegram_user_id=5846358885,
            username="dordo_dordo",
            first_name="Dordo",
            last_name=None,
            is_admin=True,
        )
        ifritian_user = await self.repository.upsert_private_user(
            telegram_user_id=901375482,
            username="ifritian",
            first_name="Ifritian",
            last_name=None,
            is_admin=True,
        )
        signal = self._make_signal(
            "QTUMUSDT",
            strategy_key="okak",
            direction="overbought",
            score=93,
        )
        signal.metadata.update({"live_price": 5.06})
        self.service._build_okak_historical_resistance_metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "historical_resistance_available": True,
                "historical_resistance_zone_low": 5.18,
                "historical_resistance_zone_high": 5.24,
                "historical_resistance_zone_price": 5.21,
                "historical_resistance_distance_pct": 2.96,
                "historical_resistance_touch_count": 3,
                "historical_resistance_avg_rejection_pct": 5.8,
                "historical_resistance_quality": "strong",
                "historical_resistance_timeframes": ["4h", "1h"],
                "historical_resistance_highest_peak_price": 5.58,
                "historical_resistance_highest_peak_timeframe": "4h",
                "historical_resistance_highest_peak_distance_pct": 10.5,
            }
        )

        dordo_signal = await self.service._enrich_okak_signal_for_private_user(signal, user=dordo_user)
        ifritian_signal = await self.service._enrich_okak_signal_for_private_user(signal, user=ifritian_user)
        regular_signal = await self.service._enrich_okak_signal_for_private_user(signal, user=self.user)

        self.assertEqual(dordo_signal.metadata.get("historical_resistance_variant"), "detailed")
        self.assertEqual(ifritian_signal.metadata.get("historical_resistance_variant"), "focus")
        self.assertTrue(bool(dordo_signal.metadata.get("historical_resistance_available")))
        self.assertTrue(bool(ifritian_signal.metadata.get("historical_resistance_available")))
        self.assertEqual(dordo_signal.metadata.get("historical_resistance_highest_peak_price"), 5.58)
        self.assertNotIn("historical_resistance_variant", regular_signal.metadata)

    async def test_ekek_historical_context_reuses_personalized_variants(self) -> None:
        dordo_user = await self.repository.upsert_private_user(
            telegram_user_id=5846358885,
            username="dordo_dordo",
            first_name="Dordo",
            last_name=None,
            is_admin=True,
        )
        signal = self._make_signal(
            "QTUMUSDT",
            strategy_key="ekek",
            direction="overbought",
            score=93,
        )
        signal.metadata.update({"live_price": 5.06})
        self.service._build_okak_historical_resistance_metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "historical_resistance_available": True,
                "historical_resistance_zone_price": 5.21,
            }
        )

        enriched_signal = await self.service._enrich_okak_signal_for_private_user(signal, user=dordo_user)

        self.assertEqual(enriched_signal.metadata.get("historical_resistance_variant"), "detailed")
        self.assertEqual(enriched_signal.metadata.get("historical_resistance_zone_price"), 5.21)

    async def test_admin_auto_enables_daily_rsi_80_strategy(self) -> None:
        admin_user = await self.repository.upsert_private_user(
            telegram_user_id=900001,
            username="admin_daily_rsi",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )

        settings = await self.service._ensure_user_settings(admin_user.telegram_user_id, preferred_language="en")
        shell_settings = await self.repository.get_user_settings(admin_user.telegram_user_id, bot_kind="premium")
        strategy_settings = await self.repository.get_premium_strategy_settings(
            admin_user.telegram_user_id,
            bot_kind="premium",
            strategy_key="daily_rsi_80",
        )

        assert shell_settings is not None
        assert strategy_settings is not None
        self.assertIn("daily_rsi_80", settings.enabled_strategy_keys)
        self.assertIn("daily_rsi_80", shell_settings.enabled_strategy_keys)
        self.assertTrue(strategy_settings.direct_signal_delivery_enabled)
        self.assertEqual(strategy_settings.direction_filter, "short")
        self.assertEqual(strategy_settings.rsi_overbought, 80.0)

    async def test_strategy_specific_defaults_are_used_for_reversal_pack(self) -> None:
        shell_settings = await self.service._ensure_user_settings(self.user.telegram_user_id, preferred_language="en")
        defaults = {
            "bollinger": 48,
            "rsi_bollinger_touch": 64,
            "rsi_divergence": 68,
        }

        for strategy_key, expected_score in defaults.items():
            strategy_settings = await self.service._ensure_premium_strategy_settings(
                self.user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            self.assertEqual(strategy_settings.preferred_min_score, expected_score)

    async def test_admin_reversal_rollout_enables_delivery_and_rebalances_scores_once(self) -> None:
        admin_user = await self.repository.upsert_private_user(
            telegram_user_id=900002,
            username="admin_reversal_pack",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )
        await self.repository.upsert_user_settings(
            telegram_user_id=admin_user.telegram_user_id,
            bot_kind="premium",
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=False,
            gold_alerts_enabled=False,
            language_code="en",
            signal_profile="balanced",
            base_signal_profile="balanced",
            preferred_min_score=82,
            min_quote_volume=5_000_000.0,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            direction_filter="both",
            watchlist_only=False,
            menu_collapsed=False,
            delivery_mode="instant",
            active_watchlist_theme="custom",
            enabled_strategy_keys=("bollinger",),
            active_strategy_key="bollinger",
            strategy_selector_completed_at=datetime.now(timezone.utc),
            personalization={},
            delivery_rules={},
        )
        shell_settings = await self.repository.get_user_settings(admin_user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        bollinger_settings = await self.service._ensure_premium_strategy_settings(
            admin_user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="bollinger",
        )
        await self.service._save_premium_strategy_settings_record(
            bollinger_settings,
            direct_signal_delivery_enabled=False,
            preferred_min_score=82,
        )

        rolled_out = await self.service._ensure_user_settings(admin_user.telegram_user_id, preferred_language="en")
        refreshed_bollinger = await self.repository.get_premium_strategy_settings(
            admin_user.telegram_user_id,
            bot_kind="premium",
            strategy_key="bollinger",
        )
        touch_settings = await self.repository.get_premium_strategy_settings(
            admin_user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi_bollinger_touch",
        )
        divergence_settings = await self.repository.get_premium_strategy_settings(
            admin_user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi_divergence",
        )

        assert refreshed_bollinger is not None
        assert touch_settings is not None
        assert divergence_settings is not None
        self.assertIn("bollinger", rolled_out.enabled_strategy_keys)
        self.assertIn("rsi_bollinger_touch", rolled_out.enabled_strategy_keys)
        self.assertIn("rsi_divergence", rolled_out.enabled_strategy_keys)
        self.assertTrue(refreshed_bollinger.direct_signal_delivery_enabled)
        self.assertTrue(touch_settings.direct_signal_delivery_enabled)
        self.assertTrue(divergence_settings.direct_signal_delivery_enabled)
        self.assertEqual(refreshed_bollinger.preferred_min_score, 48)
        self.assertEqual(touch_settings.preferred_min_score, 64)
        self.assertEqual(divergence_settings.preferred_min_score, 68)
        self.assertIn("admin_strategy_rollouts", rolled_out.personalization)
        self.assertIn("reversal_pack_v1", rolled_out.personalization["admin_strategy_rollouts"])

        await self.service._save_premium_strategy_settings_record(
            touch_settings,
            direct_signal_delivery_enabled=False,
            preferred_min_score=72,
        )
        second_pass = await self.service._ensure_user_settings(admin_user.telegram_user_id, preferred_language="en")
        touch_after_second_pass = await self.repository.get_premium_strategy_settings(
            admin_user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi_bollinger_touch",
        )

        assert touch_after_second_pass is not None
        self.assertFalse(touch_after_second_pass.direct_signal_delivery_enabled)
        self.assertEqual(touch_after_second_pass.preferred_min_score, 72)
        self.assertIn("rsi_bollinger_touch", second_pass.enabled_strategy_keys)

    async def test_watch_remove_callback_updates_favorites_without_touching_active_set(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.repository.replace_premium_strategy_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            symbols=["BTCUSDT", "ETHUSDT"],
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            active_watchlist_theme="majors",
            active_custom_theme_name=None,
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-1",
                "data": "ux:watch:remove:BTCUSDT",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 51, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.active_watchlist_theme, "majors")
        favorites = await self.service._favorite_symbols(self.user.telegram_user_id)
        self.assertNotIn("BTCUSDT", favorites)
        self.assertIn("ETHUSDT", favorites)
        active_scope = await self.service._watchlist_symbols(self.user.telegram_user_id)
        self.assertIn("BTCUSDT", active_scope)

    async def test_group_all_command_reposts_admin_message_and_deletes_command(self) -> None:
        group_chat_id = "-100555001"
        self.service.settings.community_chat = group_chat_id
        self.service.settings.admin_telegram_user_ids_raw = str(self.user.telegram_user_id)

        await self.service.handle_message(
            {
                "message_id": 301,
                "chat": {"id": int(group_chat_id), "type": "supergroup"},
                "from": {"id": 99001, "language_code": "ru", "first_name": "Max", "username": "maxdesk"},
                "text": "обычное сообщение",
            }
        )
        await self.service.handle_message(
            {
                "message_id": 302,
                "chat": {"id": int(group_chat_id), "type": "supergroup"},
                "from": {"id": self.user.telegram_user_id, "language_code": "ru", "first_name": "Admin"},
                "text": "/all Важное обновление по рынку",
            }
        )

        self.assertTrue(self.telegram.messages)
        announcement = self.telegram.messages[-1]
        self.assertEqual(str(announcement["chat_id"]), group_chat_id)
        self.assertIn("📢 Объявление", str(announcement["text"]))
        self.assertIn("Важное обновление по рынку", str(announcement["text"]))
        self.assertIn("tg://user?id=99001", str(announcement["text"]))
        self.assertTrue(self.telegram.deleted)
        self.assertEqual(self.telegram.deleted[-1]["message_id"], 302)

    async def test_group_all_command_uses_replied_message_text_when_body_missing(self) -> None:
        group_chat_id = "-100555002"
        self.service.settings.community_chat = group_chat_id
        self.service.settings.admin_telegram_user_ids_raw = str(self.user.telegram_user_id)

        await self.service.handle_message(
            {
                "message_id": 303,
                "chat": {"id": int(group_chat_id), "type": "supergroup"},
                "from": {"id": self.user.telegram_user_id, "language_code": "ru", "first_name": "Admin"},
                "text": "/all",
                "reply_to_message": {
                    "message_id": 299,
                    "text": "Собираемся в чате через 10 минут.",
                },
            }
        )

        self.assertTrue(self.telegram.messages)
        announcement = self.telegram.messages[-1]
        self.assertIn("Собираемся в чате через 10 минут.", str(announcement["text"]))
        self.assertEqual(announcement["reply_to_message_id"], 299)

    async def test_premium_first_start_shows_positioned_language_picker(self) -> None:
        new_user_id = 777099

        await self.service.handle_message(
            {
                "chat": {"id": new_user_id, "type": "private"},
                "from": {"id": new_user_id, "language_code": "en", "first_name": "New"},
                "text": "/start",
            }
        )

        self.assertTrue(self.telegram.messages)
        selector_message = self.telegram.messages[-1]
        self.assertIn("Choose Your Language", str(selector_message["text"]))
        self.assertIn("Syndicate PRO+", str(selector_message["text"]))
        self.assertIn("crypto market", str(selector_message["text"]))
        settings = await self.repository.get_user_settings(new_user_id, bot_kind="premium")
        assert settings is not None
        self.assertIsNone(settings.onboarding_completed_at)
        callbacks = [
            str(button["callback_data"])
            for row in selector_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertEqual(
            callbacks,
            ["ux:language:set:en:welcome", "ux:language:set:ru:welcome"],
        )

    async def test_language_selection_starts_v2_onboarding_after_confirmation(self) -> None:
        new_user_id = 777109

        await self.service.handle_message(
            {
                "chat": {"id": new_user_id, "type": "private"},
                "from": {"id": new_user_id, "language_code": "en", "first_name": "New"},
                "text": "/start",
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-lang-ru",
                "data": "ux:language:set:ru:welcome",
                "from": {"id": new_user_id, "language_code": "en"},
                "message": {"message_id": 1, "chat": {"id": new_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(new_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.language_code, "ru")
        self.assertIsNone(updated.onboarding_completed_at)
        self.assertTrue(updated.personalization.get("ux_v2_enabled"))
        self.assertTrue(self.telegram.edits)
        onboarding = await self.repository.get_user_onboarding_state(new_user_id, bot_kind="premium")
        assert onboarding is not None
        self.assertEqual(onboarding.step, "v2_style")
        self.assertTrue(onboarding.draft.get("v2"))
        welcome = self.telegram.edits[-1]
        self.assertIn("Какой стиль", str(welcome["text"]))
        callbacks = [
            str(button["callback_data"])
            for row in welcome.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertEqual(
            callbacks,
            [
                "v2:onboarding:style:scalp",
                "v2:onboarding:style:intraday",
                "v2:onboarding:style:swing",
                "v2:onboarding:style:balanced",
                "v2:onboarding:cancel",
            ],
        )

    async def test_v2_onboarding_persists_a_flow_and_simple_mode(self) -> None:
        settings = await self.service._ensure_shell_settings(self.user.telegram_user_id)
        personalization = self.service._personalization_state(settings)
        personalization["ux_v2_enabled"] = True
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            personalization=personalization,
        )
        await self.service._start_v2_onboarding(self.user)

        for index, callback_data in enumerate(
            (
                "v2:onboarding:style:intraday",
                "v2:onboarding:market:majors",
                "v2:onboarding:quality:best",
                "v2:onboarding:delivery:digest",
                "v2:onboarding:confirm:home",
            ),
            start=1,
        ):
            await self.service.handle_callback_query(
                {
                    "id": f"v2-onboarding-{index}",
                    "data": callback_data,
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": index, "chat": {"id": self.user.telegram_user_id}},
                }
            )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertIsNotNone(updated.onboarding_completed_at)
        self.assertEqual(updated.display_mode, "simple")
        self.assertTrue(updated.watchlist_only)
        self.assertEqual(updated.delivery_mode, "digest")
        flow = await self.service._active_saved_setup(self.user.telegram_user_id)
        self.assertIsNotNone(flow)

        self.telegram.messages.clear()
        await self.service.handle_message(
            {
                "chat": {"id": self.user.telegram_user_id, "type": "private"},
                "from": {"id": self.user.telegram_user_id, "language_code": "en", "first_name": "Test"},
                "text": "/start",
            }
        )
        self.assertIn("Main menu", str(self.telegram.messages[-1]["text"]))

    async def test_first_start_records_safe_funnel_events(self) -> None:
        new_user_id = 777110

        await self.service.handle_message(
            {
                "chat": {"id": new_user_id, "type": "private"},
                "from": {"id": new_user_id, "language_code": "en", "first_name": "New"},
                "text": "/start",
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-lang-en-funnel",
                "data": "ux:language:set:en:welcome",
                "from": {"id": new_user_id, "language_code": "en"},
                "message": {"message_id": 1, "chat": {"id": new_user_id}},
            }
        )

        counts = await self.repository.count_telemetry_events(
            start=datetime.now(timezone.utc) - timedelta(minutes=5),
            end=datetime.now(timezone.utc) + timedelta(minutes=1),
            event_names=(
                "start_seen",
                "language_picker_seen",
                "language_selected",
                "onboarding_started",
            ),
            telegram_user_id=new_user_id,
        )

        self.assertEqual(
            counts,
            {
                "language_picker_seen": 1,
                "language_selected": 1,
                "onboarding_started": 1,
                "start_seen": 1,
            },
        )

    async def test_failed_guided_welcome_does_not_complete_onboarding(self) -> None:
        new_user_id = 777119
        await self.service.handle_message(
            {
                "chat": {"id": new_user_id, "type": "private"},
                "from": {"id": new_user_id, "language_code": "en", "first_name": "New"},
                "text": "/start",
            }
        )

        with patch.object(self.service, "_start_v2_onboarding", AsyncMock(side_effect=RuntimeError("send failed"))):
            with self.assertRaisesRegex(RuntimeError, "send failed"):
                await self.service.handle_callback_query(
                    {
                        "id": "cb-lang-ru-failed",
                        "data": "ux:language:set:ru:welcome",
                        "from": {"id": new_user_id, "language_code": "en"},
                        "message": {"message_id": 1, "chat": {"id": new_user_id}},
                    }
                )

        updated = await self.repository.get_user_settings(new_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.language_code, "ru")
        self.assertIsNone(updated.onboarding_completed_at)

    async def test_onboarding_example_and_reading_guide_callbacks_are_safe(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-example",
                "data": "ux:welcome:example",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 51, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        self.assertIn("Example signal", str(self.telegram.edits[-1]["text"]))
        self.assertIn("not a live signal", str(self.telegram.edits[-1]["text"]))

        await self.service.handle_callback_query(
            {
                "id": "cb-read",
                "data": "ux:welcome:read",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 52, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        self.assertIn("How to read", str(self.telegram.edits[-1]["text"]))
        self.assertIn("No result is guaranteed", str(self.telegram.edits[-1]["text"]))

    async def test_returning_start_migrates_to_v2_simple_home(self) -> None:
        current = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert current is not None
        await self.service._save_user_settings(
            user=self.user,
            current_settings=current,
            onboarding_completed_at=datetime.now(timezone.utc),
        )
        self.telegram.messages.clear()

        await self.service.handle_message(
            {
                "chat": {"id": self.user.telegram_user_id, "type": "private"},
                "from": {"id": self.user.telegram_user_id, "language_code": "en", "first_name": "Test"},
                "text": "/start",
            }
        )

        start_message = self.telegram.messages[0]
        self.assertIn("Main menu", str(start_message["text"]))
        self.assertIn("Hi, Test!", str(start_message["text"]))
        self.assertNotIn("Active profile", str(start_message["text"]))
        callbacks = [
            str(button["callback_data"])
            for row in start_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertEqual(
            callbacks,
            [
                "v2:strategies:hub",
                "v2:flow:hub",
                "v2:results:hub",
                "v2:watchlist:hub",
                "v2:access:hub",
                "v2:settings:hub",
                "v2:home:pro",
                "v2:help:hub",
            ],
        )
        self.assertIsNotNone(await self.service._active_saved_setup(self.user.telegram_user_id))

    async def test_send_menu_opens_general_hub_before_strategy_pages(self) -> None:
        await self.service._send_menu(self.user.telegram_user_id)

        self.assertTrue(self.telegram.messages)
        latest_message = self.telegram.messages[-1]
        self.assertIn("Main menu", str(latest_message["text"]))
        self.assertIn("Hi, Test!", str(latest_message["text"]))
        self.assertNotIn("Active profile", str(latest_message["text"]))
        callbacks = [
            str(button["callback_data"])
            for row in latest_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("v2:strategies:hub", callbacks)
        self.assertIn("v2:flow:hub", callbacks)
        self.assertIn("v2:home:pro", callbacks)
        self.assertNotIn("main:strategies", callbacks)
        self.assertNotIn("main:alerts", callbacks)
        self.assertNotIn("ux:strategy:open:breakout", callbacks)

    async def test_premium_reply_keyboard_is_hidden_in_favor_of_inline_menu(self) -> None:
        markup = await self.service._main_menu_keyboard_for_user(self.user.telegram_user_id)
        self.assertEqual(markup, {"remove_keyboard": True})

    async def test_send_menu_hub_respects_russian_language_for_main_hub(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id, preferred_language="ru")
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            language_code="ru",
        )

        await self.service._send_menu_hub(self.user.telegram_user_id)

        latest_message = self.telegram.messages[-1]
        self.assertIn("Главное меню", str(latest_message["text"]))
        self.assertIn("Привет, Test!", str(latest_message["text"]))
        self.assertNotIn("Активный профиль", str(latest_message["text"]))
        texts = [
            str(button["text"])
            for row in latest_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("📈 Стратегии", texts)
        self.assertIn("⚙️ Настройки", texts)
        self.assertIn("🔧 Pro-режим", texts)

    async def test_send_strategies_hub_respects_russian_language(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id, preferred_language="ru")
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            language_code="ru",
        )

        await self.service._send_strategy_selector(self.user.telegram_user_id)

        latest_message = self.telegram.messages[-1]
        self.assertIn("Стратегии", str(latest_message["text"]))
        texts = [
            str(button["text"])
            for row in latest_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("Пробой уровня", texts)
        self.assertIn("🆚 Сравнение стратегий", texts)

    async def test_product_hubs_respect_russian_language(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id, preferred_language="ru")
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            language_code="ru",
        )

        await self.service._send_compare_hub(self.user)
        self.assertIn("Сравнение стратегий", str(self.telegram.messages[-1]["text"]))

        await self.service._send_learn_hub(self.user)
        self.assertIn("Обучение", str(self.telegram.messages[-1]["text"]))

        await self.service._send_lifecycle_hub(self.user)
        self.assertIn("Жизненный цикл сигнала", str(self.telegram.messages[-1]["text"]))

    async def test_main_menu_hub_exposes_v2_access_without_crowding_home(self) -> None:
        await self.service._send_menu_hub(self.user.telegram_user_id)

        latest_message = self.telegram.messages[-1]
        callbacks = [
            str(button["callback_data"])
            for row in latest_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]

        self.assertIn("v2:access:hub", callbacks)
        self.assertNotIn("ux:referral", callbacks)

    async def test_referral_callback_opens_dashboard(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-referral",
                "data": "ux:referral",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 95, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.edits)
        referral_message = self.telegram.edits[-1]
        self.assertIn("Referral", str(referral_message["text"]))
        self.assertIn("Invite Tools", str(referral_message["text"]))
        self.assertIn("Code:", str(referral_message["text"]))
        urls = [
            str(button["url"])
            for row in referral_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "url" in button
        ]
        self.assertTrue(any("https://t.me/" in url and "?start=ref_" in url for url in urls))
        callbacks = [
            str(button["callback_data"])
            for row in referral_message.get("reply_markup", {}).get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertEqual(callbacks, ["main:access", "ux:referral", "ux:menu"])

    async def test_main_menu_text_explains_multiple_enabled_strategies(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key="breakout",
        )
        updated = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        hub_text = self.service._main_hub_text(updated, language_code="en")

        self.assertIn("<b>✨ Syndicate PRO</b>", hub_text)
        self.assertIn("Your personal market view", hub_text)

    async def test_main_menu_ai_hub_copy_is_global_not_strategy_prefixed(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-aihub-global-copy",
                "data": "ux:aihub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 90, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        text = str(self.telegram.edits[-1]["text"])
        self.assertIn("<b>🤖 AI Desk</b>", text)
        self.assertIn("This section works across all enabled strategies.", text)
        self.assertNotIn("Breakout •", text)

    async def test_strategy_ai_hub_copy_stays_strategy_scoped(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-aihub-strategy-copy",
                "data": "ux:aihub:strategy",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 91, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        text = str(self.telegram.edits[-1]["text"])
        self.assertIn("Breakout • 🤖 AI Desk", text)
        self.assertIn("This section applies only to this strategy.", text)

    async def test_main_menu_ai_hub_back_returns_to_main_menu(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-aihub-menu",
                "data": "ux:aihub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 91, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertEqual(callbacks[-2:], ["ux:menu", "ux:menu"])

    async def test_main_menu_stats_hub_back_returns_to_main_menu(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-statshub-menu",
                "data": "ux:statshub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 92, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:menu", callbacks)
        self.assertNotIn("ux:strategy:open:rsi", callbacks)

    async def test_main_menu_delivery_hub_uses_global_shell_delivery_settings(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium"),
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=False,
        )
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._save_shell_settings_only(
            self.user.telegram_user_id,
            current_settings=shell_settings,
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-deliveryhub-menu-global",
                "data": "ux:deliveryhub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 92, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        texts = [
            str(button["text"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("🔔 Alerts On", texts)
        self.assertIn("🔄 Follow-Ups On", texts)
        self.assertIn("overall flow across all enabled strategies", str(self.telegram.edits[-1]["text"]))
        self.assertIn("own separate settings", str(self.telegram.edits[-1]["text"]))

    async def test_strategy_delivery_hub_uses_strategy_delivery_settings(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium"),
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=False,
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-deliveryhub-strategy-scoped",
                "data": "ux:deliveryhub:strategy",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 93, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        texts = [
            str(button["text"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("🔔 Alerts Off", texts)
        self.assertIn("🔄 Follow-Ups Off", texts)
        self.assertIn("Strategy: <b>Breakout</b>", str(self.telegram.edits[-1]["text"]))
        self.assertIn("apply only to this strategy", str(self.telegram.edits[-1]["text"]))

    async def test_quiet_hours_toggle_turns_night_mode_on_and_off(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            quiet_hours_start_minute=None,
            quiet_hours_end_minute=None,
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-quiet-toggle-on",
                "data": "ux:quiet:toggle",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 94, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.quiet_hours_start_minute, 23 * 60)
        self.assertEqual(updated.quiet_hours_end_minute, 7 * 60)

        await self.service.handle_callback_query(
            {
                "id": "cb-quiet-toggle-off",
                "data": "ux:quiet:toggle",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 95, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertIsNone(updated.quiet_hours_start_minute)
        self.assertIsNone(updated.quiet_hours_end_minute)

    async def test_strategy_stats_hub_back_returns_to_strategy_page(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-statshub-strategy",
                "data": "ux:statshub:strategy",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 93, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:strategy:open:rsi", callbacks)
        self.assertIn("ux:menu", callbacks)

    async def test_main_menu_language_picker_returns_to_main_menu(self) -> None:
        await self.service._send_menu(self.user.telegram_user_id)

        await self.service.handle_callback_query(
            {
                "id": "cb-language-menu",
                "data": "ux:language:picker:settings",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 94, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:menu", callbacks)
        self.assertNotIn("ux:settingshub", callbacks)

    async def test_watchlist_opened_from_main_menu_hub_returns_to_watchhub(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-watchhub-menu",
                "data": "ux:watchhub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 95, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-watchlist-from-watchhub",
                "data": "ux:watchlist",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 95, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:watchhub", callbacks)
        self.assertNotIn("ux:strategy:open:rsi", callbacks)

    async def test_setup_opened_from_watchhub_returns_to_watchhub(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-watchhub-menu-setup",
                "data": "ux:watchhub",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 96, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-setup-from-watchhub",
                "data": "ux:setup",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 96, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:watchhub", callbacks)
        self.assertNotIn("ux:strategy:open:rsi", callbacks)

    async def test_main_menu_navigation_routes_stay_in_main_menu_context(self) -> None:
        callback_expectations = {
            "ux:deliveryhub": "ux:menu",
            "ux:watchhub": "ux:menu",
            "ux:statshub": "ux:menu",
            "ux:access": "ux:menu",
            "ux:language:picker:settings": "ux:menu",
        }

        for index, (callback_data, expected_back) in enumerate(callback_expectations.items(), start=1):
            await self.service.handle_callback_query(
                {
                    "id": f"cb-main-route-{index}",
                    "data": callback_data,
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": 100 + index, "chat": {"id": self.user.telegram_user_id}},
                }
            )

            callbacks = [
                str(button["callback_data"])
                for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
                for button in row
                if isinstance(button, dict) and "callback_data" in button
            ]
            self.assertIn(expected_back, callbacks, msg=callback_data)
            self.assertNotIn("ux:strategy:open:rsi", callbacks, msg=callback_data)

    async def test_strategy_navigation_routes_keep_strategy_context(self) -> None:
        strategy_callbacks = (
            "ux:signalshub:strategy",
            "ux:deliveryhub:strategy",
            "ux:watchhub:strategy",
            "ux:statshub:strategy",
            "ux:settingshub:strategy",
            "ux:setup",
            "ux:analyze",
        )

        for index, callback_data in enumerate(strategy_callbacks, start=1):
            await self.service.handle_callback_query(
                {
                    "id": f"cb-open-breakout-for-route-{index}",
                    "data": "ux:strategy:open:breakout",
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": 120 + index, "chat": {"id": self.user.telegram_user_id}},
                }
            )
            await self.service.handle_callback_query(
                {
                    "id": f"cb-strategy-route-{index}",
                    "data": callback_data,
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": 220 + index, "chat": {"id": self.user.telegram_user_id}},
                }
            )

            callbacks = [
                str(button["callback_data"])
                for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
                for button in row
                if isinstance(button, dict) and "callback_data" in button
            ]
            self.assertIn("ux:strategy:open:breakout", callbacks, msg=callback_data)
            self.assertIn("ux:menu", callbacks, msg=callback_data)

    async def test_strategy_guide_is_sent_as_temporary_message_and_cleaned_on_navigation(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-open-breakout-guide",
                "data": "ux:strategy:open:breakout",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 240, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-guide",
                "data": "ux:guide",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 240, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.messages)
        self.assertIn("Step 1. Core idea", str(self.telegram.messages[-1]["text"]))
        guide_callbacks = [
            str(button["callback_data"])
            for row in self.telegram.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:guide:close", guide_callbacks)
        self.assertIn("ux:menu", guide_callbacks)
        guide_message_id = len(self.telegram.messages)

        await self.service.handle_callback_query(
            {
                "id": "cb-guide-home",
                "data": "ux:menu",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 240, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        deleted_ids = [int(entry["message_id"]) for entry in self.telegram.deleted if isinstance(entry.get("message_id"), int)]
        self.assertTrue(deleted_ids)
        if isinstance(guide_message_id, int):
            self.assertIn(guide_message_id, deleted_ids)

    async def test_strategy_guide_close_button_deletes_temporary_message(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-open-breakout-guide-close",
                "data": "ux:strategy:open:breakout",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 242, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        await self.service.handle_callback_query(
            {
                "id": "cb-guide-open-close",
                "data": "ux:guide",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 242, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        guide_message_id = len(self.telegram.messages)

        await self.service.handle_callback_query(
            {
                "id": "cb-guide-close",
                "data": "ux:guide:close",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": guide_message_id, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        deleted_ids = [int(entry["message_id"]) for entry in self.telegram.deleted if isinstance(entry.get("message_id"), int)]
        self.assertIn(guide_message_id, deleted_ids)
        self.assertEqual(self.telegram.answers[-1]["callback_query_id"], "cb-guide-close")

    async def test_opening_strategy_guide_twice_replaces_previous_temporary_message(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-open-breakout-guide-2",
                "data": "ux:strategy:open:breakout",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 241, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-guide-first",
                "data": "ux:guide",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 241, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        first_message_id = len(self.telegram.messages)

        await self.service.handle_callback_query(
            {
                "id": "cb-guide-second",
                "data": "ux:guide",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 241, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        deleted_ids = [int(entry["message_id"]) for entry in self.telegram.deleted if isinstance(entry.get("message_id"), int)]
        self.assertIn(first_message_id, deleted_ids)
        self.assertEqual(len(self.telegram.messages), first_message_id + 1)

    async def test_handle_message_marks_configured_admin_username(self) -> None:
        self.service.settings.admin_telegram_user_ids_raw = ""
        self.service.settings.admin_telegram_usernames_raw = "sskyv123"
        admin_user_id = 777199

        await self.service.handle_message(
            {
                "chat": {"id": admin_user_id, "type": "private"},
                "from": {
                    "id": admin_user_id,
                    "username": "sskyv123",
                    "language_code": "en",
                    "first_name": "Sky",
                },
                "text": "/start",
            }
        )

        user = await self.repository.get_private_user(admin_user_id)
        assert user is not None
        self.assertTrue(user.is_admin)
        self.assertEqual(user.access_level, "admin")
        self.assertEqual(user.access_status, "admin")

    async def test_try_pro_reply_keyboard_label_routes_to_payment_offer(self) -> None:
        current_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert current_settings is not None
        await self.service._save_user_settings(
            user=self.user,
            current_settings=current_settings,
            onboarding_completed_at=datetime.now(timezone.utc),
        )
        payment_mock = AsyncMock()
        self.service._send_payment_offer = payment_mock  # type: ignore[method-assign]
        payload = {
            "chat": {"id": self.user.telegram_user_id, "type": "private"},
            "from": {
                "id": self.user.telegram_user_id,
                "username": "tester",
                "language_code": "en",
                "first_name": "Test",
            },
            "text": ui_text("en", "menu_try_pro"),
        }

        await self.service.handle_message(payload)

        await self.service.handle_message(
            {
                "chat": {"id": self.user.telegram_user_id, "type": "private"},
                "from": {
                    "id": self.user.telegram_user_id,
                    "username": "tester",
                    "language_code": "en",
                    "first_name": "Test",
                },
                "text": "💳 Go PRO+",
            }
        )

        self.assertGreaterEqual(payment_mock.await_count, 1)

    async def test_strategy_open_shows_strategy_hub_without_auto_enabling_it(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-strategy-open",
                "data": "ux:strategy:open:breakout",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 77, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.enabled_strategy_keys, ("rsi",))
        self.assertEqual(updated.active_strategy_key, "breakout")
        self.assertTrue(self.telegram.answers)
        self.assertTrue(self.telegram.edits)
        self.assertIn("Breakout", str(self.telegram.edits[-1]["text"]))
        self.assertIn("Breakout", str(self.telegram.edits[-1]["text"]))
        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("strategy:guide:breakout", callbacks)
        self.assertIn("main:strategies", callbacks)
        self.assertIn("main:today", callbacks)

    async def test_strategy_open_preserves_target_strategy_filters(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        rsi_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=rsi_settings,
            active_strategy_key="rsi",
            signal_profile="conservative",
            base_signal_profile="conservative",
            preferred_min_score=88,
            direction_filter="long",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )
        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            active_strategy_key="breakout",
            signal_profile="aggressive",
            base_signal_profile="aggressive",
            preferred_min_score=74,
            direction_filter="short",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-strategy-open-breakout",
                "data": "ux:strategy:open:breakout",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 81, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        latest_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert latest_shell is not None
        preserved_breakout = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=latest_shell,
            strategy_key="breakout",
        )
        preserved_rsi = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=latest_shell,
            strategy_key="rsi",
        )
        self.assertEqual(preserved_breakout.signal_profile, "aggressive")
        self.assertEqual(preserved_breakout.preferred_min_score, 74)
        self.assertEqual(preserved_breakout.direction_filter, "short")
        self.assertEqual(preserved_rsi.signal_profile, "conservative")
        self.assertEqual(preserved_rsi.preferred_min_score, 88)
        self.assertEqual(preserved_rsi.direction_filter, "long")

    async def test_strategy_preferences_are_saved_per_strategy(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service._apply_strategy_preference_choice(
            self.user,
            breakout_settings,
            key="timeframe_focus",
            value="swing",
        )

        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        saved_breakout = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="breakout",
        )
        saved_rsi = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="rsi",
        )

        self.assertEqual(saved_breakout.strategy_preferences.get("timeframe_focus"), "swing")
        self.assertEqual(saved_rsi.strategy_preferences.get("timeframe_focus"), "balanced")

    async def test_strategy_preferences_filter_signal_timeframe(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
            strategy_preferences={
                "timeframe_focus": "fast",
                "market_mode": "balanced",
                "followup_priority": "move",
            },
        )

        matching_signal = self._make_signal(
            "BTCUSDT",
            strategy_key="breakout",
            direction="long",
            timeframe="5m",
            score=91,
        )
        filtered_signal = self._make_signal(
            "BTCUSDT",
            strategy_key="breakout",
            direction="long",
            timeframe="1h",
            score=91,
        )

        self.assertEqual(
            self.service._signal_matches_user_settings(
                matching_signal,
                breakout_settings,
                watchlist_symbols=set(),
            ),
            (True, "ok"),
        )
        self.assertEqual(
            self.service._signal_matches_user_settings(
                filtered_signal,
                breakout_settings,
                watchlist_symbols=set(),
            ),
            (False, "timeframe_focus"),
        )

    async def test_strategy_timeframe_preference_blocks_a_new_live_delivery(self) -> None:
        self.service.settings.private_bot_signal_delivery_enabled = True
        now = datetime.now(timezone.utc)
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            delivery_mode="instant",
            strategy_preferences={
                "timeframe_focus": "fast",
                "market_mode": "balanced",
                "followup_priority": "move",
            },
            strategy_selector_completed_at=now,
        )
        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None

        async def _recipients(*args, **kwargs):
            del args, kwargs
            return [(self.user, refreshed_shell)]

        async def _has_access(_user):
            return True

        self.repository.list_private_signal_recipients = _recipients  # type: ignore[method-assign]
        self.service._has_premium_access = _has_access  # type: ignore[method-assign]
        signal = self._make_signal(
            "BTCUSDT",
            strategy_key="breakout",
            direction="long",
            timeframe="1h",
            score=91,
            candle_close_time=now - timedelta(minutes=1),
        )
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now - timedelta(seconds=30),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )

        await self.service.deliver_pro_alert(signal, alert_id=alert_id)

        self.assertEqual(self.router.alerts, [])

    async def test_followup_priority_watchlist_prefers_watchlist_symbols(self) -> None:
        now = datetime.now(timezone.utc)
        btc_followup = FollowUpResultRecord(
            alert_id=1,
            stage="2h",
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            alert_rsi=25.0,
            score=90,
            current_price=106.0,
            current_rsi=34.0,
            move_pct=6.0,
            summary="",
            observed_at=now,
            metadata={"favorable_move_pct": 6.0},
        )
        eth_followup = FollowUpResultRecord(
            alert_id=2,
            stage="2h",
            symbol="ETHUSDT",
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            alert_rsi=25.0,
            score=84,
            current_price=103.0,
            current_rsi=32.0,
            move_pct=3.0,
            summary="",
            observed_at=now,
            metadata={"favorable_move_pct": 3.0},
        )

        btc_key = self.service._followup_top_priority_key(
            btc_followup,
            priority="watchlist",
            watchlist_symbols={"ETHUSDT"},
        )
        eth_key = self.service._followup_top_priority_key(
            eth_followup,
            priority="watchlist",
            watchlist_symbols={"ETHUSDT"},
        )

        self.assertGreater(eth_key, btc_key)

    async def test_cleanup_keeps_only_recent_navigation_messages(self) -> None:
        self.service.settings.private_bot_chat_cleanup_keep_messages = 2

        for index in range(4):
            await self.service._send_chat_message(
                chat_id=str(self.user.telegram_user_id),
                text=f"message {index}",
                parse_mode=None,
            )

        self.assertEqual(
            [int(item["message_id"]) for item in self.telegram.deleted],
            [1, 2],
        )
        remaining = await self.repository.list_delivered_signals(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            content_kind=self.service.CHAT_CLEANUP_CONTENT_KIND,
            limit=10,
        )
        self.assertEqual([record.telegram_message_id for record in remaining], [4, 3])

    async def test_complete_onboarding_deletes_previous_wizard_messages(self) -> None:
        draft = {
            "language_code": "en",
            "strategy_key": "breakout",
            "signal_profile": "balanced",
            "rsi_mode": "balanced",
            "min_quote_volume": 5_000_000.0,
            "direction_filter": "both",
            "favorite_symbols": [],
            "watchlist_only": False,
            "delivery_mode": "instant",
            "followup_delivery_enabled": True,
            "_thread_message_ids": [41, 42],
        }

        await self.service._complete_onboarding(
            self.user,
            draft=draft,
            enable_delivery=True,
        )

        self.assertEqual(
            [int(item["message_id"]) for item in self.telegram.deleted],
            [41, 42],
        )
        state = await self.repository.get_user_onboarding_state(self.user.telegram_user_id, bot_kind="premium")
        self.assertIsNone(state)

    async def test_strategy_selector_russian_copy_is_readable(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None

        selector_text = self.service._strategy_selector_text(settings, language_code="ru")
        hub_text = self.service._strategy_hub_text("breakout", strategy_enabled=True, language_code="ru")

        self.assertIn("<b>Стратегии</b>", selector_text)
        self.assertIn("Выбрано", selector_text)
        self.assertIn("свои фильтры", hub_text)
        self.assertIn("Пробой уровня", hub_text)

    async def test_signal_setup_screen_is_strategy_specific_for_breakout(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service._send_signal_setup(self.user)

        self.assertTrue(self.telegram.messages)
        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Breakout", text)
        self.assertIn("Breakout mode", text)
        self.assertNotIn("RSI gate", text)

    async def test_quick_setup_start_uses_active_strategy_flow(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-onboard-start",
                "data": "ux:onboard:start",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 88, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.edits)
        text = str(self.telegram.edits[-1]["text"])
        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("Wizard", text)
        self.assertIn("Breakout", text)
        self.assertIn("ux:onboard:preset:balanced", callbacks)
        self.assertNotIn("ux:onboard:style:balanced", callbacks)

    async def test_leaving_quick_setup_cleans_old_wizard_messages(self) -> None:
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            step="direction",
            draft={
                "language_code": "en",
                "strategy_key": "rsi",
                "_thread_message_ids": [71, 72],
            },
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-exit-onboard",
                "data": "ux:setup",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 72, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertEqual([int(item["message_id"]) for item in self.telegram.deleted], [71])
        state = await self.repository.get_user_onboarding_state(self.user.telegram_user_id, bot_kind="premium")
        self.assertIsNone(state)

    async def test_quick_setup_first_step_has_back_to_filters(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-onboard-start-back",
                "data": "ux:onboard:start",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 89, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        callbacks = [
            str(button["callback_data"])
            for row in self.telegram.edits[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if isinstance(button, dict) and "callback_data" in button
        ]
        self.assertIn("ux:setup", callbacks)
        self.assertIn("ux:menu", callbacks)

    async def test_quick_setup_use_defaults_uses_strategy_specific_symbols(self) -> None:
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            step="symbols",
            draft={
                "language_code": "en",
                "strategy_key": "false_breakout",
                "favorite_symbols": [],
            },
        )

        await self.service._apply_onboarding_choice(
            self.user,
            step="symbols",
            value="use-defaults",
        )

        state = await self.repository.get_user_onboarding_state(self.user.telegram_user_id, bot_kind="premium")
        assert state is not None
        self.assertEqual(state.draft.get("favorite_symbols"), ["BTC", "ETH", "XRP", "ADA"])

    async def test_manual_symbol_lookup_uses_active_strategy_key(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=breakout_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        now = pd.Timestamp("2026-03-16T16:45:00Z")
        enriched = pd.DataFrame(
            {
                "close": [100.0],
                "close_time": [now],
                "rsi": [42.13],
                "volume": [125_000.0],
                "avg_volume_20": [110_000.0],
                "atr": [1.2],
                "atr_pct": [0.012],
                "ema20": [99.5],
                "ema50": [98.0],
                "volume_ratio": [1.14],
            },
            index=pd.DatetimeIndex([now - pd.Timedelta(minutes=15)]),
        )

        with (
            patch("src.userbot.service.enrich_klines", return_value=enriched),
            patch("src.userbot.service.calculate_live_rsi", return_value=44.2),
        ):
            await self.service._send_symbol_lookup_card(self.user, symbol_input="BTCUSDT", timeframe="15m")

        self.assertEqual(len(self.router.alerts), 1)
        delivered_signal = self.router.alerts[-1]["signal"]
        self.assertEqual(str(delivered_signal.metadata.get("strategy_key")), "breakout")
        self.assertTrue(bool(delivered_signal.metadata.get("manual_analysis_only")))
        self.assertNotIn("tp_price_primary", delivered_signal.metadata)
        self.assertEqual(self.interactive.registered[-1]["signal"].metadata.get("strategy_key"), "breakout")

    async def test_switching_active_strategy_changes_resolved_favorites(self) -> None:
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="bollinger",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "bollinger"),
            active_strategy_key="rsi",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )
        await self.repository.replace_premium_strategy_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            symbols=["BTCUSDT"],
        )
        await self.repository.replace_premium_strategy_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="bollinger",
            symbols=["ETHUSDT"],
        )

        self.assertEqual(await self.service._favorite_symbols(self.user.telegram_user_id), ["BTCUSDT"])

        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        bollinger_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="bollinger",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=bollinger_settings,
            enabled_strategy_keys=("rsi", "bollinger"),
            active_strategy_key="bollinger",
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )

        self.assertEqual(await self.service._favorite_symbols(self.user.telegram_user_id), ["ETHUSDT"])

    async def test_profile_reset_restores_saved_base_profile(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._apply_profile_choice(self.user, settings, "aggressive")
        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        await self.service._apply_direction_choice(self.user, updated, "short")
        changed = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert changed is not None

        await self.service._reset_profile_to_base(self.user, changed)

        reset_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert reset_settings is not None
        min_score, min_volume, oversold, overbought = self.service._profile_defaults("aggressive")
        self.assertEqual(reset_settings.signal_profile, "aggressive")
        self.assertEqual(reset_settings.base_signal_profile, "aggressive")
        self.assertEqual(reset_settings.direction_filter, "both")
        self.assertEqual(reset_settings.preferred_min_score, min_score)
        self.assertEqual(reset_settings.min_quote_volume, min_volume)
        self.assertEqual(reset_settings.rsi_oversold, oversold)
        self.assertEqual(reset_settings.rsi_overbought, overbought)

    async def test_custom_theme_switch_restores_database_watchlist(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.repository.replace_premium_strategy_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            symbols=["DOGEUSDT", "PEPEUSDT"],
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            active_watchlist_theme="majors",
            active_custom_theme_name=None,
        )
        refreshed = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed is not None

        await self.service._activate_builtin_theme(self.user, refreshed, "custom")

        switched = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert switched is not None
        self.assertEqual(switched.active_watchlist_theme, "custom")
        self.assertEqual(await self.service._watchlist_symbols(self.user.telegram_user_id), ["DOGEUSDT", "PEPEUSDT"])

    async def test_save_theme_from_builtin_preserves_active_scope_and_saves_symbols(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            active_watchlist_theme="majors",
            active_custom_theme_name=None,
        )

        await self.service._prompt_theme_action(self.user, action="save")
        handled = await self.service._handle_theme_prompt_message(self.user, "Desk")

        self.assertTrue(handled)
        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.active_watchlist_theme, "majors")
        self.assertIsNone(updated.active_custom_theme_name)
        self.assertEqual(await self.service._favorite_symbols(self.user.telegram_user_id), [])

        themes = await self.repository.list_premium_strategy_watchlist_themes(
            self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
        )
        saved_theme = next((theme for theme in themes if theme.theme_name == "Desk"), None)
        self.assertIsNotNone(saved_theme)
        assert saved_theme is not None
        self.assertEqual(
            await self.repository.list_premium_strategy_watchlist_theme_symbols(saved_theme.id),
            sorted(BUILTIN_WATCHLIST_THEMES["majors"]),
        )

    async def test_activate_saved_theme_uses_saved_symbols_without_overwriting_favorites(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        await self.repository.replace_premium_strategy_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            symbols=["DOGEUSDT", "PEPEUSDT"],
        )
        saved_theme = await self.repository.save_premium_strategy_watchlist_theme(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            theme_name="Desk",
            symbols=["BTCUSDT", "ETHUSDT"],
        )

        activated = await self.service._activate_saved_theme(self.user, settings, saved_theme.id)

        self.assertTrue(activated)
        self.assertEqual(await self.service._favorite_symbols(self.user.telegram_user_id), ["DOGEUSDT", "PEPEUSDT"])
        self.assertEqual(await self.service._watchlist_symbols(self.user.telegram_user_id), ["BTCUSDT", "ETHUSDT"])

    async def test_daily_recap_followups_keep_best_profitable_symbol_per_day(self) -> None:
        now = datetime.now(timezone.utc)
        followups = [
            FollowUpResultRecord(
                alert_id=1,
                stage="2h",
                symbol="BTCUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                alert_rsi=25.0,
                score=82,
                current_price=103.0,
                current_rsi=34.0,
                move_pct=3.0,
                summary="",
                observed_at=now - timedelta(hours=4),
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 3.0},
            ),
            FollowUpResultRecord(
                alert_id=2,
                stage="6h",
                symbol="BTCUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                alert_rsi=25.0,
                score=84,
                current_price=106.0,
                current_rsi=39.0,
                move_pct=6.0,
                summary="",
                observed_at=now - timedelta(hours=2),
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 6.0},
            ),
            FollowUpResultRecord(
                alert_id=3,
                stage="2h",
                symbol="ETHUSDT",
                direction="overbought",
                timeframe="15m",
                alert_price=100.0,
                alert_rsi=75.0,
                score=81,
                current_price=104.0,
                current_rsi=78.0,
                move_pct=4.0,
                summary="",
                observed_at=now - timedelta(hours=1),
                metadata={"thesis_result_state": "adverse", "favorable_move_pct": 0.0},
            ),
            FollowUpResultRecord(
                alert_id=4,
                stage="2h",
                symbol="SOLUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                alert_rsi=28.0,
                score=78,
                current_price=104.5,
                current_rsi=35.0,
                move_pct=4.5,
                summary="",
                observed_at=now - timedelta(minutes=30),
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 4.5},
            ),
        ]

        selected = self.service._select_recap_followups(followups, period="daily")

        self.assertEqual([item.symbol for item in selected], ["BTCUSDT", "SOLUSDT"])
        self.assertEqual(
            [float(item.metadata.get("favorable_move_pct") or 0.0) for item in selected],
            [6.0, 4.5],
        )

        weekly_selected = self.service._select_recap_followups(followups, period="weekly")
        self.assertEqual([item.symbol for item in weekly_selected], ["BTCUSDT", "SOLUSDT"])

    async def test_daily_recap_ignores_alerts_and_shows_empty_state_without_good_followups(self) -> None:
        now = datetime.now(timezone.utc)
        alert = AlertRecord(
            id=1,
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=45),
            candle_close_time=now - timedelta(minutes=30),
            alert_price=100.0,
            alert_rsi=26.0,
            day_change_pct=None,
            day_volume=None,
            score=88,
            alert_sent_at=now - timedelta(minutes=25),
            followup_due_at=now + timedelta(minutes=95),
            followup_sent_at=None,
            lab_message_id=None,
            strategy_key="rsi",
            metadata={},
        )

        async def _fake_collect_recap_activity(*args, **kwargs):
            del args, kwargs
            return [alert], []

        self.service._collect_recap_activity = _fake_collect_recap_activity  # type: ignore[method-assign]

        sent = await self.service._send_recap(self.user, period="daily")

        self.assertTrue(sent)
        self.assertTrue(self.telegram.messages)
        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("No strong follow-up results yet for today.", text)
        self.assertIn("Recent delivered signals", text)
        self.assertNotIn("Strongest", text)

    async def test_send_or_edit_text_does_not_fallback_when_message_is_not_modified(self) -> None:
        async def _raise_not_modified(**kwargs):
            del kwargs
            raise Exception("Bad Request: message is not modified")

        self.telegram.edit_message_text = _raise_not_modified  # type: ignore[method-assign]

        message_id = await self.service._send_or_edit_text(
            chat_id=str(self.user.telegram_user_id),
            text="<b>Same</b>",
            reply_markup={"inline_keyboard": []},
            edit_message_id=55,
        )

        self.assertEqual(message_id, 55)
        self.assertFalse(self.telegram.messages)

    async def test_control_center_uses_batch_alert_loading(self) -> None:
        now = datetime.now(timezone.utc)
        alert_id = await self.repository.create_alert(
            self._make_signal("BTCUSDT", strategy_key="rsi", score=87, candle_close_time=now - timedelta(minutes=30)),
            sent_at=now - timedelta(minutes=25),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            alert_id=alert_id,
            content_kind="private_pro",
            message_kind="alert",
            telegram_message_id=101,
            metadata={"sent": True},
        )

        async def _no_single_alert_lookup(*args, **kwargs):
            raise AssertionError("single alert lookup should not be used in control center")

        self.repository.get_alert = _no_single_alert_lookup  # type: ignore[method-assign]

        await self.service._send_control_center(self.user)

        self.assertTrue(self.telegram.messages or self.telegram.edits)

    async def test_recap_uses_batch_followup_loading(self) -> None:
        now = datetime.now(timezone.utc)
        alert_id = await self.repository.create_alert(
            self._make_signal("ETHUSDT", strategy_key="rsi", score=84, candle_close_time=now - timedelta(hours=2)),
            sent_at=now - timedelta(hours=2),
            followup_due_at=now - timedelta(minutes=10),
            lab_message_id=None,
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=alert_id,
                symbol="ETHUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                alert_rsi=30.0,
                score=84,
                current_price=103.0,
                current_rsi=42.0,
                move_pct=3.0,
                summary="Moved higher",
                observed_at=now - timedelta(minutes=5),
                metadata={"favorable_move_pct": 3.0, "strategy_key": "rsi"},
            )
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            alert_id=alert_id,
            content_kind="private_pro",
            message_kind="alert",
            telegram_message_id=102,
            metadata={"sent": True},
        )

        async def _no_single_alert_lookup(*args, **kwargs):
            raise AssertionError("single-item recap lookup should not be used")

        self.repository.get_alert = _no_single_alert_lookup  # type: ignore[method-assign]
        self.repository.get_followup_result = _no_single_alert_lookup  # type: ignore[method-assign]

        sent = await self.service._send_recap(self.user, period="daily")

        self.assertTrue(sent)
        self.assertTrue(self.telegram.messages or self.telegram.edits)

    async def test_weekly_recap_uses_last_seven_days_of_delivered_history_across_enabled_strategies(self) -> None:
        base_now = datetime(2026, 3, 17, 15, 0, tzinfo=timezone.utc)
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=base_now,
        )

        alert_specs = (
            ("BTCUSDT", "rsi", base_now - timedelta(days=6), 201),
            ("ETHUSDT", "breakout", base_now - timedelta(days=2), 202),
            ("SOLUSDT", "rsi", base_now - timedelta(days=8), 203),
        )
        for symbol, strategy_key, delivered_at, message_id in alert_specs:
            alert_id = await self.repository.create_alert(
                self._make_signal(
                    symbol,
                    strategy_key=strategy_key,
                    score=86,
                    candle_close_time=delivered_at - timedelta(minutes=5),
                ),
                sent_at=delivered_at - timedelta(minutes=3),
                followup_due_at=delivered_at + timedelta(hours=2),
                lab_message_id=None,
            )
            with patch("src.storage.repository.utc_now", return_value=delivered_at):
                await self.repository.record_delivered_signal(
                    telegram_user_id=self.user.telegram_user_id,
                    bot_kind="premium",
                    alert_id=alert_id,
                    content_kind="private_pro",
                    message_kind="alert",
                    telegram_message_id=message_id,
                    metadata={"sent": True, "strategy_key": strategy_key, "symbol": symbol},
                )

        with patch("src.userbot.service.utc_now", return_value=base_now):
            sent = await self.service._send_recap(self.user, period="weekly")

        self.assertTrue(sent)
        self.assertTrue(self.telegram.messages)
        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Delivered signals in this period: <b>2</b>", text)
        self.assertIn("BTCUSDT", text)
        self.assertIn("ETHUSDT", text)
        self.assertNotIn("SOLUSDT", text)
        self.assertNotIn("Strategy:", text)

    async def test_strategy_weekly_recap_stays_scoped_to_open_strategy(self) -> None:
        base_now = datetime(2026, 3, 17, 15, 0, tzinfo=timezone.utc)
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        strategy_settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=base_now,
        )

        alert_specs = (
            ("BTCUSDT", "rsi", base_now - timedelta(days=6), 211),
            ("ETHUSDT", "breakout", base_now - timedelta(days=2), 212),
        )
        for symbol, strategy_key, delivered_at, message_id in alert_specs:
            alert_id = await self.repository.create_alert(
                self._make_signal(
                    symbol,
                    strategy_key=strategy_key,
                    score=86,
                    candle_close_time=delivered_at - timedelta(minutes=5),
                ),
                sent_at=delivered_at - timedelta(minutes=3),
                followup_due_at=delivered_at + timedelta(hours=2),
                lab_message_id=None,
            )
            with patch("src.storage.repository.utc_now", return_value=delivered_at):
                await self.repository.record_delivered_signal(
                    telegram_user_id=self.user.telegram_user_id,
                    bot_kind="premium",
                    alert_id=alert_id,
                    content_kind="private_pro",
                    message_kind="alert",
                    telegram_message_id=message_id,
                    metadata={"sent": True, "strategy_key": strategy_key, "symbol": symbol},
                )

        with patch("src.userbot.service.utc_now", return_value=base_now):
            sent = await self.service._send_recap(
                self.user,
                period="weekly",
                current_settings=strategy_settings,
                strategy_scoped=True,
            )

        self.assertTrue(sent)
        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Delivered signals in this period: <b>1</b>", text)
        self.assertIn("Strategy: <b>Breakout</b>", text)
        self.assertIn("ETHUSDT", text)
        self.assertNotIn("BTCUSDT", text)

    async def test_gold_weekend_helpers_point_to_next_monday(self) -> None:
        sunday = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        monday = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)

        self.assertTrue(self.service._gold_market_closed_for_weekend(now=sunday))
        self.assertFalse(self.service._gold_market_closed_for_weekend(now=monday))
        self.assertEqual(self.service._next_gold_market_day_label(language_code="ru", now=sunday), "16.03")
        self.assertEqual(self.service._next_gold_market_day_label(language_code="en", now=sunday), "2026-03-16")

    async def test_gold_weekend_note_mentions_last_closed_session(self) -> None:
        sunday = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        note = self.service._gold_weekend_note(language_code="ru", now=sunday)

        self.assertIn("последнюю закрытую сессию", note)
        self.assertIn("16.03", note)

    async def test_run_delivery_maintenance_sends_hourly_digest_for_each_enabled_strategy(self) -> None:
        now = datetime.now(timezone.utc)
        await self.repository.set_user_access_level(
            telegram_user_id=self.user.telegram_user_id,
            access_level="pro",
            user_access_status="paid",
        )
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="rsi",
            strategy_selector_completed_at=now,
        )
        for strategy_key in ("rsi", "breakout"):
            refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
            assert refreshed_shell is not None
            strategy_settings = await self.service._load_strategy_settings(
                self.user.telegram_user_id,
                shell_settings=refreshed_shell,
                strategy_key=strategy_key,
            )
            await self.service._save_user_settings(
                user=self.user,
                current_settings=strategy_settings,
                enabled_strategy_keys=("rsi", "breakout"),
                active_strategy_key=strategy_key,
                direct_signal_delivery_enabled=False,
                followup_delivery_enabled=False,
                delivery_mode="digest",
                last_digest_sent_at=now - timedelta(hours=2),
                last_daily_recap_at=now,
                last_weekly_recap_at=now,
                strategy_selector_completed_at=now,
            )

        rsi_alert_id = await self.repository.create_alert(
            self._make_signal(
                "BTCUSDT",
                strategy_key="rsi",
                direction="oversold",
                score=91,
                candle_close_time=now - timedelta(hours=1, minutes=20),
            ),
            sent_at=now - timedelta(hours=1, minutes=15),
            followup_due_at=now + timedelta(hours=1),
            lab_message_id=None,
        )
        breakout_alert_id = await self.repository.create_alert(
            self._make_signal(
                "ETHUSDT",
                strategy_key="breakout",
                direction="long",
                score=88,
                candle_close_time=now - timedelta(hours=1, minutes=5),
            ),
            sent_at=now - timedelta(hours=1),
            followup_due_at=now + timedelta(hours=1, minutes=15),
            lab_message_id=None,
        )
        for alert_id, strategy_key, symbol in (
            (rsi_alert_id, "rsi", "BTCUSDT"),
            (breakout_alert_id, "breakout", "ETHUSDT"),
        ):
            await self.repository.record_delivered_signal(
                telegram_user_id=self.user.telegram_user_id,
                bot_kind="premium",
                alert_id=alert_id,
                content_kind="private_pro",
                message_kind="queued:alert",
                telegram_message_id=None,
                metadata={"sent": False, "strategy_key": strategy_key, "symbol": symbol},
            )

        await self.service.run_delivery_maintenance()

        digest_records = await self.repository.list_delivered_signals(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            content_kind="private_pro",
            message_kind_prefix="digest:hourly",
            limit=10,
        )
        self.assertEqual(len(digest_records), 2)
        self.assertEqual(
            {(str(record.metadata.get("strategy_key")), int(record.metadata.get("alerts_count") or 0)) for record in digest_records},
            {("rsi", 1), ("breakout", 1)},
        )
        self.assertEqual(len(self.telegram.messages), 2)

        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        rsi_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="rsi",
        )
        breakout_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="breakout",
        )
        self.assertIsNotNone(rsi_settings.last_digest_sent_at)
        self.assertIsNotNone(breakout_settings.last_digest_sent_at)

    async def test_live_delivery_uses_enabled_strategies_not_only_currently_open_one(self) -> None:
        now = datetime.now(timezone.utc)
        shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert shell_settings is not None
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="breakout",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=now,
        )
        refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        rsi_settings = await self.service._load_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=self.user,
            current_settings=rsi_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
            delivery_mode="instant",
            strategy_selector_completed_at=now,
        )
        updated_user = await self.repository.get_private_user(self.user.telegram_user_id)
        assert updated_user is not None

        async def _recipients(*args, **kwargs):
            del args, kwargs
            return [(updated_user, refreshed_shell)]

        async def _has_access(_user):
            return True

        self.repository.list_private_signal_recipients = _recipients  # type: ignore[method-assign]
        self.service._has_premium_access = _has_access  # type: ignore[method-assign]

        signal = self._make_signal(
            "BTCUSDT",
            strategy_key="rsi",
            direction="long",
            score=90,
            candle_close_time=now - timedelta(minutes=1),
        )
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now - timedelta(seconds=30),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )

        await self.service.deliver_pro_alert(signal, alert_id=alert_id)

        self.assertEqual(len(self.router.alerts), 1)
        delivered_signal = self.router.alerts[0]["signal"]
        self.assertEqual(getattr(delivered_signal, "metadata", {}).get("strategy_key"), "rsi")

    async def test_multi_strategy_live_delivery_uses_strategy_toggle_even_when_shell_toggle_is_off(self) -> None:
        now = datetime.now(timezone.utc)
        admin = await self.repository.upsert_private_user(
            telegram_user_id=881001,
            username="multi_flow_admin",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )
        shell_settings = await self.service._ensure_user_settings(admin.telegram_user_id, preferred_language="en")
        for strategy_key in ("rsi", "breakout"):
            await self.service._ensure_premium_strategy_settings(
                admin.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
        shell_settings = await self.service._save_user_settings(
            user=admin,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=now,
        )
        rsi_settings = await self.service._load_strategy_settings(
            admin.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=admin,
            current_settings=rsi_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=False,
            delivery_mode="instant",
            strategy_selector_completed_at=now,
        )
        refreshed_shell = await self.repository.get_user_settings(admin.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        self.assertFalse(refreshed_shell.direct_signal_delivery_enabled)

        signal = self._make_signal(
            "BTCUSDT",
            strategy_key="rsi",
            direction="long",
            score=90,
            candle_close_time=now - timedelta(minutes=1),
        )
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now - timedelta(seconds=30),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )

        await self.service.deliver_pro_alert(signal, alert_id=alert_id)

        self.assertEqual(len(self.router.alerts), 1)
        self.assertEqual(self.router.alerts[0]["chat_id"], str(admin.telegram_user_id))

    async def test_dordo_live_alert_is_mirrored_to_results_channel(self) -> None:
        now = datetime.now(timezone.utc)
        self.service.settings.private_bot_signal_delivery_enabled = True
        self.service.settings.private_bot_results_mirror_enabled = True
        self.service.settings.private_bot_results_mirror_admin_username = "dordo_dordo"
        self.service.settings.private_bot_results_mirror_channel = ""
        self.service.settings.results_channel = "@resultrsi"
        admin = await self.repository.upsert_private_user(
            telegram_user_id=5846358885,
            username="dordo_dordo",
            first_name="Dordo",
            last_name=None,
            is_admin=True,
        )
        shell_settings = await self.service._ensure_user_settings(admin.telegram_user_id, preferred_language="en")
        await self.service._ensure_premium_strategy_settings(
            admin.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=admin,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            strategy_selector_completed_at=now,
        )
        refreshed_shell = await self.repository.get_user_settings(admin.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None
        rsi_settings = await self.service._load_strategy_settings(
            admin.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=admin,
            current_settings=rsi_settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=False,
            delivery_mode="instant",
            strategy_selector_completed_at=now,
        )
        refreshed_shell = await self.repository.get_user_settings(admin.telegram_user_id, bot_kind="premium")
        assert refreshed_shell is not None

        async def _recipients(*args, **kwargs):
            del args, kwargs
            return [(admin, refreshed_shell)]

        async def _has_access(_user):
            return True

        self.repository.list_private_signal_recipients = _recipients  # type: ignore[method-assign]
        self.service._has_premium_access = _has_access  # type: ignore[method-assign]

        signal = self._make_signal(
            "BTCUSDT",
            strategy_key="rsi",
            direction="long",
            score=90,
            candle_close_time=now - timedelta(minutes=1),
        )
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now - timedelta(seconds=30),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )

        await self.service.deliver_pro_alert(signal, alert_id=alert_id)

        self.assertEqual(len(self.router.alerts), 2)
        self.assertEqual(self.router.alerts[0]["chat_id"], str(admin.telegram_user_id))
        self.assertEqual(self.router.alerts[0]["destination_kind"], "private")
        self.assertEqual(self.router.alerts[1]["chat_id"], "@resultrsi")
        self.assertEqual(self.router.alerts[1]["destination_kind"], "results")
        self.assertEqual(len(self.interactive.registered), 2)
        self.assertEqual(self.interactive.registered[1]["chat_id"], "@resultrsi")
        self.assertEqual(self.interactive.registered[1]["destination_kind"], "results")
        self.assertEqual(self.interactive.registered[1]["message_kind"], "alert")

    async def test_multi_strategy_live_delivery_keeps_disabled_strategy_muted(self) -> None:
        now = datetime.now(timezone.utc)
        admin = await self.repository.upsert_private_user(
            telegram_user_id=881002,
            username="muted_flow_admin",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )
        shell_settings = await self.service._ensure_user_settings(admin.telegram_user_id, preferred_language="en")
        for strategy_key in ("rsi", "breakout"):
            await self.service._ensure_premium_strategy_settings(
                admin.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
        shell_settings = await self.service._save_user_settings(
            user=admin,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            strategy_selector_completed_at=now,
        )
        rsi_settings = await self.service._load_strategy_settings(
            admin.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=admin,
            current_settings=rsi_settings,
            enabled_strategy_keys=("rsi", "breakout"),
            active_strategy_key="breakout",
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=False,
            delivery_mode="instant",
            strategy_selector_completed_at=now,
        )

        signal = self._make_signal(
            "ETHUSDT",
            strategy_key="breakout",
            direction="long",
            score=90,
            candle_close_time=now - timedelta(minutes=1),
        )
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now - timedelta(seconds=30),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )

        await self.service.deliver_pro_alert(signal, alert_id=alert_id)

        self.assertEqual(len(self.router.alerts), 0)

    async def test_admin_status_includes_hidden_strategy_flow_summary(self) -> None:
        now = datetime.now(timezone.utc)
        admin = await self.repository.upsert_private_user(
            telegram_user_id=777777,
            username="admin_case",
            first_name="Admin",
            last_name=None,
            is_admin=True,
        )
        shell_settings = await self.service._ensure_user_settings(admin.telegram_user_id, preferred_language="en")
        await self.service._ensure_premium_strategy_settings(
            admin.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        await self.service._save_user_settings(
            user=admin,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            strategy_selector_completed_at=now,
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
        )

        breakout_signal = self._make_signal(
            "ETHUSDT",
            strategy_key="breakout",
            direction="long",
            score=91,
            candle_close_time=now - timedelta(hours=3),
        )
        breakout_alert_id = await self.repository.create_alert(
            breakout_signal,
            sent_at=now - timedelta(hours=3),
            followup_due_at=now - timedelta(hours=1),
            lab_message_id=None,
        )
        breakout_record = await self.service.signal_lifecycle_service.create_signal(
            signal=breakout_signal,
            alert_id=breakout_alert_id,
            created_at=now - timedelta(hours=3),
        )
        await self.service.signal_lifecycle_service.evaluate_signal_state(
            breakout_record,
            high_price=107.4,
            low_price=99.8,
            close_price=107.0,
            observed_at=now - timedelta(hours=2),
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=breakout_alert_id,
                symbol="ETHUSDT",
                direction="long",
                timeframe="15m",
                alert_price=100.0,
                current_price=106.1,
                alert_rsi=34.0,
                current_rsi=48.0,
                move_pct=6.1,
                summary="",
                score=91,
                observed_at=now - timedelta(hours=2),
                stage="4h",
                thesis_result_state="favorable",
                favorable_move_pct=6.1,
                adverse_move_pct=0.7,
                metadata={
                    "thesis_result_state": "favorable",
                    "favorable_move_pct": 6.1,
                    "adverse_move_pct": 0.7,
                },
            )
        )

        rsi_signal = self._make_signal(
            "BTCUSDT",
            strategy_key="rsi",
            direction="oversold",
            score=87,
            candle_close_time=now - timedelta(hours=1),
        )
        rsi_alert_id = await self.repository.create_alert(
            rsi_signal,
            sent_at=now - timedelta(hours=1),
            followup_due_at=now + timedelta(hours=1),
            lab_message_id=None,
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=admin.telegram_user_id,
            bot_kind="premium",
            alert_id=rsi_alert_id,
            content_kind="private_pro",
            message_kind="alert",
            telegram_message_id=501,
            metadata={"sent": True, "symbol": "BTCUSDT", "strategy_key": "rsi"},
        )

        await self.service._send_status(admin)

        self.assertTrue(self.telegram.messages)
        text = str(self.telegram.messages[-1]["text"])
        self.assertIn("Bot Status", text)
        self.assertIn("Active Strategies", text)
        self.assertNotIn("Admin Monitor", text)
        self.assertNotIn("ETHUSDT", text)

    async def test_admin_audit_digest_sends_hidden_strategy_result_once(self) -> None:
        now = datetime.now(timezone.utc)
        admin = await self.repository.upsert_private_user(
            telegram_user_id=888888,
            username="audit_admin",
            first_name="Audit",
            last_name=None,
            is_admin=True,
        )
        shell_settings = await self.service._ensure_user_settings(admin.telegram_user_id, preferred_language="en")
        await self.service._ensure_premium_strategy_settings(
            admin.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key="rsi",
        )
        shell_settings = await self.service._save_user_settings(
            user=admin,
            current_settings=shell_settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            strategy_selector_completed_at=now,
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=False,
            delivery_mode="instant",
        )

        breakout_signal = self._make_signal(
            "ETHUSDT",
            strategy_key="breakout",
            direction="long",
            score=92,
            candle_close_time=now - timedelta(hours=2),
        )
        breakout_alert_id = await self.repository.create_alert(
            breakout_signal,
            sent_at=now - timedelta(hours=2),
            followup_due_at=now - timedelta(minutes=30),
            lab_message_id=None,
        )
        breakout_record = await self.service.signal_lifecycle_service.create_signal(
            signal=breakout_signal,
            alert_id=breakout_alert_id,
            created_at=now - timedelta(hours=2),
        )
        await self.service.signal_lifecycle_service.evaluate_signal_state(
            breakout_record,
            high_price=107.6,
            low_price=99.85,
            close_price=107.2,
            observed_at=now - timedelta(hours=1, minutes=20),
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=breakout_alert_id,
                symbol="ETHUSDT",
                direction="long",
                timeframe="15m",
                alert_price=100.0,
                current_price=106.4,
                alert_rsi=34.0,
                current_rsi=47.0,
                move_pct=6.4,
                summary="",
                score=92,
                observed_at=now - timedelta(hours=1, minutes=15),
                stage="4h",
                thesis_result_state="favorable",
                favorable_move_pct=6.4,
                adverse_move_pct=0.6,
                metadata={
                    "thesis_result_state": "favorable",
                    "favorable_move_pct": 6.4,
                    "adverse_move_pct": 0.6,
                },
            )
        )

        async def _recipients(*args, **kwargs):
            del args, kwargs
            return [(admin, shell_settings)]

        async def _has_access(_user):
            return True

        self.repository.list_private_signal_recipients = _recipients  # type: ignore[method-assign]
        self.service._has_premium_access = _has_access  # type: ignore[method-assign]

        await self.service.run_delivery_maintenance()

        self.assertEqual(len(self.telegram.messages), 0)
        self.assertFalse(
            await self.repository.delivered_signal_exists(
                telegram_user_id=admin.telegram_user_id,
                bot_kind="premium",
                alert_id=breakout_alert_id,
                content_kind="private_pro",
                message_kind="admin:audit:hit_tp",
            )
        )

        await self.service.run_delivery_maintenance()
        self.assertEqual(len(self.telegram.messages), 0)

    async def test_evening_followup_top_slots_send_two_best_daily_winners_without_repeat(self) -> None:
        settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert settings is not None
        settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=True,
        )

        local_now = datetime.now(timezone.utc).astimezone(self.service.settings.timezone)
        local_day = local_now.replace(hour=12, minute=0, second=0, microsecond=0)

        def _local_to_utc(hour: int, minute: int = 0) -> datetime:
            return local_day.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc)

        def _signal(symbol: str, *, score: int, candle_close_time: datetime) -> AlertSignal:
            return AlertSignal(
                symbol=symbol,
                direction="oversold",
                timeframe="15m",
                candle_open_time=candle_close_time - timedelta(minutes=15),
                candle_close_time=candle_close_time,
                price=100.0,
                rsi=24.0,
                day_change_pct=None,
                day_volume=25_000_000.0,
                quote_volume=25_000_000.0,
                last_candle_volume=0.0,
                avg_volume_20=0.0,
                atr=0.0,
                atr_pct=0.0,
                ema20=0.0,
                ema50=0.0,
                score=score,
                explanation="",
                metadata={},
            )

        btc_alert_id = await self.repository.create_alert(
            _signal("BTCUSDT", score=92, candle_close_time=_local_to_utc(10, 0)),
            sent_at=_local_to_utc(10, 2),
            followup_due_at=_local_to_utc(12, 2),
            lab_message_id=None,
        )
        eth_alert_id = await self.repository.create_alert(
            _signal("ETHUSDT", score=88, candle_close_time=_local_to_utc(11, 0)),
            sent_at=_local_to_utc(11, 5),
            followup_due_at=_local_to_utc(13, 5),
            lab_message_id=None,
        )
        sol_alert_id = await self.repository.create_alert(
            _signal("SOLUSDT", score=86, candle_close_time=_local_to_utc(12, 0)),
            sent_at=_local_to_utc(12, 10),
            followup_due_at=_local_to_utc(14, 10),
            lab_message_id=None,
        )
        xrp_alert_id = await self.repository.create_alert(
            _signal("XRPUSDT", score=84, candle_close_time=_local_to_utc(13, 0)),
            sent_at=_local_to_utc(13, 5),
            followup_due_at=_local_to_utc(15, 5),
            lab_message_id=None,
        )

        for index, (alert_id, symbol, score) in enumerate(
            (
                (btc_alert_id, "BTCUSDT", 92),
                (eth_alert_id, "ETHUSDT", 88),
                (sol_alert_id, "SOLUSDT", 86),
                (xrp_alert_id, "XRPUSDT", 84),
            ),
            start=1,
        ):
            await self.repository.record_delivered_signal(
                telegram_user_id=self.user.telegram_user_id,
                bot_kind="premium",
                alert_id=alert_id,
                content_kind="private_pro",
                message_kind="alert",
                telegram_message_id=100 + index,
                metadata={"sent": True, "symbol": symbol, "score": score},
            )

        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=btc_alert_id,
                symbol="BTCUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                current_price=106.0,
                alert_rsi=24.0,
                current_rsi=36.0,
                move_pct=6.0,
                summary="",
                score=92,
                observed_at=_local_to_utc(17, 10),
                stage="6h",
                thesis_result_state="favorable",
                favorable_move_pct=6.0,
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 6.0},
            )
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=eth_alert_id,
                symbol="ETHUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                current_price=104.0,
                alert_rsi=24.0,
                current_rsi=35.0,
                move_pct=4.0,
                summary="",
                score=88,
                observed_at=_local_to_utc(17, 25),
                stage="6h",
                thesis_result_state="favorable",
                favorable_move_pct=4.0,
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 4.0},
            )
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=sol_alert_id,
                symbol="SOLUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                current_price=103.5,
                alert_rsi=24.0,
                current_rsi=34.0,
                move_pct=3.5,
                summary="",
                score=86,
                observed_at=_local_to_utc(16, 45),
                stage="2h",
                thesis_result_state="favorable",
                favorable_move_pct=3.5,
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 3.5},
            )
        )
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=xrp_alert_id,
                symbol="XRPUSDT",
                direction="oversold",
                timeframe="15m",
                alert_price=100.0,
                current_price=102.4,
                alert_rsi=24.0,
                current_rsi=32.0,
                move_pct=2.4,
                summary="",
                score=84,
                observed_at=_local_to_utc(16, 20),
                stage="2h",
                thesis_result_state="favorable",
                favorable_move_pct=2.4,
                metadata={"thesis_result_state": "favorable", "favorable_move_pct": 2.4},
            )
        )

        sent_symbols: list[str] = []

        async def _fake_send_followup_card(user_id: int, alert: AlertRecord, followup: FollowUpResultRecord):
            del user_id, alert
            sent_symbols.append(followup.symbol)
            return SimpleNamespace(sent=True, telegram_message_id=900 + len(sent_symbols))

        self.service._send_followup_card = _fake_send_followup_card  # type: ignore[method-assign]

        await self.service._send_evening_followup_tops_if_due(
            self.user,
            current_settings=settings,
            now=_local_to_utc(18, 5),
        )
        await self.service._send_evening_followup_tops_if_due(
            self.user,
            current_settings=settings,
            now=_local_to_utc(21, 5),
        )

        self.assertEqual(sent_symbols, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])

        delivered = await self.repository.list_delivered_signals(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            content_kind="private_pro",
            message_kind_prefix="followup:top",
            limit=10,
        )
        self.assertEqual(len(delivered), 4)
        self.assertEqual(
            sum(1 for record in delivered if int(record.metadata.get("slot_hour") or 0) == 18),
            2,
        )
        self.assertEqual(
            sum(1 for record in delivered if int(record.metadata.get("slot_hour") or 0) == 21),
            2,
        )
        self.assertEqual(
            {int(record.alert_id or 0) for record in delivered},
            {btc_alert_id, eth_alert_id, sol_alert_id, xrp_alert_id},
        )


async def _test_send_menu_hub_shows_compact_v2_summary_after_migration(self) -> None:
    settings = await self.service._ensure_shell_settings(self.user.telegram_user_id)
    assert settings is not None
    for strategy_key in ("breakout", "trend_pullback", "vwap"):
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key=strategy_key,
        )
    await self.service._save_shell_settings_only(
        self.user.telegram_user_id,
        current_settings=settings,
        direct_signal_delivery_enabled=True,
        followup_delivery_enabled=True,
    )
    await self.service._save_user_settings(
        user=self.user,
        current_settings=await self.service._ensure_shell_settings(self.user.telegram_user_id),
        enabled_strategy_keys=("rsi", "breakout", "trend_pullback", "vwap"),
        active_strategy_key="breakout",
        strategy_selector_completed_at=datetime.now(timezone.utc),
    )
    await self.service._apply_delivery_settings_to_enabled_strategies(
        self.user,
        shell_settings=await self.service._ensure_shell_settings(self.user.telegram_user_id),
        direct_signal_delivery_enabled=True,
        followup_delivery_enabled=True,
    )

    await self.service._send_menu_hub(self.user.telegram_user_id)

    latest_message = self.telegram.messages[-1]
    text = str(latest_message["text"])
    self.assertIn("Main menu", text)
    self.assertIn("Hi, Test!", text)
    self.assertNotIn("Active profile", text)
    self.assertNotIn("Notifications:", text)


UserBotServiceBehaviorTests.test_send_menu_hub_shows_compact_v2_summary_after_migration = _test_send_menu_hub_shows_compact_v2_summary_after_migration


async def _test_admin_stats_count_only_user_relevant_flow_and_disabled_strategy_candidates(self) -> None:
    now = datetime.now(timezone.utc)
    admin = await self.repository.upsert_private_user(
        telegram_user_id=919191,
        username="admin_flow_case",
        first_name="Admin",
        last_name=None,
        is_admin=True,
    )
    shell_settings = await self.service._ensure_shell_settings(admin.telegram_user_id)
    await self.service._ensure_premium_strategy_settings(
        admin.telegram_user_id,
        shell_settings=shell_settings,
        strategy_key="breakout",
    )
    await self.service._save_user_settings(
        user=admin,
        current_settings=shell_settings,
        enabled_strategy_keys=("rsi",),
        active_strategy_key="rsi",
        strategy_selector_completed_at=now,
        direct_signal_delivery_enabled=True,
        followup_delivery_enabled=True,
    )

    breakout_signal = self._make_signal(
        "ETHUSDT",
        strategy_key="breakout",
        direction="long",
        score=93,
        candle_close_time=now - timedelta(hours=3),
    )
    breakout_alert_id = await self.repository.create_alert(
        breakout_signal,
        sent_at=now - timedelta(hours=3),
        followup_due_at=now + timedelta(hours=1),
        lab_message_id=None,
    )
    breakout_record = await self.service.signal_lifecycle_service.create_signal(
        signal=breakout_signal,
        alert_id=breakout_alert_id,
        created_at=now - timedelta(hours=3),
    )
    await self.service.signal_lifecycle_service.evaluate_signal_state(
        breakout_record,
        high_price=107.5,
        low_price=99.8,
        close_price=107.1,
        observed_at=now - timedelta(hours=2),
    )

    await self.repository.create_alert(
        self._make_signal(
            "SOLUSDT",
            strategy_key="breakout",
            direction="long",
            score=20,
            candle_close_time=now - timedelta(hours=2),
        ),
        sent_at=now - timedelta(hours=2),
        followup_due_at=now + timedelta(hours=2),
        lab_message_id=None,
    )

    rsi_signal = self._make_signal(
        "BTCUSDT",
        strategy_key="rsi",
        direction="oversold",
        score=90,
        candle_close_time=now - timedelta(hours=1),
    )
    rsi_alert_id = await self.repository.create_alert(
        rsi_signal,
        sent_at=now - timedelta(hours=1),
        followup_due_at=now + timedelta(hours=2),
        lab_message_id=None,
    )
    rsi_record = await self.service.signal_lifecycle_service.create_signal(
        signal=rsi_signal,
        alert_id=rsi_alert_id,
        created_at=now - timedelta(hours=1),
    )
    await self.service.signal_lifecycle_service.evaluate_signal_state(
        rsi_record,
        high_price=107.3,
        low_price=99.7,
        close_price=107.0,
        observed_at=now - timedelta(minutes=20),
    )
    await self.repository.record_delivered_signal(
        telegram_user_id=admin.telegram_user_id,
        bot_kind="premium",
        alert_id=rsi_alert_id,
        content_kind="private_pro",
        message_kind="alert",
        telegram_message_id=777,
        metadata={"sent": True, "symbol": "BTCUSDT", "strategy_key": "rsi"},
    )

    await self.service._send_admin_stats(admin, period="1d")

    text = str(self.telegram.messages[-1]["text"])
    self.assertIn("Admin Dashboard", text)
    self.assertIn("Breakout", text)
    self.assertIn("gen <b>1</b> | sent <b>0</b> | hidden <b>1</b>", text)
    self.assertNotIn("gen <b>2</b> | sent <b>0</b> | hidden <b>2</b>", text)


UserBotServiceBehaviorTests.test_admin_stats_count_only_user_relevant_flow_and_disabled_strategy_candidates = _test_admin_stats_count_only_user_relevant_flow_and_disabled_strategy_candidates


async def _test_live_delivery_real_recipient_query_uses_strategy_delivery_not_active_shell_flag(self) -> None:
    now = datetime.now(timezone.utc)
    await self.repository.set_user_access_level(
        telegram_user_id=self.user.telegram_user_id,
        access_level="pro",
        user_access_status="paid",
    )
    shell_settings = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
    assert shell_settings is not None
    await self.service._ensure_premium_strategy_settings(
        self.user.telegram_user_id,
        shell_settings=shell_settings,
        strategy_key="breakout",
    )
    await self.service._save_user_settings(
        user=self.user,
        current_settings=shell_settings,
        enabled_strategy_keys=("rsi", "breakout"),
        active_strategy_key="breakout",
        strategy_selector_completed_at=now,
    )

    refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
    assert refreshed_shell is not None
    rsi_settings = await self.service._load_strategy_settings(
        self.user.telegram_user_id,
        shell_settings=refreshed_shell,
        strategy_key="rsi",
    )
    await self.service._save_user_settings(
        user=self.user,
        current_settings=rsi_settings,
        enabled_strategy_keys=("rsi", "breakout"),
        active_strategy_key="breakout",
        direct_signal_delivery_enabled=True,
        followup_delivery_enabled=False,
        delivery_mode="instant",
        strategy_selector_completed_at=now,
    )

    refreshed_shell = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
    assert refreshed_shell is not None
    breakout_settings = await self.service._load_strategy_settings(
        self.user.telegram_user_id,
        shell_settings=refreshed_shell,
        strategy_key="breakout",
    )
    await self.service._save_user_settings(
        user=self.user,
        current_settings=breakout_settings,
        enabled_strategy_keys=("rsi", "breakout"),
        active_strategy_key="breakout",
        direct_signal_delivery_enabled=False,
        followup_delivery_enabled=False,
        delivery_mode="instant",
        strategy_selector_completed_at=now,
    )

    async def _has_access(_user):
        return True

    self.service._has_premium_access = _has_access  # type: ignore[method-assign]

    signal = self._make_signal(
        "BTCUSDT",
        strategy_key="rsi",
        direction="long",
        score=90,
        candle_close_time=now - timedelta(minutes=1),
    )
    alert_id = await self.repository.create_alert(
        signal,
        sent_at=now - timedelta(seconds=30),
        followup_due_at=now + timedelta(hours=2),
        lab_message_id=None,
    )

    await self.service.deliver_pro_alert(signal, alert_id=alert_id)

    self.assertEqual(len(self.router.alerts), 1)
    delivered_signal = self.router.alerts[0]["signal"]
    self.assertEqual(getattr(delivered_signal, "metadata", {}).get("strategy_key"), "rsi")


UserBotServiceBehaviorTests.test_live_delivery_real_recipient_query_uses_strategy_delivery_not_active_shell_flag = _test_live_delivery_real_recipient_query_uses_strategy_delivery_not_active_shell_flag


async def _test_setup_builder_payload_enables_direct_delivery_for_non_quiet_profiles(self) -> None:
    payload = await self.service._build_setup_payload_from_draft(
        self.user.telegram_user_id,
        draft={
            "selected_strategies": ["rsi", "breakout"],
            "delivery_profile": "balanced",
        },
    )

    self.assertTrue(payload["strategies"]["rsi"]["direct_signal_delivery_enabled"])
    self.assertTrue(payload["strategies"]["breakout"]["direct_signal_delivery_enabled"])

    quiet_payload = await self.service._build_setup_payload_from_draft(
        self.user.telegram_user_id,
        draft={
            "selected_strategies": ["rsi", "breakout"],
            "delivery_profile": "quiet_digest",
        },
    )

    self.assertFalse(quiet_payload["strategies"]["rsi"]["direct_signal_delivery_enabled"])
    self.assertFalse(quiet_payload["strategies"]["breakout"]["direct_signal_delivery_enabled"])


UserBotServiceBehaviorTests.test_setup_builder_payload_enables_direct_delivery_for_non_quiet_profiles = _test_setup_builder_payload_enables_direct_delivery_for_non_quiet_profiles


if __name__ == "__main__":
    unittest.main()
