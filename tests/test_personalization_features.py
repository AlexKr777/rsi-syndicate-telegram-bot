from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.core.config import get_settings
from src.core.models import AlertSignal
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.callbacks import parse_userbot_callback_data
from src.userbot.personalization_ui import (
    build_delivery_rule_options_keyboard,
    build_delivery_rules_keyboard,
    build_hide_mute_keyboard,
    build_hide_strategy_keyboard,
    build_hide_timeframe_keyboard,
    build_noise_level_keyboard,
    build_personal_summary_keyboard,
    build_personalized_menu_hub_keyboard,
    build_personalized_results_keyboard,
    build_personalized_settings_keyboard,
    build_quick_filters_keyboard,
    build_repeat_mute_keyboard,
    build_saved_setups_keyboard,
    build_setup_detail_keyboard,
    build_score_filter_keyboard,
    build_session_filter_keyboard,
    build_setups_hub_keyboard,
    build_style_dimension_keyboard,
    build_style_profile_keyboard,
)
from src.userbot.personalization import summarize_setup_payload
from src.userbot.stabilization_ui import (
    build_create_setup_entry_keyboard,
    build_custom_filters_hub_keyboard,
    build_gold_wizard_keyboard,
    build_setup_template_picker_keyboard,
    build_truthful_setups_hub_keyboard,
)
from src.userbot.setup_builder_ui import build_setup_builder_keyboard
from src.userbot.service import PrivateBotService


def _collect_callback_data(markup: dict[str, object] | None) -> list[str]:
    if not markup:
        return []
    callback_values: list[str] = []
    for row in markup.get("inline_keyboard", []):
        for button in row:
            if isinstance(button, dict) and "callback_data" in button:
                callback_values.append(str(button["callback_data"]))
    return callback_values


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.answers: list[dict[str, object]] = []
        self.deleted: list[dict[str, object]] = []

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
        return {"id": 1, "username": "SyndicateProBot"}


class _FakeInteractiveAlertService:
    async def start_chat_loading_indicator(self, **kwargs):
        return {"id": 1, **kwargs}

    async def stop_loading_indicator(self, handle, *, final_stage: str):
        del handle, final_stage

    async def register_alert_message(self, **kwargs):
        del kwargs


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
        return SimpleNamespace(sent=True, telegram_message_id=len(self.alerts), metadata={"telegram_chat_id": chat_id})


class _FakeChartRenderer:
    async def render_alert_chart(self, frame, signal, preview: bool = False):
        del frame, signal, preview
        return Path("fake-chart.png")

    def cleanup(self, path) -> None:
        del path


class _FakeBinanceClient:
    async def get_active_usdt_symbols(self, force_refresh: bool = False):
        del force_refresh
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD"]

    async def get_all_ticker_stats(self, force_refresh: bool = False):
        del force_refresh
        return {
            "BTCUSDT": SimpleNamespace(last_price=1.0, price_change_percent=2.5, quote_volume=10_000_000.0, volume=1_000_000.0),
            "ETHUSDT": SimpleNamespace(last_price=1.0, price_change_percent=2.1, quote_volume=9_000_000.0, volume=900_000.0),
            "SOLUSDT": SimpleNamespace(last_price=1.0, price_change_percent=3.1, quote_volume=8_000_000.0, volume=800_000.0),
            "XAUUSD": SimpleNamespace(last_price=1.0, price_change_percent=0.5, quote_volume=5_000_000.0, volume=500_000.0),
        }

    async def get_klines(self, symbol: str, timeframe: str, limit: int):
        del symbol, timeframe, limit
        return pd.DataFrame()


class PersonalizationFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_root = Path(".tmp_test_personalization")
        self.temp_root.mkdir(exist_ok=True)
        self.sqlite_path = self.temp_root / f"personalization_{uuid.uuid4().hex}.db"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.telegram = _FakeTelegramClient()
        self.service = PrivateBotService(
            settings=get_settings(),
            repository=self.repository,
            telegram_client=self.telegram,
            router=_FakeRouter(),
            binance_client=_FakeBinanceClient(),
            chart_renderer=_FakeChartRenderer(),
            interactive_alert_service=_FakeInteractiveAlertService(),
            bot_kind="premium",
            destination_kind="private",
            content_kind="private_pro",
            onboarding_service=None,
        )
        self.user = await self.repository.upsert_private_user(
            telegram_user_id=778001,
            username="tester",
            first_name="Personal",
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
        score: int,
        strategy_key: str = "rsi",
        candle_close_time: datetime | None = None,
    ) -> AlertSignal:
        close_time = candle_close_time or datetime.now(timezone.utc)
        return AlertSignal(
            symbol=symbol,
            direction="oversold",
            timeframe="15m",
            candle_open_time=close_time - timedelta(minutes=15),
            candle_close_time=close_time,
            price=100.0,
            rsi=25.0,
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
            metadata={"strategy_key": strategy_key, "asset_class": "crypto"},
        )

    def test_personalization_keyboards_callbacks_are_parseable(self) -> None:
        markups = [
            build_personalized_menu_hub_keyboard(language_code="en", quick_launch_label="▶ Low Noise", quick_launch_callback_data="ux:setup:activate:3"),
            build_setups_hub_keyboard(language_code="en", back_callback_data="main:today"),
            build_truthful_setups_hub_keyboard(language_code="en", back_callback_data="main:today"),
            build_saved_setups_keyboard(language_code="en", setups=[]),
            build_setup_detail_keyboard(language_code="en", setup_id=3, is_active=False, is_pinned=True, back_callback_data="ux:setup:list"),
            build_create_setup_entry_keyboard(language_code="en", back_callback_data="main:setups"),
            build_setup_template_picker_keyboard(language_code="en", back_callback_data="ux:setup:create"),
            build_setup_builder_keyboard(
                language_code="en",
                draft={"name": "Desk", "selected_strategies": ["breakout"], "selected_timeframes": ["15m"]},
                step="review",
                parent_callback_data="main:setups",
            ),
            build_setup_builder_keyboard(
                language_code="en",
                draft={
                    "name": "Desk",
                    "selected_strategies": ["breakout"],
                    "selected_timeframes": ["15m"],
                    "asset_scope_type": "theme",
                    "asset_scope_payload": {"theme_id": 7, "theme_name": "Majors Desk", "symbols": ["BTCUSDT", "ETHUSDT"]},
                    "available_themes": [{"id": 7, "name": "Majors Desk"}],
                },
                step="scope",
                parent_callback_data="main:setups",
            ),
            build_quick_filters_keyboard(language_code="en", back_callback_data="main:today"),
            build_custom_filters_hub_keyboard(language_code="en", back_callback_data="main:setups"),
            build_noise_level_keyboard(language_code="en", selected="balanced", back_callback_data="ux:quickfiltershub"),
            build_score_filter_keyboard(language_code="en", selected="high", back_callback_data="ux:quickfiltershub"),
            build_session_filter_keyboard(language_code="en", selected="london", back_callback_data="ux:quickfiltershub"),
            build_delivery_rules_keyboard(language_code="en", back_callback_data="main:settings"),
            build_delivery_rule_options_keyboard(language_code="en", rule_key="digest_frequency_hours", back_callback_data="ux:deliveryrules"),
            build_hide_mute_keyboard(language_code="en", back_callback_data="main:settings"),
            build_hide_strategy_keyboard(language_code="en", strategy_keys=("breakout", "trend_pullback"), back_callback_data="ux:hidemute"),
            build_hide_timeframe_keyboard(language_code="en", back_callback_data="ux:hidemute"),
            build_repeat_mute_keyboard(language_code="en", back_callback_data="ux:hidemute"),
            build_style_profile_keyboard(language_code="en", back_callback_data="main:settings"),
            build_style_dimension_keyboard(
                language_code="en",
                dimension="speed_preference",
                options=(("fast", "⚡ Fast"), ("balanced", "⚖️ Balanced"), ("patient", "🧘 Patient")),
                back_callback_data="ux:stylehub",
            ),
            build_personal_summary_keyboard(language_code="en", back_callback_data="results:hub"),
            build_personalized_settings_keyboard(language_code="en", display_mode="pro", back_callback_data="main:today"),
            build_personalized_results_keyboard(language_code="en", is_admin=True),
            build_gold_wizard_keyboard(language_code="en", draft={"mode": "balanced"}, step="review"),
        ]

        for callback_data in [item for markup in markups for item in _collect_callback_data(markup)]:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

        admin_results_callbacks = _collect_callback_data(
            build_personalized_results_keyboard(language_code="en", is_admin=True)
        )
        self.assertIn("ux:health", admin_results_callbacks)

    async def test_create_setup_callback_opens_real_builder_entry(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-setup-create",
                "data": "ux:setup:create",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 58, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.edits)
        self.assertIn("Create Setup", str(self.telegram.edits[-1]["text"]))
        state = await self.service._get_setup_builder_state(self.user.telegram_user_id)
        self.assertIsNone(state)

    async def test_save_current_callback_prompts_for_name_instead_of_fake_create_flow(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-save-current",
                "data": "ux:setup:savecurrent",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 59, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.messages)
        self.assertIn("current setup", str(self.telegram.messages[-1]["text"]).lower())

    async def test_setup_builder_back_from_first_step_returns_to_create_setup_entry(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-builder-back-start",
                "data": "ux:setupbuilder:start:blank",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 59, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-builder-back",
                "data": "ux:setupbuilder:back",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 59, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertIn("Create Setup", str(self.telegram.edits[-1]["text"]))
        state = await self.service._get_setup_builder_state(self.user.telegram_user_id)
        self.assertIsNone(state)

    async def test_setup_builder_can_save_and_activate_new_setup(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-builder-start",
                "data": "ux:setupbuilder:start:current",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 60, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        state = await self.service._get_setup_builder_state(self.user.telegram_user_id)
        assert state is not None
        self.assertEqual(state.step, "name")

        for index in range(len(self.service.SETUP_BUILDER_STEPS) - 1):
            await self.service.handle_callback_query(
                {
                    "id": f"cb-builder-next-{index}",
                    "data": "ux:setupbuilder:next",
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": 60, "chat": {"id": self.user.telegram_user_id}},
                }
            )

        final_state = await self.service._get_setup_builder_state(self.user.telegram_user_id)
        assert final_state is not None
        self.assertEqual(final_state.step, "review")

        await self.service.handle_callback_query(
            {
                "id": "cb-builder-save",
                "data": "ux:setupbuilder:save:activate",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 60, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        active_setup = await self.service._active_saved_setup(self.user.telegram_user_id)
        self.assertIsNotNone(active_setup)
        current = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert current is not None
        self.assertEqual(current.current_set_id, active_setup.id)
        self.assertEqual(active_setup.last_used_at is not None, True)

    async def test_asset_scope_all_and_custom_are_saved_explicitly(self) -> None:
        draft = await self.service._current_setup_builder_draft(
            self.user.telegram_user_id,
            language_code="en",
            mode="blank",
        )
        self.service._write_setup_builder_scope(draft, scope_type="custom", payload={"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})
        custom_payload = await self.service._build_setup_payload_from_draft(self.user.telegram_user_id, draft=draft)
        self.assertEqual(custom_payload["shell"]["asset_scope_type"], "custom")
        self.assertEqual(custom_payload["shell"]["asset_scope_payload"]["symbols"], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        self.service._write_setup_builder_scope(draft, scope_type="all")
        all_payload = await self.service._build_setup_payload_from_draft(self.user.telegram_user_id, draft=draft)
        self.assertEqual(all_payload["shell"]["asset_scope_type"], "all")
        self.assertIsNone(all_payload["shell"]["asset_scope_payload"])
        for strategy_payload in all_payload["strategies"].values():
            self.assertFalse(strategy_payload["watchlist_only"])

    async def test_setup_edit_updates_same_setup_and_can_reset_scope_to_all(self) -> None:
        draft = await self.service._current_setup_builder_draft(
            self.user.telegram_user_id,
            language_code="en",
            mode="blank",
        )
        draft["name"] = "Custom Desk"
        self.service._write_setup_builder_scope(draft, scope_type="custom", payload={"symbols": ["BTCUSDT", "ETHUSDT"]})
        created = await self.repository.create_user_saved_setup(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            name="Custom Desk",
            payload=await self.service._build_setup_payload_from_draft(self.user.telegram_user_id, draft=draft),
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-setup-edit",
                "data": f"ux:setup:edit:{created.id}",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 63, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        state = await self.service._get_setup_builder_state(self.user.telegram_user_id)
        assert state is not None
        self.assertEqual(state.draft["editing_setup_id"], created.id)
        self.assertEqual(state.draft["asset_scope_type"], "custom")

        updated_draft = dict(state.draft)
        self.service._write_setup_builder_scope(updated_draft, scope_type="all")
        await self.service._save_setup_from_builder(self.user, draft=updated_draft, activate=False)

        refreshed = await self.repository.get_user_saved_setup(created.id, telegram_user_id=self.user.telegram_user_id, bot_kind="premium")
        assert refreshed is not None
        self.assertEqual(refreshed.id, created.id)
        self.assertEqual(refreshed.payload["shell"]["asset_scope_type"], "all")

    async def test_favorites_scope_uses_live_favorites_without_overwriting_them(self) -> None:
        await self.repository.replace_user_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            symbols=["BTCUSDT", "ETHUSDT"],
        )
        draft = await self.service._current_setup_builder_draft(
            self.user.telegram_user_id,
            language_code="en",
            mode="blank",
        )
        draft["name"] = "Favorites Desk"
        self.service._write_setup_builder_scope(draft, scope_type="favorites")
        setup = await self.repository.create_user_saved_setup(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            name="Favorites Desk",
            payload=await self.service._build_setup_payload_from_draft(self.user.telegram_user_id, draft=draft),
        )

        await self.repository.replace_user_watchlist_symbols(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            symbols=["SOLUSDT"],
        )
        await self.service._apply_saved_setup_payload(self.user, setup=setup)

        current_favorites = await self.repository.list_user_watchlist(self.user.telegram_user_id, bot_kind="premium")
        self.assertEqual([item.symbol for item in current_favorites], ["SOLUSDT"])
        restored = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert restored is not None
        self.assertEqual(restored.personalization["asset_scope_type"], "favorites")

    async def test_theme_scope_summary_uses_theme_name(self) -> None:
        theme = await self.repository.save_premium_strategy_watchlist_theme(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="rsi",
            theme_name="Majors Desk",
            symbols=["BTCUSDT", "ETHUSDT"],
        )
        draft = await self.service._current_setup_builder_draft(
            self.user.telegram_user_id,
            language_code="en",
            mode="blank",
        )
        self.service._write_setup_builder_scope(
            draft,
            scope_type="theme",
            payload={"theme_id": theme.id, "theme_name": theme.theme_name, "symbols": ["BTCUSDT", "ETHUSDT"]},
        )
        payload = await self.service._build_setup_payload_from_draft(self.user.telegram_user_id, draft=draft)
        self.assertIn("Majors Desk", summarize_setup_payload(payload, language_code="en"))

    async def test_gold_setup_wizard_applies_real_gold_configuration(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-gold-start",
                "data": "ux:goldwizard:start",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 61, "chat": {"id": self.user.telegram_user_id}},
            }
        )
        for callback_data in (
            "ux:goldwizard:next",
            "ux:goldwizard:set:direction:short",
            "ux:goldwizard:next",
            "ux:goldwizard:set:tempo:macro",
            "ux:goldwizard:next",
            "ux:goldwizard:set:session:london",
            "ux:goldwizard:next",
            "ux:goldwizard:set:followups:off",
            "ux:goldwizard:next",
            "ux:goldwizard:set:delivery:quiet",
            "ux:goldwizard:next",
            "ux:goldwizard:apply",
        ):
            await self.service.handle_callback_query(
                {
                    "id": f"gold-{callback_data}",
                    "data": callback_data,
                    "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                    "message": {"message_id": 61, "chat": {"id": self.user.telegram_user_id}},
                }
            )

        current = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert current is not None
        self.assertTrue(current.gold_alerts_enabled)
        self.assertEqual(current.active_strategy_key, "gold")
        self.assertIn("gold_breakout", current.enabled_strategy_keys)
        breakout = await self.repository.get_premium_strategy_settings(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            strategy_key="gold_breakout",
        )
        assert breakout is not None
        self.assertEqual(breakout.direction_filter, "short")
        self.assertFalse(breakout.followup_delivery_enabled)
        self.assertEqual(breakout.delivery_mode, "digest")
        self.assertEqual(breakout.active_watchlist_theme, "gold")
        self.assertEqual(breakout.strategy_preferences.get("session_focus"), "london")
        self.assertEqual(breakout.strategy_preferences.get("timeframe_focus"), "macro")

    async def test_gold_wizard_back_from_first_step_returns_to_gold_hub(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-gold-back-start",
                "data": "ux:goldwizard:start",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 62, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        await self.service.handle_callback_query(
            {
                "id": "cb-gold-back",
                "data": "ux:goldwizard:back",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 62, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertIn("Gold Desk", str(self.telegram.edits[-1]["text"]))
        state = await self.service._get_gold_wizard_state(self.user.telegram_user_id)
        self.assertIsNone(state)

    async def test_saved_setup_activation_restores_personalization_and_delivery_rules(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id)
        personalized = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            active_workspace="low_noise",
            personalization={
                "noise_level": "minimal",
                "score_filter": "high",
                "session_filter": "london",
                "quick_filters": ["low_noise"],
                "hidden": {"symbols": ["DOGEUSDT"]},
            },
            delivery_rules={
                "strong_signals": "instant",
                "watchlist_matches": "instant",
                "gold_signals": "digest",
                "medium_signals": "digest",
                "followups": "important",
                "overnight": "quiet",
                "repeat_cooldown_hours": 8,
                "digest_frequency_hours": 4,
                "weekend_mode": "normal",
                "one_signal_per_asset_hours": 0,
            },
        )
        saved_setup = await self.service._save_setup_snapshot(self.user.telegram_user_id, name="Low Noise Majors")

        await self.service._save_user_settings(
            user=self.user,
            current_settings=personalized,
            personalization={"noise_level": "active", "score_filter": "all", "session_filter": "all_day"},
            delivery_rules={"digest_frequency_hours": 1, "medium_signals": "instant"},
            active_workspace="aggressive",
            current_set_id=None,
        )

        await self.service._apply_saved_setup_payload(self.user, setup=saved_setup)

        restored = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert restored is not None
        self.assertEqual(restored.current_set_id, saved_setup.id)
        self.assertEqual(restored.active_workspace, "low_noise")
        self.assertEqual(restored.personalization["noise_level"], "minimal")
        self.assertEqual(restored.personalization["score_filter"], "high")
        self.assertEqual(restored.personalization["session_filter"], "london")
        self.assertEqual(restored.delivery_rules["digest_frequency_hours"], 4)
        self.assertEqual(restored.delivery_rules["medium_signals"], "digest")

    async def test_quick_filter_callback_updates_backend_and_clears_active_setup(self) -> None:
        saved_setup = await self.service._save_setup_snapshot(self.user.telegram_user_id, name="Base Setup")
        await self.service._apply_saved_setup_payload(self.user, setup=saved_setup)

        await self.service.handle_callback_query(
            {
                "id": "cb-qf-1",
                "data": "ux:qf:apply:gold_only",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 55, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertIsNone(updated.current_set_id)
        self.assertIn("gold_only", updated.personalization["quick_filters"])

    async def test_delivery_rule_callback_updates_backend_rules(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-delivery-rule",
                "data": "ux:deliveryrule:digest_frequency_hours:4",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 56, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        updated = await self.repository.get_user_settings(self.user.telegram_user_id, bot_kind="premium")
        assert updated is not None
        self.assertEqual(updated.delivery_rules["digest_frequency_hours"], 4)

    async def test_custom_filters_hub_sets_delivery_and_hide_back_targets(self) -> None:
        await self.service._send_custom_filters_hub(self.user, chat_id=str(self.user.telegram_user_id))

        self.assertEqual(
            self.service._screen_back_callback(self.user.telegram_user_id, screen="deliveryrules", default="fallback"),
            "ux:filtershub",
        )
        self.assertEqual(
            self.service._screen_back_callback(self.user.telegram_user_id, screen="hidemute", default="fallback"),
            "ux:filtershub",
        )

    async def test_non_admin_admin_stats_route_returns_restricted_results_hub(self) -> None:
        await self.service.handle_callback_query(
            {
                "id": "cb-admin-denied",
                "data": "results:admin:7d",
                "from": {"id": self.user.telegram_user_id, "language_code": "en"},
                "message": {"message_id": 57, "chat": {"id": self.user.telegram_user_id}},
            }
        )

        self.assertTrue(self.telegram.edits)
        self.assertIn("Restricted Section", str(self.telegram.edits[-1]["text"]))
        callbacks = _collect_callback_data(self.telegram.edits[-1].get("reply_markup"))
        self.assertNotIn("results:admin", callbacks)

    async def test_digest_frequency_rule_delays_digest_send(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id)
        settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            delivery_mode="digest",
            delivery_rules={"digest_frequency_hours": 4},
        )
        settings = await self.service._save_strategy_runtime_state(
            user=self.user,
            current_settings=settings,
            last_digest_sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        await self.service._send_hourly_digest_if_due(self.user, current_settings=settings)

        self.assertFalse(self.telegram.messages)

    async def test_personal_summary_uses_real_matched_and_filtered_data(self) -> None:
        settings = await self.service._ensure_user_settings(self.user.telegram_user_id)
        settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            personalization={"noise_level": "minimal", "score_filter": "high", "session_filter": "all_day"},
        )
        now = datetime.now(timezone.utc)
        matched_alert_id = await self.repository.create_alert(
            self._make_signal("BTCUSDT", score=92, candle_close_time=now - timedelta(hours=2)),
            sent_at=now - timedelta(hours=2),
            followup_due_at=now + timedelta(hours=1),
            lab_message_id=None,
        )
        await self.repository.create_alert(
            self._make_signal("SOLUSDT", score=72, candle_close_time=now - timedelta(hours=1)),
            sent_at=now - timedelta(hours=1),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            alert_id=matched_alert_id,
            content_kind="private_pro",
            message_kind="alert",
            telegram_message_id=9001,
            metadata={"sent": True, "symbol": "BTCUSDT", "score": 92, "strategy_key": "rsi"},
        )

        summary = await self.service._build_personal_summary_data(self.user, period_label="daily")

        self.assertEqual(summary.matched, 1)
        self.assertEqual(summary.delivered, 1)
        self.assertEqual(summary.strong_delivered, 1)
        self.assertGreaterEqual(summary.filtered_out, 1)
        self.assertEqual(summary.top_strategy, "RSI")
        self.assertEqual(summary.most_active_asset, "BTCUSDT")

    async def test_personal_summary_does_not_count_strategy_disabled_alerts_as_filtered_out(self) -> None:
        settings = await self.service._ensure_shell_settings(self.user.telegram_user_id)
        await self.service._ensure_premium_strategy_settings(
            self.user.telegram_user_id,
            shell_settings=settings,
            strategy_key="breakout",
        )
        settings = await self.service._save_user_settings(
            user=self.user,
            current_settings=settings,
            enabled_strategy_keys=("rsi",),
            active_strategy_key="rsi",
            preferred_min_score=85,
            strategy_selector_completed_at=datetime.now(timezone.utc),
        )
        now = datetime.now(timezone.utc)
        delivered_alert_id = await self.repository.create_alert(
            self._make_signal("BTCUSDT", strategy_key="rsi", score=92, candle_close_time=now - timedelta(hours=2)),
            sent_at=now - timedelta(hours=2),
            followup_due_at=now + timedelta(hours=1),
            lab_message_id=None,
        )
        await self.repository.create_alert(
            self._make_signal("SOLUSDT", strategy_key="rsi", score=72, candle_close_time=now - timedelta(hours=1)),
            sent_at=now - timedelta(hours=1),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        await self.repository.create_alert(
            self._make_signal("ETHUSDT", strategy_key="breakout", score=93, candle_close_time=now - timedelta(minutes=40)),
            sent_at=now - timedelta(minutes=40),
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=self.user.telegram_user_id,
            bot_kind="premium",
            alert_id=delivered_alert_id,
            content_kind="private_pro",
            message_kind="alert",
            telegram_message_id=9101,
            metadata={"sent": True, "symbol": "BTCUSDT", "score": 92, "strategy_key": "rsi"},
        )

        summary = await self.service._build_personal_summary_data(self.user, period_label="daily")

        self.assertEqual(summary.matched, 1)
        self.assertEqual(summary.delivered, 1)
        self.assertEqual(summary.filtered_out, 1)
