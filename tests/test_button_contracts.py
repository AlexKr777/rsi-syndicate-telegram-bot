from __future__ import annotations

import unittest

from src.bot.callbacks import parse_alert_callback_data
from src.bot.inline_keyboards import build_alert_inline_keyboard, build_detail_card_keyboard_with_action
from src.userbot.callbacks import parse_userbot_callback_data
from src.userbot.action_registry import action_spec_for, registered_action_kinds
from src.userbot.keyboards import (
    build_access_inline_keyboard,
    build_admin_stats_keyboard,
    build_classic_main_menu_keyboard,
    build_analyze_symbol_inline_keyboard,
    build_compare_hub_keyboard,
    build_compact_signals_inline_keyboard,
    build_custom_setup_inline_keyboard,
    build_empty_signals_keyboard,
    build_example_signal_keyboard,
    build_gold_hub_keyboard,
    build_guided_start_keyboard,
    build_help_inline_keyboard,
    build_help_more_inline_keyboard,
    build_language_picker_inline_keyboard,
    build_learn_hub_keyboard,
    build_lifecycle_hub_keyboard,
    build_main_menu_keyboard,
    build_menu_hub_inline_keyboard,
    build_onboarding_inline_keyboard,
    build_onboarding_step_keyboard,
    build_referral_inline_keyboard,
    build_results_hub_keyboard,
    build_section_hub_keyboard,
    build_signal_reading_keyboard,
    build_signal_setup_inline_keyboard,
    build_settings_center_keyboard,
    build_strategies_hub_keyboard,
    build_strategy_guide_inline_keyboard,
    build_strategy_hub_keyboard,
    build_strategy_selector_inline_keyboard,
    build_watchlist_inline_keyboard,
    build_watchlist_themes_keyboard,
    build_workspace_center_keyboard,
)
from src.userbot.personalization_ui import (
    build_personalized_menu_hub_keyboard,
    build_personalized_settings_keyboard,
    build_pro_submenu_keyboard,
    build_setup_detail_keyboard,
)
from src.userbot.stabilization_ui import (
    build_create_setup_entry_keyboard,
    build_custom_filters_hub_keyboard,
    build_gold_wizard_keyboard,
    build_setup_template_picker_keyboard,
    build_truthful_setups_hub_keyboard,
)
from src.userbot.setup_builder_ui import build_setup_builder_keyboard
from src.userbot.ux_v2 import (
    build_analytics_keyboard,
    build_assets_keyboard,
    build_flow_keyboard,
    build_flows_keyboard,
    build_gold_keyboard,
    build_help_keyboard as build_v2_help_keyboard,
    build_home_keyboard as build_v2_home_keyboard,
    build_market_keyboard,
    build_notifications_keyboard,
    build_onboarding_keyboard as build_v2_onboarding_keyboard,
    build_quality_keyboard,
    build_results_keyboard as build_v2_results_keyboard,
    build_settings_keyboard as build_v2_settings_keyboard,
    build_signal_empty_keyboard,
    build_signal_list_keyboard,
    build_style_keyboard,
    build_style_preview_keyboard,
)


def _collect_callback_data(markup: dict[str, object] | None) -> list[str]:
    if not markup:
        return []
    callback_values: list[str] = []
    for row in markup.get("inline_keyboard", []):
        for button in row:
            if isinstance(button, dict) and "callback_data" in button:
                callback_values.append(str(button["callback_data"]))
    return callback_values


USERBOT_HANDLED_ACTION_KINDS = {
    "menu",
    "setup",
    "strategies",
    "results_hub",
    "results_admin",
    "health",
    "compare_hub",
    "compare_view",
    "compare_admin",
    "learn_hub",
    "learn_page",
    "learn_guide",
    "lifecycle_hub",
    "lifecycle_view",
    "signalshub",
    "watchhub",
    "deliveryhub",
    "statshub",
    "aihub",
    "settingshub",
    "workspacehub",
    "display_mode_view",
    "pro_hub",
    "workspace_save",
    "workspace_apply",
    "setupshub",
    "setup_list",
    "setup_create",
    "setup_savecurrent",
    "setup_pinned",
    "setup_detail",
    "setup_activate",
    "setup_edit",
    "setup_update",
    "setup_rename",
    "setup_duplicate",
    "setup_delete",
    "setup_default",
    "setup_pin",
    "quickfiltershub",
    "quickfilter_apply",
    "quickfilter_reset",
    "custom_filters_hub",
    "noisehub",
    "noise_set",
    "scorehub",
    "score_set",
    "sessionhub",
    "session_set",
    "delivery_rules_hub",
    "delivery_rule_view",
    "delivery_rule_set",
    "hide_mute_hub",
    "hide_asset_prompt",
    "hide_mute_view",
    "hide_mute_toggle",
    "hide_strategy",
    "hide_timeframe",
    "hide_repeats",
    "hide_mute_resume",
    "style_hub",
    "style_view",
    "style_set",
    "style_save",
    "personal_summary",
    "setup_builder_start",
    "setup_builder_template",
    "setup_builder_prompt",
    "setup_builder_set",
    "setup_builder_toggle",
    "setup_builder_next",
    "setup_builder_back",
    "setup_builder_cancel",
    "setup_builder_save",
    "gold_wizard_start",
    "gold_wizard_set",
    "gold_wizard_next",
    "gold_wizard_back",
    "gold_wizard_cancel",
    "gold_wizard_apply",
    "strategy_toggle",
    "strategy_open",
    "strategy_signals",
    "strategy_filters",
    "strategy_alerts",
    "strategy_favorites",
    "strategy_quicksetup",
    "strategy_results",
    "strategy_guide",
    "strategy_settings",
    "strategy_compare",
    "strategy_lifecycle",
    "watchlist",
    "access",
    "referral",
    "status",
    "help",
    "help_page",
    "onboarding_example",
    "onboarding_read",
    "themes",
    "control",
    "analyze",
    "guide",
    "goldview",
    "goldhub",
    "custom",
    "ai",
    "pro",
    "pay",
    "renew",
    "signals",
    "open_signal",
    "profile",
    "strategy_pref",
    "rsi",
    "volume",
    "direction",
    "universe",
    "gold",
    "watch_open",
    "watch_remove",
    "theme_save",
    "theme_all",
    "theme_builtin",
    "theme_open",
    "theme_add",
    "theme_rename",
    "theme_delete",
    "delivery_mode",
    "snooze",
    "quiet_hours",
    "toggle",
    "recap",
    "onboard",
    "language_picker",
    "language_set",
}

