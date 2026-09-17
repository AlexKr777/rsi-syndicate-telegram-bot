from __future__ import annotations

"""Stable UX action metadata for the Telegram bot.

The bot still accepts its historical compact callback payloads.  The parser
turns each payload into an ``action.kind`` and this module is the single
catalogue describing that action: where it is handled, which product service
owns it and which capability guards it.  Keeping this metadata separate from
the callback parser makes legacy compatibility explicit and lets tests reject
new keyboard buttons that have no backend route.
"""

from dataclasses import dataclass, replace
from typing import Literal


BotKind = Literal["premium", "classic"]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action_id: str
    handler: str
    service: str
    access_requirement: str = "available"
    feature_flag: str | None = None
    allowed_bot_kinds: tuple[BotKind, ...] = ("premium", "classic")
    state_requirement: str | None = None


def _spec(
    action_id: str,
    *,
    handler: str = "PrivateBotService.handle_callback_query",
    service: str = "NavigationService",
    access: str = "available",
    flag: str | None = None,
    bots: tuple[BotKind, ...] = ("premium", "classic"),
    state: str | None = None,
) -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        handler=handler,
        service=service,
        access_requirement=access,
        feature_flag=flag,
        allowed_bot_kinds=bots,
        state_requirement=state,
    )


_SPECS: dict[str, ActionSpec] = {
    # Primary navigation and product hubs.
    "menu": _spec("nav.home", handler="PrivateBotService._send_menu_hub"),
    "display_mode_view": _spec("nav.display_mode", handler="PrivateBotService._apply_display_mode"),
    "pro_hub": _spec("nav.home.pro", handler="PrivateBotService._send_pro_submenu", service="NavigationService", bots=("premium",)),
    "signalshub": _spec("signals.hub", handler="PrivateBotService._send_section_hub", service="SignalQueryService"),
    "signals": _spec("signals.list", handler="PrivateBotService._send_recent_signals", service="SignalQueryService", access="premium_or_trial"),
    "open_signal": _spec("signals.open", handler="PrivateBotService._send_selection_card", service="SignalDetailsService", access="premium_or_trial"),
    "watchhub": _spec("watchlist.hub", handler="PrivateBotService._send_watchlists_center", service="WatchlistService"),
    "watchlist": _spec("watchlist.open", handler="PrivateBotService._send_watchlist", service="WatchlistService"),
    "watch_open": _spec("watchlist.asset.open", service="WatchlistService"),
    "watch_remove": _spec("watchlist.asset.remove", service="WatchlistService"),
    "themes": _spec("watchlist.themes", service="WatchlistService"),
    "theme_all": _spec("watchlist.themes.all", service="WatchlistService"),
    "theme_builtin": _spec("watchlist.theme.apply_builtin", service="WatchlistService"),
    "theme_open": _spec("watchlist.theme.open", service="WatchlistService"),
    "theme_add": _spec("watchlist.theme.add", service="WatchlistService"),
    "theme_save": _spec("watchlist.theme.save", service="WatchlistService"),
    "theme_rename": _spec("watchlist.theme.rename", service="WatchlistService"),
    "theme_delete": _spec("watchlist.theme.delete", service="WatchlistService"),
    "results_hub": _spec("results.hub", handler="PrivateBotService._send_results_hub", service="ResultsService"),
    "results_view": _spec("results.view", service="ResultsService"),
    "results_admin": _spec("results.admin", service="ResultsService", access="admin"),
    "statshub": _spec("results.control_center", handler="PrivateBotService._send_control_center", service="ResultsService"),
    "personal_summary": _spec("results.personal", service="ResultsService"),
    "lifecycle_hub": _spec("results.lifecycle", service="ResultsService"),
    "lifecycle_view": _spec("results.lifecycle.view", service="ResultsService"),
    "compare_hub": _spec("analytics.compare", service="ResultsService"),
    "compare_view": _spec("analytics.compare.view", service="ResultsService"),
    "compare_admin": _spec("analytics.compare.admin", service="ResultsService", access="admin"),
    "learn_hub": _spec("help.learning", service="NavigationService"),
    "learn_page": _spec("help.learning.page", service="NavigationService"),
    "learn_guide": _spec("help.strategy_guide", service="NavigationService"),
    "help": _spec("help.open", handler="PrivateBotService._send_help", service="NavigationService"),
    "help_page": _spec("help.page", handler="PrivateBotService._send_help_page", service="NavigationService"),
    "onboarding_example": _spec("help.example_signal", service="NavigationService"),
    "onboarding_read": _spec("help.read_signal", service="NavigationService"),
    "access": _spec("access.open", handler="PrivateBotService._send_access", service="AccessService"),
    "pay": _spec("access.pay", handler="PrivateBotService._send_payment_offer", service="AccessService", flag="CRYPTO_PAY_ENABLED"),
    "renew": _spec("access.renew", handler="PrivateBotService._send_payment_offer", service="AccessService", flag="CRYPTO_PAY_ENABLED"),
    "referral": _spec("access.referral", service="AccessService"),
    "status": _spec("system.status", service="NavigationService"),
    "health": _spec("system.health", service="NavigationService", access="admin"),
    "settingshub": _spec("settings.hub", handler="PrivateBotService._send_settings_center", service="NavigationService"),
    "deliveryhub": _spec("delivery.hub", handler="PrivateBotService._send_delivery_center", service="DeliverySettingsService"),
    "delivery_mode": _spec("delivery.mode.update", service="DeliverySettingsService"),
    "delivery_rules_hub": _spec("delivery.rules", service="DeliverySettingsService"),
    "delivery_rule_view": _spec("delivery.rule.view", service="DeliverySettingsService"),
    "delivery_rule_set": _spec("delivery.rule.update", service="DeliverySettingsService"),
    "snooze": _spec("delivery.snooze", service="DeliverySettingsService"),
    "quiet_hours": _spec("delivery.quiet_hours", service="DeliverySettingsService"),
    "toggle": _spec("delivery.toggle", service="DeliverySettingsService"),
    "recap": _spec("delivery.recap", service="DeliverySettingsService"),
    "goldhub": _spec("gold.open", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED"),
    "goldview": _spec("gold.view", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED"),
    "gold": _spec("gold.update", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED"),
    "gold_wizard_start": _spec("gold.flow.start", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "gold_wizard_set": _spec("gold.flow.update", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "gold_wizard_next": _spec("gold.flow.next", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "gold_wizard_back": _spec("gold.flow.back", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "gold_wizard_cancel": _spec("gold.flow.cancel", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "gold_wizard_apply": _spec("gold.flow.apply", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", state="gold_wizard"),
    "analyze": _spec("ai.request", handler="PrivateBotService._send_analyze_symbol", service="AIAnalysisService", access="premium_or_trial"),
    "ai": _spec("ai.open", service="AIAnalysisService", access="premium_or_trial"),
    "aihub": _spec("ai.hub", handler="PrivateBotService._send_section_hub", service="AIAnalysisService", access="premium_or_trial"),
    "pro": _spec("access.pro_offer", service="AccessService"),
    "control": _spec("system.control", service="NavigationService", access="admin"),
    "guide": _spec("help.guide", service="NavigationService"),

    # Flow / setup compatibility surface.  These keep historical callback
    # payloads usable while V2 exposes the same stored entity as "My flows".
    "setup": _spec("flow.hub", service="UserFlowService"),
    "setupshub": _spec("flow.hub", handler="PrivateBotService._send_setups_hub", service="UserFlowService"),
    "setup_list": _spec("flow.list", handler="PrivateBotService._send_saved_setups_list", service="UserFlowService"),
    "setup_create": _spec("flow.create", service="UserFlowService"),
    "setup_savecurrent": _spec("flow.save_current", service="UserFlowService"),
    "setup_pinned": _spec("flow.list.pinned", service="UserFlowService"),
    "setup_detail": _spec("flow.details", service="UserFlowService"),
    "setup_activate": _spec("flow.apply", service="UserFlowService"),
    "setup_edit": _spec("flow.edit", service="UserFlowService"),
    "setup_update": _spec("flow.update", service="UserFlowService"),
    "setup_rename": _spec("flow.rename", service="UserFlowService"),
    "setup_duplicate": _spec("flow.duplicate", service="UserFlowService"),
    "setup_delete": _spec("flow.delete", service="UserFlowService"),
    "setup_default": _spec("flow.default", service="UserFlowService"),
    "setup_pin": _spec("flow.pin", service="UserFlowService"),
    "setup_builder_start": _spec("flow.builder.start", service="UserFlowService", state="flow_builder"),
    "setup_builder_template": _spec("flow.builder.template", service="UserFlowService", state="flow_builder"),
    "setup_builder_prompt": _spec("flow.builder.prompt", service="UserFlowService", state="flow_builder"),
    "setup_builder_set": _spec("flow.builder.set", service="UserFlowService", state="flow_builder"),
    "setup_builder_toggle": _spec("flow.builder.toggle", service="UserFlowService", state="flow_builder"),
    "setup_builder_next": _spec("flow.builder.next", service="UserFlowService", state="flow_builder"),
    "setup_builder_back": _spec("flow.builder.back", service="UserFlowService", state="flow_builder"),
    "setup_builder_cancel": _spec("flow.builder.cancel", service="UserFlowService", state="flow_builder"),
    "setup_builder_save": _spec("flow.builder.save", service="UserFlowService", state="flow_builder"),
    "workspacehub": _spec("flow.legacy_workspace", service="UserFlowService"),
    "workspace_save": _spec("flow.legacy_workspace.save", service="UserFlowService"),
    "workspace_apply": _spec("flow.legacy_workspace.apply", service="UserFlowService"),
    "quickfiltershub": _spec("flow.quality", service="UserFlowService"),
    "quickfilter_apply": _spec("flow.quality.apply", service="UserFlowService"),
    "quickfilter_reset": _spec("flow.quality.reset", service="UserFlowService"),
    "custom_filters_hub": _spec("flow.filters", service="UserFlowService"),
    "noisehub": _spec("flow.noise", service="UserFlowService"),
    "noise_set": _spec("flow.noise.update", service="UserFlowService"),
    "scorehub": _spec("flow.score", service="UserFlowService"),
    "score_set": _spec("flow.score.update", service="UserFlowService"),
    "sessionhub": _spec("flow.session", service="UserFlowService"),
    "session_set": _spec("flow.session.update", service="UserFlowService"),
    "hide_mute_hub": _spec("flow.exclusions", service="UserFlowService"),
    "hide_asset_prompt": _spec("flow.exclusions.asset.prompt", service="UserFlowService"),
    "hide_mute_view": _spec("flow.exclusions.view", service="UserFlowService"),
    "hide_mute_toggle": _spec("flow.exclusions.toggle", service="UserFlowService"),
    "hide_strategy": _spec("flow.exclusions.strategy", service="UserFlowService"),
    "hide_timeframe": _spec("flow.exclusions.timeframe", service="UserFlowService"),
    "hide_repeats": _spec("flow.exclusions.repeats", service="UserFlowService"),
    "hide_mute_resume": _spec("flow.exclusions.resume", service="UserFlowService"),
    "style_hub": _spec("flow.style", service="UserFlowService"),
    "style_view": _spec("flow.style.view", service="UserFlowService"),
    "style_set": _spec("flow.style.update", service="UserFlowService"),
    "style_save": _spec("flow.style.save", service="UserFlowService"),
    "profile": _spec("flow.profile", service="UserFlowService"),
    "strategy_pref": _spec("flow.strategy.preference", service="UserFlowService"),
    "rsi": _spec("flow.rsi_mode", service="UserFlowService"),
    "volume": _spec("flow.liquidity", service="UserFlowService"),
    "direction": _spec("flow.direction", service="UserFlowService"),
    "universe": _spec("flow.market_scope", service="UserFlowService"),
    "strategies": _spec("flow.strategies", service="UserFlowService"),
    "strategy_open": _spec("flow.strategy.open", service="UserFlowService"),
    "strategy_toggle": _spec("flow.strategy.toggle", service="UserFlowService"),
    "strategy_signals": _spec("flow.strategy.signals", service="UserFlowService"),
    "strategy_filters": _spec("flow.strategy.filters", service="UserFlowService"),
    "strategy_alerts": _spec("flow.strategy.alerts", service="UserFlowService"),
    "strategy_favorites": _spec("flow.strategy.favorites", service="UserFlowService"),
    "strategy_quicksetup": _spec("flow.strategy.quick_setup", service="UserFlowService"),
    "strategy_results": _spec("flow.strategy.results", service="UserFlowService"),
    "strategy_guide": _spec("flow.strategy.guide", service="UserFlowService"),
    "strategy_settings": _spec("flow.strategy.settings", service="UserFlowService"),
    "strategy_compare": _spec("flow.strategy.compare", service="UserFlowService"),
    "strategy_lifecycle": _spec("flow.strategy.lifecycle", service="UserFlowService"),

    # User onboarding and localisation.
    "onboard": _spec("onboarding.choice", service="UserFlowService", state="onboarding"),
    "custom": _spec("onboarding.custom_input", service="UserFlowService", state="onboarding"),
    "language_picker": _spec("settings.language.open", service="NavigationService"),
    "language_set": _spec("settings.language.set", handler="PrivateBotService._apply_language_choice", service="NavigationService"),
}

_SPECS.update(
    {
        "v2_home_simple": _spec("nav.home.simple", handler="PrivateBotService._send_v2_home"),
        "v2_home_pro": _spec("nav.home.pro", handler="PrivateBotService._send_v2_home", bots=("premium",)),
        "v2_onboarding_style": _spec("onboarding.style", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_market": _spec("onboarding.market", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_quality": _spec("onboarding.quality", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_delivery": _spec("onboarding.delivery", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_back": _spec("onboarding.back", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_confirm": _spec("onboarding.confirm", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_onboarding_cancel": _spec("onboarding.cancel", handler="PrivateBotService._handle_v2_action", service="UserFlowService", state="onboarding"),
        "v2_signals_best": _spec("signals.list.best", handler="PrivateBotService._handle_v2_action", service="SignalQueryService"),
        "v2_signals_new": _spec("signals.list.new", handler="PrivateBotService._handle_v2_action", service="SignalQueryService"),
        "v2_signals_watchlist": _spec("signals.list.watchlist", handler="PrivateBotService._handle_v2_action", service="SignalQueryService"),
        "v2_signals_all": _spec("signals.list.all", handler="PrivateBotService._handle_v2_action", service="SignalQueryService"),
        "v2_signals_strategy": _spec("signals.list.strategy", handler="PrivateBotService._handle_v2_action", service="SignalQueryService"),
        "v2_signal_open": _spec("signals.open", handler="PrivateBotService._handle_v2_action", service="SignalDetailsService", access="premium_or_trial"),
        "v2_strategies_hub": _spec("strategies.hub", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_open": _spec("strategies.open", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_toggle": _spec("strategies.toggle", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_settings": _spec("strategies.settings", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_delivery": _spec("strategies.delivery.update", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_quality": _spec("strategies.quality.update", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_compare": _spec("strategies.compare", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_strategies_guide": _spec("strategies.guide", handler="PrivateBotService._handle_v2_action", service="StrategyService"),
        "v2_flow_hub": _spec("flow.hub", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_style": _spec("flow.style", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_style_preview": _spec("flow.style.preview", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_style_apply": _spec("flow.style.apply", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_assets": _spec("flow.assets", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_assets_apply": _spec("flow.assets.apply", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_assets_manual": _spec("flow.assets.manual", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_quality": _spec("flow.quality", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_quality_apply": _spec("flow.quality.apply", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flow_reset": _spec("flow.reset", handler="PrivateBotService._handle_v2_action", service="UserFlowService"),
        "v2_flows_hub": _spec("flows.hub", handler="PrivateBotService._handle_v2_action", service="UserFlowService", bots=("premium",)),
        "v2_flows_list": _spec("flows.list", handler="PrivateBotService._handle_v2_action", service="UserFlowService", bots=("premium",)),
        "v2_notifications_hub": _spec("delivery.open", handler="PrivateBotService._handle_v2_action", service="DeliverySettingsService"),
        "v2_notifications_toggle": _spec("delivery.update", handler="PrivateBotService._handle_v2_action", service="DeliverySettingsService"),
        "v2_notifications_delivery": _spec("delivery.mode.update", handler="PrivateBotService._handle_v2_action", service="DeliverySettingsService"),
        "v2_notifications_snooze": _spec("delivery.snooze", handler="PrivateBotService._handle_v2_action", service="DeliverySettingsService"),
        "v2_settings_hub": _spec("settings.hub", handler="PrivateBotService._handle_v2_action", service="NavigationService"),
        "v2_results_hub": _spec("results.hub", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_today": _spec("results.today", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_week": _spec("results.week", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_strategies": _spec("results.strategies", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_lifecycle": _spec("results.lifecycle", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_recent": _spec("results.recent", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_methodology": _spec("results.methodology", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_results_diagnostics": _spec("results.diagnostics", handler="PrivateBotService._handle_v2_action", service="ResultsService"),
        "v2_watchlist_hub": _spec("watchlist.open", handler="PrivateBotService._handle_v2_action", service="WatchlistService"),
        "v2_watchlist_manage": _spec("watchlist.manage", handler="PrivateBotService._handle_v2_action", service="WatchlistService"),
        "v2_access_hub": _spec("access.open", handler="PrivateBotService._handle_v2_action", service="AccessService"),
        "v2_help_hub": _spec("help.open", handler="PrivateBotService._handle_v2_action", service="NavigationService"),
        "v2_analytics_hub": _spec("analytics.hub", handler="PrivateBotService._handle_v2_action", service="AIAnalysisService", bots=("premium",)),
        "v2_analytics_analyze": _spec("analytics.asset.open", handler="PrivateBotService._handle_v2_action", service="AIAnalysisService", bots=("premium",)),
        "v2_market_hub": _spec("market.hub", handler="PrivateBotService._handle_v2_action", service="WatchlistService", bots=("premium",)),
        "v2_market_sets": _spec("market.sets", handler="PrivateBotService._handle_v2_action", service="WatchlistService", bots=("premium",)),
        "v2_market_set": _spec("market.set.apply", handler="PrivateBotService._handle_v2_action", service="WatchlistService", bots=("premium",)),
        "v2_gold_hub": _spec("gold.open", handler="PrivateBotService._handle_v2_action", service="GoldFlowService", flag="GOLD_ALERTS_ENABLED", bots=("premium",)),
        "v2_nav_back": _spec("nav.back", handler="PrivateBotService._handle_v2_action", service="NavigationService"),
    }
)

# V2 is an intentionally Premium-only presentation surface. Keeping this
# restriction in the registry lets the callback dispatcher reject forged V2
# payloads when they reach the Classic bot.
for _kind, _action_spec in tuple(_SPECS.items()):
    if _kind.startswith("v2_"):
        _SPECS[_kind] = replace(_action_spec, allowed_bot_kinds=("premium",))


def action_spec_for(kind: str | None) -> ActionSpec | None:
    """Return registered metadata for a parsed callback action."""

    return _SPECS.get(str(kind or ""))


def registered_action_kinds() -> frozenset[str]:
    return frozenset(_SPECS)