ALERT_HANDLED_ACTION_KINDS = {
    "delete_detail",
    "timeframe",
    "ai",
    "compare",
    "risk",
    "reason",
}


def _representative_userbot_markups() -> list[dict[str, object] | None]:
    markups = [
        build_setup_detail_keyboard(language_code="en", setup_id=3, is_active=False, is_pinned=False, back_callback_data="ux:setup:list"),
        build_access_inline_keyboard(can_renew=True, language_code="en", renew_label="Renew"),
        build_signal_setup_inline_keyboard(
            language_code="en",
            strategy_key="breakout",
            profile="custom",
            rsi_mode="custom",
            min_quote_volume=5_000_000.0,
            direction_filter="both",
            watchlist_only=False,
            set_scope_active=False,
            set_button_label="Set",
            include_gold_toggle=True,
            gold_alerts_enabled=True,
            show_reset_button=True,
        ),
        build_custom_setup_inline_keyboard(language_code="en", direction_step=True),
        build_compact_signals_inline_keyboard(
            language_code="en",
            entries=[(1, "BTCUSDT • 15m")],
            strong_only=False,
        ),
        build_watchlist_inline_keyboard(language_code="en", symbols=["BTCUSDT", "ETHUSDT"]),
        build_analyze_symbol_inline_keyboard(language_code="en", symbols=["BTCUSDT", "ETHUSDT"]),
        build_help_inline_keyboard(language_code="en"),
        build_strategy_selector_inline_keyboard(
            rows=[("RSI", "ux:strategy:open:rsi", "Enable", "ux:strategy:toggle:rsi")],
            include_home_button=True,
            language_code="en",
        ),
        build_strategy_hub_keyboard(
            language_code="en",
            strategy_key="breakout",
            strategy_enabled=False,
            include_gold_shortcut=False,
        ),
        build_strategy_guide_inline_keyboard(language_code="en"),
        build_menu_hub_inline_keyboard(
            language_code="en",
            bot_kind="premium",
            include_gold_button=True,
            payment_label="Pay PRO+",
        ),
        build_referral_inline_keyboard(
            language_code="en",
            referral_link="https://t.me/example_bot?start=ref_test",
            share_url="https://t.me/share/url?url=test",
        ),
        build_gold_hub_keyboard(
            language_code="en",
            gold_alerts_enabled=True,
            gold_web_url="https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
        ),
        build_watchlist_themes_keyboard(language_code="en", saved_themes=[(1, "Desk"), (2, "Scalp")]),
        build_language_picker_inline_keyboard(language_code="en", selected_language="en", context="settings"),
        build_settings_center_keyboard(
            language_code="en",
            display_mode="simple",
            active_workspace="low_noise",
            has_saved_workspace=True,
        ),
        build_workspace_center_keyboard(
            language_code="en",
            active_workspace="low_noise",
            has_saved_workspace=True,
        ),
        build_truthful_setups_hub_keyboard(language_code="en", back_callback_data="main:today"),
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
        build_custom_filters_hub_keyboard(language_code="en", back_callback_data="main:setups"),
        build_gold_wizard_keyboard(language_code="en", draft={"mode": "balanced"}, step="review"),
        build_strategies_hub_keyboard(language_code="en"),
        build_results_hub_keyboard(is_admin=True, language_code="en"),
        build_compare_hub_keyboard(is_admin=True, language_code="en"),
        build_learn_hub_keyboard(language_code="en"),
        build_lifecycle_hub_keyboard(language_code="en"),
        build_admin_stats_keyboard(back_callback_data="main:results", language_code="en"),
    ]
    markups.extend(
        build_section_hub_keyboard(
            language_code="en",
            section=section,
            include_gold_button=True,
            premium=True,
            direct_delivery_enabled=True,
            followup_delivery_enabled=True,
            gold_alerts_enabled=True,
        )
        for section in ("signals", "watchlists", "delivery", "stats", "settings", "ai")
    )
    for step in ("preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"):
        markups.append(
            build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="breakout")
        )
    for step in ("preset", "rsi_mode", "direction", "symbols", "universe", "delivery", "followups", "summary"):
        markups.append(
            build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="rsi")
        )
    for step in ("preset", "direction", "delivery", "followups", "summary"):
        markups.append(
            build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="gold")
        )
    return markups


class KeyboardCallbackContractTests(unittest.TestCase):
    def test_classic_main_menu_stays_compact_and_separate(self) -> None:
        markup = build_classic_main_menu_keyboard(
            direct_delivery_enabled=True,
            followup_delivery_enabled=True,
            include_community_button=True,
            include_gold_button=True,
            language_code="ru",
        )
        labels = [
            str(button["text"])
            for row in markup["keyboard"]
            for button in row
        ]
        self.assertEqual(
            labels,
            ["📡 Сигналы", "🎯 Настройка", "👀 Вотчлист", "💎 Premium", "❓ Помощь"],
        )

    def test_all_userbot_callbacks_are_parseable(self) -> None:
        markups = [
            build_access_inline_keyboard(can_renew=True, language_code="en", renew_label="Renew"),
            build_signal_setup_inline_keyboard(
                language_code="en",
                strategy_key="breakout",
                profile="custom",
                rsi_mode="custom",
                min_quote_volume=5_000_000.0,
                direction_filter="both",
                watchlist_only=False,
                set_scope_active=False,
                set_button_label="Set",
                include_gold_toggle=True,
                gold_alerts_enabled=True,
                show_reset_button=True,
            ),
            build_custom_setup_inline_keyboard(language_code="en", direction_step=True),
            build_compact_signals_inline_keyboard(
                language_code="en",
                entries=[(1, "BTCUSDT • 15m")],
                strong_only=False,
            ),
            build_watchlist_inline_keyboard(language_code="en", symbols=["BTCUSDT", "ETHUSDT"]),
            build_analyze_symbol_inline_keyboard(language_code="en", symbols=["BTCUSDT", "ETHUSDT"]),
            build_help_inline_keyboard(language_code="en"),
            build_strategy_selector_inline_keyboard(
                rows=[("RSI", "ux:strategy:open:rsi", "Enable", "ux:strategy:toggle:rsi")],
                include_home_button=True,
                language_code="en",
            ),
            build_strategy_hub_keyboard(
                language_code="en",
                strategy_key="breakout",
                strategy_enabled=False,
                include_gold_shortcut=False,
            ),
            build_strategy_guide_inline_keyboard(language_code="en"),
            build_menu_hub_inline_keyboard(
                language_code="en",
                bot_kind="premium",
                include_gold_button=True,
                payment_label="Pay PRO+",
            ),
            build_referral_inline_keyboard(
                language_code="en",
                referral_link="https://t.me/example_bot?start=ref_test",
                share_url="https://t.me/share/url?url=test",
            ),
            build_gold_hub_keyboard(
                language_code="en",
                gold_alerts_enabled=True,
                gold_web_url="https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
            ),
            build_watchlist_themes_keyboard(language_code="en", saved_themes=[(1, "Desk"), (2, "Scalp")]),
            build_language_picker_inline_keyboard(language_code="en", selected_language="en", context="settings"),
            build_truthful_setups_hub_keyboard(language_code="en", back_callback_data="main:today"),
            build_create_setup_entry_keyboard(language_code="en", back_callback_data="main:setups"),
            build_setup_template_picker_keyboard(language_code="en", back_callback_data="ux:setup:create"),
            build_setup_builder_keyboard(
                language_code="en",
                draft={"name": "Desk", "selected_strategies": ["breakout"], "selected_timeframes": ["15m"]},
                step="review",
                parent_callback_data="main:setups",
            ),
            build_custom_filters_hub_keyboard(language_code="en", back_callback_data="main:setups"),
            build_gold_wizard_keyboard(language_code="en", draft={"mode": "balanced"}, step="review"),
        ]
        markups.extend(
            build_section_hub_keyboard(
                language_code="en",
                section=section,
                include_gold_button=True,
                premium=True,
                direct_delivery_enabled=True,
                followup_delivery_enabled=True,
                gold_alerts_enabled=True,
            )
            for section in ("signals", "watchlists", "delivery", "stats", "settings", "ai")
        )
        for step in ("preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"):
            markups.append(build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="breakout"))
        for step in ("preset", "rsi_mode", "direction", "symbols", "universe", "delivery", "followups", "summary"):
            markups.append(build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="rsi"))
        for step in ("preset", "direction", "delivery", "followups", "summary"):
            markups.append(build_onboarding_step_keyboard(language_code="en", step=step, include_gold=True, strategy_key="gold"))

        for callback_data in [item for markup in markups for item in _collect_callback_data(markup)]:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_all_userbot_callbacks_are_backed_by_handlers(self) -> None:
        for callback_data in [item for markup in _representative_userbot_markups() for item in _collect_callback_data(markup)]:
            action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(action, msg=callback_data)
            assert action is not None
            self.assertIn(action.kind, USERBOT_HANDLED_ACTION_KINDS, msg=callback_data)
            spec = action_spec_for(action.kind)
            self.assertIsNotNone(spec, msg=callback_data)
            assert spec is not None
            self.assertTrue(spec.action_id, msg=callback_data)
            self.assertTrue(spec.handler, msg=callback_data)
            self.assertTrue(spec.service, msg=callback_data)

    def test_action_registry_covers_the_legacy_callback_contract(self) -> None:
        """A keyboard cannot surface a parser action without registry metadata."""

        self.assertTrue(USERBOT_HANDLED_ACTION_KINDS <= registered_action_kinds())

    def test_v2_navigation_callbacks_are_parseable_and_registered(self) -> None:
        markups = [
            build_v2_home_keyboard(language_code="ru", is_pro=False, include_gold=True),
            build_v2_home_keyboard(language_code="en", is_pro=True, include_gold=True),
            *(build_v2_onboarding_keyboard(language_code="en", step=step) for step in ("style", "market", "quality", "delivery", "review")),
            build_signal_list_keyboard(language_code="en", entries=[(7, "BTCUSDT · Long · 1h")]),
            build_signal_empty_keyboard(language_code="en"),
            build_flow_keyboard(language_code="en"),
            build_flows_keyboard(language_code="en"),
            build_style_keyboard(language_code="en"),
            build_style_preview_keyboard(language_code="en", style_key="balanced"),
            build_assets_keyboard(language_code="en"),
            build_quality_keyboard(language_code="en"),
            build_notifications_keyboard(language_code="en", gold_available=True),
            build_v2_settings_keyboard(language_code="en"),
            build_v2_results_keyboard(language_code="en"),
            build_v2_help_keyboard(language_code="en"),
            build_analytics_keyboard(language_code="en", include_gold=True),
            build_market_keyboard(language_code="en", include_gold=True),
            build_gold_keyboard(language_code="en"),
        ]
        for callback_data in [item for markup in markups for item in _collect_callback_data(markup)]:
            action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(action, msg=callback_data)
            assert action is not None
            spec = action_spec_for(action.kind)
            self.assertIsNotNone(spec, msg=callback_data)
            assert spec is not None
            if callback_data.startswith("v2:"):
                self.assertEqual(spec.allowed_bot_kinds, ("premium",), msg=callback_data)

    def test_watchlists_hub_is_not_duplicated(self) -> None:
        callbacks = _collect_callback_data(
            build_section_hub_keyboard(
                language_code="en",
                section="watchlists",
                include_gold_button=True,
                premium=True,
                gold_alerts_enabled=True,
            )
        )
        self.assertEqual(callbacks[0], "ux:watchlist")
        self.assertIn("ux:themes", callbacks)
        self.assertIn("ux:theme:save", callbacks)
        self.assertIn("ux:deliveryruleview:watchlist_matches", callbacks)
        self.assertNotIn("ux:filtershub", callbacks)
        self.assertNotIn("ux:setup", callbacks)
        self.assertEqual(callbacks[-1], "ux:menu")

    def test_ai_hub_exposes_core_actions_and_home(self) -> None:
        callbacks = _collect_callback_data(
            build_section_hub_keyboard(
                language_code="ru",
                section="ai",
                include_gold_button=True,
                premium=True,
                direct_delivery_enabled=True,
                followup_delivery_enabled=True,
                gold_alerts_enabled=True,
            )
        )
        self.assertEqual(
            callbacks,
            ["ux:analyze", "learn:ai_guide", "main:signals", "ux:goldhub", "ux:menu"],
        )

    def test_setups_hub_keeps_only_real_primary_actions(self) -> None:
        callbacks = _collect_callback_data(
            build_truthful_setups_hub_keyboard(language_code="ru", back_callback_data="main:today")
        )
        self.assertIn("ux:setup:list", callbacks)
        self.assertIn("ux:setup:create", callbacks)
        self.assertIn("ux:filtershub", callbacks)
        self.assertNotIn("ux:setup:savecurrent", callbacks)
        self.assertNotIn("ux:setup:pinned", callbacks)
        self.assertNotIn("ux:quickfiltershub", callbacks)

    def test_strategy_hub_is_strategy_specific(self) -> None:
        breakout_callbacks = _collect_callback_data(
            build_strategy_hub_keyboard(
                language_code="en",
                strategy_key="breakout",
                strategy_enabled=False,
                include_gold_shortcut=False,
            )
        )
        gold_callbacks = _collect_callback_data(
            build_strategy_hub_keyboard(
                language_code="en",
                strategy_key="gold",
                strategy_enabled=True,
                include_gold_shortcut=True,
            )
        )

        self.assertNotIn("ux:goldhub", breakout_callbacks)
        self.assertIn("ux:goldhub", gold_callbacks)
        self.assertIn("strategy:toggle:breakout", breakout_callbacks)
        self.assertIn("strategy:toggle:gold", gold_callbacks)
        self.assertIn("strategy:filters:breakout", breakout_callbacks)
        self.assertIn("strategy:quicksetup:breakout", breakout_callbacks)
        self.assertIn("strategy:guide:breakout", breakout_callbacks)
        self.assertIn("main:today", breakout_callbacks)

    def test_strategy_hub_groups_related_actions_together(self) -> None:
        callbacks = _collect_callback_data(
            build_strategy_hub_keyboard(
                language_code="en",
                strategy_key="breakout",
                strategy_enabled=True,
                include_gold_shortcut=False,
            )
        )

        self.assertEqual(
            callbacks[:8],
            [
                "strategy:signals:breakout",
                "strategy:filters:breakout",
                "strategy:alerts:breakout",
                "strategy:favorites:breakout",
                "strategy:quicksetup:breakout",
                "strategy:results:breakout",
                "main:ai",
                "strategy:guide:breakout",
            ],
        )
        self.assertNotIn("strategy:compare:breakout", callbacks)
        self.assertEqual(callbacks[-2:], ["main:strategies", "main:today"])

    def test_gold_strategy_hub_removes_single_asset_clutter(self) -> None:
        callbacks = _collect_callback_data(
            build_strategy_hub_keyboard(
                language_code="ru",
                strategy_key="gold",
                strategy_enabled=True,
                include_gold_shortcut=False,
            )
        )
        self.assertNotIn("main:ai", callbacks)
        self.assertNotIn("strategy:favorites:gold", callbacks)
        self.assertNotIn("strategy:compare:gold", callbacks)

    def test_strategy_hub_localizes_labels_for_russian(self) -> None:
        markup = build_strategy_hub_keyboard(
            language_code="ru",
            strategy_key="breakout",
            strategy_enabled=True,
            include_gold_shortcut=False,
        )
        texts = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]

        self.assertIn("📡 Сигналы", texts)
        self.assertIn("🎛 Фильтры сигналов", texts)
        self.assertIn("⚙️ Настройки", texts)

    def test_strategy_guide_keyboard_exposes_close_and_home(self) -> None:
        callbacks = _collect_callback_data(build_strategy_guide_inline_keyboard(language_code="en"))
        self.assertEqual(callbacks, ["ux:guide:close", "ux:menu"])

    def test_menu_hub_starts_with_main_navigation_sections(self) -> None:
        callbacks = _collect_callback_data(
            build_menu_hub_inline_keyboard(
                language_code="en",
                bot_kind="premium",
                include_gold_button=True,
                payment_label="Pay PRO+",
            )
        )

        self.assertEqual(
            callbacks[:10],
            [
                "ux:signals:strong",
                "ux:watchhub",
                "main:ai",
                "main:alerts",
                "main:strategies",
                "main:results",
                "ux:workspacehub",
                "ux:filtershub",
                "main:settings",
                "main:access",
            ],
        )
        self.assertIn("main:help", callbacks)
        self.assertIn("ux:referral", callbacks)
        self.assertEqual(callbacks[-1], "ux:pay")

    def test_menu_hub_exposes_referral_entry(self) -> None:
        markup = build_menu_hub_inline_keyboard(
            language_code="en",
            bot_kind="premium",
            include_gold_button=True,
        )
        texts = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]

        self.assertIn("🎁 Referral", texts)

    def test_menu_hub_localizes_labels_for_russian(self) -> None:
        markup = build_menu_hub_inline_keyboard(
            language_code="ru",
            bot_kind="premium",
            include_gold_button=True,
        )
        texts = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]

        self.assertIn("💥 Сильные сетапы", texts)
        self.assertIn("📈 Стратегии", texts)
        self.assertIn("❓ Помощь", texts)

    def test_referral_keyboard_has_refresh_and_home_callbacks(self) -> None:
        callbacks = _collect_callback_data(
            build_referral_inline_keyboard(
                language_code="en",
                referral_link="https://t.me/example_bot?start=ref_test",
                share_url="https://t.me/share/url?url=test",
            )
        )

        self.assertEqual(callbacks, ["main:access", "ux:referral", "ux:menu"])

    def test_referral_keyboard_adds_back_when_context_is_provided(self) -> None:
        callbacks = _collect_callback_data(
            build_referral_inline_keyboard(
                language_code="en",
                referral_link="https://t.me/example_bot?start=ref_test",
                share_url="https://t.me/share/url?url=test",
                back_callback_data="ux:settingshub",
            )
        )

        self.assertEqual(callbacks, ["main:access", "ux:referral", "ux:settingshub", "ux:menu"])

    def test_results_hub_hides_admin_stats_for_non_admins(self) -> None:
        callbacks = _collect_callback_data(build_results_hub_keyboard(is_admin=False, language_code="en"))
        self.assertNotIn("results:admin", callbacks)

    def test_create_setup_entry_routes_to_real_builder_choices(self) -> None:
        callbacks = _collect_callback_data(
            build_create_setup_entry_keyboard(language_code="en", back_callback_data="main:setups")
        )
        self.assertEqual(
            callbacks,
            [
                "ux:setupbuilder:start:blank",
                "ux:setupbuilder:start:current",
                "ux:setupbuilder:start:template",
                "main:today",
                "main:setups",
            ],
        )

    def test_custom_filters_hub_routes_to_real_filter_and_delivery_editors(self) -> None:
        callbacks = _collect_callback_data(
            build_custom_filters_hub_keyboard(language_code="en", back_callback_data="main:setups")
        )
        self.assertIn("ux:noisehub", callbacks)
        self.assertIn("ux:scorehub", callbacks)
        self.assertIn("ux:sessionhub", callbacks)
        self.assertIn("ux:deliveryrules", callbacks)
        self.assertIn("ux:hidemute", callbacks)
        self.assertEqual(callbacks[-2:], ["main:today", "main:setups"])

    def test_gold_wizard_keyboard_stays_inside_gold_flow(self) -> None:
        callbacks = _collect_callback_data(
            build_gold_wizard_keyboard(language_code="en", draft={"mode": "balanced"}, step="review")
        )
        self.assertIn("ux:goldwizard:apply", callbacks)
        self.assertIn("ux:goldwizard:back", callbacks)
        self.assertEqual(callbacks[-1], "main:today")

    def test_menu_hub_exposes_favorites_entry(self) -> None:
        markup = build_menu_hub_inline_keyboard(
            language_code="en",
            bot_kind="premium",
            include_gold_button=True,
        )
        texts = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]

        self.assertIn("👀 Watchlist", texts)

    def test_analyze_keyboard_is_callback_only_without_copy_shortcuts(self) -> None:
        markup = build_analyze_symbol_inline_keyboard(language_code="en", symbols=[])
        buttons = [
            button
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict)
        ]
        self.assertFalse(any("copy_text" in button for button in buttons))

    def test_delivery_hub_shows_resume_only_while_snoozed(self) -> None:
        active_pause_callbacks = _collect_callback_data(
            build_section_hub_keyboard(
                language_code="en",
                section="delivery",
                include_gold_button=True,
                premium=True,
                direct_delivery_enabled=True,
                followup_delivery_enabled=True,
                gold_alerts_enabled=True,
                snoozed=True,
            )
        )
        normal_callbacks = _collect_callback_data(
            build_section_hub_keyboard(
                language_code="en",
                section="delivery",
                include_gold_button=True,
                premium=True,
                direct_delivery_enabled=True,
                followup_delivery_enabled=True,
                gold_alerts_enabled=True,
                snoozed=False,
            )
        )

        self.assertIn("ux:snooze:resume", active_pause_callbacks)
        self.assertNotIn("ux:snooze:resume", normal_callbacks)

    def test_signal_setup_keyboard_shows_reset_only_for_custom(self) -> None:
        custom_callbacks = _collect_callback_data(
            build_signal_setup_inline_keyboard(
                language_code="en",
                strategy_key="rsi",
                profile="custom",
                rsi_mode="custom",
                min_quote_volume=5_000_000.0,
                direction_filter="both",
                watchlist_only=False,
                set_scope_active=False,
                set_button_label="Set",
                include_gold_toggle=False,
                gold_alerts_enabled=False,
                show_reset_button=True,
            )
        )
        preset_callbacks = _collect_callback_data(
            build_signal_setup_inline_keyboard(
                language_code="en",
                strategy_key="breakout",
                profile="balanced",
                rsi_mode="balanced",
                min_quote_volume=5_000_000.0,
                direction_filter="both",
                watchlist_only=False,
                set_scope_active=False,
                set_button_label="Set",
                include_gold_toggle=False,
                gold_alerts_enabled=False,
                show_reset_button=False,
            )
        )
        self.assertIn("ux:profile:reset", custom_callbacks)
        self.assertNotIn("ux:profile:reset", preset_callbacks)

    def test_gold_signal_setup_only_shows_gold_relevant_controls(self) -> None:
        callbacks = _collect_callback_data(
            build_signal_setup_inline_keyboard(
                language_code="en",
                strategy_key="gold",
                profile="balanced",
                rsi_mode="balanced",
                min_quote_volume=5_000_000.0,
                direction_filter="both",
                watchlist_only=False,
                set_scope_active=False,
                set_button_label="Set",
                include_gold_toggle=True,
                gold_alerts_enabled=True,
                show_reset_button=False,
            )
        )
        self.assertIn("ux:gold:toggle", callbacks)
        self.assertFalse(any(callback.startswith("ux:volume:") for callback in callbacks))
        self.assertFalse(any(callback.startswith("ux:universe:") for callback in callbacks))
        self.assertIn("ux:pref:session_focus:london", callbacks)
        self.assertFalse(any(callback.startswith("ux:pref:market_mode:") for callback in callbacks))

    def test_breakout_signal_setup_exposes_strategy_specific_controls(self) -> None:
        callbacks = _collect_callback_data(
            build_signal_setup_inline_keyboard(
                language_code="en",
                strategy_key="breakout",
                profile="balanced",
                rsi_mode="balanced",
                strategy_preferences={
                    "timeframe_focus": "core",
                    "market_mode": "balanced",
                    "followup_priority": "move",
                },
                min_quote_volume=5_000_000.0,
                direction_filter="both",
                watchlist_only=False,
                set_scope_active=False,
                set_button_label="Set",
                include_gold_toggle=False,
                gold_alerts_enabled=False,
                show_reset_button=False,
            )
        )

        self.assertIn("ux:pref:timeframe_focus:fast", callbacks)
        self.assertIn("ux:pref:timeframe_focus:core", callbacks)
        self.assertIn("ux:pref:market_mode:expansion", callbacks)
        self.assertIn("ux:pref:followup_priority:watchlist", callbacks)

    def test_language_picker_settings_includes_back_and_home(self) -> None:
        callbacks = _collect_callback_data(
            build_language_picker_inline_keyboard(language_code="en", selected_language="en", context="settings")
        )
        self.assertEqual(
            callbacks,
            ["ux:language:set:en:settings", "ux:language:set:ru:settings", "ux:settingshub", "ux:menu"],
        )

    def test_onboarding_first_step_has_back_to_signal_setup(self) -> None:
        callbacks = _collect_callback_data(
            build_onboarding_step_keyboard(
                language_code="en",
                step="preset",
                include_gold=True,
                strategy_key="breakout",
            )
        )
        self.assertIn("ux:setup", callbacks)
        self.assertIn("ux:menu", callbacks)

    def test_settings_hub_includes_language_picker(self) -> None:
        callbacks = _collect_callback_data(
            build_section_hub_keyboard(
                language_code="en",
                section="settings",
                include_gold_button=True,
                premium=True,
            )
        )
        self.assertIn("ux:language:picker:settings", callbacks)

    def test_settings_center_exposes_workspace_and_display_controls(self) -> None:
        callbacks = _collect_callback_data(
            build_settings_center_keyboard(
                language_code="en",
                display_mode="simple",
                active_workspace="low_noise",
                has_saved_workspace=True,
            )
        )
        self.assertIn("ux:deliveryhub", callbacks)
        self.assertIn("ux:filtershub", callbacks)
        self.assertIn("ux:workspacehub", callbacks)
        self.assertIn("ux:language:picker:settings", callbacks)
        self.assertIn("ux:display:simple", callbacks)
        self.assertIn("ux:display:pro", callbacks)
        self.assertIn("ux:workspace:apply:saved", callbacks)
        self.assertIn("ux:onboard:start", callbacks)
        self.assertEqual(callbacks[-1], "ux:menu")

    def test_personalized_settings_keyboard_uses_clearer_russian_labels(self) -> None:
        markup = build_personalized_settings_keyboard(
            language_code="ru",
            display_mode="pro",
            back_callback_data="main:today",
        )
        texts = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("📬 Как доставлять", texts)
        self.assertIn("📊 Качество сигналов", texts)
        self.assertIn("🕒 Время рынка", texts)
        self.assertIn("🚫 Что скрыть", texts)
        self.assertIn("🧩 Рабочие режимы", texts)
        self.assertIn("🖥 Сделать проще", texts)

    def test_russian_labels_are_translated_and_language_button_points_to_other_language(self) -> None:
        markup = build_main_menu_keyboard(
            direct_delivery_enabled=True,
            followup_delivery_enabled=True,
            include_community_button=True,
            include_gold_button=True,
            language_code="ru",
        )
        texts = [
            str(button["text"])
            for row in markup.get("keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("👀 Вотчлист", texts)
        self.assertIn("AI анализ монеты", texts)
        self.assertIn("🪙 Золото / XAUUSD", texts)
        self.assertIn("Язык: English", texts)

        themes_markup = build_watchlist_themes_keyboard(language_code="ru", saved_themes=[(1, "Desk")])
        theme_texts = [
            str(button["text"])
            for row in themes_markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]
        self.assertIn("Топ монеты", theme_texts)
        self.assertIn("Мем-монеты", theme_texts)
        self.assertIn("Золото", theme_texts)
        self.assertIn("Избранные", theme_texts)

    def test_onboarding_keyboard_includes_channels_folder_button_when_configured(self) -> None:
        markup = build_onboarding_inline_keyboard(
            public_channel="@rsisyndicate",
            results_channel="@resultrsi",
            language_code="en",
            community_target="https://t.me/rsicommunityy",
            channels_folder_target="https://t.me/addlist/OoRiRoEMra03NTdi",
        )
        buttons = [
            button
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict)
        ]

        self.assertIn(
            {"text": "Join All Channels", "url": "https://t.me/addlist/OoRiRoEMra03NTdi"},
            buttons,
        )

    def test_guided_start_keyboard_contains_only_clear_first_actions(self) -> None:
        markup = build_guided_start_keyboard(language_code="en")
        callbacks = _collect_callback_data(markup)
        labels = [
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        ]

        self.assertEqual(
            callbacks,
            [
                "ux:welcome:example",
                "ux:welcome:read",
                "ux:signals:strong",
                "ux:access",
                "ux:deliveryhub",
                "main:help",
                "ux:menu",
            ],
        )
        self.assertIn("Example Signal", " ".join(labels))
        self.assertIn("How to Read Signals", " ".join(labels))
        self.assertIn("Strong Setups", " ".join(labels))
        self.assertIn("My PRO+ Access", " ".join(labels))
        self.assertIn("All Sections", " ".join(labels))
        for callback_data in callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_classic_guided_start_keyboard_uses_classic_actions(self) -> None:
        markup = build_guided_start_keyboard(language_code="en", bot_kind="classic")
        callbacks = _collect_callback_data(markup)
        labels = " ".join(
            str(button["text"])
            for row in markup.get("inline_keyboard", [])
            for button in row
            if isinstance(button, dict) and "text" in button
        )

        self.assertIn("Latest Classic Signals", labels)
        self.assertIn("Classic vs PRO+", labels)
        self.assertIn("ux:help:compare", callbacks)
        self.assertNotIn("Referral", labels)
        for callback_data in callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_help_keyboard_keeps_example_and_signal_guide_accessible(self) -> None:
        callbacks = _collect_callback_data(build_help_inline_keyboard(language_code="en"))

        self.assertIn("ux:welcome:example", callbacks)
        self.assertIn("ux:welcome:read", callbacks)
        self.assertIn("ux:help:no_signals", callbacks)
        self.assertIn("ux:help:compare", callbacks)
        self.assertIn("ux:help:risk", callbacks)
        self.assertIn("ux:help:support", callbacks)
        self.assertIn("ux:help:more", callbacks)
        self.assertNotIn("ux:help:notifications", callbacks)
        more_callbacks = _collect_callback_data(build_help_more_inline_keyboard(language_code="en"))
        self.assertIn("ux:help:notifications", more_callbacks)
        self.assertIn("ux:help:commands", more_callbacks)
        for callback_data in callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)
        for callback_data in more_callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_example_and_reading_screens_have_contextual_next_steps(self) -> None:
        example_callbacks = _collect_callback_data(build_example_signal_keyboard(language_code="en"))
        reading_callbacks = _collect_callback_data(build_signal_reading_keyboard(language_code="en"))

        self.assertEqual(
            example_callbacks,
            ["ux:welcome:read", "ux:signals:strong", "main:results", "ux:access", "ux:menu"],
        )
        self.assertEqual(
            reading_callbacks,
            ["ux:welcome:example", "ux:signals:strong", "main:results", "ux:access", "ux:menu"],
        )
        for callback_data in [*example_callbacks, *reading_callbacks]:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_simple_and_pro_main_menus_keep_different_depth(self) -> None:
        simple_callbacks = _collect_callback_data(
            build_personalized_menu_hub_keyboard(language_code="en", display_mode="simple")
        )
        pro_callbacks = _collect_callback_data(
            build_personalized_menu_hub_keyboard(language_code="en", display_mode="pro")
        )

        for expected in (
            "ux:signals:strong",
            "ux:signals:fresh",
            "ux:welcome:example",
            "ux:welcome:read",
            "main:results",
            "main:alerts",
            "main:access",
            "main:help",
            "ux:display:pro",
        ):
            self.assertIn(expected, simple_callbacks)
        self.assertNotIn("main:ai", simple_callbacks)
        self.assertNotIn("ux:watchhub", simple_callbacks)
        self.assertNotIn("main:settings", simple_callbacks)
        self.assertNotIn("main:setups", simple_callbacks)
        self.assertNotIn("ux:filtershub", simple_callbacks)
        for expected in (
            "ux:prohub:signals",
            "ux:prohub:analytics",
            "ux:prohub:flow",
            "ux:prohub:watchlist",
            "ux:prohub:results",
            "ux:prohub:access",
            "ux:prohub:system",
        ):
            self.assertIn(expected, pro_callbacks)
        self.assertNotIn("main:setups", pro_callbacks)
        self.assertNotIn("ux:filtershub", pro_callbacks)
        self.assertNotIn("ux:deliveryrules", pro_callbacks)
        self.assertNotIn("ux:hidemute", pro_callbacks)
        self.assertIn("ux:display:simple", pro_callbacks)

    def test_pro_submenus_keep_advanced_routes_reachable(self) -> None:
        submenu_callbacks = []
        for hub in ("signals", "analytics", "flow", "watchlist", "results", "access", "system"):
            submenu_callbacks.extend(_collect_callback_data(build_pro_submenu_keyboard(hub=hub, language_code="en", payment_label="Pay PRO+")))

        for expected in (
            "main:setups",
            "main:strategies",
            "ux:filtershub",
            "ux:deliveryrules",
            "ux:hidemute",
            "main:ai",
            "ux:watchhub",
            "main:settings",
            "ux:pay",
        ):
            self.assertIn(expected, submenu_callbacks)
        for callback_data in submenu_callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_empty_signals_keyboard_offers_explanation_and_next_actions(self) -> None:
        callbacks = _collect_callback_data(build_empty_signals_keyboard(language_code="en"))

        self.assertEqual(
            callbacks,
            [
                "ux:welcome:example",
                "main:results",
                "ux:filtershub",
                "main:help",
                "ux:menu",
            ],
        )
        for callback_data in callbacks:
            self.assertIsNotNone(parse_userbot_callback_data(callback_data), msg=callback_data)

    def test_alert_callbacks_are_parseable(self) -> None:
        markups = [
            build_alert_inline_keyboard(
                symbol="BTCUSDT",
                selected_timeframe="15m",
                supported_timeframes=("1m", "5m", "15m", "1h"),
                futures_base_url="https://www.binance.com/en/futures",
                language_code="en",
                include_ai_analysis=True,
                include_risk_management=True,
                include_signal_reason=True,
                include_compare=True,
                include_copy_symbol=True,
                include_home_button=True,
            ),
            build_detail_card_keyboard_with_action(
                include_delete=True,
                language_code="en",
                back_label="Back",
                back_callback_data="alert:ai:BTCUSDT",
            ),
        ]
        for callback_data in [item for markup in markups for item in _collect_callback_data(markup)]:
            self.assertTrue(
                parse_alert_callback_data(callback_data) is not None
                or parse_userbot_callback_data(callback_data) is not None,
                msg=callback_data,
            )

    def test_alert_callbacks_are_backed_by_handlers(self) -> None:
        markups = [
            build_alert_inline_keyboard(
                symbol="BTCUSDT",
                selected_timeframe="15m",
                supported_timeframes=("1m", "5m", "15m", "1h"),
                futures_base_url="https://www.binance.com/en/futures",
                language_code="en",
                include_ai_analysis=True,
                include_risk_management=True,
                include_signal_reason=True,
                include_compare=True,
                include_copy_symbol=True,
                include_home_button=True,
            ),
            build_detail_card_keyboard_with_action(
                include_delete=True,
                language_code="en",
                back_label="Back",
                back_callback_data="alert:ai:BTCUSDT",
            ),
        ]
        callbacks = [item for markup in markups for item in _collect_callback_data(markup)]
        self.assertIn("main:today", callbacks)
        for callback_data in callbacks:
            alert_action = parse_alert_callback_data(callback_data)
            if alert_action is not None:
                self.assertIn(alert_action.kind, ALERT_HANDLED_ACTION_KINDS, msg=callback_data)
                continue
            user_action = parse_userbot_callback_data(callback_data)
            self.assertIsNotNone(user_action, msg=callback_data)
            assert user_action is not None
            self.assertIn(user_action.kind, USERBOT_HANDLED_ACTION_KINDS, msg=callback_data)

    def test_non_private_alert_keyboard_hides_main_menu_button(self) -> None:
        callbacks = _collect_callback_data(
            build_alert_inline_keyboard(
                symbol="BTCUSDT",
                selected_timeframe="15m",
                supported_timeframes=("1m", "5m", "15m", "1h"),
                futures_base_url="https://www.binance.com/en/futures",
                language_code="ru",
                include_ai_analysis=True,
                include_risk_management=True,
                include_signal_reason=True,
                include_compare=True,
                include_copy_symbol=True,
                include_home_button=False,
            )
        )
        self.assertNotIn("main:today", callbacks)

    def test_alert_keyboard_places_timeframes_before_analysis_actions(self) -> None:
        markup = build_alert_inline_keyboard(
            symbol="BTCUSDT",
            selected_timeframe="15m",
            supported_timeframes=("1m", "5m", "15m", "1h"),
            futures_base_url="https://www.binance.com/en/futures",
            language_code="en",
            include_ai_analysis=True,
            include_risk_management=True,
            include_signal_reason=True,
            include_compare=True,
            include_copy_symbol=True,
            include_home_button=True,
        )
        rows = markup["inline_keyboard"]
        self.assertEqual([button["text"] for button in rows[0]], ["1m", "5m", "[15m]", "1h"])
        self.assertEqual(rows[1][0]["callback_data"], "alert:ai:BTCUSDT")

    def test_alert_keyboard_adds_binance_app_button_when_app_base_is_provided(self) -> None:
        markup = build_alert_inline_keyboard(
            symbol="BTCUSDT",
            selected_timeframe="15m",
            supported_timeframes=("1m", "5m", "15m", "1h"),
            futures_base_url="https://www.binance.com/en/futures",
            futures_app_base_url="https://app.binance.com/en/futures",
            language_code="ru",
            include_ai_analysis=True,
            include_risk_management=True,
            include_signal_reason=True,
            include_compare=True,
            include_copy_symbol=True,
            include_binance_app_link=True,
            include_tradingview_link=True,
            include_home_button=True,
        )
        rows = markup["inline_keyboard"]
        self.assertEqual(rows[-4][0]["text"], "Скопировать BTCUSDT")
        self.assertEqual(rows[-3][0]["text"], "TradingView")
        self.assertEqual(rows[-3][0]["url"], "https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT.P")
        self.assertEqual(rows[-3][1]["text"], "Открыть в приложении")
        self.assertTrue(rows[-3][1]["url"].startswith("https://app.binance.com/en/download?_dp="))
        self.assertEqual(rows[-2][0]["url"], "https://www.binance.com/en/futures/BTCUSDT")

    def test_alert_keyboard_uses_direct_app_button_without_bridge_webapp(self) -> None:
        markup = build_alert_inline_keyboard(
            symbol="BTCUSDT",
            selected_timeframe="15m",
            supported_timeframes=("1m", "5m", "15m", "1h"),
            futures_base_url="https://www.binance.com/en/futures",
            futures_app_base_url="https://app.binance.com/en/futures",
            language_code="ru",
            include_ai_analysis=True,
            include_risk_management=True,
            include_signal_reason=True,
            include_compare=True,
            include_copy_symbol=True,
            include_binance_app_link=True,
            include_tradingview_link=True,
            include_home_button=True,
        )
        rows = markup["inline_keyboard"]
        self.assertTrue(rows[-3][1]["url"].startswith("https://app.binance.com/en/download?_dp="))
        self.assertIn("url", rows[-3][1])
        self.assertNotIn("web_app", rows[-3][1])

    def test_alert_keyboard_hides_copy_and_external_links_for_invalid_futures_symbol(self) -> None:
        markup = build_alert_inline_keyboard(
            symbol="USDT",
            selected_timeframe="15m",
            supported_timeframes=("1m", "5m", "15m", "1h"),
            futures_base_url="https://www.binance.com/en/futures",
            futures_app_base_url="https://app.binance.com/en/futures",
            language_code="ru",
            include_ai_analysis=True,
            include_risk_management=True,
            include_signal_reason=True,
            include_compare=True,
            include_copy_symbol=True,
            include_binance_app_link=True,
            include_tradingview_link=True,
            include_home_button=True,
        )
        rows = markup["inline_keyboard"]
        buttons = [button for row in rows for button in row]
        self.assertFalse(any(button.get("copy_text", {}).get("text") == "USDT" for button in buttons))
        self.assertFalse(any(str(button.get("url") or "").startswith("https://www.binance.com/en/futures/USDT") for button in buttons))
        self.assertFalse(any(str(button.get("url") or "").startswith("https://app.binance.com/") for button in buttons))


    def test_alert_keyboard_keeps_selected_daily_timeframe_visible(self) -> None:
        markup = build_alert_inline_keyboard(
            symbol="BTCUSDT",
            selected_timeframe="1d",
            supported_timeframes=("1m", "5m", "15m", "1h"),
            futures_base_url="https://www.binance.com/en/futures",
            language_code="en",
            include_ai_analysis=False,
            include_risk_management=False,
            include_signal_reason=False,
            include_compare=False,
            include_copy_symbol=False,
        )
        self.assertEqual([button["text"] for button in markup["inline_keyboard"][0]], ["[1d]", "1m", "5m", "15m", "1h"])

    def test_strategies_hub_lists_daily_rsi_80_strategy(self) -> None:
        callbacks = _collect_callback_data(build_strategies_hub_keyboard(language_code="en"))
        self.assertIn("strategy:open:daily_rsi_80", callbacks)

    def test_strategies_hub_lists_ekek_strategy(self) -> None:
        callbacks = _collect_callback_data(build_strategies_hub_keyboard(language_code="en"))
        self.assertIn("strategy:open:ekek", callbacks)


if __name__ == "__main__":
    unittest.main()
