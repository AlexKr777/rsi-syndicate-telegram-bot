from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from src.bot.formatters import format_interactive_analysis_message
from src.bot.inline_keyboards import (
    build_alert_inline_keyboard,
    build_detail_card_keyboard,
    build_detail_card_keyboard_with_action,
)
from src.bot.routing import MessageRouter
from src.bot.telegram_client import TelegramClient
from src.bot.interactive_alerts import InteractiveAlertService
from src.analysis.historical_resistance import analyze_historical_resistance
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.followup_logic import evaluate_thesis_result, summarize_followup
from src.core.models import AlertSignal, FollowUpResult
from src.core.strategy_keys import (
    EKEK_STRATEGY_KEY,
    GOLD_MASTER_STRATEGY_KEY,
    GOLD_SUBSTRATEGY_KEYS,
    GOLD_SUBSTRATEGY_KEY_SET,
    OKAK_STRATEGY_KEY,
    PREMIUM_STRATEGY_KEYS,
    VISIBLE_PREMIUM_STRATEGY_KEYS,
)
from src.core.utils import escape_html, format_volume, local_day_bounds, normalize_symbol, utc_now
from src.localization import normalize_language, toggle_language, ui_text
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.referrals.service import ReferralService
from src.signals.service import SignalLifecycleService
from src.storage.models import (
    AlertRecord,
    DeliveredSignalRecord,
    FollowUpResultRecord,
    PremiumStrategySettingsRecord,
    PrivateBotUserRecord,
    SignalLifecycleRecord,
    StrategyStatsSnapshotRecord,
    UserSavedSetupRecord,
    UserSettingsRecord,
    UserStyleProfileRecord,
)
from src.storage.repository import Repository
from src.userbot.action_registry import action_spec_for
from src.userbot.access_view import build_access_view_model
from src.userbot.callbacks import UserBotCallbackAction, parse_userbot_callback_data
from src.userbot.admin_monitoring import AdminMonitoringService
from src.userbot.experience import (
    BUILTIN_WATCHLIST_THEMES,
    build_control_center_metrics,
    display_mode_label,
    delivery_mode_label,
    format_digest_message,
    format_gold_center_message,
    format_quiet_hours_window,
    format_recap_message,
    format_resume_message,
    is_snoozed,
    is_within_quiet_hours,
    tracking_scope_label,
    watchlist_theme_label,
)
from src.userbot.formatters import (
    format_access_message,
    format_admin_health_message,
    format_analyze_symbol_message,
    format_custom_signal_setup_message,
    format_custom_signal_setup_saved_message,
    format_empty_signals_message,
    format_example_signal_message,
    format_first_start_message,
    format_help_page_message,
    format_help_message,
    format_menu_panel_message,
    format_pro_link_message,
    format_signal_reading_guide_message,
    format_signal_setup_message,
    format_start_message,
    format_status_message,
    format_watchlist_message,
)
from src.userbot.onboarding_flow import (
    apply_quiet_hours_preset,
    empty_onboarding_draft,
    format_onboarding_message,
    format_onboarding_summary_message,
    next_onboarding_step,
    onboarding_steps,
    parse_favorite_symbols_input,
    previous_onboarding_step,
    resolve_quick_setup_strategy_key,
    strategy_preset_label,
    strategy_quick_setup_label,
    strategy_symbol_suggestions,
    strategy_supports_rsi_mode,
    strategy_supports_universe,
    strategy_supports_volume,
)
from src.userbot.personalization import (
    PersonalFilterDecision,
    PersonalSummaryData,
    asset_scope_summary,
    apply_quick_filter_preset,
    build_style_title_summary,
    clear_quick_filters,
    default_delivery_rules,
    default_personalization,
    infer_asset_scope_from_payload,
    default_style_preferences,
    evaluate_personal_filters,
    humanize_filter_reason,
    normalize_asset_scope_payload,
    normalize_asset_scope_type,
    normalize_delivery_rules,
    normalize_personalization,
    normalize_style_preferences,
    resolve_delivery_route,
    session_label_for_datetime,
    summarize_setup_payload,
)
from src.userbot.personalization_ui import (
    build_admin_health_keyboard,
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
    build_pro_submenu_keyboard,
    build_quick_filters_keyboard,
    build_repeat_mute_keyboard,
    build_saved_setups_keyboard,
    build_score_filter_keyboard,
    build_session_filter_keyboard,
    build_setup_detail_keyboard,
    build_setups_hub_keyboard,
    build_style_dimension_keyboard,
    build_style_profile_keyboard,
    format_delivery_rule_options_message,
    format_delivery_rules_message,
    format_hide_mute_message,
    format_noise_level_message,
    format_personal_summary_message,
    format_pro_submenu_message,
    format_quick_filters_message,
    format_saved_setups_message,
    format_score_filter_message,
    format_session_filter_message,
    format_setup_detail_message,
    format_setups_hub_message,
    format_style_dimension_message,
    format_style_profile_message,
)
from src.userbot.stabilization_ui import (
    build_create_setup_entry_keyboard,
    build_custom_filters_hub_keyboard,
    build_gold_wizard_keyboard,
    build_setup_template_picker_keyboard,
    build_truthful_setups_hub_keyboard,
    format_create_setup_entry_message,
    format_custom_filters_hub_message,
    format_gold_wizard_message,
    format_setup_template_picker_message,
)
from src.userbot.setup_builder_ui import build_setup_builder_keyboard, format_setup_builder_message
from src.userbot.polished_experience import (
    format_control_center_message,
    format_delivery_center_message,
    format_scoped_delivery_center_message,
    format_section_hub,
    format_settings_center_message,
    format_watchlists_message,
    format_workspace_center_message,
)
from src.userbot.keyboards import (
    build_access_inline_keyboard,
    build_analyze_symbol_inline_keyboard,
    build_admin_stats_keyboard,
    build_channel_inline_keyboard,
    build_collapsed_menu_keyboard,
    build_compare_hub_keyboard,
    build_custom_setup_inline_keyboard,
    build_empty_signals_keyboard,
    build_example_signal_keyboard,
    build_gold_hub_keyboard,
    build_guided_start_keyboard,
    build_help_more_inline_keyboard,
    build_hidden_menu_keyboard,
    build_language_picker_inline_keyboard,
    build_learn_hub_keyboard,
    build_lifecycle_hub_keyboard,
    build_main_menu_keyboard,
    build_menu_hub_inline_keyboard,
    build_onboarding_step_keyboard,
    build_onboarding_inline_keyboard,
    build_product_strategy_hub_keyboard,
    build_help_inline_keyboard,
    build_referral_inline_keyboard,
    build_results_hub_keyboard,
    build_section_hub_keyboard,
    build_settings_center_keyboard,
    build_signal_reading_keyboard,
    build_strategies_hub_keyboard,
    build_strategy_guide_inline_keyboard,
    build_strategy_guides_keyboard,
    build_strategy_selector_inline_keyboard,
    build_strategy_hub_keyboard,
    build_status_inline_keyboard,
    build_signal_setup_inline_keyboard,
    build_watchlist_themes_keyboard,
    build_watchlist_inline_keyboard,
    build_workspace_center_keyboard,
)
from src.userbot.product import CompareService, LearnService, MessageRenderService, RoleGuardService
from src.userbot.navigation_state import NavigationRoute, NavigationService
from src.userbot.performance import PerformanceTelemetryService, RouteTiming
from src.userbot.results_service import ResultsService
from src.userbot.premium_text import premium_text
from src.userbot.strategy_preferences import (
    normalize_strategy_preferences,
    strategy_allowed_timeframes,
    strategy_followup_priority,
    strategy_market_filter,
    strategy_preference_controls,
    strategy_preference_defaults,
)
from src.userbot.ux_v2 import (
    build_analytics_keyboard,
    build_assets_keyboard,
    build_flow_keyboard,
    build_flows_keyboard,
    build_gold_keyboard,
    build_help_keyboard as build_v2_help_keyboard,
    build_home_keyboard as build_v2_home_keyboard,
    build_market_keyboard,
    build_market_sets_keyboard,
    build_notifications_keyboard,
    build_onboarding_keyboard as build_v2_onboarding_keyboard,
    build_quality_keyboard,
    build_results_keyboard as build_v2_results_keyboard,
    build_strategies_keyboard as build_v2_strategies_keyboard,
    build_strategy_keyboard as build_v2_strategy_keyboard,
    build_strategy_settings_keyboard as build_v2_strategy_settings_keyboard,
    build_settings_keyboard as build_v2_settings_keyboard,
    build_signal_empty_keyboard,
    build_signal_list_keyboard,
    build_style_keyboard,
    build_style_preview_keyboard,
    build_watchlist_keyboard as build_v2_watchlist_keyboard,
    choice_label as v2_choice_label,
    format_flow_message as format_v2_flow_message,
    format_home_message as format_v2_home_message,
    format_results_message as format_v2_results_message,
    format_strategies_message as format_v2_strategies_message,
    format_strategy_message as format_v2_strategy_message,
    format_strategy_settings_message as format_v2_strategy_settings_message,
    format_market_sets_message as format_v2_market_sets_message,
    format_hub_message as format_v2_hub_message,
    format_invalid_symbols_message,
    format_notifications_message as format_v2_notifications_message,
    format_onboarding_message as format_v2_onboarding_message,
    format_assets_choice_message,
    format_quality_choice_message,
    format_signal_empty_message as format_v2_signal_empty_message,
    format_signal_list_message as format_v2_signal_list_message,
    format_settings_message,
    format_style_choice_message,
    format_style_preview as format_v2_style_preview,
    style_preview_summary as v2_style_preview_summary,
)

LOGGER = logging.getLogger(__name__)

PREMIUM_STRATEGY_DEFAULT_MIN_SCORES: dict[str, int] = {
    "okak": 90,
    EKEK_STRATEGY_KEY: 90,
    "daily_rsi_80": 68,
    "bollinger": 48,
    "rsi_bollinger_touch": 64,
    "rsi_divergence": 68,
}
ADMIN_REVERSAL_ROLLOUT_MARKER = "reversal_pack_v1"
ADMIN_REVERSAL_ROLLOUT_STRATEGIES = ("bollinger", "rsi_bollinger_touch", "rsi_divergence")

if TYPE_CHECKING:
    from src.payments.onboarding import EffectiveAccessState, OnboardingPaymentService


@dataclass(frozen=True, slots=True)
class _PrivateSelection:
    alert: AlertRecord
    followup: FollowUpResultRecord | None


@dataclass(frozen=True, slots=True)
class _PrivateDeliveryDecision:
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class _SignalSetupState:
    profile: str
    profile_label: str
    base_profile: str
    base_profile_label: str
    min_score: int
    min_quote_volume: float
    rsi_oversold: float
    rsi_overbought: float
    rsi_mode: str
    rsi_mode_label: str
    direction_filter: str
    direction_label: str
    watchlist_only: bool


@dataclass(slots=True)
class _CustomSetupSession:
    chat_id: str
    prompt_message_id: int | None
    step: str
    rsi_oversold: float
    rsi_overbought: float
    min_quote_volume: float
    min_score: int
    direction_filter: str


@dataclass(slots=True)
class _ThemePromptSession:
    action: str
    theme_id: int | None = None
    theme_name: str | None = None


@dataclass(slots=True)
class _PersonalizationPromptSession:
    action: str
    target_id: int | None = None
    name: str | None = None


@dataclass(slots=True)
class _DeliveredAlertBundle:
    deliveries: list[DeliveredSignalRecord]
    alerts_by_id: dict[int, AlertRecord]
    followups_by_alert_id: dict[int, FollowUpResultRecord]


class PrivateBotService:
    CHAT_CLEANUP_CONTENT_KIND = "chat_cleanup"
    CHAT_CLEANUP_MESSAGE_KIND = "ui"
    EVENING_FOLLOWUP_TOP_SLOT_HOURS = (18, 21)
    EVENING_FOLLOWUP_TOPS_PER_SLOT = 2
    ADMIN_AUDIT_DIGEST_COOLDOWN_MINUTES = 90
    ADMIN_AUDIT_DIGEST_ITEM_LIMIT = 3
    FUNNEL_EVENT_NAMES = frozenset(
        {
            "start_seen",
            "language_picker_seen",
            "language_selected",
            "onboarding_started",
            "onboarding_step_completed",
            "onboarding_completed",
            "welcome_seen",
            "trial_explained",
            "risk_seen",
            "guided_menu_seen",
            "example_signal_opened",
            "how_to_read_opened",
            "strong_setups_opened",
            "no_signals_empty_seen",
            "my_access_opened",
            "classic_vs_pro_opened",
            "help_opened",
            "support_opened",
        }
    )
    STRATEGY_KEYS = PREMIUM_STRATEGY_KEYS
    PROFILE_LABELS = {
        "conservative": "Conservative",
        "balanced": "Balanced",
        "aggressive": "Aggressive",
        "custom": "Custom",
    }
    RSI_MODE_LABELS = {
        "tight": "Tight",
        "balanced": "Balanced",
        "early": "Early",
        "custom": "Custom",
    }
    DIRECTION_LABELS = {
        "both": "Both sides",
        "long": "Long only",
        "short": "Short only",
    }
    RSI_MODE_THRESHOLDS = {
        "tight": (27.0, 73.0),
        "balanced": (30.0, 70.0),
        "early": (33.0, 67.0),
    }
    _USER_CACHE_TTL_SECONDS = 8.0
    OKAK_ALLOWED_TELEGRAM_USER_IDS = frozenset({5846358885, 901375482})
    LOOKUP_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
    SETUP_BUILDER_TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d")
    SETUP_BUILDER_STEPS = ("name", "scope", "strategies", "timeframes", "direction", "session", "selectivity", "delivery", "review")
    GOLD_WIZARD_STEPS = ("mode", "direction", "tempo", "session", "followups", "delivery", "review")
    WATCHLIST_LIMIT = 20
    _LOOKUP_SUFFIXES = ("PERPETUAL", "PERP", "SWAP", "FUTURES", "FUT")
    _WATCHLIST_SYMBOL_PATTERN = r"[A-Za-z0-9:./_\- ]{1,40}"

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        telegram_client: TelegramClient,
        router: MessageRouter,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        interactive_alert_service: InteractiveAlertService,
        *,
        bot_kind: str = "premium",
        destination_kind: str = "private",
        content_kind: str = "private_pro",
        onboarding_service: OnboardingPaymentService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.telegram_client = telegram_client
        self.router = router
        self.binance_client = binance_client
        self.chart_renderer = chart_renderer
        self.interactive_alert_service = interactive_alert_service
        self._custom_setup_sessions: dict[int, _CustomSetupSession] = {}
        self._theme_prompt_sessions: dict[int, _ThemePromptSession] = {}
        self._personalization_prompt_sessions: dict[int, _PersonalizationPromptSession] = {}
        self._user_cache: dict[int, tuple[float, PrivateBotUserRecord]] = {}
        self._hub_origin_context: dict[tuple[int, str], str] = {}
        self._screen_back_context: dict[tuple[int, str], str] = {}
        self._v2_home_route_by_user: dict[int, str] = {}
        self._strategy_guide_message_ids: dict[int, int] = {}
        self.signal_lifecycle_service = SignalLifecycleService(repository)
        self.results_service = ResultsService(repository)
        self.navigation_service = NavigationService()
        self.performance_telemetry_service = PerformanceTelemetryService()
        self.admin_monitoring_service = AdminMonitoringService(repository)
        self.role_guard = RoleGuardService()
        self.compare_service = CompareService()
        self.learn_service = LearnService()
        self.message_render_service = MessageRenderService()
        self.bot_kind = bot_kind
        self.destination_kind = destination_kind
        self.content_kind = content_kind
        self.onboarding_service = onboarding_service
        self.referral_service = ReferralService(
            settings,
            repository,
            telegram_client=telegram_client,
        )

    def _profile_defaults(self, profile: str) -> tuple[int, float, float, float]:
        normalized = (profile or "balanced").strip().lower()
        if self.bot_kind == "classic":
            defaults = {
                "conservative": (84, 12_000_000.0, 27.0, 73.0),
                "aggressive": (72, 3_000_000.0, 33.0, 67.0),
            }
            return defaults.get(normalized, (78, 8_000_000.0, 30.0, 70.0))
        defaults = {
            "conservative": (88, 10_000_000.0, 27.0, 73.0),
            "aggressive": (74, 1_000_000.0, 33.0, 67.0),
        }
        return defaults.get(normalized, (82, 5_000_000.0, 30.0, 70.0))

    def _language_code(self, settings: UserSettingsRecord | None) -> str:
        return normalize_language(settings.language_code if settings is not None else None)

    def _get_cached_settings(self, telegram_user_id: int) -> UserSettingsRecord | None:
        del telegram_user_id
        return None

    def _store_cached_settings(self, settings: UserSettingsRecord) -> UserSettingsRecord:
        return settings

    def _drop_cached_settings(self, telegram_user_id: int) -> None:
        del telegram_user_id

    def _get_cached_user(self, telegram_user_id: int) -> PrivateBotUserRecord | None:
        entry = self._user_cache.get(telegram_user_id)
        if entry is None:
            return None
        cached_at, user = entry
        if monotonic() - cached_at > self._USER_CACHE_TTL_SECONDS:
            self._user_cache.pop(telegram_user_id, None)
            return None
        return user

    def _store_cached_user(self, user: PrivateBotUserRecord) -> PrivateBotUserRecord:
        self._user_cache[user.telegram_user_id] = (monotonic(), user)
        return user

    async def _get_private_user(self, telegram_user_id: int) -> PrivateBotUserRecord | None:
        cached = self._get_cached_user(telegram_user_id)
        if cached is not None:
            return cached
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            return None
        return self._store_cached_user(user)

    def _normalized_private_username(self, user: PrivateBotUserRecord | None) -> str:
        return str(user.username or "").strip().lstrip("@").casefold() if user is not None else ""

    def _okak_historical_variant_for_user(self, user: PrivateBotUserRecord | None) -> str | None:
        if user is None:
            return None
        username = self._normalized_private_username(user)
        if user.telegram_user_id == 5846358885 or username == "dordo_dordo":
            return "detailed"
        if user.telegram_user_id == 901375482 or username == "ifritian":
            return "focus"
        return None

    async def _build_okak_historical_resistance_metadata(self, signal: AlertSignal) -> dict[str, object] | None:
        current_price = (
            float(signal.metadata["live_price"])
            if isinstance(signal.metadata.get("live_price"), (int, float))
            else float(signal.price)
        )
        klines_1h_limit = max(int(self.settings.klines_limit), 320)
        klines_4h_limit = max(int(self.settings.klines_limit), 240)
        frame_1h, frame_4h = await asyncio.gather(
            self.binance_client.get_klines(normalize_symbol(signal.symbol), "1h", klines_1h_limit),
            self.binance_client.get_klines(normalize_symbol(signal.symbol), "4h", klines_4h_limit),
        )
        analysis = analyze_historical_resistance(
            {
                "1h": frame_1h,
                "4h": frame_4h,
            },
            current_price=current_price,
            rsi_length=self.settings.rsi_length,
        )
        zone = analysis.zone
        metadata: dict[str, object] = {
            "historical_resistance_available": zone is not None,
        }
        highest_peak_touch = analysis.highest_peak_touch
        if highest_peak_touch is not None:
            metadata.update(
                {
                    "historical_resistance_highest_peak_price": highest_peak_touch.price,
                    "historical_resistance_highest_peak_timeframe": highest_peak_touch.timeframe,
                    "historical_resistance_highest_peak_distance_pct": (
                        ((highest_peak_touch.price - current_price) / current_price) * 100.0
                    ),
                }
            )
        if zone is None:
            return metadata
        metadata.update(
            {
                "historical_resistance_zone_low": zone.zone_low,
                "historical_resistance_zone_high": zone.zone_high,
                "historical_resistance_zone_price": zone.zone_price,
                "historical_resistance_distance_pct": zone.distance_pct,
                "historical_resistance_touch_count": zone.touch_count,
                "historical_resistance_strong_rejections": zone.strong_rejections,
                "historical_resistance_avg_rejection_pct": zone.avg_rejection_pct,
                "historical_resistance_avg_impulse_pct": zone.avg_impulse_pct,
                "historical_resistance_quality": zone.quality,
                "historical_resistance_confidence": zone.confidence,
                "historical_resistance_timeframes": list(zone.timeframes),
            }
        )
        return metadata

    async def _enrich_okak_signal_for_private_user(
        self,
        signal: AlertSignal,
        *,
        user: PrivateBotUserRecord | None,
    ) -> AlertSignal:
        if self.bot_kind != "premium" or self.destination_kind != "private":
            return signal
        if self._signal_strategy_key(signal) not in {OKAK_STRATEGY_KEY, EKEK_STRATEGY_KEY}:
            return signal
        variant = self._okak_historical_variant_for_user(user)
        if variant is None:
            return signal
        try:
            historical_metadata = await self._build_okak_historical_resistance_metadata(signal)
        except Exception:
            LOGGER.exception(
                "OKAK historical resistance enrichment failed user=%s symbol=%s",
                user.telegram_user_id if user is not None else "unknown",
                signal.symbol,
            )
            return signal
        return replace(
            signal,
            metadata={
                **signal.metadata,
                **(historical_metadata or {}),
                "historical_resistance_variant": variant,
            },
        )

    def _matches_ui_label(self, normalized_text: str, key: str) -> bool:
        return normalized_text in {
            ui_text("en", key).casefold(),
            ui_text("ru", key).casefold(),
        }

    def _matches_premium_label(self, normalized_text: str, key: str) -> bool:
        return normalized_text in {
            premium_text("en", key).casefold(),
            premium_text("ru", key).casefold(),
        }

    def _strategy_label(self, strategy_key: str, *, language_code: str) -> str:
        language = normalize_language(language_code)
        labels = {
            "breakout": ("Breakout", "Пробой уровня"),
            "trend_pullback": ("Trend Pullback", "Откат по тренду"),
            "rsi_bollinger_mr": ("RSI + Bollinger MR", "RSI + Bollinger MR"),
            "rsi_bollinger_touch": ("RSI + Bollinger Touch", "RSI + Bollinger Touch"),
            "daily_rsi_80": ("Daily RSI 80+", "Daily RSI 80+"),
            "vwap": ("VWAP", "VWAP"),
            "false_breakout": ("False Breakout", "Ложный пробой"),
            "rsi": ("RSI", "RSI"),
            "rsi_divergence": ("RSI Divergence", "RSI Divergence"),
            OKAK_STRATEGY_KEY: ("OKAK", "OKAK"),
            EKEK_STRATEGY_KEY: ("EKEK", "EKEK"),
            "bollinger": ("Bollinger", "Боллинджер"),
            "gold": ("Gold / XAUUSD", "Золото / XAUUSD"),
            "gold_breakout": ("Gold Breakout", "Gold Breakout"),
            "gold_pullback": ("Gold Pullback", "Gold Pullback"),
            "gold_liquidity": ("Gold Liquidity", "Gold Liquidity"),
        }
        english, russian = labels.get(strategy_key, labels["rsi"])
        return russian if language == "ru" else english

    def _strategy_accessible_for_user_id(self, telegram_user_id: int | None, strategy_key: str | None) -> bool:
        normalized = str(strategy_key or "").strip().lower()
        if normalized not in self.STRATEGY_KEYS:
            return False
        if normalized == OKAK_STRATEGY_KEY:
            return telegram_user_id in self.OKAK_ALLOWED_TELEGRAM_USER_IDS
        return True

    def _visible_strategy_keys(
        self,
        settings: UserSettingsRecord | None = None,
        *,
        telegram_user_id: int | None = None,
    ) -> tuple[str, ...]:
        user_id = telegram_user_id if telegram_user_id is not None else getattr(settings, "telegram_user_id", None)
        keys = list(VISIBLE_PREMIUM_STRATEGY_KEYS)
        if self.bot_kind == "premium" and user_id in self.OKAK_ALLOWED_TELEGRAM_USER_IDS:
            keys.append(OKAK_STRATEGY_KEY)
        return tuple(
            key
            for key in keys
            if key in self.STRATEGY_KEYS and self._strategy_accessible_for_user_id(user_id, key)
        )

    def _is_gold_substrategy(self, strategy_key: str | None) -> bool:
        return str(strategy_key or "").strip().lower() in GOLD_SUBSTRATEGY_KEY_SET

    def _gold_enabled_keys(self, settings: UserSettingsRecord | None) -> tuple[str, ...]:
        enabled = self._enabled_strategy_keys(settings)
        return tuple(key for key in enabled if key in GOLD_SUBSTRATEGY_KEYS)

    def _enabled_strategy_keys(self, settings: UserSettingsRecord | None) -> tuple[str, ...]:
        if self.bot_kind != "premium" or settings is None:
            return ()
        return tuple(
            key
            for key in settings.enabled_strategy_keys
            if key in self.STRATEGY_KEYS and self._strategy_accessible_for_user_id(settings.telegram_user_id, key)
        )

    def _resolved_active_strategy_key(self, settings: UserSettingsRecord | None) -> str | None:
        if self.bot_kind != "premium":
            return None
        enabled = self._enabled_strategy_keys(settings)
        if not enabled:
            active = str(settings.active_strategy_key or "").strip().lower() if settings is not None else ""
            return (
                active
                if active in self.STRATEGY_KEYS and self._strategy_accessible_for_user_id(getattr(settings, "telegram_user_id", None), active)
                else None
            )
        active = str(settings.active_strategy_key or "").strip().lower() if settings is not None else ""
        if active in self.STRATEGY_KEYS and self._strategy_accessible_for_user_id(getattr(settings, "telegram_user_id", None), active):
            return active
        return enabled[0]

    def _strategy_hub_callback_data(self, settings: UserSettingsRecord | None) -> str:
        if self.bot_kind == "premium":
            active_strategy_key = self._resolved_active_strategy_key(settings)
            if active_strategy_key is not None:
                return f"ux:strategy:open:{active_strategy_key}"
        return "ux:menu"

    def _strategy_enabled_for_settings(
        self,
        settings: UserSettingsRecord | None,
        *,
        strategy_key: str,
    ) -> bool:
        if self.bot_kind != "premium":
            return True
        enabled = set(self._enabled_strategy_keys(settings))
        normalized = str(strategy_key or "").strip().lower()
        if normalized in GOLD_SUBSTRATEGY_KEY_SET:
            return GOLD_MASTER_STRATEGY_KEY in enabled and normalized in enabled
        return normalized in enabled

    def _normalize_hub_origin(self, origin: str | None, *, default: str = "menu") -> str:
        return "strategy" if str(origin or "").strip().lower() == "strategy" else default

    def _action_hub_origin(self, action) -> str:
        explicit_origin = str(action.extra or "").strip().lower()
        if explicit_origin in {"menu", "strategy"}:
            return explicit_origin
        if action.kind in {"watchhub", "deliveryhub", "statshub", "aihub", "settingshub", "access"}:
            return "menu"
        return "strategy"

    def _remember_hub_origin(self, telegram_user_id: int, *, section: str, origin: str | None) -> str:
        normalized = self._normalize_hub_origin(origin, default="menu")
        self._hub_origin_context[(telegram_user_id, section)] = normalized
        return normalized

    def _hub_origin_for(self, telegram_user_id: int, *, section: str, default: str = "menu") -> str:
        return self._hub_origin_context.get((telegram_user_id, section), default)

    def _hub_back_callback_data(
        self,
        settings: UserSettingsRecord | None,
        *,
        origin: str | None,
    ) -> str:
        if self._normalize_hub_origin(origin, default="menu") == "strategy":
            return self._strategy_hub_callback_data(settings)
        return "ux:menu"

    def _hub_callback_data(self, kind: str, *, origin: str | None) -> str:
        if self._normalize_hub_origin(origin, default="menu") == "strategy":
            return f"ux:{kind}:strategy"
        return f"ux:{kind}"

    def _remember_screen_back_callback(self, telegram_user_id: int, *, screen: str, callback_data: str) -> str:
        self._screen_back_context[(telegram_user_id, screen)] = callback_data
        return callback_data

    def _screen_back_callback(self, telegram_user_id: int, *, screen: str, default: str) -> str:
        return self._screen_back_context.get((telegram_user_id, screen), default)

    def _navigation_back_callback(
        self,
        telegram_user_id: int,
        *,
        settings: UserSettingsRecord | None,
        screen: str,
        section: str | None = None,
    ) -> str:
        explicit = self._screen_back_context.get((telegram_user_id, screen))
        if explicit:
            return explicit
        if section:
            remembered_origin = self._hub_origin_context.get((telegram_user_id, section))
            if remembered_origin is not None:
                return self._hub_back_callback_data(settings, origin=remembered_origin)
        return "ux:menu"

    def _setup_builder_bot_kind(self) -> str:
        return f"{self.bot_kind}:setup_builder"

    def _gold_wizard_bot_kind(self) -> str:
        return f"{self.bot_kind}:gold_wizard"

    async def _get_setup_builder_state(self, telegram_user_id: int):
        return await self.repository.get_user_onboarding_state(
            telegram_user_id,
            bot_kind=self._setup_builder_bot_kind(),
        )

    async def _save_setup_builder_state(
        self,
        telegram_user_id: int,
        *,
        step: str,
        draft: dict[str, object],
    ) -> None:
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=telegram_user_id,
            bot_kind=self._setup_builder_bot_kind(),
            step=step,
            draft=draft,
        )

    async def _clear_setup_builder_state(self, telegram_user_id: int) -> None:
        await self.repository.delete_user_onboarding_state(
            telegram_user_id,
            bot_kind=self._setup_builder_bot_kind(),
        )

    async def _get_gold_wizard_state(self, telegram_user_id: int):
        return await self.repository.get_user_onboarding_state(
            telegram_user_id,
            bot_kind=self._gold_wizard_bot_kind(),
        )

    async def _save_gold_wizard_state(
        self,
        telegram_user_id: int,
        *,
        step: str,
        draft: dict[str, object],
    ) -> None:
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=telegram_user_id,
            bot_kind=self._gold_wizard_bot_kind(),
            step=step,
            draft=draft,
        )

    async def _clear_gold_wizard_state(self, telegram_user_id: int) -> None:
        await self.repository.delete_user_onboarding_state(
            telegram_user_id,
            bot_kind=self._gold_wizard_bot_kind(),
        )

    async def _cleanup_strategy_guide_message(
        self,
        *,
        telegram_user_id: int,
        chat_id: str,
    ) -> None:
        message_id = self._strategy_guide_message_ids.pop(telegram_user_id, None)
        if message_id is None:
            return
        with suppress(Exception):
            await self.telegram_client.delete_message(chat_id=chat_id, message_id=message_id)

    async def _cleanup_temporary_navigation_messages(
        self,
        *,
        telegram_user_id: int,
        chat_id: str,
    ) -> None:
        await self._cleanup_strategy_guide_message(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )

    def _signal_strategy_key(self, signal: AlertSignal) -> str:
        strategy_key = str(signal.metadata.get("strategy_key") or "").strip().lower()
        if strategy_key in self.STRATEGY_KEYS:
            return strategy_key
        if self._is_gold_signal(signal):
            return "gold"
        return "rsi"

    def _alert_strategy_key(self, alert: AlertRecord) -> str:
        strategy_key = str(getattr(alert, "strategy_key", "") or "").strip().lower()
        if strategy_key in self.STRATEGY_KEYS:
            return strategy_key
        if self._is_gold_alert_record(alert):
            return "gold"
        return "rsi"

    def _followup_strategy_key(self, followup: FollowUpResultRecord) -> str:
        strategy_key = str(followup.metadata.get("strategy_key") or "").strip().lower()
        return strategy_key if strategy_key in self.STRATEGY_KEYS else "rsi"

    def _merge_shell_with_strategy(
        self,
        shell_settings: UserSettingsRecord,
        strategy_settings: PremiumStrategySettingsRecord,
    ) -> UserSettingsRecord:
        return UserSettingsRecord(
            telegram_user_id=shell_settings.telegram_user_id,
            bot_kind=shell_settings.bot_kind,
            direct_signal_delivery_enabled=strategy_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=strategy_settings.followup_delivery_enabled,
            gold_alerts_enabled="gold" in self._enabled_strategy_keys(shell_settings),
            language_code=shell_settings.language_code,
            signal_profile=strategy_settings.signal_profile,
            base_signal_profile=strategy_settings.base_signal_profile,
            preferred_min_score=strategy_settings.preferred_min_score,
            min_quote_volume=strategy_settings.min_quote_volume,
            rsi_oversold=strategy_settings.rsi_oversold,
            rsi_overbought=strategy_settings.rsi_overbought,
            direction_filter=strategy_settings.direction_filter,
            watchlist_only=strategy_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=strategy_settings.delivery_mode,
            delivery_mode_changed_at=strategy_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=strategy_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=strategy_settings.quiet_hours_end_minute,
            snooze_until=strategy_settings.snooze_until,
            snooze_started_at=strategy_settings.snooze_started_at,
            snooze_label=strategy_settings.snooze_label,
            last_resume_summary_at=strategy_settings.last_resume_summary_at,
            last_digest_sent_at=strategy_settings.last_digest_sent_at,
            last_daily_recap_at=strategy_settings.last_daily_recap_at,
            last_weekly_recap_at=strategy_settings.last_weekly_recap_at,
            active_watchlist_theme=strategy_settings.active_watchlist_theme,
            active_custom_theme_name=strategy_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at,
            updated_at=max(shell_settings.updated_at, strategy_settings.updated_at),
            enabled_strategy_keys=shell_settings.enabled_strategy_keys,
            active_strategy_key=strategy_settings.strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
            current_context=shell_settings.current_context,
            current_strategy_context=shell_settings.current_strategy_context,
            current_set_id=shell_settings.current_set_id,
            timezone_name=shell_settings.timezone_name,
            strategy_preferences=strategy_settings.strategy_preferences,
            display_mode=shell_settings.display_mode,
            active_workspace=shell_settings.active_workspace,
            saved_workspace_payload=shell_settings.saved_workspace_payload,
            personalization=shell_settings.personalization,
            delivery_rules=shell_settings.delivery_rules,
        )

    async def _ensure_premium_strategy_settings(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord,
        strategy_key: str,
    ) -> PremiumStrategySettingsRecord:
        existing = await self.repository.get_premium_strategy_settings(
            telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
        )
        if existing is not None:
            return existing
        default_score, default_volume, default_oversold, default_overbought = self._profile_defaults("balanced")
        default_score = PREMIUM_STRATEGY_DEFAULT_MIN_SCORES.get(strategy_key, default_score)
        default_direction_filter = "both"
        if strategy_key in {OKAK_STRATEGY_KEY, EKEK_STRATEGY_KEY}:
            default_volume = 5_000_000.0
            default_overbought = 76.0
            default_direction_filter = "short"
        elif strategy_key == "daily_rsi_80":
            default_volume = 5_000_000.0
            default_overbought = 80.0
            default_direction_filter = "short"
        await self.repository.upsert_premium_strategy_settings(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=self.settings.private_bot_followups_default,
            signal_profile="balanced",
            base_signal_profile="balanced",
            preferred_min_score=default_score,
            min_quote_volume=default_volume,
            rsi_oversold=default_oversold,
            rsi_overbought=default_overbought,
            direction_filter=default_direction_filter,
            watchlist_only=(strategy_key == GOLD_MASTER_STRATEGY_KEY or self._is_gold_substrategy(strategy_key)),
            delivery_mode="instant",
            active_watchlist_theme="gold" if strategy_key == GOLD_MASTER_STRATEGY_KEY or self._is_gold_substrategy(strategy_key) else "custom",
            active_custom_theme_name=None,
            strategy_preferences=strategy_preference_defaults(strategy_key),
        )
        created = await self.repository.get_premium_strategy_settings(
            telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
        )
        assert created is not None
        return created

    async def _save_premium_strategy_settings_record(
        self,
        strategy_settings: PremiumStrategySettingsRecord,
        *,
        direct_signal_delivery_enabled: bool | None = None,
        followup_delivery_enabled: bool | None = None,
        preferred_min_score: int | None = None,
        signal_profile: str | None = None,
        base_signal_profile: str | None = None,
    ) -> PremiumStrategySettingsRecord:
        await self.repository.upsert_premium_strategy_settings(
            telegram_user_id=strategy_settings.telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_settings.strategy_key,
            direct_signal_delivery_enabled=(
                strategy_settings.direct_signal_delivery_enabled
                if direct_signal_delivery_enabled is None
                else direct_signal_delivery_enabled
            ),
            followup_delivery_enabled=(
                strategy_settings.followup_delivery_enabled
                if followup_delivery_enabled is None
                else followup_delivery_enabled
            ),
            signal_profile=strategy_settings.signal_profile if signal_profile is None else signal_profile,
            base_signal_profile=(
                strategy_settings.base_signal_profile
                if base_signal_profile is None
                else base_signal_profile
            ),
            preferred_min_score=(
                strategy_settings.preferred_min_score
                if preferred_min_score is None
                else preferred_min_score
            ),
            min_quote_volume=strategy_settings.min_quote_volume,
            rsi_oversold=strategy_settings.rsi_oversold,
            rsi_overbought=strategy_settings.rsi_overbought,
            direction_filter=strategy_settings.direction_filter,
            watchlist_only=strategy_settings.watchlist_only,
            delivery_mode=strategy_settings.delivery_mode,
            delivery_mode_changed_at=strategy_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=strategy_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=strategy_settings.quiet_hours_end_minute,
            snooze_until=strategy_settings.snooze_until,
            snooze_started_at=strategy_settings.snooze_started_at,
            snooze_label=strategy_settings.snooze_label,
            last_resume_summary_at=strategy_settings.last_resume_summary_at,
            last_digest_sent_at=strategy_settings.last_digest_sent_at,
            last_daily_recap_at=strategy_settings.last_daily_recap_at,
            last_weekly_recap_at=strategy_settings.last_weekly_recap_at,
            active_watchlist_theme=strategy_settings.active_watchlist_theme,
            active_custom_theme_name=strategy_settings.active_custom_theme_name,
            strategy_preferences=strategy_settings.strategy_preferences,
        )
        refreshed = await self.repository.get_premium_strategy_settings(
            strategy_settings.telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_settings.strategy_key,
        )
        assert refreshed is not None
        return refreshed

    async def _sync_shell_to_strategy(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord,
        strategy_key: str,
        strategy_selector_completed_at=...,
    ) -> UserSettingsRecord:
        strategy_settings = await self._ensure_premium_strategy_settings(
            telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        enabled_keys = self._enabled_strategy_keys(shell_settings)
        await self.repository.upsert_user_settings(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=strategy_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=strategy_settings.followup_delivery_enabled,
            gold_alerts_enabled="gold" in enabled_keys,
            language_code=shell_settings.language_code,
            signal_profile=strategy_settings.signal_profile,
            base_signal_profile=strategy_settings.base_signal_profile,
            preferred_min_score=strategy_settings.preferred_min_score,
            min_quote_volume=strategy_settings.min_quote_volume,
            rsi_oversold=strategy_settings.rsi_oversold,
            rsi_overbought=strategy_settings.rsi_overbought,
            direction_filter=strategy_settings.direction_filter,
            watchlist_only=strategy_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=strategy_settings.delivery_mode,
            delivery_mode_changed_at=strategy_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=strategy_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=strategy_settings.quiet_hours_end_minute,
            snooze_until=strategy_settings.snooze_until,
            snooze_started_at=strategy_settings.snooze_started_at,
            snooze_label=strategy_settings.snooze_label,
            last_resume_summary_at=strategy_settings.last_resume_summary_at,
            last_digest_sent_at=strategy_settings.last_digest_sent_at,
            last_daily_recap_at=strategy_settings.last_daily_recap_at,
            last_weekly_recap_at=strategy_settings.last_weekly_recap_at,
            active_watchlist_theme=strategy_settings.active_watchlist_theme,
            active_custom_theme_name=strategy_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at,
            enabled_strategy_keys=enabled_keys,
            active_strategy_key=strategy_key,
            strategy_selector_completed_at=(
                shell_settings.strategy_selector_completed_at
                if strategy_selector_completed_at is Ellipsis
                else strategy_selector_completed_at
            ),
            current_context=shell_settings.current_context,
            current_strategy_context=shell_settings.current_strategy_context,
            current_set_id=shell_settings.current_set_id,
            timezone_name=shell_settings.timezone_name,
            display_mode=shell_settings.display_mode,
            active_workspace=shell_settings.active_workspace,
            saved_workspace_payload=shell_settings.saved_workspace_payload,
            strategy_preferences=strategy_settings.strategy_preferences,
            personalization=shell_settings.personalization,
            delivery_rules=shell_settings.delivery_rules,
        )
        refreshed = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        assert refreshed is not None
        return self._merge_shell_with_strategy(refreshed, strategy_settings)

    async def _load_strategy_settings(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord,
        strategy_key: str,
    ) -> UserSettingsRecord:
        strategy_settings = await self._ensure_premium_strategy_settings(
            telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        return self._merge_shell_with_strategy(shell_settings, strategy_settings)

    def _strategy_selector_text(self, settings: UserSettingsRecord, *, language_code: str) -> str:
        enabled = self._enabled_strategy_keys(settings)
        active = self._resolved_active_strategy_key(settings)
        selected_line = ", ".join(self._strategy_label(key, language_code=language_code) for key in enabled) or (
            "Nothing selected yet" if language_code == "en" else "Пока ничего не выбрано"
        )
        active_line = (
            self._strategy_label(active, language_code=language_code)
            if active is not None
            else ("Open any strategy card" if language_code == "en" else "Открой любую стратегию")
        )
        if language_code == "ru":
            return (
                "<b>Стратегии</b>\n\n"
                "Нажми на название стратегии, чтобы открыть её страницу, быстро понять логику и настроить всё отдельно.\n\n"
                f"Выбрано: <b>{selected_line}</b>\n"
                f"Открыта: <b>{active_line}</b>"
            )
        return (
            "<b>Trading Strategies</b>\n\n"
            "Tap a strategy name to open its own page, read the idea in short form, and configure it separately.\n\n"
            f"Selected: <b>{selected_line}</b>\n"
            f"Open now: <b>{active_line}</b>"
        )

    async def _home_enabled_notification_labels(
        self,
        telegram_user_id: int,
        settings: UserSettingsRecord | None,
        *,
        language_code: str,
    ) -> list[str]:
        if settings is None:
            return []
        enabled_keys = self._enabled_strategy_keys(settings)
        direct_enabled = bool(settings.direct_signal_delivery_enabled)
        followup_enabled = bool(settings.followup_delivery_enabled)
        if self.bot_kind == "premium" and enabled_keys:
            direct_enabled = False
            followup_enabled = False
            for strategy_key in enabled_keys:
                strategy_settings = await self._load_strategy_settings(
                    telegram_user_id,
                    shell_settings=settings,
                    strategy_key=strategy_key,
                )
                direct_enabled = direct_enabled or bool(strategy_settings.direct_signal_delivery_enabled)
                followup_enabled = followup_enabled or bool(strategy_settings.followup_delivery_enabled)
                if direct_enabled and followup_enabled:
                    break
        labels: list[str] = []
        if direct_enabled:
            labels.append("Signals" if language_code == "en" else "Сигналы")
        if followup_enabled:
            labels.append("Follow-Ups" if language_code == "en" else "Фоллоу-апы")
        if self._gold_alerts_enabled_for_settings(settings) and any(
            strategy_key == GOLD_MASTER_STRATEGY_KEY or strategy_key in GOLD_SUBSTRATEGY_KEY_SET
            for strategy_key in enabled_keys
        ):
            labels.append("Gold" if language_code == "en" else "Золото")
        return labels

    def _compact_home_labels(
        self,
        labels: list[str],
        *,
        language_code: str,
        empty_label: str,
        max_items: int = 3,
    ) -> str:
        normalized = [str(item).strip() for item in labels if str(item).strip()]
        if not normalized:
            return empty_label
        visible = normalized[:max_items]
        summary = ", ".join(visible)
        remaining = len(normalized) - len(visible)
        if remaining > 0:
            summary = f"{summary} +{remaining}"
        return summary

    def _strategy_rows(self, settings: UserSettingsRecord, *, language_code: str) -> list[tuple[str, str, str | None, str | None]]:
        enabled = set(self._enabled_strategy_keys(settings))
        active = self._resolved_active_strategy_key(settings)
        rows: list[tuple[str, str, str | None, str | None]] = []
        for strategy_key in self._visible_strategy_keys(settings):
            label = self._strategy_label(strategy_key, language_code=language_code)
            if active == strategy_key:
                primary = f"▸ {label}"
            elif strategy_key in enabled:
                primary = f"✓ {label}"
            else:
                primary = label
            secondary = (
                "Disable" if strategy_key in enabled else "Enable"
            ) if language_code == "en" else (
                "Выключить" if strategy_key in enabled else "Включить"
            )
            rows.append(
                (
                    primary,
                    f"ux:strategy:open:{strategy_key}",
                    secondary,
                    f"ux:strategy:toggle:{strategy_key}",
                )
            )
        return rows

    def _strategy_enabled_note(self, *, strategy_enabled: bool, language_code: str) -> str:
        if language_code == "ru":
            if strategy_enabled:
                return "🟢 Стратегия включена. Сигналы и follow-up по ней могут приходить пользователю."
            return "⚪ Стратегия пока выключена. Здесь можно спокойно посмотреть логику и настроить всё заранее."
        if strategy_enabled:
            return "🟢 Strategy is enabled. Live alerts and follow-ups from it can be delivered to the user."
        return "⚪ Strategy is currently disabled. You can read the logic and prepare the setup first."

    def _strategy_copy(self, strategy_key: str, *, language_code: str) -> dict[str, object]:
        language = normalize_language(language_code)
        copy = {
            "breakout": {
                "ru": {
                    "summary": "Ловит выход цены из диапазона, когда рынок готов продолжить импульс.",
                    "what": "Ищет чистый пробой уровня после сжатия и закрепления.",
                    "when": "Подходит, когда хочешь торговать продолжение сильного движения, а не ловить разворот.",
                    "tracks": (
                        "ключевой уровень",
                        "сжатие перед выходом",
                        "закрытие свечи выше или ниже уровня",
                    ),
                    "meaning": "Выше уровня — long-приоритет. Ниже уровня — short-приоритет.",
                },
                "en": {
                    "summary": "Tracks range breaks when price is ready to continue with momentum.",
                    "what": "Looks for a clean level break after compression and acceptance.",
                    "when": "Best when you want continuation trades instead of reversal catches.",
                    "tracks": (
                        "a key level",
                        "compression before the move",
                        "candle acceptance above or below the level",
                    ),
                    "meaning": "Above the level means long bias. Below the level means short bias.",
                },
            },
            "trend_pullback": {
                "ru": {
                    "summary": "Ждёт откат к тренду и помогает входить спокойнее, чем в резкий пробой.",
                    "what": "Ищет возврат в EMA-зону и повторное подтверждение движения по тренду.",
                    "when": "Подходит, когда хочешь торговать вместе с трендом и не гнаться за ценой.",
                    "tracks": (
                        "структуру тренда",
                        "возврат в EMA-зону",
                        "свечное подтверждение продолжения",
                    ),
                    "meaning": "Если откат удержан, сигнал указывает на продолжение основного движения.",
                },
                "en": {
                    "summary": "Waits for a pullback into trend structure instead of chasing the first push.",
                    "what": "Looks for a return into the EMA zone and confirmation back with trend.",
                    "when": "Best when you want to trade with trend and enter more patiently.",
                    "tracks": (
                        "trend structure",
                        "return into the EMA zone",
                        "confirmation back with the move",
                    ),
                    "meaning": "If the pullback holds, the signal points to continuation with trend.",
                },
            },
            "rsi_bollinger_mr": {
                "ru": {
                    "summary": "Ищет откат к средней после сильного выброса цены.",
                    "what": "Проверяет выход за полосы, экстремум RSI и возврат обратно в диапазон.",
                    "when": "Подходит, когда хочешь брать ослабление перегиба, а не продолжение импульса.",
                    "tracks": (
                        "выброс за Bollinger",
                        "RSI в экстремальной зоне",
                        "возврат обратно в диапазон",
                    ),
                    "meaning": "Сигнал означает, что выброс ослабевает и возможен откат к средней.",
                },
                "en": {
                    "summary": "Looks for mean reversion after price stretches too far from balance.",
                    "what": "Checks the band extension, RSI extreme, and re-entry back into range.",
                    "when": "Best when you want pullback trades after exhaustion, not continuation.",
                    "tracks": (
                        "a Bollinger extension",
                        "RSI in an extreme zone",
                        "re-entry back into range",
                    ),
                    "meaning": "The signal means exhaustion may be fading and price can snap back.",
                },
            },
            "rsi_bollinger_touch": {
                "ru": {
                    "summary": "Ищет касание 30-периодной полосы Боллинджера одновременно с RSI-экстремумом.",
                    "what": "Проверяет RSI ниже 30 или выше 70, касание края полосы и анти-sideways фильтр против плоского рынка.",
                    "when": "Подходит, когда хочешь брать растянутые касания полос, но не получать сигналы в боковике.",
                    "tracks": (
                        "касание 30-period Bollinger",
                        "RSI в экстремальной зоне",
                        "небоковой режим рынка",
                    ),
                    "meaning": "Сигнал означает, что цена растянулась к краю полосы и рынок всё ещё имеет направленную структуру.",
                },
                "en": {
                    "summary": "Looks for a 30-period Bollinger touch that happens together with an RSI extreme.",
                    "what": "Checks RSI below 30 or above 70, an outer-band tag, and an anti-sideways filter against flat chop.",
                    "when": "Best when you want stretched Bollinger touches without getting spammed by sideways noise.",
                    "tracks": (
                        "a 30-period Bollinger touch",
                        "RSI in an extreme zone",
                        "non-sideways market structure",
                    ),
                    "meaning": "The signal means price is stretched into the outer band while the market still has direction.",
                },
            },
            "daily_rsi_80": {
                "ru": {
                    "summary": "Показывает монеты, где дневной RSI уже закрылся выше 80 и рынок выглядит перегретым на старшем ТФ.",
                    "what": "Ищет закрытую дневную свечу с RSI 80+ и превращает это в отдельный high-timeframe shortlist.",
                    "when": "Подходит, когда нужен список перегретых монет по 1d, а не быстрый шумный поток на младших таймфреймах.",
                    "tracks": (
                        "RSI 80+ на 1d",
                        "закрытую дневную свечу",
                        "старший short-bias контекст",
                    ),
                    "meaning": "Это не мгновенный вход, а старший сигнал внимания: монета уже сильно перегрета и её стоит держать в short-watchlist.",
                },
                "en": {
                    "summary": "Surfaces coins whose daily RSI already closed above 80 and now look overheated on a higher timeframe.",
                    "what": "Looks for a closed 1d candle with RSI 80+ and turns it into a dedicated high-timeframe shortlist.",
                    "when": "Best when you want an overheated 1d watchlist instead of a faster lower-timeframe stream.",
                    "tracks": (
                        "RSI 80+ on 1d",
                        "a closed daily candle",
                        "higher-timeframe short-bias context",
                    ),
                    "meaning": "This is not an instant entry by itself. It is a higher-timeframe heads-up that a coin is already very stretched.",
                },
            },
            "vwap": {
                "ru": {
                    "summary": "Следит за тем, удерживает ли цена VWAP внутри дня или теряет его.",
                    "what": "Ищет возврат над VWAP, отказ от него и дневной intraday-контекст.",
                    "when": "Подходит для внутридневной торговли, когда важен текущий баланс покупателей и продавцов.",
                    "tracks": (
                        "возврат над VWAP",
                        "отказ обратно под VWAP",
                        "контекст текущей сессии",
                    ),
                    "meaning": "Выше VWAP — long-приоритет, ниже VWAP — short-приоритет.",
                },
                "en": {
                    "summary": "Tracks whether intraday price is holding VWAP or losing it.",
                    "what": "Looks for reclaims above VWAP, rejections below it, and session context.",
                    "when": "Best for intraday trading when session flow matters.",
                    "tracks": (
                        "reclaim above VWAP",
                        "rejection back below VWAP",
                        "current session context",
                    ),
                    "meaning": "Above VWAP means long priority, below VWAP means short priority.",
                },
            },
            "false_breakout": {
                "ru": {
                    "summary": "Ловит вынос за уровень и быстрый возврат обратно в диапазон.",
                    "what": "Ищет sweep хая или лоя и раннее подтверждение разворота.",
                    "when": "Подходит, когда хочешь брать разворот после ловушки, а не поздний пробой.",
                    "tracks": (
                        "вынос локального экстремума",
                        "закрытие обратно в диапазон",
                        "раннюю реакцию на разворот",
                    ),
                    "meaning": "Ложный вынос хая даёт short-идею, лоя — long-идею.",
                },
                "en": {
                    "summary": "Looks for stop sweeps beyond a level and quick return back inside range.",
                    "what": "Checks for a local high or low sweep and early reversal confirmation.",
                    "when": "Best when you want reversal after a trap instead of a late breakout entry.",
                    "tracks": (
                        "a local high or low sweep",
                        "close back into range",
                        "early reversal response",
                    ),
                    "meaning": "A false high break favors short. A false low break favors long.",
                },
            },
            "rsi": {
                "ru": {
                    "summary": "Показывает монеты, где рынок уже перегрет или перепродан.",
                    "what": "Ищет RSI-экстремумы на закрытой свече и даёт ранний сигнал внимания.",
                    "when": "Подходит, когда нужен быстрый фильтр для поиска растянутого движения.",
                    "tracks": (
                        "перекупленность",
                        "перепроданность",
                        "закрытую свечу на выбранном ТФ",
                    ),
                    "meaning": "Сигнал говорит о перегибе. Для входа лучше дождаться подтверждения по цене.",
                },
                "en": {
                    "summary": "Flags coins that already look overheated or washed out.",
                    "what": "Looks for RSI extremes on closed candles and sends an early heads-up.",
                    "when": "Best when you want a fast filter for stretched markets.",
                    "tracks": (
                        "overbought conditions",
                        "oversold conditions",
                        "a closed candle on the chosen timeframe",
                    ),
                    "meaning": "The signal shows an extreme. Price confirmation is still recommended.",
                },
            },
            "rsi_divergence": {
                "ru": {
                    "summary": "Ищет расхождение между новым экстремумом цены и более слабым подтверждением со стороны RSI.",
                    "what": "Проверяет первый swing ниже 30 или выше 70, затем откат и второй push с новым экстремумом цены, но без подтверждения RSI.",
                    "when": "Подходит, когда нужен более структурный разворотный сигнал, а не просто касание зоны перекупленности или перепроданности.",
                    "tracks": (
                        "первый swing в зоне RSI-экстремума",
                        "откат между двумя pushes",
                        "новый экстремум цены без подтверждения RSI",
                    ),
                    "meaning": "Сигнал говорит, что цена ещё обновила экстремум, а импульс уже ослаб, поэтому шанс на разворот растёт.",
                },
                "en": {
                    "summary": "Looks for a mismatch between a fresh price extreme and weaker RSI confirmation.",
                    "what": "Checks a first swing below 30 or above 70, then a pullback, then a second push that makes a new price extreme without RSI confirmation.",
                    "when": "Best when you want a structured reversal setup instead of a simple overbought or oversold tag.",
                    "tracks": (
                        "a first swing inside the RSI extreme zone",
                        "a pullback between the two pushes",
                        "a new price extreme without RSI confirmation",
                    ),
                    "meaning": "The signal means price still extended, but momentum did not confirm the move, so reversal odds improve.",
                },
            },
            OKAK_STRATEGY_KEY: {
                "ru": {
                    "summary": "Строгий overbought-only режим для short-идей с упором на RSI, score и ликвидность.",
                    "what": "Пускает сигнал только когда совпали минимум 2 из 3 условий: объём 5-20M или 50M+, RSI 76+ и score 90+.",
                    "when": "Подходит, когда нужен узкий shortlist по перегретым монетам вместо всего обычного RSI-потока.",
                    "tracks": (
                        "перекупленность на закрытой свече",
                        "RSI 76+",
                        "сильный score и нужную ликвидность",
                    ),
                    "meaning": "Это не общий RSI-фильтр, а отдельный строгий shortlist для short-реакции после перегрева.",
                },
                "en": {
                    "summary": "A stricter overbought-only mode for short ideas with extra focus on RSI, score, and liquidity.",
                    "what": "It only lets alerts through when at least 2 of 3 conditions line up: 5-20M or 50M+ volume, RSI 76+, and score 90+.",
                    "when": "Best when you want a narrow shortlist of overheated names instead of the full RSI stream.",
                    "tracks": (
                        "an overbought close",
                        "RSI 76+",
                        "high score with preferred liquidity",
                    ),
                    "meaning": "This is not the general RSI stream. It is a stricter shortlist for short-side exhaustion reactions.",
                },
            },
            EKEK_STRATEGY_KEY: {
                "ru": {
                    "summary": "Импульсная версия OKAK: ищет только резкие перегретые выстрелы вверх вместо плавного роста.",
                    "what": "Сохраняет строгие OKAK-фильтры, но добавляет обязательную проверку на свежий резкий импульс.",
                    "when": "Подходит, когда нужен shortlist именно по быстрым разгонам перед возможной short-реакцией.",
                    "tracks": (
                        "перекупленность на закрытой свече",
                        "минимум 2 из 3 OKAK-условий",
                        "резкий импульс вместо постепенного подъёма",
                    ),
                    "meaning": "Это отдельный поток для перегретых импульсов, где цена ускорилась слишком резко.",
                },
                "en": {
                    "summary": "The impulse version of OKAK: it only keeps sharp overheated bursts instead of gradual climbs.",
                    "what": "It keeps the strict OKAK filters, then adds a mandatory fresh impulse check.",
                    "when": "Best when you want a shortlist specifically for fast squeeze-like runs before a possible short reaction.",
                    "tracks": (
                        "an overbought close",
                        "at least 2 of 3 OKAK conditions",
                        "a sharp impulse instead of a gradual climb",
                    ),
                    "meaning": "This is a separate stream for overheated impulse bursts where price accelerated too quickly.",
                },
            },
            "bollinger": {
                "ru": {
                    "summary": "Ищет возврат цены обратно в канал Bollinger без жёсткого RSI-фильтра.",
                    "what": "Смотрит на выход за полосу и мягкий возврат обратно в диапазон.",
                    "when": "Подходит, когда хочешь более мягкий mean reversion без строгих условий MR-стратегии.",
                    "tracks": (
                        "выход за полосу",
                        "возврат обратно в канал",
                        "мягкий контртрендовый импульс",
                    ),
                    "meaning": "Если цена вернулась в канал, возможен ход обратно к средней.",
                },
                "en": {
                    "summary": "Looks for price coming back inside Bollinger Bands without the stricter RSI gate.",
                    "what": "Tracks an extension beyond the band and a softer return back into range.",
                    "when": "Best when you want gentler mean reversion without stricter MR rules.",
                    "tracks": (
                        "a band extension",
                        "return back inside the channel",
                        "softer counter-trend behavior",
                    ),
                    "meaning": "If price returns into the channel, a move back toward the mean is possible.",
                },
            },
            "gold": {
                "ru": {
                    "summary": "Отдельный поток только по XAUUSD со своими фильтрами и уведомлениями.",
                    "what": "Держит золото отдельно от крипты и позволяет настроить под него свой режим.",
                    "when": "Подходит, когда хочешь следить только за золотом и не смешивать его с крипто-потоком.",
                    "tracks": (
                        "движение XAUUSD",
                        "RSI-экстремумы по золоту",
                        "отдельные delivery и session-настройки",
                    ),
                    "meaning": "Это самостоятельные сигналы по золоту, не смешанные с крипто-стратегиями.",
                },
                "en": {
                    "summary": "A separate XAUUSD-only flow with its own filters and delivery rules.",
                    "what": "Keeps gold separate from crypto and gives it its own setup.",
                    "when": "Best when you want gold-only alerts without mixing them with crypto flow.",
                    "tracks": (
                        "XAUUSD movement",
                        "gold RSI extremes",
                        "separate delivery and session controls",
                    ),
                    "meaning": "These are dedicated gold alerts, not mixed with crypto strategies.",
                },
            },
            "gold_breakout": {
                "ru": {
                    "summary": "Ищет пробой диапазона по XAUUSD после сжатия и готовности рынка к импульсу.",
                    "what": "Следит за ключевым диапазоном, удержанием пробоя и продолжением движения по золоту.",
                    "when": "Подходит, когда нужен пробойный сценарий по золоту, а не реакция против импульса.",
                    "tracks": (
                        "диапазон XAUUSD",
                        "закрытие за уровнем",
                        "готовность продолжения",
                    ),
                    "meaning": "Если пробой удерживается, приоритет остаётся за продолжением импульса.",
                },
                "en": {
                    "summary": "Tracks XAUUSD range breaks after compression when gold is ready to extend.",
                    "what": "Looks for a clean range break, acceptance, and follow-through on gold.",
                    "when": "Best when you want gold breakouts instead of reacting against momentum.",
                    "tracks": (
                        "the XAUUSD range",
                        "acceptance beyond the level",
                        "follow-through pressure",
                    ),
                    "meaning": "If the break holds, the continuation bias stays in place.",
                },
            },
            "gold_pullback": {
                "ru": {
                    "summary": "Ждёт откат XAUUSD к EMA-зоне и подтверждение продолжения основного движения.",
                    "what": "Следит за возвратом к тренду и реакцией от EMA20/EMA50 по золоту.",
                    "when": "Подходит, когда нужен более спокойный вход по золоту вместе с трендом.",
                    "tracks": (
                        "структуру тренда",
                        "касание EMA",
                        "свечное подтверждение",
                    ),
                    "meaning": "Если откат удержан, сценарий остаётся трендовым и рабочим.",
                },
                "en": {
                    "summary": "Waits for XAUUSD pullbacks into EMA structure before continuation.",
                    "what": "Tracks gold returning into EMA20/EMA50 and confirming back with trend.",
                    "when": "Best when you want calmer gold entries that stay with the main trend.",
                    "tracks": (
                        "trend structure",
                        "EMA touch",
                        "confirmation candle",
                    ),
                    "meaning": "If the pullback holds, the trend continuation thesis remains active.",
                },
            },
            "gold_liquidity": {
                "ru": {
                    "summary": "Ловит ложный вынос по золоту и быстрый возврат обратно в диапазон.",
                    "what": "Ищет sweep экстремума и раннее подтверждение возврата по XAUUSD.",
                    "when": "Подходит, когда нужен сценарий разворота после ловушки, а не пробой.",
                    "tracks": (
                        "вынос экстремума",
                        "возврат в диапазон",
                        "раннюю реакцию разворота",
                    ),
                    "meaning": "Если возврат удерживается, золото чаще даёт реакцию в обратную сторону.",
                },
                "en": {
                    "summary": "Looks for gold liquidity sweeps and quick reclaim back inside range.",
                    "what": "Tracks a sweep of the local extreme and early reversal confirmation on XAUUSD.",
                    "when": "Best when you want a trap reversal on gold instead of a breakout continuation.",
                    "tracks": (
                        "a sweep of the extreme",
                        "reclaim back into range",
                        "early reversal response",
                    ),
                    "meaning": "If the reclaim holds, gold often reacts back away from the trap.",
                },
            },
        }
        strategy_copy = copy.get(strategy_key, copy["rsi"])
        return dict(strategy_copy["ru" if language == "ru" else "en"])

    def _strategy_guide_text(self, strategy_key: str, *, language_code: str) -> str:
        return self._strategy_guide_detail_text(strategy_key, language_code=language_code)

    def _strategy_hub_text(self, strategy_key: str, *, strategy_enabled: bool, language_code: str) -> str:
        copy = self._strategy_copy(strategy_key, language_code=language_code)
        label = self._strategy_label(strategy_key, language_code=language_code)
        if language_code == "ru":
            summary = (
                f"{escape_html(str(copy['summary']))}\n\n"
                f"🧠 <b>Когда полезна</b>\n{escape_html(str(copy['when']))}"
            )
            footer = "🧩 У этой стратегии свои фильтры, избранные, уведомления и быстрая настройка."
        else:
            summary = (
                f"{escape_html(str(copy['summary']))}\n\n"
                f"🧠 <b>When it fits</b>\n{escape_html(str(copy['when']))}"
            )
            footer = "🧩 This strategy has its own filters, favorites, delivery rules, and quick setup."
        return (
            f"<b>{escape_html(label)}</b>\n\n"
            f"{summary}\n\n"
            f"{self._strategy_enabled_note(strategy_enabled=strategy_enabled, language_code=language_code)}\n\n"
            f"{escape_html(footer)}"
        )

    def _strategy_guide_detail_text(self, strategy_key: str, *, language_code: str) -> str:
        label = self._strategy_label(strategy_key, language_code=language_code)
        descriptions = {
            "breakout": {
                "ru": (
                    "🧱 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ловит момент, когда цена выходит из диапазона и рынок готов продолжить импульс.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь брать продолжение движения, а не разворот против рынка.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• важный уровень\n"
                    "• сжатие / консолидацию перед выходом\n"
                    "• закрытие свечи выше или ниже уровня\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Выше уровня → long-приоритет.\n"
                    "Ниже уровня → short-приоритет.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Сначала смотри, был ли чистый выход и закрепление. Потом уже открывай риск-карту и решай, есть ли нормальный вход."
                ),
                "en": (
                    "🧱 <b>Step 1. Core idea</b>\n"
                    "This strategy looks for price leaving a range when the market is ready to continue the move.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want continuation, not reversal trades.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• a meaningful level\n"
                    "• compression / consolidation before the move\n"
                    "• a candle close above or below the level\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "Above the level → long priority.\n"
                    "Below the level → short priority.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "First check if the breakout is clean and confirmed. Then open the risk card and decide whether the entry is still valid."
                ),
            },
            "trend_pullback": {
                "ru": (
                    "📈 <b>Шаг 1. В чём идея</b>\n"
                    "Бот ждёт не пробой, а откат к тренду, чтобы искать вход спокойнее и чище.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь торговать по основному движению, а не догонять цену.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• структура тренда вверх или вниз\n"
                    "• касание зоны EMA\n"
                    "• возвратное подтверждение свечой\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если откат удержан и цена снова идёт по тренду, появляется сигнал на продолжение.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Лучше работает, когда тренд уже виден заранее. Не спеши, если рынок пилит без структуры."
                ),
                "en": (
                    "📈 <b>Step 1. Core idea</b>\n"
                    "The bot waits for a pullback into trend instead of chasing the first breakout.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want to trade with the main direction, not after price already ran away.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• clean bullish or bearish structure\n"
                    "• touch into the EMA zone\n"
                    "• reaction candle back with the trend\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If the pullback holds and price starts moving with trend again, the setup is active.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "It works best when trend is already visible. Be careful when the market is choppy and structure is weak."
                ),
            },
            "rsi_bollinger_mr": {
                "ru": (
                    "🎯 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ищет перегиб движения, когда цену унесло слишком далеко и возможен возврат к средней.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь ловить откат после выброса, а не продолжение импульса.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• выход / касание вне полос\n"
                    "• RSI в перекупленности или перепроданности\n"
                    "• возврат обратно внутрь диапазона\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если выброс ослабевает и цена возвращается внутрь диапазона, появляется идея на откат к средней.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Не относись к нему как к входу вслепую. Сильный тренд может ещё тянуть цену дальше."
                ),
                "en": (
                    "🎯 <b>Step 1. Core idea</b>\n"
                    "This strategy looks for an overstretched move that may snap back toward the mean.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a pullback trade, not continuation.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• touch or close outside the bands\n"
                    "• RSI overbought / oversold gate\n"
                    "• re-entry back inside the band range\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If exhaustion fades and price comes back inside the range, the mean-reversion idea becomes stronger.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "Do not treat it as a blind entry. A strong trend can still keep stretching longer."
                ),
            },
            "rsi_bollinger_touch": {
                "ru": (
                    "🎯 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ждёт, когда RSI уже в экстремуме, а цена одновременно касается 30-периодной полосы Боллинджера.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь ловить растянутые движения у края полос, но без сигналов в боковом шуме.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• RSI ниже 30 или выше 70\n"
                    "• касание нижней или верхней 30-периодной полосы\n"
                    "• анти-sideways фильтр против плоского рынка\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если рынок не в боковике, а цена растянулась к краю полосы, появляется идея на реакцию от этого экстремума.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Лучше всего работает там, где у рынка есть структура. Если цена просто пилит вокруг средней, сигнал лучше пропустить."
                ),
                "en": (
                    "🎯 <b>Step 1. Core idea</b>\n"
                    "This strategy waits for RSI to hit an extreme while price tags the 30-period Bollinger Band.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want stretched band-touch reactions without flat sideways chop.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• RSI below 30 or above 70\n"
                    "• a tag of the lower or upper 30-period band\n"
                    "• an anti-sideways filter against flat conditions\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If the market is not trapped in chop and price is stretched into the band edge, the setup is looking for a reaction from that extreme.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "It works best when the market still has structure. If price is just ping-ponging around the mean, skip it."
                ),
            },
            "vwap": {
                "ru": (
                    "⚖️ <b>Шаг 1. В чём идея</b>\n"
                    "VWAP показывает среднюю цену дня. Стратегия помогает понять, кто сейчас сильнее внутри дня.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит для intraday-торговли, когда важен контекст текущей сессии.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• возврат VWAP снизу вверх\n"
                    "• уход обратно под VWAP\n"
                    "• intraday-контекст текущего дня\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Выше VWAP → long-приоритет.\n"
                    "Ниже VWAP → short-приоритет.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Это больше про контекст и смещение дня, чем про ловлю экстремумов. Особенно полезно для быстрых intraday-решений."
                ),
                "en": (
                    "⚖️ <b>Step 1. Core idea</b>\n"
                    "VWAP acts like the session fair price. This strategy helps you read who is stronger during the day.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best for intraday trading when session context matters.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• reclaim back above VWAP\n"
                    "• rejection back below VWAP\n"
                    "• intraday context for the current UTC day\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "Above VWAP → long bias.\n"
                    "Below VWAP → short bias.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "This is more about intraday bias and context than extreme reversals. Very useful for fast session decisions."
                ),
            },
            "false_breakout": {
                "ru": (
                    "🪤 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ловит ложный пробой, когда рынок выносит стопы за уровень и быстро возвращается назад.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь искать разворот после выноса, а не поздний вход в пробой.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• вынос локального хая / лоя\n"
                    "• закрытие обратно внутрь диапазона\n"
                    "• раннее подтверждение разворота\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Ложный пробой хая → short-приоритет.\n"
                    "Ложный пробой лоя → long-приоритет.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Лучше всего работает после явного выноса ликвидности. Если возврат слабый, лучше не торопиться."
                ),
                "en": (
                    "🪤 <b>Step 1. Core idea</b>\n"
                    "This strategy looks for stop sweeps beyond a level followed by a fast return back inside.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want reversal after a liquidity sweep, not a late breakout entry.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• sweep above a local high or below a local low\n"
                    "• close back inside the range\n"
                    "• early reversal confirmation\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "False high break → short priority.\n"
                    "False low break → long priority.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "It works best after a clear liquidity sweep. If the return is weak, avoid rushing into the trade."
                ),
            },
            "rsi": {
                "ru": (
                    "📊 <b>Шаг 1. В чём идея</b>\n"
                    "Это базовый alert на перегрев или перепроданность. Он показывает, что движение уже стало экстремальным.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь быстро видеть монеты, где рынок уже слишком горячий или слишком слабый.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• перекупленность\n"
                    "• перепроданность\n"
                    "• закрытую свечу на выбранном таймфрейме\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Сигнал говорит, что есть экстремум. Это повод посмотреть рынок внимательнее, а не входить вслепую.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Хорошо подходит как первый фильтр. Лучше совмещать с уровнем, структурой цены или AI-разбором."
                ),
                "en": (
                    "📊 <b>Step 1. Core idea</b>\n"
                    "This is the simplest stretched-market alert. It tells you price may already be overheated or washed out.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a fast watchlist of coins that are already extended.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• overbought conditions\n"
                    "• oversold conditions\n"
                    "• closed candle confirmation on the selected timeframe\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "The signal means an extreme exists. It is a reason to inspect the chart, not a blind entry.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "Great as a first filter. It works better when combined with levels, structure, or AI analysis."
                ),
            },
            "rsi_divergence": {
                "ru": (
                    "🧭 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ищет ситуацию, когда цена делает новый хай или лоу, а RSI уже не подтверждает это движение.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если нужен более структурный сигнал на возможный разворот после ослабления импульса.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• первый swing ниже 30 или выше 70\n"
                    "• откат между двумя pushes\n"
                    "• второй экстремум цены с более слабым RSI\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если цена ещё обновила экстремум, а RSI уже нет, значит импульс слабеет и шанс на разворот растёт.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Лучше работает, когда между двумя swings есть понятный откат. В рваном шуме дивергенции быстро теряют смысл."
                ),
                "en": (
                    "🧭 <b>Step 1. Core idea</b>\n"
                    "This strategy looks for price making a fresh high or low while RSI no longer confirms the extension.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a more structured reversal signal after momentum starts weakening.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• a first swing below 30 or above 70\n"
                    "• a pullback between the two pushes\n"
                    "• a second price extreme with weaker RSI confirmation\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If price still made a new extreme but RSI did not, momentum is fading and reversal odds improve.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "It works best when the structure between the two swings is clean. In noisy chop, divergence loses meaning fast."
                ),
            },
            OKAK_STRATEGY_KEY: {
                "ru": (
                    "🧪 <b>Шаг 1. В чём идея</b>\n"
                    "OKAK — это отдельный строгий RSI-режим только для перекупленности и short-идей.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если нужен очень узкий shortlist по перегретым монетам, а не весь обычный RSI-поток.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• перекупленность на закрытой свече\n"
                    "• минимум 2 из 3 условий: объём 5-20M или 50M+, RSI 76+, score 90+\n"
                    "• short-сценарий после перегрева\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Это shortlist для short-реакции. В начале алерта сразу показаны RSI, score и объём, чтобы качество сигнала читалось с первого экрана.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Сначала смотри, какие 2 из 3 фильтров совпали. Потом уже решай, есть ли по цене нормальное подтверждение для short-входа."
                ),
                "en": (
                    "🧪 <b>Step 1. Core idea</b>\n"
                    "OKAK is a separate stricter RSI mode built only for overbought short ideas.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a very narrow shortlist of overheated names instead of the full RSI stream.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• an overbought close\n"
                    "• at least 2 of 3 conditions: 5-20M or 50M+ volume, RSI 76+, score 90+\n"
                    "• a short-side exhaustion setup\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "This is a short-side shortlist. The alert header shows RSI, score, and volume first so the quality is clear immediately.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "First check which 2 of the 3 filters matched. Then decide whether price action still gives a clean short confirmation."
                ),
            },
            EKEK_STRATEGY_KEY: {
                "ru": (
                    "🌊 <b>Шаг 1. В чём идея</b>\n"
                    "EKEK — это импульсная версия OKAK. Здесь нужны те же short-условия, но сигнал идёт только когда рост был резким, а не постепенным.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь отдельно смотреть перегретые импульсы и резкие выносы вверх перед short-реакцией.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• перекупленность на закрытой свече\n"
                    "• минимум 2 из 3 условий OKAK: объём 5-20M или 50M+, RSI 76+, score 90+\n"
                    "• свежий резкий импульс за последние свечи, а не плавный подъём\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если это EKEK, значит бот увидел именно разгон цены. В начале алерта это помечено сразу.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Сначала смотри на силу импульса и исторический контекст. Потом уже решай, есть ли нормальное подтверждение для short-входа."
                ),
                "en": (
                    "🌊 <b>Step 1. Core idea</b>\n"
                    "EKEK is the impulse version of OKAK. It keeps the same short-side logic, but only alerts when the rise was sharp instead of gradual.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a separate stream for overheated impulse bursts before a short reaction.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• an overbought close\n"
                    "• at least 2 of 3 OKAK conditions: 5-20M or 50M+ volume, RSI 76+, score 90+\n"
                    "• a fresh sharp impulse over the last candles instead of a gradual climb\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If it is EKEK, the bot saw a real acceleration burst. The alert tells you that from the first line.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "First judge the burst and historical context. Then decide whether price action still gives a clean short confirmation."
                ),
            },
            "bollinger": {
                "ru": (
                    "🎈 <b>Шаг 1. В чём идея</b>\n"
                    "Стратегия ищет возврат цены обратно в канал Bollinger. Это мягкий контртрендовый стиль без жёсткого RSI-гейта.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если хочешь более спокойный re-entry в диапазон без строгих условий MR-версии.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• выход за полосу\n"
                    "• возврат обратно в диапазон\n"
                    "• мягкую mean reversion-логику\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Если цена вернулась в канал, возможен ход обратно к средней линии.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Обычно лучше работает на спокойном рынке, чем в жёстком импульсе без откатов."
                ),
                "en": (
                    "🎈 <b>Step 1. Core idea</b>\n"
                    "This strategy looks for price returning back inside Bollinger Bands. It is a softer mean-reversion style without the stricter RSI gate.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want a calmer re-entry setup without the stricter MR rules.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• move outside the band\n"
                    "• re-entry back into the range\n"
                    "• softer mean-reversion behavior\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "If price returns into the channel, a move back toward the mean becomes possible.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "It usually works better in calmer markets than in one-sided impulse moves."
                ),
            },
            "gold": {
                "ru": (
                    "🥇 <b>Шаг 1. В чём идея</b>\n"
                    "Это отдельный поток только по золоту. Он нужен, если хочешь держать XAUUSD отдельно от крипты.\n\n"
                    "✅ <b>Шаг 2. Когда подходит</b>\n"
                    "Подходит, если интересует именно золото и не хочется смешивать его с крипто-сигналами.\n\n"
                    "👀 <b>Шаг 3. Что бот проверяет</b>\n"
                    "• текущее движение XAUUSD\n"
                    "• RSI-экстремумы по золоту\n"
                    "• отдельные фильтры и уведомления\n\n"
                    "📌 <b>Шаг 4. Как читать сигнал</b>\n"
                    "Любой сигнал здесь относится только к золоту, без примеси крипто-логики.\n\n"
                    "🛠 <b>Шаг 5. Как использовать</b>\n"
                    "Полезно, если у тебя отдельный режим под XAUUSD и нужны свои quiet hours, delivery и фильтры."
                ),
                "en": (
                    "🥇 <b>Step 1. Core idea</b>\n"
                    "This is a gold-only flow. It is built for XAUUSD without mixing it with crypto logic.\n\n"
                    "✅ <b>Step 2. When it fits</b>\n"
                    "Best when you want dedicated gold alerts and separate filters.\n\n"
                    "👀 <b>Step 3. What the bot checks</b>\n"
                    "• current XAUUSD movement\n"
                    "• gold RSI extremes\n"
                    "• separate filters and delivery rules\n\n"
                    "📌 <b>Step 4. How to read the signal</b>\n"
                    "Every signal here belongs to gold only, without crypto overlap.\n\n"
                    "🛠 <b>Step 5. How to use it</b>\n"
                    "Useful when you keep a separate XAUUSD workflow with its own quiet hours, delivery, and filters."
                ),
            },
        }
        description = descriptions.get(strategy_key, descriptions["rsi"])[language_code]
        if language_code == "ru":
            footer = (
                "⚙️ После guide можно вернуться на экран стратегии и спокойно докрутить фильтры, "
                "уведомления и быструю настройку под себя."
            )
            title = f"<b>📘 Гайд по стратегии • {escape_html(label)}</b>"
        else:
            footer = (
                "⚙️ After the guide, go back to the strategy screen and fine-tune filters, "
                "delivery, and quick setup your way."
            )
            title = f"<b>📘 Strategy Guide • {escape_html(label)}</b>"
        return (
            f"{title}\n\n"
            f"{description}\n\n"
            f"{footer}"
        )

    def _main_hub_text(self, settings: UserSettingsRecord, *, language_code: str) -> str:
        if language_code == "ru":
            return "<b>✨ Syndicate PRO</b>\n\nТвой персональный взгляд на рынок"
        return "<b>✨ Syndicate PRO</b>\n\nYour personal market view"

    def _workspace_label(self, workspace_key: str | None, *, language_code: str) -> str:
        labels = {
            "scalp": "Scalp" if language_code == "en" else "Скальп",
            "intraday": "Intraday" if language_code == "en" else "Интрадей",
            "swing": "Swing" if language_code == "en" else "Свинг",
            "gold_focus": "Gold Focus" if language_code == "en" else "Фокус на золоте",
            "low_noise": "Low Noise" if language_code == "en" else "Мало шума",
            "aggressive": "Aggressive" if language_code == "en" else "Агрессивный",
            "saved": "Saved" if language_code == "en" else "Сохранённый",
        }
        normalized = str(workspace_key or "").strip().lower()
        if normalized in labels:
            return labels[normalized]
        return "Adaptive" if language_code == "en" else "Адаптивный"

    def _saved_workspace_available(self, settings: UserSettingsRecord) -> bool:
        payload = settings.saved_workspace_payload if isinstance(settings.saved_workspace_payload, dict) else {}
        snapshot = payload.get("snapshot")
        return isinstance(snapshot, dict) and bool(snapshot)

    def _resume_context_label(self, settings: UserSettingsRecord, *, language_code: str) -> str:
        current_context = str(settings.current_context or "").strip().lower()
        current_strategy_context = str(settings.current_strategy_context or "").strip().lower()
        if current_strategy_context:
            return self._strategy_label(current_strategy_context, language_code=language_code)
        if current_context.startswith("strategy_"):
            return self._strategy_label(current_context.split("_", maxsplit=1)[1], language_code=language_code)
        mapping = {
            "watchhub": "Watchlist" if language_code == "en" else "Вотчлист",
            "watchlist": "Watchlist" if language_code == "en" else "Вотчлист",
            "themes": "Watchlist" if language_code == "en" else "Вотчлист",
            "deliveryhub": "Alerts" if language_code == "en" else "Уведомления",
            "settingshub": "Settings" if language_code == "en" else "Настройки",
            "signalshub": "Signals" if language_code == "en" else "Сигналы",
            "results_hub": "Results" if language_code == "en" else "Результаты",
            "statshub": "Results" if language_code == "en" else "Результаты",
            "analyze": "AI Desk" if language_code == "en" else "AI-разбор",
            "aihub": "AI Desk" if language_code == "en" else "AI-разбор",
        }
        return mapping.get(current_context, "Home" if language_code == "en" else "Главная")

    def _is_strategy_origin(self, origin: str | None, *, default: str = "menu") -> bool:
        return self._normalize_hub_origin(origin, default=default) == "strategy"

    async def _settings_for_hub_section(
        self,
        telegram_user_id: int,
        *,
        section: str,
        origin: str | None = None,
        shell_settings: UserSettingsRecord | None = None,
    ) -> tuple[UserSettingsRecord, str]:
        if self.bot_kind == "premium":
            base_settings = shell_settings or await self._ensure_shell_settings(telegram_user_id)
        else:
            base_settings = shell_settings or await self._ensure_user_settings(telegram_user_id)
        resolved_origin = self._normalize_hub_origin(
            origin if origin is not None else self._hub_origin_for(telegram_user_id, section=section),
            default="menu",
        )
        if self.bot_kind == "premium" and resolved_origin == "strategy":
            strategy_key = self._resolved_active_strategy_key(base_settings)
            if strategy_key is not None:
                strategy_settings = await self._load_strategy_settings(
                    telegram_user_id,
                    shell_settings=base_settings,
                    strategy_key=strategy_key,
                )
                return strategy_settings, resolved_origin
        return base_settings, resolved_origin

    async def _ensure_shell_settings(
        self,
        telegram_user_id: int,
        *,
        preferred_language: str | None = None,
    ) -> UserSettingsRecord:
        settings = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        if settings is not None:
            if self.bot_kind == "premium":
                settings = await self._migrate_gold_substrategies_if_needed(settings)
                settings = await self._migrate_admin_daily_rsi80_if_needed(settings)
                settings = await self._migrate_admin_reversal_strategies_if_needed(settings)
            return settings
        await self._ensure_user_settings(telegram_user_id, preferred_language=preferred_language)
        created = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        assert created is not None
        return created

    async def _migrate_gold_substrategies_if_needed(
        self,
        shell_settings: UserSettingsRecord,
    ) -> UserSettingsRecord:
        if self.bot_kind != "premium":
            return shell_settings
        enabled = tuple(key for key in shell_settings.enabled_strategy_keys if key in self.STRATEGY_KEYS)
        if GOLD_MASTER_STRATEGY_KEY not in enabled:
            return shell_settings
        if any(key in GOLD_SUBSTRATEGY_KEY_SET for key in enabled):
            return shell_settings
        migrated_enabled = tuple(dict.fromkeys([*enabled, *GOLD_SUBSTRATEGY_KEYS]))
        for strategy_key in GOLD_SUBSTRATEGY_KEYS:
            await self._ensure_premium_strategy_settings(
                shell_settings.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
        await self.repository.upsert_user_settings(
            telegram_user_id=shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=shell_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=shell_settings.followup_delivery_enabled,
            gold_alerts_enabled=shell_settings.gold_alerts_enabled,
            language_code=shell_settings.language_code,
            signal_profile=shell_settings.signal_profile,
            base_signal_profile=shell_settings.base_signal_profile,
            preferred_min_score=shell_settings.preferred_min_score,
            min_quote_volume=shell_settings.min_quote_volume,
            rsi_oversold=shell_settings.rsi_oversold,
            rsi_overbought=shell_settings.rsi_overbought,
            direction_filter=shell_settings.direction_filter,
            watchlist_only=shell_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=shell_settings.delivery_mode,
            delivery_mode_changed_at=shell_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=shell_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=shell_settings.quiet_hours_end_minute,
            snooze_until=shell_settings.snooze_until,
            snooze_started_at=shell_settings.snooze_started_at,
            snooze_label=shell_settings.snooze_label,
            last_resume_summary_at=shell_settings.last_resume_summary_at,
            last_digest_sent_at=shell_settings.last_digest_sent_at,
            last_daily_recap_at=shell_settings.last_daily_recap_at,
            last_weekly_recap_at=shell_settings.last_weekly_recap_at,
            active_watchlist_theme=shell_settings.active_watchlist_theme,
            active_custom_theme_name=shell_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at,
            enabled_strategy_keys=migrated_enabled,
            active_strategy_key=shell_settings.active_strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
            current_context=shell_settings.current_context,
            current_strategy_context=shell_settings.current_strategy_context,
            current_set_id=shell_settings.current_set_id,
            timezone_name=shell_settings.timezone_name,
            strategy_preferences=shell_settings.strategy_preferences,
        )
        refreshed = await self.repository.get_user_settings(
            shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
        )
        assert refreshed is not None
        return refreshed

    async def _migrate_admin_daily_rsi80_if_needed(
        self,
        shell_settings: UserSettingsRecord,
    ) -> UserSettingsRecord:
        if self.bot_kind != "premium":
            return shell_settings
        user = await self._get_private_user(shell_settings.telegram_user_id)
        if user is None or not user.is_admin:
            return shell_settings

        strategy_key = "daily_rsi_80"
        strategy_settings = await self._ensure_premium_strategy_settings(
            shell_settings.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        enabled = list(self._enabled_strategy_keys(shell_settings))
        needs_enabled_key = strategy_key not in enabled
        needs_direct_delivery = not strategy_settings.direct_signal_delivery_enabled
        if not needs_enabled_key and not needs_direct_delivery:
            return shell_settings

        if needs_enabled_key:
            enabled.append(strategy_key)
        await self._save_premium_strategy_settings_record(
            strategy_settings,
            direct_signal_delivery_enabled=True,
        )
        await self.repository.upsert_user_settings(
            telegram_user_id=shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=shell_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=shell_settings.followup_delivery_enabled,
            gold_alerts_enabled=shell_settings.gold_alerts_enabled,
            language_code=shell_settings.language_code,
            signal_profile=shell_settings.signal_profile,
            base_signal_profile=shell_settings.base_signal_profile,
            preferred_min_score=shell_settings.preferred_min_score,
            min_quote_volume=shell_settings.min_quote_volume,
            rsi_oversold=shell_settings.rsi_oversold,
            rsi_overbought=shell_settings.rsi_overbought,
            direction_filter=shell_settings.direction_filter,
            watchlist_only=shell_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=shell_settings.delivery_mode,
            delivery_mode_changed_at=shell_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=shell_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=shell_settings.quiet_hours_end_minute,
            snooze_until=shell_settings.snooze_until,
            snooze_started_at=shell_settings.snooze_started_at,
            snooze_label=shell_settings.snooze_label,
            last_resume_summary_at=shell_settings.last_resume_summary_at,
            last_digest_sent_at=shell_settings.last_digest_sent_at,
            last_daily_recap_at=shell_settings.last_daily_recap_at,
            last_weekly_recap_at=shell_settings.last_weekly_recap_at,
            active_watchlist_theme=shell_settings.active_watchlist_theme,
            active_custom_theme_name=shell_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at,
            enabled_strategy_keys=tuple(enabled),
            active_strategy_key=shell_settings.active_strategy_key or strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
            current_context=shell_settings.current_context,
            current_strategy_context=shell_settings.current_strategy_context,
            current_set_id=shell_settings.current_set_id,
            timezone_name=shell_settings.timezone_name,
            strategy_preferences=shell_settings.strategy_preferences,
            display_mode=shell_settings.display_mode,
            active_workspace=shell_settings.active_workspace,
            saved_workspace_payload=shell_settings.saved_workspace_payload,
            personalization=shell_settings.personalization,
            delivery_rules=shell_settings.delivery_rules,
        )
        refreshed = await self.repository.get_user_settings(
            shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
        )
        assert refreshed is not None
        return refreshed

    async def _migrate_admin_reversal_strategies_if_needed(
        self,
        shell_settings: UserSettingsRecord,
    ) -> UserSettingsRecord:
        if self.bot_kind != "premium":
            return shell_settings
        user = await self._get_private_user(shell_settings.telegram_user_id)
        if user is None or not user.is_admin:
            return shell_settings

        personalization = dict(shell_settings.personalization or {})
        rollout_state_raw = personalization.get("admin_strategy_rollouts")
        rollout_state = (
            dict(rollout_state_raw)
            if isinstance(rollout_state_raw, dict)
            else {}
        )
        if rollout_state.get(ADMIN_REVERSAL_ROLLOUT_MARKER):
            return shell_settings

        balanced_default_score = self._profile_defaults("balanced")[0]
        enabled = list(self._enabled_strategy_keys(shell_settings))
        enabled_changed = False
        strategy_changed = False

        for strategy_key in ADMIN_REVERSAL_ROLLOUT_STRATEGIES:
            strategy_settings = await self._ensure_premium_strategy_settings(
                shell_settings.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            should_enable_strategy = (
                strategy_key in enabled
                or strategy_key in {"rsi_bollinger_touch", "rsi_divergence"}
            )
            if should_enable_strategy and strategy_key not in enabled:
                enabled.append(strategy_key)
                enabled_changed = True
            if not should_enable_strategy:
                continue

            desired_score = PREMIUM_STRATEGY_DEFAULT_MIN_SCORES.get(
                strategy_key,
                strategy_settings.preferred_min_score or balanced_default_score,
            )
            current_score = (
                strategy_settings.preferred_min_score
                if strategy_settings.preferred_min_score is not None
                else balanced_default_score
            )
            needs_score_rebalance = current_score >= balanced_default_score
            needs_direct_delivery = not strategy_settings.direct_signal_delivery_enabled
            if not needs_direct_delivery and not needs_score_rebalance:
                continue
            await self._save_premium_strategy_settings_record(
                strategy_settings,
                direct_signal_delivery_enabled=True,
                preferred_min_score=desired_score if needs_score_rebalance else None,
            )
            strategy_changed = True

        personalization["admin_strategy_rollouts"] = {
            **rollout_state,
            ADMIN_REVERSAL_ROLLOUT_MARKER: utc_now().isoformat(),
        }
        if not enabled_changed and not strategy_changed and personalization == shell_settings.personalization:
            return shell_settings
        await self.repository.upsert_user_settings(
            telegram_user_id=shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=shell_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=shell_settings.followup_delivery_enabled,
            gold_alerts_enabled=shell_settings.gold_alerts_enabled,
            language_code=shell_settings.language_code,
            signal_profile=shell_settings.signal_profile,
            base_signal_profile=shell_settings.base_signal_profile,
            preferred_min_score=shell_settings.preferred_min_score,
            min_quote_volume=shell_settings.min_quote_volume,
            rsi_oversold=shell_settings.rsi_oversold,
            rsi_overbought=shell_settings.rsi_overbought,
            direction_filter=shell_settings.direction_filter,
            watchlist_only=shell_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=shell_settings.delivery_mode,
            delivery_mode_changed_at=shell_settings.delivery_mode_changed_at,
            quiet_hours_start_minute=shell_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=shell_settings.quiet_hours_end_minute,
            snooze_until=shell_settings.snooze_until,
            snooze_started_at=shell_settings.snooze_started_at,
            snooze_label=shell_settings.snooze_label,
            last_resume_summary_at=shell_settings.last_resume_summary_at,
            last_digest_sent_at=shell_settings.last_digest_sent_at,
            last_daily_recap_at=shell_settings.last_daily_recap_at,
            last_weekly_recap_at=shell_settings.last_weekly_recap_at,
            active_watchlist_theme=shell_settings.active_watchlist_theme,
            active_custom_theme_name=shell_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at,
            enabled_strategy_keys=tuple(enabled),
            active_strategy_key=shell_settings.active_strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
            current_context=shell_settings.current_context,
            current_strategy_context=shell_settings.current_strategy_context,
            current_set_id=shell_settings.current_set_id,
            timezone_name=shell_settings.timezone_name,
            strategy_preferences=shell_settings.strategy_preferences,
            display_mode=shell_settings.display_mode,
            active_workspace=shell_settings.active_workspace,
            saved_workspace_payload=shell_settings.saved_workspace_payload,
            personalization=personalization,
            delivery_rules=shell_settings.delivery_rules,
        )
        refreshed = await self.repository.get_user_settings(
            shell_settings.telegram_user_id,
            bot_kind=self.bot_kind,
        )
        assert refreshed is not None
        return refreshed

    async def _save_shell_settings_only(
        self,
        telegram_user_id: int,
        *,
        current_settings: UserSettingsRecord,
        direct_signal_delivery_enabled: bool | None = None,
        followup_delivery_enabled: bool | None = None,
        delivery_mode: str | None = None,
        delivery_mode_changed_at=...,
        quiet_hours_start_minute=...,
        quiet_hours_end_minute=...,
        snooze_until=...,
        snooze_started_at=...,
        snooze_label=...,
    ) -> UserSettingsRecord:
        await self.repository.upsert_user_settings(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=(
                current_settings.direct_signal_delivery_enabled
                if direct_signal_delivery_enabled is None
                else direct_signal_delivery_enabled
            ),
            followup_delivery_enabled=(
                current_settings.followup_delivery_enabled
                if followup_delivery_enabled is None
                else followup_delivery_enabled
            ),
            gold_alerts_enabled=current_settings.gold_alerts_enabled,
            language_code=current_settings.language_code,
            signal_profile=current_settings.signal_profile,
            base_signal_profile=current_settings.base_signal_profile,
            preferred_min_score=current_settings.preferred_min_score,
            min_quote_volume=current_settings.min_quote_volume,
            rsi_oversold=current_settings.rsi_oversold,
            rsi_overbought=current_settings.rsi_overbought,
            direction_filter=current_settings.direction_filter,
            watchlist_only=current_settings.watchlist_only,
            menu_collapsed=current_settings.menu_collapsed,
            delivery_mode=current_settings.delivery_mode if delivery_mode is None else delivery_mode,
            delivery_mode_changed_at=delivery_mode_changed_at,
            quiet_hours_start_minute=quiet_hours_start_minute,
            quiet_hours_end_minute=quiet_hours_end_minute,
            snooze_until=snooze_until,
            snooze_started_at=snooze_started_at,
            snooze_label=snooze_label,
            last_resume_summary_at=current_settings.last_resume_summary_at,
            last_digest_sent_at=current_settings.last_digest_sent_at,
            last_daily_recap_at=current_settings.last_daily_recap_at,
            last_weekly_recap_at=current_settings.last_weekly_recap_at,
            active_watchlist_theme=current_settings.active_watchlist_theme,
            active_custom_theme_name=current_settings.active_custom_theme_name,
            onboarding_completed_at=current_settings.onboarding_completed_at,
            enabled_strategy_keys=current_settings.enabled_strategy_keys,
            active_strategy_key=current_settings.active_strategy_key,
            strategy_selector_completed_at=current_settings.strategy_selector_completed_at,
            strategy_preferences=current_settings.strategy_preferences,
        )
        refreshed = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        assert refreshed is not None
        return self._store_cached_settings(refreshed)

    async def _apply_delivery_settings_to_enabled_strategies(
        self,
        user: PrivateBotUserRecord,
        *,
        shell_settings: UserSettingsRecord,
        direct_signal_delivery_enabled: bool | None = None,
        followup_delivery_enabled: bool | None = None,
        delivery_mode: str | None = None,
        delivery_mode_changed_at=...,
        quiet_hours_start_minute=...,
        quiet_hours_end_minute=...,
        snooze_until=...,
        snooze_started_at=...,
        snooze_label=...,
    ) -> UserSettingsRecord:
        refreshed_shell = await self._save_shell_settings_only(
            user.telegram_user_id,
            current_settings=shell_settings,
            direct_signal_delivery_enabled=direct_signal_delivery_enabled,
            followup_delivery_enabled=followup_delivery_enabled,
            delivery_mode=delivery_mode,
            delivery_mode_changed_at=delivery_mode_changed_at,
            quiet_hours_start_minute=quiet_hours_start_minute,
            quiet_hours_end_minute=quiet_hours_end_minute,
            snooze_until=snooze_until,
            snooze_started_at=snooze_started_at,
            snooze_label=snooze_label,
        )
        for strategy_key in self._enabled_strategy_keys(refreshed_shell):
            strategy_settings = await self._load_strategy_settings(
                user.telegram_user_id,
                shell_settings=refreshed_shell,
                strategy_key=strategy_key,
            )
            await self._save_user_settings(
                user=user,
                current_settings=strategy_settings,
                direct_signal_delivery_enabled=direct_signal_delivery_enabled,
                followup_delivery_enabled=followup_delivery_enabled,
                delivery_mode=delivery_mode,
                delivery_mode_changed_at=delivery_mode_changed_at,
                quiet_hours_start_minute=quiet_hours_start_minute,
                quiet_hours_end_minute=quiet_hours_end_minute,
                snooze_until=snooze_until,
                snooze_started_at=snooze_started_at,
                snooze_label=snooze_label,
            )
        final_shell = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
        assert final_shell is not None
        return self._store_cached_settings(final_shell)

    async def _global_delivery_display_settings(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord,
        now: datetime,
    ) -> tuple[UserSettingsRecord, bool]:
        enabled_keys = self._enabled_strategy_keys(shell_settings)
        if self.bot_kind != "premium" or not enabled_keys:
            return shell_settings, False
        strategy_settings_list = [
            await self._load_strategy_settings(
                telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            for strategy_key in enabled_keys
        ]
        direct_values = {item.direct_signal_delivery_enabled for item in strategy_settings_list}
        followup_values = {item.followup_delivery_enabled for item in strategy_settings_list}
        mode_values = {str(item.delivery_mode or "instant").strip().lower() for item in strategy_settings_list}
        quiet_pairs = {
            (item.quiet_hours_start_minute, item.quiet_hours_end_minute)
            for item in strategy_settings_list
        }
        aggregate = replace(
            shell_settings,
            delivery_mode=(
                next(iter(mode_values))
                if len(mode_values) == 1
                else str(shell_settings.delivery_mode or "instant")
            ),
            quiet_hours_start_minute=(
                next(iter(quiet_pairs))[0]
                if len(quiet_pairs) == 1
                else shell_settings.quiet_hours_start_minute
            ),
            quiet_hours_end_minute=(
                next(iter(quiet_pairs))[1]
                if len(quiet_pairs) == 1
                else shell_settings.quiet_hours_end_minute
            ),
        )
        mixed = len(direct_values) > 1 or len(followup_values) > 1 or len(mode_values) > 1 or len(quiet_pairs) > 1
        return aggregate, mixed

    def _section_hub_copy(
        self,
        *,
        section: str,
        settings: UserSettingsRecord,
        origin: str,
        language_code: str,
    ) -> tuple[str, str]:
        is_ru = language_code == "ru"
        copy_map = {
            "signals": (
                "📡 Сигналы" if is_ru else "📡 Signals",
                "Живой поток сигналов, follow-up и самые сильные текущие сетапы."
                if is_ru
                else "Live signal flow, follow-ups, and the strongest current opportunities.",
            ),
            "watchlists": (
                "👀 Вотчлист" if is_ru else "👀 Watchlist",
                "Символы, избранное, темы и сохранённые наборы в одном месте."
                if is_ru
                else "Your symbols, favorites, themes, and saved sets in one place.",
            ),
            "delivery": (
                "🔔 Уведомления" if is_ru else "🔔 Notifications",
                "Управляй тем, что приходит, и как именно бот это доставляет."
                if is_ru
                else "Control what you receive and how it reaches you.",
            ),
            "stats": (
                "📊 Результаты" if is_ru else "📊 Results",
                "Смотри итоги, follow-up и то, как сигналы дошли до результата."
                if is_ru
                else "Review outcomes, follow-ups, and how signals evolved.",
            ),
            "ai": (
                "🤖 AI-разбор" if is_ru else "🤖 AI Desk",
                "Ручной разбор по символу, таймфрейму и текущему контексту."
                if is_ru
                else "Manual analysis for symbols, timeframes, and setup context.",
            ),
            "settings": (
                "⚙️ Настройки" if is_ru else "⚙️ Settings",
                "Управляй потоком, привычками и режимом отображения."
                if is_ru
                else "Control your flow, preferences, and default experience.",
            ),
        }
        title, body = copy_map.get(section, copy_map["signals"])
        if self.bot_kind != "premium":
            return title, body
        active_strategy_key = self._resolved_active_strategy_key(settings)
        if self._is_strategy_origin(origin):
            strategy_label = self._strategy_label(active_strategy_key, language_code=language_code)
            scoped_note = (
                "Этот раздел относится только к этой стратегии."
                if language_code == "ru"
                else "This section applies only to this strategy."
            )
            return f"{strategy_label} • {title}", f"{body}\n{scoped_note}"
        global_note = (
            "Этот раздел работает по всем включённым стратегиям."
            if language_code == "ru"
            else "This section works across all enabled strategies."
        )
        return title, f"{body}\n{global_note}"

    def _strategy_signal_setup_text(
        self,
        strategy_key: str,
        *,
        settings: UserSettingsRecord,
        setup_state: _SignalSetupState,
        language_code: str,
        show_gold_controls: bool,
    ) -> str:
        language = normalize_language(language_code)
        title = strategy_quick_setup_label(strategy_key, language_code=language)
        active_mode = strategy_preset_label(
            strategy_key,
            setup_state.base_profile if setup_state.profile == "custom" else setup_state.profile,
            language_code=language,
        )
        intro = {
            "breakout": (
                "Настрой, насколько рано и на каких монетах бот должен брать пробой уровня."
                if language == "ru"
                else "Tune how early and on which markets the bot should accept a breakout."
            ),
            "trend_pullback": (
                "Здесь настраивается, насколько спокойно бот должен ждать откат по тренду."
                if language == "ru"
                else "Tune how patient the bot should be before accepting a trend pullback."
            ),
            "rsi_bollinger_mr": (
                "Это быстрая настройка возврата к средней после выброса цены."
                if language == "ru"
                else "This is the fast setup for mean reversion after an overextended move."
            ),
            "rsi_bollinger_touch": (
                "Здесь настраивается стратегия, где RSI-экстремум совпадает с касанием 30-периодной полосы Боллинджера без sideways-шума."
                if language == "ru"
                else "This setup waits for RSI extremes to tag the 30-period Bollinger Band while avoiding flat sideways noise."
            ),
            "vwap": (
                "Выбери, насколько чисто цена должна работать вокруг VWAP внутри дня."
                if language == "ru"
                else "Choose how clean the intraday action around VWAP should be."
            ),
            "false_breakout": (
                "Настрой, насколько подтвержденным должен быть ложный пробой перед алертом."
                if language == "ru"
                else "Tune how confirmed the false breakout should be before the alert."
            ),
            "rsi": (
                "Управляй тем, насколько рано бот должен показывать перегретые и перепроданные зоны."
                if language == "ru"
                else "Control how early the bot should flag overbought and oversold RSI extremes."
            ),
            "rsi_divergence": (
                "Бот ищет новый экстремум по цене без подтверждения со стороны RSI."
                if language == "ru"
                else "The bot looks for a new price extreme that RSI fails to confirm."
            ),
            "bollinger": (
                "Быстрая настройка для возврата цены обратно в канал Боллинджера."
                if language == "ru"
                else "Fast setup for price moving back inside Bollinger Bands."
            ),
            "gold": (
                "Отдельная настройка именно под XAUUSD без лишних крипто-параметров."
                if language == "ru"
                else "A separate setup for XAUUSD without extra crypto noise."
            ),
        }.get(strategy_key, "")
        mode_label = {
            "breakout": ("Режим пробоя", "Breakout mode"),
            "trend_pullback": ("Режим отката", "Pullback mode"),
            "rsi_bollinger_mr": ("Режим возврата", "Reversion mode"),
            "rsi_bollinger_touch": ("Режим касания", "Touch mode"),
            "vwap": ("Режим VWAP", "VWAP mode"),
            "false_breakout": ("Режим выноса", "Trap mode"),
            "rsi": ("Режим качества", "Quality mode"),
            "rsi_divergence": ("Режим дивергенции", "Divergence mode"),
            "bollinger": ("Режим возврата", "Re-entry mode"),
            "gold": ("Режим золота", "Gold mode"),
        }.get(strategy_key, ("Режим", "Mode"))
        lines = [
            f"<b>🎛 {escape_html(title)}</b>",
            "",
            escape_html(intro),
            "",
            f"• <b>{escape_html(mode_label[0 if language == 'ru' else 1])}</b>: <b>{escape_html(active_mode)}</b>",
            f"• <b>{'Порог качества' if language == 'ru' else 'Quality floor'}</b>: <b>{escape_html(self._score_label(setup_state))}</b>",
        ]
        if setup_state.profile == "custom":
            lines.append(
                f"• <b>{'Ручные правки' if language == 'ru' else 'Manual tweaks'}</b>: <b>{escape_html(ui_text(language, 'status_on'))}</b>"
            )
        if strategy_supports_rsi_mode(strategy_key):
            lines.append(
                f"• <b>{'RSI-гейт' if language == 'ru' else 'RSI gate'}</b>: <b>{escape_html(setup_state.rsi_mode_label)}</b>"
            )
        if strategy_supports_volume(strategy_key):
            lines.append(
                f"• <b>{'Ликвидность' if language == 'ru' else 'Liquidity'}</b>: <b>{escape_html(self._volume_label(setup_state.min_quote_volume))}</b>"
            )
        lines.append(
            f"• <b>{'Направление' if language == 'ru' else 'Direction'}</b>: <b>{escape_html(setup_state.direction_label)}</b>"
        )
        if strategy_supports_universe(strategy_key):
            lines.append(
                f"• <b>{'Охват' if language == 'ru' else 'Universe'}</b>: <b>{escape_html(tracking_scope_label(settings, language_code=language))}</b>"
            )
        if show_gold_controls:
            lines.append(
                f"• <b>{'Золото' if language == 'ru' else 'Gold alerts'}</b>: <b>{escape_html(ui_text(language, 'status_on' if settings.gold_alerts_enabled else 'status_off'))}</b>"
            )
        preference_rows = self._strategy_preference_rows(
            strategy_key,
            settings=settings,
            language_code=language,
        )
        if preference_rows:
            lines.extend(
                [
                    "",
                    f"<b>{'🧩 Тонкая настройка стратегии' if language == 'ru' else '🧩 Strategy fine-tuning'}</b>",
                ]
            )
            for row in preference_rows:
                lines.append(
                    f"• <b>{escape_html(str(row['title']))}</b>: <b>{escape_html(str(row['selected_label']))}</b>"
                )
                lines.append(f"  {escape_html(str(row['selected_help']))}")
        lines.extend(
            [
                "",
                (
                    "⚡ Быстрая настройка ниже проводит только по важным шагам для этой стратегии."
                    if language == "ru"
                    else "⚡ Quick Setup below walks only through the steps that matter for this strategy."
                ),
                (
                    "✨ Ниже уже лежат кнопки именно под эту стратегию: темп, контекст рынка и приоритет follow-up."
                    if language == "ru"
                    else "✨ The rows below are specific to this strategy: pace, market context, and follow-up priority."
                ),
                (
                    "🛠 Custom оставляет ручную подстройку порогов, если хочешь собрать совсем свой шаблон."
                    if language == "ru"
                    else "🛠 Custom still lets you hand-tune the raw thresholds if you want a personal template."
                ),
            ]
        )
        return "\n".join(lines)

    def _is_language_toggle_label(self, normalized_text: str) -> bool:
        labels: set[str] = set()
        for ui_language in ("en", "ru"):
            for language_name in {
                ui_text(ui_language, "language_name"),
                ui_text(ui_language, "language_switch_to"),
                ui_text("en", "language_name"),
                ui_text("ru", "language_name"),
            }:
                labels.add(
                    ui_text(ui_language, "menu_language").format(
                        language=language_name,
                        language_name=language_name,
                    ).casefold()
                )
        return normalized_text in labels or normalized_text.startswith("language:") or normalized_text.startswith("язык:")

    def _profile_label(self, profile: str, language_code: str) -> str:
        key = {
            "conservative": "profile_conservative",
            "balanced": "profile_balanced",
            "aggressive": "profile_aggressive",
            "custom": "profile_custom",
        }.get(profile, "profile_custom")
        return ui_text(language_code, key)

    def _rsi_mode_label(self, mode: str, language_code: str) -> str:
        key = {
            "tight": "rsi_mode_tight",
            "balanced": "rsi_mode_balanced",
            "early": "rsi_mode_early",
            "custom": "rsi_mode_custom",
        }.get(mode, "rsi_mode_custom")
        return ui_text(language_code, key)

    def _direction_label(self, direction_filter: str, language_code: str) -> str:
        key = {
            "both": "direction_both",
            "long": "direction_long",
            "short": "direction_short",
        }.get(direction_filter, "direction_both")
        return ui_text(language_code, key)

    def _signal_direction_label(self, direction: str, language_code: str) -> str:
        if direction == "long":
            return "Лонг" if language_code == "ru" else "Long"
        if direction == "short":
            return "Шорт" if language_code == "ru" else "Short"
        if direction == "oversold":
            return "Перепроданность" if language_code == "ru" else "Oversold"
        if direction == "overbought":
            return "Перекупленность" if language_code == "ru" else "Overbought"
        return "Нейтрально" if language_code == "ru" else "Neutral"

    async def _ensure_user_settings(
        self,
        telegram_user_id: int,
        *,
        preferred_language: str | None = None,
    ) -> UserSettingsRecord:
        cached = self._get_cached_settings(telegram_user_id)
        if cached is not None:
            return cached
        settings = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        if settings is not None:
            if self.bot_kind == "premium":
                settings = await self._migrate_gold_substrategies_if_needed(settings)
                settings = await self._migrate_admin_daily_rsi80_if_needed(settings)
                settings = await self._migrate_admin_reversal_strategies_if_needed(settings)
            if self.bot_kind != "premium":
                return self._store_cached_settings(settings)
            active_strategy_key = self._resolved_active_strategy_key(settings)
            if active_strategy_key is None:
                return self._store_cached_settings(settings)
            return self._store_cached_settings(
                await self._load_strategy_settings(
                    telegram_user_id,
                    shell_settings=settings,
                    strategy_key=active_strategy_key,
                )
            )
        default_score, default_volume, default_oversold, default_overbought = self._profile_defaults("balanced")
        await self.repository.upsert_user_settings(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=False,
            followup_delivery_enabled=(
                self.settings.private_bot_followups_default
                if self.bot_kind == "premium"
                else self.settings.classic_bot_followups_default
            ),
            gold_alerts_enabled=(
                self.settings.private_bot_gold_alerts_default
                if self.bot_kind == "premium"
                else False
            ),
            signal_profile="balanced",
            base_signal_profile="balanced",
            preferred_min_score=default_score,
            min_quote_volume=default_volume,
            rsi_oversold=default_oversold,
            rsi_overbought=default_overbought,
            direction_filter="both",
            watchlist_only=False,
            menu_collapsed=False,
            delivery_mode="instant",
            active_watchlist_theme="custom",
            language_code=normalize_language(preferred_language),
            enabled_strategy_keys=() if self.bot_kind == "premium" else None,
            active_strategy_key=None if self.bot_kind == "premium" else ...,
            strategy_selector_completed_at=None if self.bot_kind == "premium" else ...,
            personalization=default_personalization(),
            delivery_rules=default_delivery_rules(),
        )
        created = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        assert created is not None
        if self.bot_kind == "premium":
            created = await self._migrate_gold_substrategies_if_needed(created)
            created = await self._migrate_admin_daily_rsi80_if_needed(created)
            created = await self._migrate_admin_reversal_strategies_if_needed(created)
        if self.bot_kind != "premium":
            return self._store_cached_settings(created)
        active_strategy_key = self._resolved_active_strategy_key(created)
        if active_strategy_key is None:
            return self._store_cached_settings(created)
        return self._store_cached_settings(
            await self._load_strategy_settings(
                telegram_user_id,
                shell_settings=created,
                strategy_key=active_strategy_key,
            )
        )

    def _rsi_mode_for_values(self, oversold: float, overbought: float) -> str:
        for mode, (mode_oversold, mode_overbought) in self.RSI_MODE_THRESHOLDS.items():
            if abs(oversold - mode_oversold) < 0.001 and abs(overbought - mode_overbought) < 0.001:
                return mode
        return "custom"

    def _resolve_signal_setup_state(
        self,
        settings: UserSettingsRecord | None,
        *,
        language_code: str | None = None,
    ) -> _SignalSetupState:
        language = normalize_language(language_code or self._language_code(settings))
        profile = str((settings.signal_profile if settings is not None else "balanced") or "balanced").strip().lower()
        base_profile = str(
            (settings.base_signal_profile if settings is not None else profile) or "balanced"
        ).strip().lower()
        if base_profile not in {"conservative", "balanced", "aggressive"}:
            base_profile = profile if profile in {"conservative", "balanced", "aggressive"} else "balanced"
        default_score, default_volume, default_oversold, default_overbought = self._profile_defaults(base_profile)
        min_score = int(settings.preferred_min_score) if settings and settings.preferred_min_score is not None else default_score
        min_quote_volume = (
            float(settings.min_quote_volume)
            if settings and settings.min_quote_volume is not None
            else default_volume
        )
        rsi_oversold = (
            float(settings.rsi_oversold)
            if settings and settings.rsi_oversold is not None
            else default_oversold
        )
        rsi_overbought = (
            float(settings.rsi_overbought)
            if settings and settings.rsi_overbought is not None
            else default_overbought
        )
        direction_filter = str((settings.direction_filter if settings is not None else "both") or "both").strip().lower()
        watchlist_only = bool(settings.watchlist_only) if settings is not None else False
        rsi_mode = self._rsi_mode_for_values(rsi_oversold, rsi_overbought)
        if profile not in self.PROFILE_LABELS:
            profile = "custom"
        normalized_direction = direction_filter if direction_filter in self.DIRECTION_LABELS else "both"
        return _SignalSetupState(
            profile=profile,
            profile_label=self._profile_label(profile, language),
            base_profile=base_profile,
            base_profile_label=self._profile_label(base_profile, language),
            min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            rsi_mode=rsi_mode,
            rsi_mode_label=self._rsi_mode_label(rsi_mode, language),
            direction_filter=normalized_direction,
            direction_label=self._direction_label(normalized_direction, language),
            watchlist_only=watchlist_only,
        )

    def _score_label(self, state: _SignalSetupState, *, strong_only: bool = False) -> str:
        if strong_only:
            return f"{self._selection_min_score(state, strong_only=True)}/100"
        return f"{state.min_score}/100"

    def _signal_list_limit(self, *, strong_only: bool) -> int:
        return (
            self.settings.private_bot_strong_signals_limit
            if strong_only
            else min(self.settings.private_bot_recent_signals_limit, 3)
        )

    def _selection_min_score(self, state: _SignalSetupState, *, strong_only: bool) -> int:
        return min(100, state.min_score + 6) if strong_only else state.min_score

    def _volume_label(self, min_quote_volume: float) -> str:
        return f"{format_volume(min_quote_volume)} USDT"

    def _rsi_window_label(self, state: _SignalSetupState) -> str:
        return f"<= {state.rsi_oversold:.0f} / >= {state.rsi_overbought:.0f}"

    def _personalization_state(self, settings: UserSettingsRecord | None) -> dict[str, object]:
        return normalize_personalization(settings.personalization if settings is not None else None)

    def _v2_navigation_enabled(self, settings: UserSettingsRecord | None) -> bool:
        return bool(self._personalization_state(settings).get("ux_v2_enabled", False))

    async def _enable_v2_navigation(
        self,
        user: PrivateBotUserRecord,
        settings: UserSettingsRecord,
    ) -> UserSettingsRecord:
        """Migrate an existing Premium account to the additive V2 shell once."""

        if self.bot_kind != "premium" or self._v2_navigation_enabled(settings):
            return settings
        personalization = self._personalization_state(settings)
        personalization["ux_v2_enabled"] = True
        updated = await self._save_user_settings(
            user=user,
            current_settings=settings,
            personalization=personalization,
            display_mode="simple",
        )
        await self._sync_v2_active_flow(user)
        return updated

    def _delivery_rules_state(self, settings: UserSettingsRecord | None) -> dict[str, object]:
        return normalize_delivery_rules(settings.delivery_rules if settings is not None else None)

    def _strategy_preferences(
        self,
        settings: UserSettingsRecord | None,
        *,
        strategy_key: str | None = None,
    ) -> dict[str, str]:
        target_strategy = resolve_quick_setup_strategy_key(
            strategy_key or self._resolved_active_strategy_key(settings) or "rsi",
        )
        if settings is None:
            return strategy_preference_defaults(target_strategy)
        return normalize_strategy_preferences(
            target_strategy,
            settings.strategy_preferences,
        )

    def _strategy_preference_rows(
        self,
        strategy_key: str,
        *,
        settings: UserSettingsRecord | None,
        language_code: str,
    ) -> list[dict[str, object]]:
        return strategy_preference_controls(
            strategy_key,
            self._strategy_preferences(settings, strategy_key=strategy_key),
            language_code=language_code,
        )

    def _signal_matches_strategy_preferences(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord | None,
        *,
        strategy_key: str,
    ) -> tuple[bool, str]:
        preferences = self._strategy_preferences(settings, strategy_key=strategy_key)
        allowed_timeframes = strategy_allowed_timeframes(strategy_key, preferences)
        if allowed_timeframes and signal.timeframe not in allowed_timeframes:
            return False, "timeframe_focus"
        market_filter = strategy_market_filter(strategy_key, preferences)
        if market_filter.get("key") == "session_focus":
            windows = tuple(market_filter.get("session_windows") or ())
            if windows:
                signal_hour = signal.candle_close_time.hour
                if not any(start_hour <= signal_hour < end_hour for start_hour, end_hour in windows):
                    return False, "session_focus"
        atr_value = float(signal.atr_pct or signal.metadata.get("atr_pct", 0.0) or 0.0)
        atr_min = market_filter.get("atr_min")
        atr_max = market_filter.get("atr_max")
        if isinstance(atr_min, (int, float)) and atr_value > 0.0 and atr_value < float(atr_min):
            return False, "market_mode"
        if isinstance(atr_max, (int, float)) and atr_value > float(atr_max):
            return False, "market_mode"
        return True, "ok"

    def _clear_custom_setup_session(self, telegram_user_id: int) -> None:
        self._custom_setup_sessions.pop(telegram_user_id, None)

    def _custom_setup_direction_label(self, direction_filter: str, language_code: str) -> str:
        return self._direction_label(direction_filter if direction_filter in self.DIRECTION_LABELS else "both", language_code)

    def _custom_setup_prompt_text(
        self,
        session: _CustomSetupSession,
        *,
        language_code: str,
        error_text: str | None = None,
    ) -> str:
        return format_custom_signal_setup_message(
            step=session.step,
            lower_rsi_label=f"{session.rsi_oversold:.0f}",
            upper_rsi_label=f"{session.rsi_overbought:.0f}",
            min_quote_volume_label=self._volume_label(session.min_quote_volume),
            min_score_label=f"{session.min_score}/100",
            direction_label=self._custom_setup_direction_label(session.direction_filter, language_code),
            language_code=language_code,
            error_text=error_text,
        )

    async def _send_custom_setup_prompt(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        error_text: str | None = None,
    ) -> None:
        session = self._custom_setup_sessions.get(user.telegram_user_id)
        if session is None:
            return
        language = self._language_code(current_settings)
        await self._send_or_edit_text(
            chat_id=session.chat_id,
            text=self._custom_setup_prompt_text(session, language_code=language, error_text=error_text),
            reply_markup=build_custom_setup_inline_keyboard(
                language_code=language,
                direction_step=session.step == "direction",
            ),
            edit_message_id=session.prompt_message_id,
        )

    async def _start_custom_setup(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        setup_state = self._resolve_signal_setup_state(current_settings, language_code=self._language_code(current_settings))
        self._custom_setup_sessions[user.telegram_user_id] = _CustomSetupSession(
            chat_id=chat_id or str(user.telegram_user_id),
            prompt_message_id=edit_message_id,
            step="lower_rsi",
            rsi_oversold=setup_state.rsi_oversold,
            rsi_overbought=setup_state.rsi_overbought,
            min_quote_volume=max(setup_state.min_quote_volume, 0.0),
            min_score=max(0, min(setup_state.min_score, 100)),
            direction_filter=setup_state.direction_filter,
        )
        await self._send_custom_setup_prompt(user, current_settings=current_settings)

    async def _cancel_custom_setup(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
    ) -> None:
        session = self._custom_setup_sessions.get(user.telegram_user_id)
        self._clear_custom_setup_session(user.telegram_user_id)
        if session is not None:
            await self._send_signal_setup(
                user,
                chat_id=session.chat_id,
                edit_message_id=session.prompt_message_id,
            )

    def _parse_float_input(self, raw_text: str) -> float | None:
        cleaned = str(raw_text or "").strip().replace(",", ".")
        match = re.search(r"(-?\d+(?:\.\d+)?)", cleaned)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _parse_custom_direction(self, raw_text: str) -> str | None:
        normalized = str(raw_text or "").strip().casefold()
        mapping = {
            "all": "both",
            "both": "both",
            "все": "both",
            "оба": "both",
            "обе": "both",
            "long": "long",
            "лонг": "long",
            "buy": "long",
            "short": "short",
            "шорт": "short",
            "sell": "short",
        }
        return mapping.get(normalized)

    def _custom_setup_navigation_requested(self, normalized_text: str, command_token: str) -> bool:
        if command_token:
            return True
        return any(
            self._matches_ui_label(normalized_text, key)
            for key in (
                "menu_help",
                "menu_signal_setup",
                "menu_watchlist",
                "menu_analyze_symbol",
                "menu_gold_snapshot",
                "menu_latest_signals",
                "menu_market_status",
                "menu_alerts_on",
                "menu_alerts_off",
                "menu_followups_on",
                "menu_followups_off",
                "menu_ai_analysis",
                "menu_results_channel",
                "menu_public_channel",
                "menu_community_chat",
                "menu_my_access",
                "menu_try_pro",
                "menu_continue_pro",
                "menu_pay_pro",
                "menu_renew_pro",
                "menu_hide",
                "menu_open",
            )
        ) or self._is_language_toggle_label(normalized_text)

    async def _handle_active_custom_setup_message(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        text: str,
    ) -> bool:
        session = self._custom_setup_sessions.get(user.telegram_user_id)
        if session is None:
            return False
        language = self._language_code(current_settings)
        normalized = text.strip().casefold()
        if normalized in {"/cancel", "cancel", "отмена"}:
            self._clear_custom_setup_session(user.telegram_user_id)
            await self._send_chat_message(
                chat_id=session.chat_id,
                text=ui_text(language, "callback_custom_cancelled"),
                parse_mode=None,
            )
            await self._send_signal_setup(
                user,
                chat_id=session.chat_id,
                edit_message_id=session.prompt_message_id,
            )
            return True

        error_text: str | None = None
        if session.step == "lower_rsi":
            value = self._parse_float_input(text)
            if value is None or value < 5 or value > 45:
                error_text = (
                    "Нижний RSI должен быть числом от 5 до 45."
                    if language == "ru"
                    else "Lower RSI must be a number from 5 to 45."
                )
            else:
                session.rsi_oversold = value
                session.step = "upper_rsi"
        elif session.step == "upper_rsi":
            value = self._parse_float_input(text)
            if value is None or value < 55 or value > 95 or value <= session.rsi_oversold:
                error_text = (
                    "Верхний RSI должен быть числом от 55 до 95 и выше нижнего RSI."
                    if language == "ru"
                    else "Upper RSI must be a number from 55 to 95 and greater than the lower RSI."
                )
            else:
                session.rsi_overbought = value
                session.step = "volume"
        elif session.step == "volume":
            value = self._parse_float_input(text)
            if value is None or value <= 0 or value > 1000:
                error_text = (
                    "Объем нужно отправить числом в миллионах USDT, например 5 или 7.5."
                    if language == "ru"
                    else "Send volume as a number in millions of USDT, for example 5 or 7.5."
                )
            else:
                session.min_quote_volume = value * 1_000_000.0
                session.step = "score"
        elif session.step == "score":
            value = self._parse_float_input(text)
            if value is None or value < 0 or value > 100:
                error_text = (
                    "Порог качества должен быть числом от 0 до 100."
                    if language == "ru"
                    else "Quality floor must be a number from 0 to 100."
                )
            else:
                session.min_score = int(round(value))
                session.step = "direction"
        elif session.step == "direction":
            parsed_direction = self._parse_custom_direction(text)
            if parsed_direction is None:
                error_text = (
                    "Напиши все, лонг или шорт. Можно просто нажать кнопку ниже."
                    if language == "ru"
                    else "Send all, long, or short. You can also tap a button below."
                )
            else:
                await self._complete_custom_setup(
                    user,
                    current_settings=current_settings,
                    direction_filter=parsed_direction,
                )
                return True

        self._custom_setup_sessions[user.telegram_user_id] = session
        await self._send_custom_setup_prompt(
            user,
            current_settings=current_settings,
            error_text=error_text,
        )
        return True

    async def _complete_custom_setup(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        direction_filter: str,
    ) -> None:
        session = self._custom_setup_sessions.get(user.telegram_user_id)
        if session is None:
            return
        session.direction_filter = direction_filter
        updated = await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile="custom",
            preferred_min_score=int(max(0, min(session.min_score, 100))),
            min_quote_volume=max(session.min_quote_volume, 0.0),
            rsi_oversold=session.rsi_oversold,
            rsi_overbought=session.rsi_overbought,
            direction_filter=direction_filter,
        )
        language = self._language_code(updated)
        await self._send_chat_message(
            chat_id=session.chat_id,
            text=format_custom_signal_setup_saved_message(
                lower_rsi_label=f"{session.rsi_oversold:.0f}",
                upper_rsi_label=f"{session.rsi_overbought:.0f}",
                min_quote_volume_label=self._volume_label(session.min_quote_volume),
                min_score_label=f"{session.min_score}/100",
                direction_label=self._custom_setup_direction_label(direction_filter, language),
                language_code=language,
            ),
            parse_mode="HTML",
        )
        self._clear_custom_setup_session(user.telegram_user_id)
        await self._send_signal_setup(
            user,
            chat_id=session.chat_id,
            edit_message_id=session.prompt_message_id,
        )

    async def _reset_profile_to_base(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
    ) -> None:
        base_profile = str(current_settings.base_signal_profile or "balanced").strip().lower()
        if base_profile not in {"conservative", "balanced", "aggressive"}:
            base_profile = "balanced"
        min_score, min_quote_volume, rsi_oversold, rsi_overbought = self._profile_defaults(base_profile)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile=base_profile,
            base_signal_profile=base_profile,
            preferred_min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            direction_filter="both",
        )

    def _access_state_line(self, state: EffectiveAccessState, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        if state.is_admin:
            return ui_text(language, "access_status_admin")
        if state.access_status == "trial" and state.ends_at is not None:
            timestamp = state.ends_at.astimezone(self.settings.timezone).strftime("%Y-%m-%d %H:%M %Z")
            return (
                ui_text(
                    language,
                    "access_trial_ends",
                    timestamp=timestamp,
                    relative=self._relative_time_label(state.ends_at, language_code=language),
                )
            )
        if state.access_status == "paid" and state.ends_at is not None:
            timestamp = state.ends_at.astimezone(self.settings.timezone).strftime("%Y-%m-%d %H:%M %Z")
            return (
                ui_text(
                    language,
                    "access_paid_until",
                    timestamp=timestamp,
                    relative=self._relative_time_label(state.ends_at, language_code=language),
                )
            )
        if state.access_status == "expired" and state.ends_at is not None:
            return ui_text(
                language,
                "access_expired",
                timestamp=state.ends_at.astimezone(self.settings.timezone).strftime("%Y-%m-%d %H:%M %Z"),
            )
        return ui_text(language, "access_status_free")

    def _relative_time_label(self, dt, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        delta_seconds = int((dt - utc_now()).total_seconds())
        if delta_seconds <= 0:
            return ui_text(language, "relative_ended")
        days, remainder = divmod(delta_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            return ui_text(language, "relative_in_days", days=days, hours=hours)
        if hours > 0:
            return ui_text(language, "relative_in_hours", hours=hours, minutes=minutes)
        return ui_text(language, "relative_in_minutes", minutes=minutes)

    async def _favorite_symbols(self, telegram_user_id: int) -> list[str]:
        if self.bot_kind == "premium":
            settings = await self._ensure_user_settings(telegram_user_id)
            strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
            return await self._favorite_symbols_for_strategy(telegram_user_id, strategy_key)
        entries = await self.repository.list_user_watchlist(telegram_user_id, bot_kind=self.bot_kind)
        return [entry.symbol for entry in entries]

    async def _favorite_symbols_for_strategy(self, telegram_user_id: int, strategy_key: str) -> list[str]:
        if self.bot_kind != "premium":
            return await self._favorite_symbols(telegram_user_id)
        entries = await self.repository.list_premium_strategy_watchlist(
            telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
        )
        return [entry.symbol for entry in entries]

    async def _watchlist_symbols(self, telegram_user_id: int) -> list[str]:
        settings = await self._ensure_user_settings(telegram_user_id)
        strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        return await self._watchlist_symbols_for_strategy(
            telegram_user_id,
            strategy_key=strategy_key,
            settings=settings,
        )

    async def _watchlist_symbols_for_strategy(
        self,
        telegram_user_id: int,
        *,
        strategy_key: str,
        settings: UserSettingsRecord | None = None,
    ) -> list[str]:
        if self.bot_kind != "premium":
            current_settings = settings or await self._ensure_user_settings(telegram_user_id)
            theme_key = str(current_settings.active_watchlist_theme or "custom").strip().lower()
            if theme_key in BUILTIN_WATCHLIST_THEMES:
                return list(BUILTIN_WATCHLIST_THEMES[theme_key])
            if current_settings.active_custom_theme_name:
                theme = await self.repository.get_user_watchlist_theme(
                    telegram_user_id=telegram_user_id,
                    bot_kind=self.bot_kind,
                    theme_name=current_settings.active_custom_theme_name,
                )
                if theme is not None:
                    return await self.repository.list_user_watchlist_theme_symbols(theme.id)
            return await self._favorite_symbols(telegram_user_id)
        effective_settings = settings or await self._load_strategy_settings(
            telegram_user_id,
            shell_settings=(
                await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
                or await self._ensure_user_settings(telegram_user_id)
            ),
            strategy_key=strategy_key,
        )
        theme_key = str(effective_settings.active_watchlist_theme or "custom").strip().lower()
        if theme_key in BUILTIN_WATCHLIST_THEMES:
            return list(BUILTIN_WATCHLIST_THEMES[theme_key])
        if theme_key == "favorites":
            return await self._global_favorite_symbols(telegram_user_id)
        if theme_key == "watchlist":
            return await self._favorite_symbols_for_strategy(telegram_user_id, strategy_key)
        if effective_settings.active_custom_theme_name:
            theme = await self.repository.get_premium_strategy_watchlist_theme(
                telegram_user_id=telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                theme_name=effective_settings.active_custom_theme_name,
            )
            if theme is not None:
                return await self.repository.list_premium_strategy_watchlist_theme_symbols(theme.id)
        return await self._favorite_symbols_for_strategy(telegram_user_id, strategy_key)

    def _set_scope_active(self, settings: UserSettingsRecord | None) -> bool:
        if settings is None:
            return False
        theme_key = str(settings.active_watchlist_theme or "custom").strip().lower()
        return theme_key in BUILTIN_WATCHLIST_THEMES or bool(settings.active_custom_theme_name)

    def _set_scope_button_label(self, settings: UserSettingsRecord, *, language_code: str) -> str:
        if self._set_scope_active(settings):
            return premium_text(
                language_code,
                "scope_set_short",
                theme=self._active_watchlist_theme_label(settings, language_code=language_code),
            )
        return ui_text(language_code, "setup_set_only")

    async def _materialize_watchlist_as_custom(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
    ) -> UserSettingsRecord:
        theme_key = str(current_settings.active_watchlist_theme or "custom").strip().lower()
        if theme_key not in BUILTIN_WATCHLIST_THEMES and current_settings.active_custom_theme_name is None:
            return current_settings
        symbols = await self._watchlist_symbols(user.telegram_user_id)
        if self.bot_kind == "premium":
            await self.repository.replace_premium_strategy_watchlist_symbols(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=self._resolved_active_strategy_key(current_settings) or "rsi",
                symbols=symbols,
            )
        else:
            await self.repository.replace_user_watchlist_symbols(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                symbols=symbols,
            )
        return await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            active_watchlist_theme="custom",
            active_custom_theme_name=None,
        )

    async def _saved_watchlist_themes(self, telegram_user_id: int) -> list[tuple[int, str]]:
        if self.bot_kind == "premium":
            settings = await self._ensure_user_settings(telegram_user_id)
            themes = await self.repository.list_premium_strategy_watchlist_themes(
                telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=self._resolved_active_strategy_key(settings) or "rsi",
            )
        else:
            themes = await self.repository.list_user_watchlist_themes(telegram_user_id, bot_kind=self.bot_kind)
        return [(theme.id, theme.theme_name) for theme in themes]

    def _active_watchlist_theme_label(self, settings: UserSettingsRecord, *, language_code: str) -> str:
        return watchlist_theme_label(
            settings.active_watchlist_theme,
            language_code=language_code,
            custom_theme_name=settings.active_custom_theme_name,
        )

    async def _watchlist_summary(
        self,
        telegram_user_id: int,
        *,
        watchlist_only: bool,
        language_code: str = "en",
    ) -> str:
        language = normalize_language(language_code)
        symbols = (
            await self._watchlist_symbols(telegram_user_id)
            if watchlist_only
            else await self._favorite_symbols(telegram_user_id)
        )
        if not symbols:
            return ui_text(language, "watchlist_empty")
        if watchlist_only:
            return ui_text(language, "watchlist_count_only", count=len(symbols))
        return ui_text(language, "watchlist_count", count=len(symbols))

    def _can_offer_renewal(self, state: EffectiveAccessState) -> bool:
        return not state.is_admin

    def _direction_matches(self, direction_filter: str, signal_direction: str) -> bool:
        if direction_filter == "both":
            return True
        if direction_filter == "long":
            return signal_direction in {"oversold", "long"}
        if direction_filter == "short":
            return signal_direction in {"overbought", "short"}
        return True

    def _signal_quote_volume(self, signal: AlertSignal) -> float:
        return float(signal.quote_volume or signal.day_volume or 0.0)

    def _okak_filter_checks(self, signal: AlertSignal) -> dict[str, bool]:
        quote_volume = self._signal_quote_volume(signal)
        return {
            "preferred_volume_band": 5_000_000.0 <= quote_volume <= 20_000_000.0 or quote_volume >= 50_000_000.0,
            "rsi_76_plus": float(signal.rsi) >= 76.0,
            "score_90_plus": int(signal.score) >= 90,
        }

    def _okak_signal_matches_strategy_rule(self, signal: AlertSignal) -> bool:
        checks = self._okak_filter_checks(signal)
        return sum(1 for passed in checks.values() if passed) >= 2

    def _ekek_impulse_checks(self, signal: AlertSignal) -> dict[str, bool]:
        metadata = signal.metadata
        atr_pct = float(signal.atr_pct or 0.0)
        recent_move_pct = float(metadata.get("ekek_impulse_move_pct") or 0.0)
        recent_range_pct = float(metadata.get("ekek_recent_range_pct") or 0.0)
        impulse_share = float(metadata.get("ekek_impulse_share") or 0.0)
        baseline_move_pct = float(metadata.get("ekek_baseline_move_pct") or 0.0)
        body_expansion_ratio = float(metadata.get("ekek_body_expansion_ratio") or 0.0)
        terminal_acceleration_ratio = float(metadata.get("ekek_terminal_acceleration_ratio") or 0.0)
        volume_expansion_ratio = float(metadata.get("ekek_volume_expansion_ratio") or 0.0)
        impulse_candle_count = float(metadata.get("ekek_impulse_candle_count") or 0.0)
        recent_move_gate = max(atr_pct * 2.4, 0.012)
        recent_range_gate = max(atr_pct * 3.0, 0.016)
        return {
            "strong_recent_move": recent_move_pct >= recent_move_gate,
            "impulse_candle_present": impulse_candle_count >= 1.0,
            "wide_recent_range": recent_range_pct >= recent_range_gate,
            "impulse_is_concentrated": impulse_share >= 0.5,
            "recent_beats_baseline": recent_move_pct >= max(baseline_move_pct * 1.3, recent_move_gate * 0.9),
            "body_expansion": body_expansion_ratio >= 1.45,
            "terminal_acceleration": terminal_acceleration_ratio >= 1.7,
            "volume_expansion": volume_expansion_ratio >= 1.12,
        }

    def _ekek_signal_matches_strategy_rule(self, signal: AlertSignal) -> bool:
        okak_checks = self._okak_filter_checks(signal)
        if sum(1 for passed in okak_checks.values() if passed) < 2:
            return False
        impulse_checks = self._ekek_impulse_checks(signal)
        if not impulse_checks["strong_recent_move"]:
            return False
        if not impulse_checks["impulse_candle_present"]:
            return False
        if not impulse_checks["impulse_is_concentrated"]:
            return False
        if not (impulse_checks["body_expansion"] or impulse_checks["terminal_acceleration"]):
            return False
        optional_impulse_passed = sum(
            1
            for key, passed in impulse_checks.items()
            if key not in {"strong_recent_move", "impulse_candle_present", "impulse_is_concentrated"} and passed
        )
        return optional_impulse_passed >= 2

    async def _watchlist_set(
        self,
        telegram_user_id: int,
        *,
        cache: dict[int, set[str]] | None = None,
    ) -> set[str]:
        strategy_key = None
        if self.bot_kind == "premium":
            settings = await self._ensure_user_settings(telegram_user_id)
            strategy_key = self._resolved_active_strategy_key(settings)
        cache_key = hash((telegram_user_id, strategy_key))
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        symbols = set(await self._watchlist_symbols(telegram_user_id))
        if cache is not None:
            cache[cache_key] = symbols
        return symbols

    def _build_threshold_context(
        self,
        direction: str,
        timeframe: str,
        state: _SignalSetupState,
        *,
        language_code: str = "en",
    ) -> str:
        language = normalize_language(language_code)
        if direction == "long":
            return (
                f"Цена закрылась в пользу лонгового сценария на {timeframe}. Это рабочий бычий триггер, но ему еще нужно развитие."
                if language == "ru"
                else f"Price closed in favor of a long setup on {timeframe}. This is a workable bullish trigger, but it still needs follow-through."
            )
        if direction == "short":
            return (
                f"Цена закрылась в пользу шортового сценария на {timeframe}. Это рабочий медвежий триггер, но ему еще нужно развитие."
                if language == "ru"
                else f"Price closed in favor of a short setup on {timeframe}. This is a workable bearish trigger, but it still needs follow-through."
            )
        if direction == "oversold":
            return ui_text(
                language,
                "threshold_context_oversold",
                oversold=f"{state.rsi_oversold:.0f}",
                timeframe=timeframe,
            )
        if direction == "overbought":
            return ui_text(
                language,
                "threshold_context_overbought",
                overbought=f"{state.rsi_overbought:.0f}",
                timeframe=timeframe,
            )
        return ui_text(
            language,
            "threshold_context_neutral",
            oversold=f"{state.rsi_oversold:.0f}",
            overbought=f"{state.rsi_overbought:.0f}",
            timeframe=timeframe,
        )

    def _apply_user_preferences_to_signal(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord | None,
        *,
        watchlist_symbols: set[str] | None = None,
    ) -> AlertSignal:
        language = self._language_code(settings)
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        strategy_key = self._signal_strategy_key(signal)
        if strategy_key in {"rsi", "gold"}:
            context_text = self._build_threshold_context(
                signal.direction,
                signal.timeframe,
                setup_state,
                language_code=language,
            )
        else:
            context_text = str(signal.metadata.get("context_text") or signal.explanation or "").strip()
            if not context_text:
                context_text = self._build_threshold_context(
                    signal.direction,
                    signal.timeframe,
                    setup_state,
                    language_code=language,
                )
        why_received_text = self._why_received_text(
            signal,
            settings,
            watchlist_symbols=watchlist_symbols or set(),
            language_code=language,
        )
        metadata = {
            **signal.metadata,
            "rsi_oversold_threshold": setup_state.rsi_oversold,
            "rsi_overbought_threshold": setup_state.rsi_overbought,
            "context_text": context_text,
            "signal_profile": setup_state.profile,
            "display_mode": getattr(settings, "display_mode", "pro") if settings is not None else "pro",
            "text_layout": (
                "v2_3_signal"
                if self.bot_kind == "premium" and self.destination_kind == "private"
                else str(signal.metadata.get("text_layout") or "").strip()
            ),
            "why_received_text": why_received_text,
            "strategy_preferences": self._strategy_preferences(settings, strategy_key=strategy_key),
            "language_code": language,
        }
        return replace(
            signal,
            explanation=context_text,
            metadata=metadata,
        )

    def _signal_matches_user_settings(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord | None,
        *,
        watchlist_symbols: set[str],
        favorite_symbols: set[str] | None = None,
        seen_symbols: set[str] | None = None,
        is_followup: bool = False,
        strong_only: bool = False,
    ) -> tuple[bool, str]:
        setup_state = self._resolve_signal_setup_state(settings)
        strategy_key = self._signal_strategy_key(signal)
        symbol = normalize_symbol(signal.symbol)
        if setup_state.watchlist_only and symbol not in watchlist_symbols:
            return False, "watchlist_only"
        if not self._direction_matches(setup_state.direction_filter, signal.direction):
            return False, "direction_filter"
        matches_strategy_prefs, strategy_reason = self._signal_matches_strategy_preferences(
            signal,
            settings,
            strategy_key=strategy_key,
        )
        if not matches_strategy_prefs:
            return False, strategy_reason
        if strategy_key == OKAK_STRATEGY_KEY and not self._okak_signal_matches_strategy_rule(signal):
            return False, "okak_rule"
        if strategy_key == EKEK_STRATEGY_KEY and not self._ekek_signal_matches_strategy_rule(signal):
            return False, "ekek_rule"
        if strategy_key not in {OKAK_STRATEGY_KEY, EKEK_STRATEGY_KEY}:
            if self._signal_quote_volume(signal) < setup_state.min_quote_volume:
                return False, "min_quote_volume"
            if signal.score < self._selection_min_score(setup_state, strong_only=strong_only):
                return False, "min_score"
            if signal.direction == "oversold" and signal.rsi > setup_state.rsi_oversold:
                return False, "oversold_threshold"
            if signal.direction == "overbought" and signal.rsi < setup_state.rsi_overbought:
                return False, "overbought_threshold"
        personal_decision = evaluate_personal_filters(
            symbol=symbol,
            timeframe=signal.timeframe,
            strategy_key=strategy_key,
            score=int(signal.score),
            occurred_at=signal.candle_close_time,
            base_min_score=self._selection_min_score(setup_state, strong_only=strong_only),
            personalization=self._personalization_state(settings),
            watchlist_symbols=watchlist_symbols,
            favorite_symbols=favorite_symbols or set(),
            is_gold=self._is_gold_signal(signal),
            is_followup=is_followup,
            seen_symbols=seen_symbols,
        )
        if not personal_decision.allowed:
            return False, personal_decision.reason
        return True, "ok"

    def _alert_record_matches_user_settings(
        self,
        alert: AlertRecord,
        settings: UserSettingsRecord | None,
        *,
        watchlist_symbols: set[str],
        favorite_symbols: set[str] | None = None,
        seen_symbols: set[str] | None = None,
        is_followup: bool = False,
        strong_only: bool = False,
    ) -> tuple[bool, str]:
        signal = self._apply_user_preferences_to_signal(self._signal_from_alert_record(alert), settings)
        return self._signal_matches_user_settings(
            signal,
            settings,
            watchlist_symbols=watchlist_symbols,
            favorite_symbols=favorite_symbols,
            seen_symbols=seen_symbols,
            is_followup=is_followup,
            strong_only=strong_only,
        )

    async def _try_handle_watchlist_input(self, user: PrivateBotUserRecord, text: str) -> bool:
        cleaned = text.strip()
        add_match = re.fullmatch(rf"\+\s*({self._WATCHLIST_SYMBOL_PATTERN})", cleaned)
        remove_match = re.fullmatch(rf"-\s*({self._WATCHLIST_SYMBOL_PATTERN})", cleaned)
        verb_match = re.fullmatch(
            rf"(?i)(watch|add|unwatch|remove|добав[ьй]?|убери|удали)\s+({self._WATCHLIST_SYMBOL_PATTERN})",
            cleaned,
        )
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        action: str | None = None
        raw_symbol: str | None = None
        if add_match:
            action = "add"
            raw_symbol = add_match.group(1)
        elif remove_match:
            action = "remove"
            raw_symbol = remove_match.group(1)
        elif verb_match:
            action = "remove" if verb_match.group(1).casefold() in {"unwatch", "remove", "убери", "удали"} else "add"
            raw_symbol = verb_match.group(2)
        if action is None or raw_symbol is None:
            return False

        symbol = await self._resolve_symbol_input(raw_symbol)
        if not symbol:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_not_recognized"),
                parse_mode=None,
            )
            return True

        watchlist_symbols = await self._favorite_symbols(user.telegram_user_id)
        strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        if action == "add":
            if len(watchlist_symbols) >= self.WATCHLIST_LIMIT and symbol not in watchlist_symbols:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "watchlist_full", limit=self.WATCHLIST_LIMIT),
                    parse_mode=None,
                )
                return True
            if self.bot_kind == "premium":
                added = await self.repository.add_premium_strategy_watchlist_symbol(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    symbol=symbol,
                )
            else:
                added = await self.repository.add_user_watchlist_symbol(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    symbol=symbol,
                )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "watchlist_added" if added else "watchlist_exists", symbol=symbol),
                parse_mode=None,
                reply_markup=build_watchlist_inline_keyboard(
                    language_code=language,
                    symbols=await self._favorite_symbols(user.telegram_user_id),
                    back_callback_data=self._screen_back_callback(
                        user.telegram_user_id,
                        screen="watchlist",
                        default=self._hub_callback_data(
                            "watchhub",
                            origin=self._hub_origin_for(user.telegram_user_id, section="watchlists"),
                        ),
                    ),
                ),
            )
            return True

        if self.bot_kind == "premium":
            removed = await self.repository.remove_premium_strategy_watchlist_symbol(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                symbol=symbol,
            )
        else:
            removed = await self.repository.remove_user_watchlist_symbol(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                symbol=symbol,
            )
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(language, "watchlist_removed" if removed else "watchlist_missing", symbol=symbol),
            parse_mode=None,
            reply_markup=build_watchlist_inline_keyboard(
                language_code=language,
                symbols=await self._favorite_symbols(user.telegram_user_id),
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="watchlist",
                    default=self._hub_callback_data(
                        "watchhub",
                        origin=self._hub_origin_for(user.telegram_user_id, section="watchlists"),
                    ),
                ),
            ),
        )
        return True

    def _parse_symbol_lookup_request(
        self,
        text: str,
        *,
        allow_command_prefix: bool = False,
    ) -> tuple[str, str] | None:
        cleaned = text.strip()
        if allow_command_prefix and cleaned.lower().startswith("/analyze"):
            cleaned = cleaned.split(maxsplit=1)[1].strip() if " " in cleaned else ""
        if not cleaned or cleaned.startswith("/"):
            return None
        parts = cleaned.split()
        if len(parts) > 4:
            return None
        timeframe = self.settings.scan_timeframe
        symbol_parts = parts
        timeframe_candidate = parts[-1].lower()
        if timeframe_candidate in self.LOOKUP_TIMEFRAMES:
            timeframe = timeframe_candidate
            symbol_parts = parts[:-1]
        if not symbol_parts:
            return None
        symbol_candidate = "".join(symbol_parts)
        return symbol_candidate, timeframe

    def _symbol_lookup_candidates(self, raw_symbol: str) -> list[str]:
        raw = str(raw_symbol or "").strip()
        if not raw:
            return []

        raw_variants: list[str] = []
        for candidate in (
            raw,
            raw.replace(" ", ""),
            raw.rsplit(":", maxsplit=1)[-1].strip() if ":" in raw else "",
            raw[1:].strip() if raw.startswith("$") else "",
        ):
            if candidate and candidate not in raw_variants:
                raw_variants.append(candidate)

        ordered: list[str] = []
        seen: set[str] = set()
        queue: list[str] = [normalize_symbol(candidate) for candidate in raw_variants]

        while queue:
            current = str(queue.pop(0) or "").strip().upper()
            if not current or current in seen:
                continue
            seen.add(current)
            ordered.append(current)

            if current.endswith("USDTUSDT") and len(current) > 8:
                queue.append(current[:-4])
            if current.endswith("USDTP") and len(current) > 5:
                queue.append(current[:-1])
            if current.endswith("USDTM") and len(current) > 5:
                queue.append(current[:-1])
            if current.endswith("USDM") and len(current) > 4:
                queue.append(current[:-4])
            for suffix in self._LOOKUP_SUFFIXES:
                if current.endswith(suffix) and len(current) > len(suffix):
                    queue.append(current[:-len(suffix)])
            if current.endswith("USD") and not current.endswith("USDT") and len(current) > 3:
                queue.append(current[:-3])
            if not current.endswith("USDT"):
                queue.append(f"{current}USDT")

        return ordered

    def _should_refresh_symbol_lookup(self, raw_symbol: str) -> bool:
        raw = str(raw_symbol or "").strip().upper()
        if not raw:
            return False
        return any(marker in raw for marker in ("USDT", "USD", "PERP", "SWAP", ":", "/", "-", ".", " "))

    def _gold_market_closed_for_weekend(self, *, now: datetime | None = None) -> bool:
        local_now = (now or utc_now()).astimezone(self.settings.timezone)
        return local_now.weekday() >= 5

    def _next_gold_market_day_label(self, *, language_code: str, now: datetime | None = None) -> str:
        local_now = (now or utc_now()).astimezone(self.settings.timezone)
        next_open = local_now
        while next_open.weekday() != 0:
            next_open += timedelta(days=1)
        if normalize_language(language_code) == "ru":
            return next_open.strftime("%d.%m")
        return next_open.strftime("%Y-%m-%d")

    def _gold_weekend_note(self, *, language_code: str, now: datetime | None = None) -> str:
        return premium_text(
            language_code,
            "gold_weekend_note",
            date=self._next_gold_market_day_label(language_code=language_code, now=now),
        )

    def _gold_weekend_fallback(self, *, language_code: str, now: datetime | None = None) -> str:
        return premium_text(
            language_code,
            "gold_weekend_fallback",
            date=self._next_gold_market_day_label(language_code=language_code, now=now),
        )

    async def _handle_analyze_request(self, user: PrivateBotUserRecord, text: str) -> bool:
        request = self._parse_symbol_lookup_request(text, allow_command_prefix=True)
        if request is None:
            return False
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        symbol_candidate, timeframe = request
        resolved_symbol = await self._resolve_symbol_input(symbol_candidate)
        if not resolved_symbol:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_not_recognized_analyze"),
                parse_mode=None,
                reply_markup=build_analyze_symbol_inline_keyboard(
                    language_code=language,
                    symbols=await self._watchlist_symbols(user.telegram_user_id),
                    back_callback_data=self._screen_back_callback(
                        user.telegram_user_id,
                        screen="analyze",
                        default=self._hub_callback_data(
                            "signalshub",
                            origin=self._hub_origin_for(user.telegram_user_id, section="signals", default="menu"),
                        ),
                    ),
                ),
            )
            return True
        await self._send_symbol_lookup_result(user, symbol_input=resolved_symbol, timeframe=timeframe)
        return True

    async def _send_gold_snapshot(self, user: PrivateBotUserRecord) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not self.settings.gold_alerts_enabled:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_unavailable"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        await self._send_symbol_lookup_card(
            user,
            symbol_input=self.settings.gold_symbol,
            timeframe=self.settings.scan_timeframe,
        )

    async def _try_handle_symbol_lookup(self, user: PrivateBotUserRecord, text: str) -> bool:
        request = self._parse_symbol_lookup_request(text)
        if request is None:
            return False
        symbol_candidate, timeframe = request
        resolved_symbol = await self._resolve_symbol_input(symbol_candidate)
        if not resolved_symbol:
            return False
        await self._send_symbol_lookup_result(user, symbol_input=resolved_symbol, timeframe=timeframe)
        return True

    async def _resolve_symbol_input(self, raw_symbol: str) -> str | None:
        candidates = self._symbol_lookup_candidates(raw_symbol)
        if not candidates:
            return None

        gold_symbol = normalize_symbol(self.settings.gold_symbol)
        if self.settings.gold_alerts_enabled:
            gold_aliases = {gold_symbol, "GOLD"}
            if gold_symbol.endswith("USD") and len(gold_symbol) > 3:
                gold_aliases.add(gold_symbol[:-3])
            for candidate in candidates:
                if candidate in gold_aliases:
                    return gold_symbol

        for force_refresh in (False, True):
            if force_refresh and not self._should_refresh_symbol_lookup(raw_symbol):
                continue
            try:
                active_symbols = set(await self.binance_client.get_active_usdt_symbols(force_refresh=force_refresh))
            except Exception:
                LOGGER.exception("Failed to load active futures symbols while resolving lookup input=%s", raw_symbol)
                continue
            for candidate in candidates:
                if candidate in active_symbols:
                    return candidate

        if self._should_refresh_symbol_lookup(raw_symbol):
            try:
                ticker_symbols = set(await self.binance_client.get_all_ticker_stats(force_refresh=True))
            except Exception:
                LOGGER.exception("Failed to load futures ticker map while resolving lookup input=%s", raw_symbol)
                ticker_symbols = set()
            for candidate in candidates:
                if candidate in ticker_symbols:
                    return candidate
        return None

    async def _send_symbol_lookup_card(
        self,
        user: PrivateBotUserRecord,
        *,
        symbol_input: str,
        timeframe: str,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        resolved_symbol = await self._resolve_symbol_input(symbol_input)
        if not resolved_symbol:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_unavailable"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
            chat_id=str(user.telegram_user_id),
            title=ui_text(language, "loading_symbol_title", symbol=resolved_symbol),
            subtitle=ui_text(language, "loading_symbol_subtitle", timeframe=timeframe),
            language_code=language,
        )
        chart_path = None
        snapshot_now = utc_now()
        try:
            ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=False)
            frame = await self.binance_client.get_klines(
                resolved_symbol,
                timeframe,
                self.settings.klines_limit,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            if enriched.empty:
                raise RuntimeError(f"No candle data available for {resolved_symbol}")
            row = enriched.iloc[-1]
            ticker = ticker_map.get(resolved_symbol)
            live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
            live_rsi = calculate_live_rsi(enriched["close"], live_price, self.settings.rsi_length)
            direction = self._classify_zone_for_thresholds(
                float(row["rsi"]),
                oversold_threshold=setup_state.rsi_oversold,
                overbought_threshold=setup_state.rsi_overbought,
            )
            score = self._score_signal_for_thresholds(
                row,
                direction,
                oversold_threshold=setup_state.rsi_oversold,
                overbought_threshold=setup_state.rsi_overbought,
            )
            is_gold = self._is_gold_symbol(resolved_symbol)
            strategy_key = "gold" if is_gold else (self._resolved_active_strategy_key(settings) or "rsi")
            gold_detail_buttons_enabled = (
                is_gold
                and self.bot_kind == "premium"
                and await self._has_premium_access(user)
            )
            context_text = self._build_threshold_context(
                direction,
                timeframe,
                setup_state,
                language_code=language,
            )
            if is_gold and self._gold_market_closed_for_weekend(now=snapshot_now):
                context_text = f"{context_text}\n\n{self._gold_weekend_note(language_code=language, now=snapshot_now)}"
            signal = AlertSignal(
                symbol=resolved_symbol,
                direction=direction,
                timeframe=timeframe,
                candle_open_time=row.name.to_pydatetime(),
                candle_close_time=row["close_time"].to_pydatetime(),
                price=float(row["close"]),
                rsi=float(row["rsi"]),
                day_change_pct=ticker.price_change_percent if ticker else None,
                day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
                quote_volume=ticker.quote_volume if ticker else None,
                last_candle_volume=float(row["volume"]),
                avg_volume_20=float(row["avg_volume_20"]) if row["avg_volume_20"] == row["avg_volume_20"] else 0.0,
                atr=float(row["atr"]) if row["atr"] == row["atr"] else 0.0,
                atr_pct=float(row["atr_pct"]) if row["atr_pct"] == row["atr_pct"] else 0.0,
                ema20=float(row["ema20"]),
                ema50=float(row["ema50"]),
                score=score,
                explanation=context_text,
                metadata={
                    "interactive_context": True,
                    "strategy_key": strategy_key,
                    "asset_class": "gold" if is_gold else "crypto",
                    "volume_ratio": float(row["volume_ratio"]) if row["volume_ratio"] == row["volume_ratio"] else None,
                    "rsi_mode": "closed_display",
                    "rsi_source": "yahoo_gold_klines+wilder_rma" if is_gold else "binance_futures_klines+wilder_rma",
                    "closed_rsi": float(row["rsi"]),
                    "live_rsi": live_rsi,
                    "live_price": live_price,
                    "signal_close_price": float(row["close"]),
                    "signal_candle_close_time": row["close_time"].to_pydatetime().isoformat(),
                    "external_link_label": ui_text(language, "open_gold_chart") if is_gold else "",
                    "external_link_url": self.settings.gold_web_base_url if is_gold else "",
                    "interactive_ai_enabled": (not is_gold) or gold_detail_buttons_enabled,
                    "interactive_risk_enabled": (not is_gold) or gold_detail_buttons_enabled,
                    "interactive_reason_enabled": (not is_gold) or gold_detail_buttons_enabled,
                    "rsi_oversold_threshold": setup_state.rsi_oversold,
                    "rsi_overbought_threshold": setup_state.rsi_overbought,
                    "context_text": context_text,
                    "origin_timeframe": timeframe,
                    "language_code": language,
                },
            )
            if direction != "neutral":
                prepared_signal = self.signal_lifecycle_service.prepare_signal_metadata(
                    signal,
                    created_at=snapshot_now,
                    source_type="manual_ai_request" if self.bot_kind == "premium" else "manual_lookup",
                )
                self.signal_lifecycle_service.apply_prepared_metadata(signal, prepared_signal)
            else:
                # This is an on-demand market snapshot, not an executable trade
                # payload. It deliberately bypasses lifecycle level generation.
                signal.metadata = {**signal.metadata, "manual_analysis_only": True}
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal, preview=False)
            signal.chart_path = chart_path
            delivery = await self.router.send_raw_alert_to_chat(
                signal,
                chat_id=str(user.telegram_user_id),
                destination_kind=self.destination_kind,
                preview=False,
            )
            if delivery.telegram_message_id is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind=self.destination_kind,
                    chat_id=str(user.telegram_user_id),
                    message_id=delivery.telegram_message_id,
                    signal=signal,
                    alert_id=None,
                    is_preview=False,
                    message_kind="alert",
                )
        except Exception:
            LOGGER.exception(
                "Manual symbol lookup failed user=%s symbol=%s timeframe=%s",
                user.telegram_user_id,
                resolved_symbol,
                timeframe,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=(
                    self._gold_weekend_fallback(language_code=language, now=snapshot_now)
                    if self._is_gold_symbol(resolved_symbol) and self._gold_market_closed_for_weekend(now=snapshot_now)
                    else ui_text(language, "symbol_card_failed")
                ),
                parse_mode=None,
            )
        finally:
            self.chart_renderer.cleanup(chart_path)
            await self.interactive_alert_service.stop_loading_indicator(
                loading_handle,
                final_stage="Снимок готов" if language == "ru" else "Snapshot ready",
            )

    async def _send_symbol_lookup_result(
        self,
        user: PrivateBotUserRecord,
        *,
        symbol_input: str,
        timeframe: str,
    ) -> None:
        resolved_symbol = await self._resolve_symbol_input(symbol_input)
        if not resolved_symbol:
            settings = await self._ensure_user_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_unavailable"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return

        should_use_ai = (
            self.bot_kind == "premium"
            and not self._is_gold_symbol(resolved_symbol)
            and await self._has_premium_access(user)
        )
        if should_use_ai:
            try:
                await self._send_symbol_lookup_ai_analysis(
                    user,
                    symbol_input=resolved_symbol,
                    timeframe=timeframe,
                )
                return
            except Exception:
                LOGGER.exception(
                    "Manual AI symbol analysis failed user=%s symbol=%s timeframe=%s; falling back to live card",
                    user.telegram_user_id,
                    resolved_symbol,
                    timeframe,
                )

        await self._send_symbol_lookup_card(user, symbol_input=resolved_symbol, timeframe=timeframe)

    async def _send_symbol_lookup_ai_analysis(
        self,
        user: PrivateBotUserRecord,
        *,
        symbol_input: str,
        timeframe: str,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        resolved_symbol = await self._resolve_symbol_input(symbol_input)
        if not resolved_symbol:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_unavailable"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return

        loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
            chat_id=str(user.telegram_user_id),
            title=ui_text(language, "loading_manual_ai_title", symbol=resolved_symbol),
            subtitle=ui_text(language, "loading_manual_ai_subtitle", timeframe=timeframe),
            language_code=language,
        )
        try:
            progress_callback = self.interactive_alert_service.build_loading_progress_callback(loading_handle)
            analysis_text = await self.interactive_alert_service.generate_analysis_text(
                symbol=resolved_symbol,
                timeframe=timeframe,
                alert_id=None,
                destination_kind=self.destination_kind,
                language=language,
                progress_callback=progress_callback,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=format_interactive_analysis_message(
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    analysis_text=analysis_text,
                    language_code=language,
                ),
                parse_mode="HTML",
                reply_markup=build_detail_card_keyboard(include_delete=True, language_code=language),
            )
        finally:
            await self.interactive_alert_service.stop_loading_indicator(
                loading_handle,
                final_stage="Анализ готов" if language == "ru" else "Analysis ready",
            )

    def _is_gold_symbol(self, symbol: str) -> bool:
        return normalize_symbol(symbol) == normalize_symbol(self.settings.gold_symbol)

    def _classify_zone_for_thresholds(
        self,
        rsi: float,
        *,
        oversold_threshold: float,
        overbought_threshold: float,
    ) -> str:
        if rsi <= oversold_threshold:
            return "oversold"
        if rsi >= overbought_threshold:
            return "overbought"
        return "neutral"

    def _nearest_direction_for_thresholds(
        self,
        rsi: float,
        *,
        oversold_threshold: float,
        overbought_threshold: float,
    ) -> str:
        return (
            "oversold"
            if abs(rsi - oversold_threshold) <= abs(rsi - overbought_threshold)
            else "overbought"
        )

    def _score_signal_for_thresholds(
        self,
        row,
        direction: str,
        *,
        oversold_threshold: float,
        overbought_threshold: float,
    ) -> int:
        effective_direction = (
            direction
            if direction != "neutral"
            else self._nearest_direction_for_thresholds(
                float(row["rsi"]),
                oversold_threshold=oversold_threshold,
                overbought_threshold=overbought_threshold,
            )
        )
        if effective_direction == "oversold":
            threshold_distance = max(oversold_threshold - float(row["rsi"]), 0.0)
            trend_score = 12 if row["close"] < row["ema20"] < row["ema50"] else 5
            stretch = max((row["ema20"] - row["close"]) / row["close"], 0.0)
        else:
            threshold_distance = max(float(row["rsi"]) - overbought_threshold, 0.0)
            trend_score = 12 if row["close"] > row["ema20"] > row["ema50"] else 5
            stretch = max((row["close"] - row["ema20"]) / row["close"], 0.0)
        extremeness_score = min(threshold_distance * 4.2, 42)
        volume_ratio = float(row["volume_ratio"]) if row["volume_ratio"] == row["volume_ratio"] else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16, 18)
        volatility_score = min(float(row["atr_pct"]) * 600, 16)
        stretch_score = min(stretch * 4000, 14)
        total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score
        if direction == "neutral":
            nearest_distance = min(
                abs(float(row["rsi"]) - oversold_threshold),
                abs(float(row["rsi"]) - overbought_threshold),
            )
            total = max(0.0, 20.0 - nearest_distance) + min(volume_score, 12) + min(volatility_score, 10) + max(trend_score - 2, 3)
            total = min(total, 62)
        return int(max(0, min(round(total), 100)))

    async def handle_message(self, message: dict[str, object]) -> None:
        if not self.settings.private_bot_enabled:
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_type = str(chat.get("type") or "").strip().lower()
        if chat_type in {"group", "supergroup"}:
            await self._track_group_chat_member(message)
            if await self._handle_group_announcement_command(message):
                return
            return
        if chat_type != "private":
            return

        user = message.get("from")
        if not isinstance(user, dict):
            return

        user_id = int(user.get("id") or 0)
        if user_id <= 0:
            return

        text = str(message.get("text") or "").strip()
        normalized = text.casefold()
        command_token = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower() if text else ""
        start_payload = text.split(maxsplit=1)[1] if command_token == "/start" and " " in text else None
        preferred_language = normalize_language(str(user.get("language_code") or ""))
        existing_user = await self._get_private_user(user_id)
        if self.onboarding_service is not None:
            user_record = await self.onboarding_service.register_contact(
                telegram_user_id=user_id,
                username=user.get("username"),
                first_name=user.get("first_name"),
                last_name=user.get("last_name"),
                bot_kind=self.bot_kind,
                start_payload=start_payload,
            )
        else:
            user_record = await self.repository.upsert_private_user(
                telegram_user_id=user_id,
                username=user.get("username"),
                first_name=user.get("first_name"),
                last_name=user.get("last_name"),
                is_admin=self.settings.is_configured_admin(user_id, user.get("username")),
            )
        user_record = self._store_cached_user(user_record)
        settings = await self._ensure_user_settings(user_id, preferred_language=preferred_language)
        language = self._language_code(settings)
        if not text:
            return
        onboarding_state = await self.repository.get_user_onboarding_state(user_id, bot_kind=self.bot_kind)
        setup_builder_state = await self._get_setup_builder_state(user_id)
        gold_wizard_state = await self._get_gold_wizard_state(user_id)
        if command_token == "/start":
            await self._record_funnel_event(
                "start_seen",
                user_id,
                context="first" if settings.onboarding_completed_at is None else "returning",
                language_code=language,
            )
        if command_token == "/cancel" and user_id in self._custom_setup_sessions:
            await self._cancel_custom_setup(user_record, current_settings=settings)
            await self._send_chat_message(
                chat_id=str(user_id),
                text=ui_text(language, "callback_custom_cancelled"),
                parse_mode=None,
            )
            return
        if command_token == "/cancel" and setup_builder_state is not None and setup_builder_state.completed_at is None:
            await self._clear_setup_builder_state(user_id)
            await self._send_setups_hub(user_record)
            return
        if command_token == "/cancel" and gold_wizard_state is not None and gold_wizard_state.completed_at is None:
            await self._clear_gold_wizard_state(user_id)
            await self._send_gold_center(user_record)
            return
        if (
            command_token == "/cancel"
            and onboarding_state is not None
            and onboarding_state.completed_at is None
            and bool(onboarding_state.draft.get("v2"))
        ):
            await self.repository.delete_user_onboarding_state(user_id, bot_kind=self.bot_kind)
            await self._send_v2_home(user_record, is_pro=False)
            return
        if user_id in self._custom_setup_sessions and self._custom_setup_navigation_requested(normalized, command_token):
            self._clear_custom_setup_session(user_id)

        if command_token == "/start":
            if settings.onboarding_completed_at is None:
                if onboarding_state is not None and onboarding_state.completed_at is None:
                    if bool(onboarding_state.draft.get("v2")):
                        await self._send_v2_onboarding_step(
                            user_record,
                            step=str(onboarding_state.step).removeprefix("v2_"),
                            draft=dict(onboarding_state.draft),
                        )
                        return
                    await self._send_onboarding_step(
                        user_id,
                        step=onboarding_state.step,
                        draft=onboarding_state.draft,
                        preferred_language=preferred_language,
                    )
                    return
                if self.bot_kind == "premium" and self._v2_navigation_enabled(settings):
                    await self._send_v2_home(user_record, is_pro=False)
                    return
                await self._send_language_picker(
                    user_id,
                    preferred_language=preferred_language,
                    first_time=True,
                )
                return
            if self.bot_kind == "premium":
                settings = await self._enable_v2_navigation(user_record, settings)
                await self._send_v2_home(
                    user_record,
                    is_pro=str(settings.display_mode or "simple").strip().lower() == "pro",
                )
                return
            if self.bot_kind == "premium" and self._resolved_active_strategy_key(settings) is None:
                await self._send_start(user_id, start_payload, first_time=existing_user is None)
                return
            await self._send_start(user_id, start_payload, first_time=existing_user is None)
            await self._maybe_send_return_summary(
                user_record,
                previous_last_seen_at=existing_user.last_seen_at if existing_user is not None else None,
            )
            return
        if command_token == "/health":
            await self._send_admin_health(user_record)
            return
        if (
            settings.onboarding_completed_at is None
            and (onboarding_state is None or onboarding_state.completed_at is not None)
            and command_token not in {"/help", "/lang"}
            and not self._matches_ui_label(normalized, "menu_help")
        ):
            await self._send_language_picker(
                user_id,
                preferred_language=preferred_language,
                first_time=False,
            )
            return
        if onboarding_state is not None and onboarding_state.completed_at is None:
            if bool(onboarding_state.draft.get("v2")):
                if await self._handle_onboarding_text(user_record, text):
                    return
                if command_token not in {"/help", "/lang", "/menu"} and not self._matches_ui_label(normalized, "menu_help"):
                    await self._send_v2_onboarding_step(
                        user_record,
                        step=str(onboarding_state.step).removeprefix("v2_"),
                        draft=dict(onboarding_state.draft),
                    )
                    return
            else:
                if command_token in {"/help", "/lang", "/menu"} or any(
                    self._matches_ui_label(normalized, key)
                    for key in ("menu_help", "menu_open")
                ):
                    await self._cleanup_onboarding_thread(
                        telegram_user_id=user_id,
                        chat_id=str(user_id),
                        draft=onboarding_state.draft,
                    )
                    await self.repository.delete_user_onboarding_state(user_id, bot_kind=self.bot_kind)
                    onboarding_state = None
                else:
                    if await self._handle_onboarding_text(user_record, text):
                        return
                    if command_token not in {"/help", "/lang", "/menu"} and not self._matches_ui_label(normalized, "menu_help"):
                        await self._send_onboarding_step(
                            user_id,
                            step=onboarding_state.step,
                            draft=onboarding_state.draft,
                            preferred_language=preferred_language,
                        )
                        return
        if setup_builder_state is not None and setup_builder_state.completed_at is None:
            if command_token in {"/help", "/lang", "/menu"}:
                await self._clear_setup_builder_state(user_id)
            elif await self._handle_setup_builder_text(user_record, text):
                return
        if gold_wizard_state is not None and gold_wizard_state.completed_at is None:
            if command_token in {"/help", "/lang", "/menu"}:
                await self._clear_gold_wizard_state(user_id)
        if command_token == "/help" or normalized == "help" or self._matches_ui_label(normalized, "menu_help"):
            await self._send_help(user_id)
            return
        if command_token == "/referral" or self._matches_ui_label(normalized, "menu_referral"):
            await self._send_referral_screen(user_record)
            return
        if self._matches_premium_label(normalized, "menu_signals"):
            await self._send_section_hub(user_id, section="signals")
            return
        if self._matches_premium_label(normalized, "menu_watchlists"):
            await self._send_watchlists_center(user_record)
            return
        if self._matches_premium_label(normalized, "menu_delivery"):
            await self._send_delivery_center(user_record)
            return
        if self._matches_premium_label(normalized, "menu_stats"):
            await self._send_control_center(user_record)
            return
        if self._matches_premium_label(normalized, "menu_ai_tools"):
            await self._send_section_hub(user_id, section="ai")
            return
        if self._matches_premium_label(normalized, "menu_settings_premium"):
            await self._send_section_hub(user_id, section="settings")
            return
        if command_token == "/setup" or self._matches_ui_label(normalized, "menu_signal_setup"):
            await self._send_signal_setup(user_record)
            return
        if command_token == "/watchlist" or self._matches_ui_label(normalized, "menu_watchlist"):
            await self._send_watchlist(user_record)
            return
        if command_token in {"/xau", "/goldnow", "/goldcard"}:
            await self._send_gold_snapshot(user_record)
            return
        if self._matches_ui_label(normalized, "menu_gold_snapshot"):
            await self._send_gold_center(user_record)
            return
        if command_token == "/analyze":
            if await self._handle_analyze_request(user_record, text):
                return
            await self._send_analyze_symbol_help(user_record)
            return
        if self._matches_ui_label(normalized, "menu_analyze_symbol"):
            await self._send_analyze_symbol_help(user_record)
            return
        if command_token in {"/last", "/signals"} or self._matches_ui_label(normalized, "menu_latest_signals"):
            if self.bot_kind == "premium" and not await self._has_premium_access(user_record):
                await self._send_payment_offer(user_record)
                return
            await self._send_recent_signals(user_record, strong_only=False)
            return
        if command_token == "/strong" or normalized in {
            ui_text("en", "signals_title_strong").casefold(),
            ui_text("ru", "signals_title_strong").casefold(),
        }:
            if self.bot_kind == "premium" and not await self._has_premium_access(user_record):
                await self._send_payment_offer(user_record)
                return
            await self._send_recent_signals(user_record, strong_only=True)
            return
        if command_token == "/status" or self._matches_ui_label(normalized, "menu_market_status"):
            await self._send_status(user_record)
            return
        if command_token in {"/alerts", "/notify"} or any(
            self._matches_ui_label(normalized, key)
            for key in ("menu_alerts_on", "menu_alerts_off")
        ):
            await self._toggle_direct_delivery(
                user_record,
                enable=await self._resolve_direct_delivery_target(user_record, normalized, command_token),
            )
            return
        if command_token == "/followups" or any(
            self._matches_ui_label(normalized, key)
            for key in ("menu_followups_on", "menu_followups_off")
        ):
            await self._toggle_followup_delivery(
                user_record,
                enable=await self._resolve_followup_delivery_target(user_record, normalized, command_token),
            )
            return
        if command_token == "/gold" or normalized in {"gold alerts on", "gold alerts off", "gold alerts: on", "gold alerts: off"}:
            await self._toggle_gold_alert_delivery(
                user_record,
                enable=await self._resolve_gold_delivery_target(user_record, normalized, command_token),
            )
            return
        if command_token == "/menu" or normalized == "menu" or self._matches_ui_label(normalized, "menu_open"):
            await self._send_menu(user_id)
            await self._maybe_send_return_summary(
                user_record,
                previous_last_seen_at=existing_user.last_seen_at if existing_user is not None else None,
            )
            return
        if command_token == "/hide" or self._matches_ui_label(normalized, "menu_hide"):
            await self._hide_menu(user_record)
            return
        if command_token == "/lang" or self._is_language_toggle_label(normalized):
            await self._toggle_language_preference(user_record, settings)
            return
        if command_token == "/pay" or normalized in {"payment", "billing"} or any(
            self._matches_ui_label(normalized, key)
            for key in ("menu_try_pro", "menu_continue_pro", "menu_pay_pro", "menu_renew_pro")
        ):
            access_state = await self._effective_access_state_for_user(user_record)
            await self._send_payment_offer(
                user_record,
                allow_renewal=access_state.is_paid or access_state.access_status == "trial",
            )
            return
        if command_token == "/ai" or self._matches_ui_label(normalized, "menu_ai_analysis"):
            if not await self._has_premium_access(user_record):
                await self._send_premium_access_required(
                    user_record.telegram_user_id,
                    feature_name=ui_text(language, "button_ai_analysis"),
                )
                return
            await self._send_ai_pick(user_record)
            return
        if command_token == "/pro" or normalized == "open pro channel":
            await self._send_pro_link(user_id)
            return
        if self._matches_ui_label(normalized, "menu_results_channel"):
            await self._send_results_link(user_id)
            return
        if self._matches_ui_label(normalized, "menu_public_channel"):
            await self._send_public_link(user_id)
            return
        if self._matches_ui_label(normalized, "menu_community_chat"):
            await self._send_community_link(user_id)
            return
        if command_token == "/settings" or self._matches_ui_label(normalized, "menu_my_access"):
            await self._send_access(user_record)
            return
        if await self._handle_theme_prompt_message(user_record, text):
            return
        if await self._handle_active_custom_setup_message(user_record, settings, text):
            return
        if await self._handle_personalization_prompt_message(user_record, text):
            return
        if await self._try_handle_watchlist_input(user_record, text):
            return
        if await self._try_handle_symbol_lookup(user_record, text):
            return

        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "menu_hint_private"),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user_id),
        )

    def _announcement_chat_ids(self) -> set[str]:
        chat_ids: set[str] = set()
        for raw_value in (
            self.settings.community_chat,
            self.settings.lab_channel,
            self.settings.pro_channel,
            self.settings.results_channel,
            self.settings.public_channel,
        ):
            normalized = str(raw_value or "").strip()
            if normalized and normalized.lstrip("-").isdigit():
                chat_ids.add(normalized)
        return chat_ids

    def _is_allowed_announcement_chat(self, *, chat_id: str, chat_type: str) -> bool:
        return chat_type in {"group", "supergroup"} and chat_id in self._announcement_chat_ids()

    async def _track_group_chat_member(self, message: dict[str, object]) -> None:
        chat = message.get("chat")
        user = message.get("from")
        if not isinstance(chat, dict) or not isinstance(user, dict):
            return
        chat_id = str(chat.get("id") or "").strip()
        chat_type = str(chat.get("type") or "").strip().lower()
        user_id = int(user.get("id") or 0)
        if not self._is_allowed_announcement_chat(chat_id=chat_id, chat_type=chat_type):
            return
        if user_id <= 0:
            return
        await self.repository.upsert_chat_member_roster(
            chat_id=chat_id,
            telegram_user_id=user_id,
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            is_bot=bool(user.get("is_bot")),
        )

    def _extract_group_announcement_text(self, message: dict[str, object]) -> str:
        text = str(message.get("text") or "").strip()
        if text:
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
        reply = message.get("reply_to_message")
        if isinstance(reply, dict):
            reply_text = str(reply.get("text") or reply.get("caption") or "").strip()
            if reply_text:
                return reply_text
        return ""

    async def _group_announcement_mentions(self, *, chat_id: str, exclude_user_id: int | None = None) -> str:
        members = await self.repository.list_chat_member_roster(chat_id, limit=48, include_bots=False)
        chunks: list[str] = []
        extra_count = 0
        max_length = 1200
        total_length = 0
        for member in members:
            if exclude_user_id is not None and member.telegram_user_id == exclude_user_id:
                continue
            label = (
                f"@{member.username}"
                if member.username
                else member.first_name
                or member.last_name
                or str(member.telegram_user_id)
            ).strip()
            if not label:
                continue
            token = f'<a href="tg://user?id={member.telegram_user_id}">{escape_html(label[:24])}</a>'
            projected = total_length + len(token) + (1 if chunks else 0)
            if projected > max_length:
                extra_count += 1
                continue
            chunks.append(token)
            total_length = projected
        if not chunks:
            return ""
        mention_line = " ".join(chunks)
        if extra_count > 0:
            mention_line = f"{mention_line} <i>+{extra_count}</i>"
        return mention_line

    async def _handle_group_announcement_command(self, message: dict[str, object]) -> bool:
        chat = message.get("chat")
        user = message.get("from")
        if not isinstance(chat, dict) or not isinstance(user, dict):
            return False
        chat_id = str(chat.get("id") or "").strip()
        chat_type = str(chat.get("type") or "").strip().lower()
        if not self._is_allowed_announcement_chat(chat_id=chat_id, chat_type=chat_type):
            return False
        user_id = int(user.get("id") or 0)
        if user_id <= 0 or not self.settings.is_configured_admin(user_id, user.get("username")):
            return False
        text = str(message.get("text") or "").strip()
        normalized = text.casefold()
        command_token = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower() if text else ""
        if command_token != "/all" and not normalized.startswith("all "):
            return False
        body = self._extract_group_announcement_text(message)
        message_id = message.get("message_id")
        reply_to_message_id = None
        reply = message.get("reply_to_message")
        if isinstance(reply, dict) and isinstance(reply.get("message_id"), int):
            reply_to_message_id = int(reply.get("message_id"))
        language = normalize_language(str(user.get("language_code") or "ru"))
        if not body:
            await self._send_chat_message(
                chat_id=chat_id,
                text=(
                    "Используй /all текст или ответь командой /all на сообщение."
                    if language == "ru"
                    else "Use /all <text> or reply with /all to a message."
                ),
                parse_mode=None,
                reply_to_message_id=int(message_id) if isinstance(message_id, int) else None,
                cleanup=False,
            )
            return True
        mentions = await self._group_announcement_mentions(chat_id=chat_id, exclude_user_id=user_id)
        title = "<b>📢 Объявление</b>" if language == "ru" else "<b>📢 Announcement</b>"
        announcement_text = f"{title}\n\n{escape_html(body)}"
        if mentions:
            announcement_text = f"{announcement_text}\n\n{mentions}"
        await self._send_chat_message(
            chat_id=chat_id,
            text=announcement_text,
            reply_to_message_id=reply_to_message_id,
            cleanup=False,
        )
        if isinstance(message_id, int):
            with suppress(Exception):
                await self.telegram_client.delete_message(chat_id=chat_id, message_id=message_id)
        return True

    async def handle_callback_query(self, callback_query: dict[str, object]) -> None:
        action = parse_userbot_callback_data(str(callback_query.get("data") or ""))
        query_id = str(callback_query.get("id") or "")
        from_user = callback_query.get("from")
        requested_language = normalize_language(
            str(from_user.get("language_code") or "") if isinstance(from_user, dict) else None
        )
        if action is None:
            if query_id:
                with suppress(Exception):
                    await self.telegram_client.answer_callback_query(
                        callback_query_id=query_id,
                        text=ui_text(requested_language, "unknown_action"),
                    )
            return
        action_spec = action_spec_for(action.kind)
        feature_enabled = (
            action_spec is not None
            and (
                action_spec.feature_flag is None
                or bool(getattr(self.settings, action_spec.feature_flag.lower(), False))
            )
        )
        if (
            action_spec is None
            or self.bot_kind not in action_spec.allowed_bot_kinds
            or not feature_enabled
        ):
            LOGGER.warning("Rejected unavailable userbot action kind=%s bot=%s", action.kind, self.bot_kind)
            if query_id:
                with suppress(Exception):
                    await self.telegram_client.answer_callback_query(
                        callback_query_id=query_id,
                        text=ui_text(requested_language, "unknown_action"),
                    )
            return

        message = callback_query.get("message")
        if not isinstance(from_user, dict) or not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        user_id = int(from_user.get("id") or 0)
        chat_id = str(chat.get("id") or "")
        message_id = message.get("message_id")
        if user_id <= 0 or not chat_id or not isinstance(message_id, int):
            return

        optimistic_text = self._optimistic_callback_text(action, language_code=requested_language)
        if optimistic_text is not None:
            await self._answer_callback_query(query_id, text=optimistic_text)
            query_id = ""

        user = await self._get_private_user(user_id)
        if user is None:
            user = await self.repository.upsert_private_user(
                telegram_user_id=user_id,
                username=from_user.get("username"),
                first_name=from_user.get("first_name"),
                last_name=from_user.get("last_name"),
                is_admin=self.settings.is_configured_admin(user_id, from_user.get("username")),
            )
        user = self._store_cached_user(user)
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        onboarding_state = await self.repository.get_user_onboarding_state(user_id, bot_kind=self.bot_kind)
        setup_builder_state = await self._get_setup_builder_state(user_id)
        gold_wizard_state = await self._get_gold_wizard_state(user_id)
        if action.kind.startswith("v2_"):
            await self._handle_v2_action(
                user,
                action=action,
                query_id=query_id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if user_id in self._custom_setup_sessions and action.kind not in {"custom", "direction"}:
            self._clear_custom_setup_session(user_id)
        if onboarding_state is not None and onboarding_state.completed_at is None and action.kind != "onboard":
            await self._cleanup_onboarding_thread(
                telegram_user_id=user_id,
                chat_id=chat_id,
                draft=onboarding_state.draft,
                keep_message_id=message_id,
            )
            await self.repository.delete_user_onboarding_state(user_id, bot_kind=self.bot_kind)
            onboarding_state = None
        if setup_builder_state is not None and setup_builder_state.completed_at is None and not action.kind.startswith("setup_builder"):
            if action.kind not in {"setup_create", "setup_savecurrent", "setup_list", "setup_detail", "setup_activate", "setup_edit", "setup_update", "setup_rename", "setup_duplicate", "setup_delete", "setup_default", "setup_pin"}:
                await self._clear_setup_builder_state(user_id)
                setup_builder_state = None
        if gold_wizard_state is not None and gold_wizard_state.completed_at is None and not action.kind.startswith("gold_wizard"):
            if action.kind != "goldhub":
                await self._clear_gold_wizard_state(user_id)
                gold_wizard_state = None
        if action.kind in {
            "setup",
            "strategies",
            "signalshub",
            "watchhub",
            "deliveryhub",
            "statshub",
            "results_hub",
            "results_view",
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
            "aihub",
            "settingshub",
            "menu",
            "strategy_toggle",
            "strategy_open",
            "watchlist",
            "access",
            "status",
            "help",
            "help_page",
            "onboarding_example",
            "onboarding_read",
            "themes",
            "control",
            "analyze",
            "goldhub",
            "custom",
            "language_picker",
            "language_set",
            "recap",
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
            "pro_hub",
        }:
            await self._cleanup_temporary_navigation_messages(
                telegram_user_id=user_id,
                chat_id=chat_id,
            )

        if action.kind == "setup":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_setup"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "strategies":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_strategy_selector(user.telegram_user_id, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "results_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_product_results_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "results_admin":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_admin_stats(
                user,
                period=str(action.value or "7d"),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "health":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_admin_health(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "compare_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_compare_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "compare_view" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_compare_view(user, view=action.value, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "compare_admin":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_admin_stats(user, period="7d", chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "learn_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_learn_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "learn_page" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_learn_page(user, page=action.value, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "learn_guide" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_learn_page(
                user,
                page="guides",
                strategy_code=action.value,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "lifecycle_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_lifecycle_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "lifecycle_view" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_lifecycle_view(user, view=action.value, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "signalshub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_section_hub(
                user.telegram_user_id,
                section="signals",
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "watchhub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_watchlists_center(
                user,
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "deliveryhub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_delivery_center(
                user,
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "statshub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_control_center(
                user,
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "aihub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_section_hub(
                user.telegram_user_id,
                section="ai",
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "settingshub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_settings_center(
                user,
                origin=self._action_hub_origin(action),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "workspacehub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_workspace_center(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setupshub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_setups_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_list":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_pinned":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_saved_setups_list(
                user,
                only_pinned=True,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_create":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_savecurrent":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._prompt_personalization_action(user, action="setup_savecurrent")
            return
        if action.kind == "setup_detail" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_saved_setup_detail(
                user,
                setup_id=int(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_activate" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            setup = await self.repository.get_user_saved_setup(
                int(action.value),
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._apply_saved_setup_payload(user, setup=setup)
            await self._send_saved_setup_detail(
                user,
                setup_id=setup.id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_update" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            setup_id = int(action.value)
            existing_setup = await self.repository.get_user_saved_setup(
                setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if existing_setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            payload = await self._build_current_setup_payload(user.telegram_user_id)
            await self.repository.update_user_saved_setup(
                setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                payload=payload,
            )
            await self._send_saved_setup_detail(
                user,
                setup_id=setup_id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_rename" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            existing_setup = await self.repository.get_user_saved_setup(
                int(action.value),
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if existing_setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._prompt_personalization_action(
                user,
                action="setup_rename",
                target_id=existing_setup.id,
                name=existing_setup.name,
            )
            return
        if action.kind == "setup_duplicate" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            existing_setup = await self.repository.get_user_saved_setup(
                int(action.value),
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if existing_setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._prompt_personalization_action(
                user,
                action="setup_duplicate",
                target_id=existing_setup.id,
                name=existing_setup.name,
            )
            return
        if action.kind == "setup_edit" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            existing_setup = await self.repository.get_user_saved_setup(
                int(action.value),
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if existing_setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = await self._setup_builder_draft_from_payload(
                user.telegram_user_id,
                language_code=language,
                payload=existing_setup.payload if isinstance(existing_setup.payload, dict) else {},
                mode="edit",
                parent_callback=f"ux:setup:detail:{existing_setup.id}",
                preferred_name=existing_setup.name,
                editing_setup_id=existing_setup.id,
            )
            await self._save_setup_builder_state(user.telegram_user_id, step="name", draft=draft)
            await self._send_setup_builder_step(
                user,
                step="name",
                draft=draft,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_delete" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            setup_id = int(action.value)
            deleted = await self.repository.delete_user_saved_setup(
                setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if deleted:
                shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
                if shell_settings.current_set_id == setup_id:
                    await self._save_user_settings(
                        user=user,
                        current_settings=settings,
                        current_set_id=None,
                    )
            await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_default" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            setup_id = int(action.value)
            setup = await self.repository.get_user_saved_setup(
                setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self.repository.update_user_saved_setup(
                setup.id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                is_default=True,
            )
            await self._send_saved_setup_detail(
                user,
                setup_id=setup.id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_pin" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            setup_id = int(action.value)
            setup = await self.repository.get_user_saved_setup(
                setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if setup is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self.repository.update_user_saved_setup(
                setup.id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                is_pinned=not setup.is_pinned,
            )
            await self._send_saved_setup_detail(
                user,
                setup_id=setup.id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "quickfiltershub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_quick_filters_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "custom_filters_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_custom_filters_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_builder_start" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            start_mode = str(action.value)
            if start_mode == "template":
                await self._send_setup_template_picker(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._begin_setup_builder(
                user,
                mode=start_mode,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_builder_template" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._begin_setup_builder(
                user,
                mode="template",
                template_key=str(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_builder_prompt" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = dict(state.draft or {})
            prompt_kind = str(action.value)
            draft["awaiting_input"] = "name" if prompt_kind == "name" else prompt_kind
            await self._save_setup_builder_state(user.telegram_user_id, step=state.step, draft=draft)
            prompt_text = (
                "Send the setup name."
                if prompt_kind == "name" and language == "en"
                else "Отправь название сетапа."
                if prompt_kind == "name"
                else "Send symbols to add, like BTC, ETH, SOL."
                if prompt_kind == "symbols_add" and language == "en"
                else "Отправь символы, которые нужно добавить, например BTC, ETH, SOL."
                if prompt_kind == "symbols_add"
                else "Send symbols to remove, like BTC or SOL."
                if prompt_kind == "symbols_remove" and language == "en"
                else "Отправь символы, которые нужно убрать, например BTC или SOL."
                if prompt_kind == "symbols_remove"
                else "Send symbols like BTC, ETH, SOL."
                if language == "en"
                else "Отправь символы вроде BTC, ETH, SOL."
            )
            await self._send_chat_message(
                chat_id=chat_id or str(user.telegram_user_id),
                text=prompt_text,
                parse_mode=None,
            )
            await self._send_setup_builder_step(
                user,
                step=state.step,
                draft=draft,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_builder_set" and action.value and action.extra:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = dict(state.draft or {})
            category = str(action.value)
            raw_value = str(action.extra)
            if category == "scope":
                self._write_setup_builder_scope(draft, scope_type=raw_value)
            elif category == "theme":
                theme_options = [item for item in await self._setup_builder_theme_options(user.telegram_user_id) if isinstance(item, dict)]
                selected_theme = next((item for item in theme_options if str(item.get("id")) == raw_value), None)
                if selected_theme is not None:
                    theme_id = int(selected_theme["id"])
                    self._write_setup_builder_scope(
                        draft,
                        scope_type="theme",
                        payload={
                            "theme_id": theme_id,
                            "theme_name": str(selected_theme["name"]),
                            "symbols": await self.repository.list_premium_strategy_watchlist_theme_symbols(theme_id),
                        },
                    )
            elif category == "custom" and raw_value == "clear":
                self._write_setup_builder_scope(draft, scope_type="custom", payload={"symbols": []})
            elif category == "direction":
                draft["direction"] = raw_value
            elif category == "session":
                draft["session"] = raw_value
            elif category == "noise":
                draft["noise_level"] = raw_value
            elif category == "score":
                draft["score_filter"] = raw_value
            elif category == "delivery":
                draft["delivery_profile"] = raw_value
            await self._save_setup_builder_state(user.telegram_user_id, step=state.step, draft=draft)
            await self._send_setup_builder_step(user, step=state.step, draft=draft, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_builder_toggle" and action.value and action.extra:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = dict(state.draft or {})
            collection_key = str(action.value)
            item = str(action.extra)
            current = list(draft.get("selected_strategies" if collection_key == "strategy" else "selected_timeframes") or [])
            if item in current:
                current = [value for value in current if value != item]
            else:
                current.append(item)
            if collection_key == "strategy":
                draft["selected_strategies"] = current
            else:
                draft["selected_timeframes"] = [value for value in self.SETUP_BUILDER_TIMEFRAMES if value in current]
            await self._save_setup_builder_state(user.telegram_user_id, step=state.step, draft=draft)
            await self._send_setup_builder_step(user, step=state.step, draft=draft, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_builder_next":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = dict(state.draft or {})
            error_text = self._validate_setup_builder_step(state.step, draft, language_code=language)
            if error_text:
                await self._answer_callback_query(query_id, text=error_text)
                return
            current_index = self.SETUP_BUILDER_STEPS.index(state.step)
            next_step = self.SETUP_BUILDER_STEPS[min(current_index + 1, len(self.SETUP_BUILDER_STEPS) - 1)]
            await self._save_setup_builder_state(user.telegram_user_id, step=next_step, draft=draft)
            await self._send_setup_builder_step(user, step=next_step, draft=draft, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "setup_builder_back":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._setup_builder_back_target(
                user,
                step=state.step,
                draft=dict(state.draft or {}),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_builder_cancel":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            await self._clear_setup_builder_state(user.telegram_user_id)
            await self._send_setup_builder_parent(
                user,
                draft=dict(state.draft or {}) if state is not None else {},
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "setup_builder_save" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_setup_builder_state(user.telegram_user_id)
            if state is None:
                await self._send_setups_hub(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._save_setup_from_builder(
                user,
                draft=dict(state.draft or {}),
                activate=str(action.value) == "activate",
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "quickfilter_apply" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = apply_quick_filter_preset(self._personalization_state(shell_settings), str(action.value))
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_quick_filters_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "quickfilter_reset":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = clear_quick_filters(self._personalization_state(shell_settings))
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_quick_filters_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "noisehub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_noise_level_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "noise_set" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            personalization["noise_level"] = str(action.value)
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_noise_level_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "scorehub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_score_filter_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "score_set" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            personalization["score_filter"] = str(action.value)
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_score_filter_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "sessionhub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_session_filter_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "session_set" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            personalization["session_filter"] = str(action.value)
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_session_filter_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "delivery_rules_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_delivery_rules_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "delivery_rule_view" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_delivery_rule_view(
                user,
                rule_key=str(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "delivery_rule_set" and action.value and action.extra:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            rules = self._delivery_rules_state(shell_settings)
            raw_value = str(action.extra)
            rules[str(action.value)] = int(raw_value) if raw_value.isdigit() else raw_value
            await self._save_personalization_state(user, settings, delivery_rules=rules)
            await self._send_delivery_rule_view(
                user,
                rule_key=str(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "hide_mute_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_hide_mute_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "hide_asset_prompt":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._prompt_personalization_action(user, action="hide_asset")
            return
        if action.kind == "hide_mute_view" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            if action.value == "strategies":
                await self._send_hide_strategy_view(user, chat_id=chat_id, edit_message_id=message_id)
                return
            if action.value == "timeframes":
                await self._send_hide_timeframe_view(user, chat_id=chat_id, edit_message_id=message_id)
                return
            if action.value == "repeats":
                await self._send_repeat_mute_view(user, chat_id=chat_id, edit_message_id=message_id)
                return
        if action.kind == "hide_mute_toggle" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            hidden = dict(personalization.get("hidden") or {})
            toggle_key = str(action.value)
            hidden[toggle_key] = not bool(hidden.get(toggle_key))
            personalization["hidden"] = hidden
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_hide_mute_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "hide_strategy" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            hidden = dict(personalization.get("hidden") or {})
            strategies = {str(item) for item in hidden.get("strategies", [])}
            strategy_key = str(action.value)
            if strategy_key in strategies:
                strategies.remove(strategy_key)
            else:
                strategies.add(strategy_key)
            hidden["strategies"] = sorted(strategies)
            personalization["hidden"] = hidden
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_hide_strategy_view(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "hide_timeframe" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            hidden = dict(personalization.get("hidden") or {})
            timeframes = {str(item) for item in hidden.get("timeframes", [])}
            timeframe = str(action.value).lower()
            if timeframe in timeframes:
                timeframes.remove(timeframe)
            else:
                timeframes.add(timeframe)
            hidden["timeframes"] = sorted(timeframes)
            personalization["hidden"] = hidden
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_hide_timeframe_view(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "hide_repeats" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            hidden = dict(personalization.get("hidden") or {})
            hidden["mute_repeats_hours"] = max(0, int(action.value or 0))
            personalization["hidden"] = hidden
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_repeat_mute_view(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "hide_mute_resume":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            personalization = self._personalization_state(shell_settings)
            personalization["hidden"] = normalize_personalization(None)["hidden"]
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_hide_mute_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "style_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_style_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "style_view" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_style_dimension_view(
                user,
                dimension=str(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "style_set" and action.value and action.extra:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            profile = await self.repository.get_user_style_profile(user.telegram_user_id, bot_kind=self.bot_kind)
            preferences = normalize_style_preferences(profile.preferences if profile is not None else default_style_preferences())
            preferences[str(action.value)] = str(action.extra)
            title, summary = build_style_title_summary(preferences, language_code=language)
            await self.repository.upsert_user_style_profile(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                title=title,
                summary=summary,
                preferences=preferences,
            )
            await self._send_style_dimension_view(
                user,
                dimension=str(action.value),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "style_save":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            profile = await self.repository.get_user_style_profile(user.telegram_user_id, bot_kind=self.bot_kind)
            preferences = normalize_style_preferences(profile.preferences if profile is not None else default_style_preferences())
            title, summary = build_style_title_summary(preferences, language_code=language)
            await self.repository.upsert_user_style_profile(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                title=title,
                summary=summary,
                preferences=preferences,
            )
            await self._send_style_hub(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "personal_summary":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_personal_summary(
                user,
                period_label="weekly" if str(action.value or "daily").strip().lower() == "weekly" else "daily",
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "display_mode_view":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._apply_display_mode(
                user,
                mode=str(action.value or "pro"),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "pro_hub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_pro_submenu(
                user,
                hub=str(action.value or ""),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "workspace_save":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._save_current_workspace_snapshot(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "workspace_apply":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._apply_workspace_profile(
                user,
                workspace_key=str(action.value or "intraday"),
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "menu":
            await self._answer_callback_query(query_id, text=ui_text(language, "menu_reopened"))
            await self._send_menu_hub(user.telegram_user_id, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "strategy_toggle" and action.value:
            strategy_key = str(action.value).strip().lower()
            if not self._strategy_accessible_for_user_id(user.telegram_user_id, strategy_key):
                await self._answer_callback_query(query_id, text=ui_text(language, "unknown_action"))
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            assert shell_settings is not None
            enabled = list(self._enabled_strategy_keys(shell_settings))
            if strategy_key in enabled:
                enabled = [key for key in enabled if key != strategy_key]
            else:
                if self._is_gold_substrategy(strategy_key) and GOLD_MASTER_STRATEGY_KEY not in enabled:
                    enabled.append(GOLD_MASTER_STRATEGY_KEY)
                enabled.append(strategy_key)
                await self._ensure_premium_strategy_settings(
                    user.telegram_user_id,
                    shell_settings=shell_settings,
                    strategy_key=strategy_key,
                )
            next_active = self._resolved_active_strategy_key(shell_settings)
            if next_active not in enabled:
                next_active = enabled[0] if enabled else None
            selector_completed_at = utc_now() if enabled else None
            settings = await self._save_user_settings(
                user=user,
                current_settings=settings,
                enabled_strategy_keys=tuple(enabled),
                active_strategy_key=next_active,
                strategy_selector_completed_at=selector_completed_at,
                onboarding_completed_at=(
                    settings.onboarding_completed_at
                    if settings.onboarding_completed_at is not None or not enabled
                    else utc_now()
                ),
            )
            if self._is_gold_substrategy(strategy_key):
                await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._send_strategy_selector(user.telegram_user_id, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "strategy_open" and action.value:
            strategy_key = str(action.value).strip().lower()
            if not self._strategy_accessible_for_user_id(user.telegram_user_id, strategy_key):
                await self._answer_callback_query(query_id, text=ui_text(language, "unknown_action"))
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            assert shell_settings is not None
            await self._ensure_premium_strategy_settings(
                user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            settings = await self._save_user_settings(
                user=user,
                current_settings=settings,
                active_strategy_key=strategy_key,
                strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
                onboarding_completed_at=settings.onboarding_completed_at,
            )
            if strategy_key == "gold":
                await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._send_strategy_hub(user.telegram_user_id, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind in {
            "strategy_signals",
            "strategy_filters",
            "strategy_alerts",
            "strategy_favorites",
            "strategy_quicksetup",
            "strategy_results",
            "strategy_guide",
            "strategy_settings",
            "strategy_compare",
        } and action.value:
            strategy_key = str(action.value).strip().lower()
            if not self._strategy_accessible_for_user_id(user.telegram_user_id, strategy_key):
                await self._answer_callback_query(query_id, text=ui_text(language, "unknown_action"))
                return
            settings = await self._activate_strategy_context(
                user,
                current_settings=settings,
                strategy_key=strategy_key,
            )
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            if action.kind == "strategy_signals":
                await self._send_section_hub(
                    user.telegram_user_id,
                    section="signals",
                    origin="strategy",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_filters":
                await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
                return
            if action.kind == "strategy_alerts":
                await self._send_delivery_center(
                    user,
                    origin="strategy",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_favorites":
                await self._send_watchlists_center(
                    user,
                    origin="strategy",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_quicksetup":
                await self._start_or_resume_onboarding(
                    user.telegram_user_id,
                    restart=True,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_results":
                await self._send_product_results_hub(
                    user,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                    strategy_code=strategy_key,
                )
                return
            if action.kind == "strategy_guide":
                await self._send_learn_page(
                    user,
                    page="guides",
                    strategy_code=strategy_key,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_settings":
                await self._send_section_hub(
                    user.telegram_user_id,
                    section="settings",
                    origin="strategy",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.kind == "strategy_compare":
                await self._send_compare_view(
                    user,
                    view="all",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
        if action.kind == "strategy_lifecycle" and action.value:
            strategy_key = str(action.value).strip().lower()
            if strategy_key not in self.STRATEGY_KEYS:
                await self._answer_callback_query(query_id, text=ui_text(language, "unknown_action"))
                return
            settings = await self._activate_strategy_context(
                user,
                current_settings=settings,
                strategy_key=strategy_key,
            )
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            if str(action.extra or "hub") == "hub":
                await self._send_lifecycle_hub(
                    user,
                    strategy_code=strategy_key,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            else:
                await self._send_lifecycle_view(
                    user,
                    view=str(action.extra or "open"),
                    strategy_code=strategy_key,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            return
        if action.kind == "watchlist":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_watchlist"))
            await self._send_watchlist(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "access":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_access"))
            await self._send_access(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "referral":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_referral"))
            await self._send_referral_screen(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "status":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_status(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "help":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_help(user.telegram_user_id, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "help_page" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_help_page(
                user.telegram_user_id,
                page=action.value,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "onboarding_example":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_onboarding_example(
                user.telegram_user_id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "onboarding_read":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_signal_reading_guide(
                user.telegram_user_id,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "themes":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "control":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_control_center(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "analyze":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_analyze"))
            await self._send_analyze_symbol_help(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "guide":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            if action.value == "close":
                await self._cleanup_strategy_guide_message(
                    telegram_user_id=user.telegram_user_id,
                    chat_id=chat_id,
                )
                return
            await self._send_strategy_guide(user.telegram_user_id, chat_id=chat_id)
            return
        if action.kind == "goldview":
            await self._answer_callback_query(query_id)
            loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
                chat_id=chat_id,
                title=ui_text(language, "loading_symbol_title", symbol=normalize_symbol(self.settings.gold_symbol)),
                subtitle=ui_text(language, "loading_symbol_subtitle", timeframe=self.settings.scan_timeframe),
                language_code=language,
                reply_to_message_id=message_id,
            )
            try:
                await self._send_gold_snapshot(user)
            finally:
                await self.interactive_alert_service.stop_loading_indicator(
                    loading_handle,
                    final_stage="Снимок готов" if language == "ru" else "Snapshot ready",
                )
            return
        if action.kind == "goldhub":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_start":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._start_gold_wizard(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_set" and action.value and action.extra:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_gold_wizard_state(user.telegram_user_id)
            if state is None:
                await self._start_gold_wizard(user, chat_id=chat_id, edit_message_id=message_id)
                return
            draft = dict(state.draft or {})
            key = str(action.value)
            raw_value = str(action.extra)
            if key == "followups":
                draft["followups"] = raw_value == "on"
            else:
                draft[key] = raw_value
            await self._save_gold_wizard_state(user.telegram_user_id, step=state.step, draft=draft)
            await self._send_gold_wizard_step(user, step=state.step, draft=draft, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_next":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_gold_wizard_state(user.telegram_user_id)
            if state is None:
                await self._start_gold_wizard(user, chat_id=chat_id, edit_message_id=message_id)
                return
            current_index = self.GOLD_WIZARD_STEPS.index(state.step)
            next_step = self.GOLD_WIZARD_STEPS[min(current_index + 1, len(self.GOLD_WIZARD_STEPS) - 1)]
            await self._save_gold_wizard_state(user.telegram_user_id, step=next_step, draft=dict(state.draft or {}))
            await self._send_gold_wizard_step(user, step=next_step, draft=dict(state.draft or {}), chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_back":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_gold_wizard_state(user.telegram_user_id)
            if state is None:
                await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
                return
            if state.step == self.GOLD_WIZARD_STEPS[0]:
                await self._clear_gold_wizard_state(user.telegram_user_id)
                await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
                return
            current_index = self.GOLD_WIZARD_STEPS.index(state.step)
            prev_step = self.GOLD_WIZARD_STEPS[max(current_index - 1, 0)]
            await self._save_gold_wizard_state(user.telegram_user_id, step=prev_step, draft=dict(state.draft or {}))
            await self._send_gold_wizard_step(user, step=prev_step, draft=dict(state.draft or {}), chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_cancel":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._clear_gold_wizard_state(user.telegram_user_id)
            await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold_wizard_apply":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            state = await self._get_gold_wizard_state(user.telegram_user_id)
            if state is None:
                await self._send_gold_center(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._apply_gold_wizard(user, draft=dict(state.draft or {}), chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "custom" and action.value == "start":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_custom"))
            await self._start_custom_setup(
                user,
                settings,
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            return
        if action.kind == "custom" and action.value == "cancel":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_custom_cancelled"))
            await self._cancel_custom_setup(user, current_settings=settings)
            return
        if action.kind == "ai":
            if self.bot_kind == "premium" and not await self._has_premium_access(user):
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_premium_required"))
                await self._send_premium_access_required(
                    user.telegram_user_id,
                    feature_name=ui_text(language, "button_ai_analysis"),
                )
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_ai_pick(user)
            return
        if action.kind == "pro":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_pro_link(user.telegram_user_id)
            return
        if action.kind == "pay":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_preparing_renewal"))
            access_state = await self._effective_access_state_for_user(user)
            await self._send_payment_offer(
                user,
                allow_renewal=access_state.is_paid or access_state.access_status == "trial",
            )
            return
        if action.kind == "renew":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_preparing_renewal"))
            access_state = await self._effective_access_state_for_user(user)
            await self._send_payment_offer(user, allow_renewal=access_state.is_paid)
            return
        if action.kind == "signals":
            if self.bot_kind == "premium" and not await self._has_premium_access(user):
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_premium_required"))
                await self._send_payment_offer(user)
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_refreshing_list"))
            loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
                chat_id=chat_id,
                title=ui_text(language, "loading_signals_title"),
                subtitle=ui_text(language, "loading_signals_subtitle"),
                language_code=language,
                reply_to_message_id=message_id,
            )
            try:
                await self._send_recent_signals(
                    user,
                    strong_only=action.value == "strong",
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            finally:
                await self.interactive_alert_service.stop_loading_indicator(
                    loading_handle,
                    final_stage="Сигналы готовы" if language == "ru" else "Signals ready",
                )
            return
        if action.kind == "open_signal" and action.value and action.value.isdigit():
            if self.bot_kind == "premium" and not await self._has_premium_access(user):
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_premium_required"))
                await self._send_payment_offer(user)
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_signal"))
            alert = await self.repository.get_alert(int(action.value))
            if alert is None:
                await self._send_inline_error(chat_id, ui_text(language, "interactive_stale"))
                return
            selection = _PrivateSelection(
                alert=alert,
                followup=None,
            )
            loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
                chat_id=chat_id,
                title=ui_text(language, "loading_symbol_title", symbol=normalize_symbol(alert.symbol)),
                subtitle=ui_text(language, "loading_signal_card_subtitle", timeframe=alert.timeframe),
                language_code=language,
                reply_to_message_id=message_id,
            )
            try:
                await self._send_selection_card(user.telegram_user_id, selection)
            finally:
                await self.interactive_alert_service.stop_loading_indicator(
                    loading_handle,
                    final_stage="Карточка готова" if language == "ru" else "Card ready",
                )
            return
        if action.kind == "profile" and action.value:
            if action.value == "reset":
                await self._reset_profile_to_base(user, settings)
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_profile_reset"))
            else:
                await self._apply_profile_choice(user, settings, action.value)
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_profile_updated"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "strategy_pref" and action.value and action.extra:
            await self._apply_strategy_preference_choice(
                user,
                settings,
                key=action.value,
                value=action.extra,
            )
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "rsi" and action.value:
            await self._apply_rsi_mode_choice(user, settings, action.value)
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_rsi_updated"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "volume" and action.value:
            await self._apply_volume_choice(user, settings, action.value)
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_volume_updated"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "direction" and action.value:
            session = self._custom_setup_sessions.get(user.telegram_user_id)
            if session is not None:
                if session.step == "direction":
                    await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
                    await self._complete_custom_setup(
                        user,
                        current_settings=settings,
                        direction_filter=action.value,
                    )
                    return
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_opening_custom"))
                await self._send_custom_setup_prompt(user, current_settings=settings)
                return
            await self._apply_direction_choice(user, settings, action.value)
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_direction_updated"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "universe" and action.value:
            if action.value == "set" and not self._set_scope_active(settings):
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_choose_set"))
                await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._apply_universe_choice(user, settings, action.value)
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_universe_updated"))
            await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "gold" and action.value in {"toggle", "delivery", "hub"}:
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_gold_updated"))
            await self._toggle_gold_alert_delivery(
                user,
                enable=not self._gold_alerts_enabled_for_settings(shell_settings),
                refresh_hub=action.value in {"delivery", "hub"},
                origin="delivery" if action.value == "delivery" else "gold",
                chat_id=chat_id,
                edit_message_id=message_id,
            )
            if action.value == "toggle":
                await self._send_signal_setup(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "watch_open" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
                chat_id=chat_id,
                title=ui_text(language, "loading_symbol_title", symbol=normalize_symbol(action.value)),
                subtitle=ui_text(language, "loading_symbol_subtitle", timeframe=self.settings.scan_timeframe),
                language_code=language,
                reply_to_message_id=message_id,
            )
            try:
                await self._send_symbol_lookup_result(user, symbol_input=action.value, timeframe=self.settings.scan_timeframe)
            finally:
                await self.interactive_alert_service.stop_loading_indicator(
                    loading_handle,
                    final_stage="Готово" if language == "ru" else "Ready",
                )
            return
        if action.kind == "watch_remove" and action.value:
            if self.bot_kind == "premium":
                removed = await self.repository.remove_premium_strategy_watchlist_symbol(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=self._resolved_active_strategy_key(settings) or "rsi",
                    symbol=normalize_symbol(action.value),
                )
            else:
                removed = await self.repository.remove_user_watchlist_symbol(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    symbol=normalize_symbol(action.value),
                )
            await self._answer_callback_query(
                query_id,
                text=ui_text(language, "callback_removed_watchlist" if removed else "callback_watchlist_missing"),
            )
            await self._send_watchlist(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "theme_save":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._prompt_theme_action(user, action="save")
            return
        if action.kind == "theme_all":
            await self._apply_universe_choice(user, settings, "all")
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "theme_builtin" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._activate_builtin_theme(user, settings, action.value)
            await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind == "theme_open" and action.value and action.value.isdigit():
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._activate_saved_theme(user, settings, int(action.value))
            await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
            return
        if action.kind in {"theme_add", "theme_rename", "theme_delete"} and action.value and action.value.isdigit():
            if self.bot_kind == "premium":
                themes = await self.repository.list_premium_strategy_watchlist_themes(
                    user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=self._resolved_active_strategy_key(settings) or "rsi",
                )
            else:
                themes = await self.repository.list_user_watchlist_themes(user.telegram_user_id, bot_kind=self.bot_kind)
            theme = next((item for item in themes if item.id == int(action.value)), None)
            if theme is None:
                await self._answer_callback_query(query_id, text=premium_text(language, "watchlists_theme_missing"))
                return
            if action.kind == "theme_delete":
                if self.bot_kind == "premium":
                    deleted = await self.repository.delete_premium_strategy_watchlist_theme(
                        telegram_user_id=user.telegram_user_id,
                        bot_kind=self.bot_kind,
                        strategy_key=self._resolved_active_strategy_key(settings) or "rsi",
                        theme_name=theme.theme_name,
                    )
                else:
                    deleted = await self.repository.delete_user_watchlist_theme(
                        telegram_user_id=user.telegram_user_id,
                        bot_kind=self.bot_kind,
                        theme_name=theme.theme_name,
                    )
                if deleted and settings.active_custom_theme_name == theme.theme_name:
                    settings = await self._save_user_settings(
                        user=user,
                        current_settings=settings,
                        active_custom_theme_name=None,
                        active_watchlist_theme="custom",
                    )
                await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
                await self._send_watchlist_themes_manager(user, chat_id=chat_id, edit_message_id=message_id)
                return
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            await self._prompt_theme_action(
                user,
                action="add" if action.kind == "theme_add" else "rename",
                theme_id=theme.id,
                theme_name=theme.theme_name,
            )
            return
        if action.kind == "delivery_mode" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            raw_shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            delivery_settings, delivery_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="delivery",
                shell_settings=raw_shell_settings,
            )
            if self.bot_kind == "premium" and not self._is_strategy_origin(delivery_origin):
                now = utc_now()
                previous_mode = str(raw_shell_settings.delivery_mode or "instant")
                await self._apply_delivery_settings_to_enabled_strategies(
                    user,
                    shell_settings=raw_shell_settings,
                    delivery_mode=action.value,
                    delivery_mode_changed_at=now,
                )
                if previous_mode in {"digest", "quiet"} and action.value == "instant":
                    since = raw_shell_settings.delivery_mode_changed_at or (now - timedelta(hours=24))
                    await self._send_resume_summary(user, since=since)
                else:
                    await self._send_delivery_center(
                        user,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
            else:
                await self._change_delivery_mode(
                    user,
                    delivery_settings,
                    action.value,
                    origin=delivery_origin,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            return
        if action.kind == "snooze" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            raw_shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            delivery_settings, delivery_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="delivery",
                shell_settings=raw_shell_settings,
            )
            if self.bot_kind == "premium" and not self._is_strategy_origin(delivery_origin):
                now = utc_now()
                if action == "resume":
                    since = delivery_settings.snooze_started_at or (now - timedelta(hours=24))
                    await self._apply_delivery_settings_to_enabled_strategies(
                        user,
                        shell_settings=raw_shell_settings,
                        snooze_until=now,
                        snooze_started_at=None,
                        snooze_label=None,
                    )
                    await self._send_resume_summary(user, since=since)
                else:
                    local_now = now.astimezone(self.settings.timezone)
                    if action == "1h":
                        snooze_until = now + timedelta(hours=1)
                    elif action == "8h":
                        snooze_until = now + timedelta(hours=8)
                    elif action == "tomorrow":
                        tomorrow = (local_now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
                        snooze_until = tomorrow.astimezone(now.tzinfo)
                    else:
                        tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        snooze_until = tomorrow.astimezone(now.tzinfo)
                    await self._apply_delivery_settings_to_enabled_strategies(
                        user,
                        shell_settings=raw_shell_settings,
                        snooze_until=snooze_until,
                        snooze_started_at=now,
                        snooze_label=action,
                    )
                    await self._send_delivery_center(
                        user,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
            else:
                await self._apply_snooze_action(
                    user,
                    delivery_settings,
                    action.value,
                    origin=delivery_origin,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            return
        if action.kind == "quiet_hours" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            raw_shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            delivery_settings, delivery_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="delivery",
                shell_settings=raw_shell_settings,
            )
            preset_key = str(action.value or "").strip().lower()
            if preset_key == "toggle":
                quiet_hours_active = (
                    delivery_settings.quiet_hours_start_minute is not None
                    and delivery_settings.quiet_hours_end_minute is not None
                )
                preset_key = "off" if quiet_hours_active else "late"
            if self.bot_kind == "premium" and not self._is_strategy_origin(delivery_origin):
                draft = apply_quiet_hours_preset({}, preset_key)
                await self._apply_delivery_settings_to_enabled_strategies(
                    user,
                    shell_settings=raw_shell_settings,
                    quiet_hours_start_minute=draft.get("quiet_hours_start_minute"),
                    quiet_hours_end_minute=draft.get("quiet_hours_end_minute"),
                )
                await self._send_delivery_center(
                    user,
                    origin=delivery_origin,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            else:
                await self._apply_quiet_hours_preset(
                    user,
                    delivery_settings,
                    preset_key,
                    origin=delivery_origin,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
            return
        if action.kind == "toggle" and action.value:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            raw_shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            delivery_settings, delivery_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="delivery",
                shell_settings=raw_shell_settings,
            )
            if action.value == "alerts":
                if self.bot_kind == "premium" and not self._is_strategy_origin(delivery_origin):
                    await self._apply_delivery_settings_to_enabled_strategies(
                        user,
                        shell_settings=raw_shell_settings,
                        direct_signal_delivery_enabled=not delivery_settings.direct_signal_delivery_enabled,
                    )
                    await self._send_delivery_center(
                        user,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
                else:
                    await self._toggle_direct_delivery(
                        user,
                        enable=not delivery_settings.direct_signal_delivery_enabled,
                        current_settings=delivery_settings,
                        refresh_hub=True,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
                return
            if action.value == "followups":
                if self.bot_kind == "premium" and not self._is_strategy_origin(delivery_origin):
                    await self._apply_delivery_settings_to_enabled_strategies(
                        user,
                        shell_settings=raw_shell_settings,
                        followup_delivery_enabled=not delivery_settings.followup_delivery_enabled,
                    )
                    await self._send_delivery_center(
                        user,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
                else:
                    await self._toggle_followup_delivery(
                        user,
                        enable=not delivery_settings.followup_delivery_enabled,
                        current_settings=delivery_settings,
                        refresh_hub=True,
                        origin=delivery_origin,
                        chat_id=chat_id,
                        edit_message_id=message_id,
                    )
                return
        if action.kind == "recap" and action.value in {"daily", "weekly"}:
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            raw_shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            stats_settings, stats_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="stats",
                shell_settings=raw_shell_settings,
            )
            await self._send_recap(
                user,
                period=action.value,
                chat_id=chat_id,
                edit_message_id=message_id,
                current_settings=stats_settings,
                strategy_scoped=self._is_strategy_origin(stats_origin),
            )
            return
        if action.kind == "onboard":
            await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
            if action.value == "start":
                await self._start_or_resume_onboarding(
                    user.telegram_user_id,
                    restart=True,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
            if action.value and action.extra:
                await self._apply_onboarding_choice(
                    user,
                    step=action.value,
                    value=action.extra,
                    chat_id=chat_id,
                    edit_message_id=message_id,
                )
                return
        if action.kind == "language_picker":
            await self._send_language_picker(
                user.telegram_user_id,
                chat_id=chat_id,
                edit_message_id=message_id,
                preferred_language=language,
                context=action.value or "settings",
                first_time=False,
            )
            return
        if action.kind == "language_set" and action.value in {"en", "ru"}:
            await self._apply_language_choice(
                user,
                current_settings=settings,
                language_code=action.value,
                chat_id=chat_id,
                edit_message_id=message_id,
                context=action.extra or "settings",
            )
            return

        await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))

    async def deliver_pro_alert(self, signal: AlertSignal, alert_id: int) -> None:
        if not self.settings.private_bot_enabled or not self.settings.private_bot_signal_delivery_enabled:
            LOGGER.info("Skipping PRIVATE live for %s: private bot delivery disabled", signal.symbol)
            await self._update_tracked_signal_delivery_audit(
                alert_id=alert_id,
                delivery_sent=False,
                delivery_suppressed_reason="private_delivery_disabled",
                strategy_enabled_at_delivery=False,
            )
            return
        live_decision = self._evaluate_private_live(signal)
        if not live_decision.eligible:
            LOGGER.info("Skipping PRIVATE live for %s: %s", signal.symbol, live_decision.reason)
            await self._update_tracked_signal_delivery_audit(
                alert_id=alert_id,
                delivery_sent=False,
                delivery_suppressed_reason="global_live_filter",
                strategy_enabled_at_delivery=False,
                extra_metadata={"delivery_filter_reason": live_decision.reason},
            )
            return
        recipients = await self.repository.list_private_signal_recipients(
            bot_kind=self.bot_kind,
            access_levels=self._recipient_access_levels(),
            require_direct_enabled=self.bot_kind != "premium",
        )
        if not recipients:
            LOGGER.info("Skipping PRIVATE live for %s: no opted-in recipients", signal.symbol)
            await self._update_tracked_signal_delivery_audit(
                alert_id=alert_id,
                delivery_sent=False,
                delivery_suppressed_reason="no_recipients",
                strategy_enabled_at_delivery=False,
            )
            return
        is_gold_signal = self._is_gold_signal(signal)
        sent_count = 0
        filter_skips = 0
        duplicate_skips = 0
        access_skips = 0
        gold_toggle_skips = 0
        strategy_disabled_skips = 0
        delivery_toggle_skips = 0
        queued_count = 0
        strategy_enabled_recipients = 0
        watchlist_cache: dict[int, set[str]] = {}
        now = utc_now()
        strategy_key = self._signal_strategy_key(signal)
        for user, settings in recipients:
            if not await self._has_premium_access(user):
                access_skips += 1
                continue
            shell_settings = settings or await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            if shell_settings is None:
                shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            if shell_settings is None:
                shell_settings = await self._ensure_user_settings(user.telegram_user_id)
            if not self._strategy_enabled_for_settings(shell_settings, strategy_key=strategy_key):
                strategy_disabled_skips += 1
                if is_gold_signal:
                    gold_toggle_skips += 1
                continue
            strategy_enabled_recipients += 1
            effective_settings = await self._load_strategy_settings(
                user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            if not effective_settings.direct_signal_delivery_enabled:
                delivery_toggle_skips += 1
                continue
            watchlist_symbols = await self._watchlist_set(
                user.telegram_user_id,
                cache=watchlist_cache,
            )
            if self.bot_kind == "premium":
                watchlist_symbols = set(
                    await self._watchlist_symbols_for_strategy(
                        user.telegram_user_id,
                        strategy_key=strategy_key,
                        settings=effective_settings,
                    )
                )
            favorite_symbols = set(await self._global_favorite_symbols(user.telegram_user_id))
            personalized_signal = self._apply_user_preferences_to_signal(
                signal,
                effective_settings,
                watchlist_symbols=watchlist_symbols,
            )
            matches_filters, _ = self._signal_matches_user_settings(
                personalized_signal,
                effective_settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                strong_only=False,
            )
            if not matches_filters:
                filter_skips += 1
                continue
            if await self.repository.delivered_signal_exists(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=alert_id,
                content_kind=self.content_kind,
                message_kind="alert",
            ):
                duplicate_skips += 1
                continue
            watchlist_hit = self._watchlist_hit(personalized_signal.symbol, watchlist_symbols)
            queue_reason = await self._live_delivery_queue_reason(
                personalized_signal,
                effective_settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                telegram_user_id=user.telegram_user_id,
                now=now,
            )
            if queue_reason is not None:
                await self._record_private_candidate(
                    user=user,
                    alert_id=alert_id,
                    message_kind="queued:alert",
                    symbol=personalized_signal.symbol,
                    score=personalized_signal.score,
                    queue_reason=queue_reason,
                    watchlist_hit=watchlist_hit,
                    metadata={
                        "delivery_mode": effective_settings.delivery_mode,
                        "direction": personalized_signal.direction,
                        "strategy_key": strategy_key,
                        "favorite_hit": normalize_symbol(personalized_signal.symbol) in favorite_symbols,
                    },
                )
                queued_count += 1
                continue
            personalized_signal = await self._enrich_okak_signal_for_private_user(
                personalized_signal,
                user=user,
            )
            delivery = await self.router.send_raw_alert_to_chat(
                personalized_signal,
                chat_id=str(user.telegram_user_id),
                destination_kind="private",
                preview=False,
            )
            await self._register_private_delivery(
                user=user,
                delivery=delivery,
                signal=personalized_signal,
                alert_id=alert_id,
                message_kind="alert",
                content_kind=self.content_kind,
                record_metadata={
                    "symbol": normalize_symbol(personalized_signal.symbol),
                    "score": personalized_signal.score,
                    "watchlist_hit": watchlist_hit,
                    "favorite_hit": normalize_symbol(personalized_signal.symbol) in favorite_symbols,
                    "delivery_mode": effective_settings.delivery_mode,
                    "strategy_key": strategy_key,
                },
            )
            if delivery.sent:
                sent_count += 1
                await self._mirror_private_admin_alert_to_results(
                    user=user,
                    delivery=delivery,
                    signal=personalized_signal,
                    alert_id=alert_id,
                )
        LOGGER.info(
            "PRIVATE live delivery for %s: eligible (%s), recipients=%s, sent=%s, queued=%s, skipped_by_access=%s, skipped_by_strategy_toggle=%s, skipped_by_user_filters=%s, skipped_duplicates=%s",
            signal.symbol,
            live_decision.reason,
            len(recipients),
            sent_count,
            queued_count,
            access_skips,
            delivery_toggle_skips,
            filter_skips,
            duplicate_skips,
        )
        if gold_toggle_skips:
            LOGGER.info(
                "PRIVATE live delivery for %s skipped %s recipients because gold alerts were disabled",
                signal.symbol,
                gold_toggle_skips,
            )
        suppressed_reason: str | None = None
        if sent_count <= 0:
            if queued_count > 0:
                suppressed_reason = "queued"
            elif strategy_enabled_recipients <= 0:
                suppressed_reason = "strategy_disabled"
            elif delivery_toggle_skips >= strategy_enabled_recipients > 0:
                suppressed_reason = "delivery_disabled"
            elif filter_skips > 0:
                suppressed_reason = "user_filters"
            elif access_skips >= len(recipients):
                suppressed_reason = "no_access"
            elif duplicate_skips > 0:
                suppressed_reason = "duplicates_only"
            else:
                suppressed_reason = "not_sent"
        await self._update_tracked_signal_delivery_audit(
            alert_id=alert_id,
            delivery_sent=sent_count > 0,
            delivery_suppressed_reason=suppressed_reason,
            strategy_enabled_at_delivery=strategy_enabled_recipients > 0,
            extra_metadata={
                "delivery_attempted_recipients": len(recipients),
                "delivery_sent_count": sent_count,
                "delivery_suppressed_count": max(len(recipients) - sent_count, 0),
                "delivery_filter_skips": filter_skips,
                "delivery_duplicate_skips": duplicate_skips,
                "delivery_access_skips": access_skips,
                "delivery_gold_toggle_skips": gold_toggle_skips,
                "delivery_strategy_disabled_skips": strategy_disabled_skips,
                "delivery_toggle_skips": delivery_toggle_skips,
                "delivery_queued_count": queued_count,
                "strategy_enabled_recipients": strategy_enabled_recipients,
            },
        )

    async def _update_tracked_signal_delivery_audit(
        self,
        *,
        alert_id: int,
        delivery_sent: bool,
        delivery_suppressed_reason: str | None,
        strategy_enabled_at_delivery: bool,
        extra_metadata: dict[str, object] | None = None,
    ) -> None:
        tracked_signal = await self.repository.get_tracked_signal_by_alert_id(alert_id)
        if tracked_signal is None:
            return
        metadata = dict(tracked_signal.metadata or {})
        metadata.update(
            {
                "delivery_sent": bool(delivery_sent),
                "delivery_suppressed_reason": delivery_suppressed_reason,
                "strategy_enabled_at_delivery": bool(strategy_enabled_at_delivery),
            }
        )
        if extra_metadata:
            metadata.update(extra_metadata)
        await self.repository.update_tracked_signal(
            tracked_signal.signal_id,
            metadata=metadata,
        )

    def _is_results_mirror_admin(self, user: PrivateBotUserRecord) -> bool:
        configured_username = self.settings.private_bot_results_mirror_admin_username.strip().lstrip("@").casefold()
        username = str(user.username or "").strip().lstrip("@").casefold()
        return bool(configured_username) and username == configured_username

    async def _mirror_private_admin_alert_to_results(
        self,
        *,
        user: PrivateBotUserRecord,
        delivery,
        signal: AlertSignal,
        alert_id: int,
    ) -> None:
        if (
            self.bot_kind != "premium"
            or self.destination_kind != "private"
            or not self.settings.private_bot_results_mirror_enabled
            or not delivery.sent
            or not self._is_results_mirror_admin(user)
        ):
            return
        destination = self.settings.private_bot_results_mirror_destination
        if not destination:
            return
        try:
            mirror_delivery = await self.router.send_raw_alert_to_chat(
                signal,
                chat_id=destination,
                destination_kind="results",
                preview=False,
            )
            if mirror_delivery.sent and mirror_delivery.telegram_message_id is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="results",
                    chat_id=str(mirror_delivery.metadata.get("telegram_chat_id") or destination),
                    message_id=mirror_delivery.telegram_message_id,
                    signal=signal,
                    alert_id=alert_id,
                    is_preview=False,
                    message_kind="alert",
                )
            LOGGER.info(
                "Mirrored PRIVATE admin alert for %s user=%s destination=%s sent=%s",
                signal.symbol,
                user.telegram_user_id,
                destination,
                mirror_delivery.sent,
            )
        except Exception:
            LOGGER.exception(
                "Failed to mirror PRIVATE admin alert for %s user=%s destination=%s",
                signal.symbol,
                user.telegram_user_id,
                destination,
            )

    def _why_received_text(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord | None,
        *,
        watchlist_symbols: set[str],
        language_code: str,
    ) -> str:
        if settings is None:
            return (
                "It matches your current delivery filters."
                if language_code == "en"
                else "Он совпал с твоими текущими фильтрами доставки."
            )
        strategy_key = self._signal_strategy_key(signal)
        preferences = self._strategy_preferences(settings, strategy_key=strategy_key)
        reasons: list[str] = []
        symbol = normalize_symbol(signal.symbol)
        if symbol in watchlist_symbols:
            reasons.append(
                "your current watchlist"
                if language_code == "en"
                else "твой текущий watchlist"
            )
        allowed_timeframes = strategy_allowed_timeframes(strategy_key, preferences)
        if allowed_timeframes:
            reasons.append(
                f"your {'/'.join(allowed_timeframes)} timeframe focus"
                if language_code == "en"
                else f"твой фокус по ТФ {'/'.join(allowed_timeframes)}"
            )
        profile_label = str(settings.signal_profile or "balanced").replace("_", " ").title()
        reasons.append(
            f"your {profile_label} setup"
            if language_code == "en"
            else f"твой режим {profile_label}"
        )
        if settings.direction_filter != "both":
            direction_label = "long only" if settings.direction_filter == "long" else "short only"
            reasons.append(
                f"your {direction_label} bias"
                if language_code == "en"
                else ("лонг-фильтр" if settings.direction_filter == "long" else "шорт-фильтр")
            )
        if strategy_key in GOLD_SUBSTRATEGY_KEY_SET or strategy_key == "gold":
            reasons.append(
                "gold is enabled in your workspace"
                if language_code == "en"
                else "золото включено в твоём workspace"
            )
        compact_reasons = ", ".join(reason for reason in reasons[:3] if reason)
        if language_code == "ru":
            return (
                f"Ты получил этот сигнал, потому что он совпал с настройками: {compact_reasons}."
                if compact_reasons
                else "Ты получил этот сигнал, потому что он совпал с твоими текущими фильтрами."
            )
        return (
            f"You received this because it matches {compact_reasons}."
            if compact_reasons
            else "You received this because it matches your current delivery filters."
        )

    async def deliver_pro_followup(
        self,
        signal: AlertSignal,
        result: FollowUpResult,
        *,
        preferred_chart_path: Path | None = None,
        mirror_if_twitter_eligible: bool = False,
    ) -> None:
        del preferred_chart_path
        if not self.settings.private_bot_enabled or not self.settings.private_bot_signal_delivery_enabled:
            LOGGER.info("Skipping PRIVATE follow-up for %s: private bot delivery disabled", result.symbol)
            return
        followup_decision = self._evaluate_private_followup(signal, result)
        if not followup_decision.eligible:
            if mirror_if_twitter_eligible and (result.thesis_result_state or "neutral") == "favorable":
                LOGGER.info(
                    "Mirroring PRIVATE follow-up for %s despite strict private filter skip: %s",
                    result.symbol,
                    followup_decision.reason,
                )
            else:
                LOGGER.info("Skipping PRIVATE follow-up for %s: %s", result.symbol, followup_decision.reason)
                return
        LOGGER.info(
            "PRIVATE follow-up for %s stage=%s is deferred to evening top-result slots at 18:00 and 21:00 %s",
            result.symbol,
            result.stage,
            self.settings.timezone.key,
        )
        return

    async def _register_private_delivery(
        self,
        *,
        user: PrivateBotUserRecord,
        delivery,
        signal: AlertSignal,
        alert_id: int,
        message_kind: str,
        content_kind: str,
        record_message_kind: str | None = None,
        record_metadata: dict[str, object] | None = None,
    ) -> None:
        if delivery.sent and delivery.telegram_message_id is not None:
            await self.interactive_alert_service.register_alert_message(
                destination_kind=self.destination_kind,
                chat_id=str(user.telegram_user_id),
                message_id=delivery.telegram_message_id,
                signal=signal,
                alert_id=alert_id,
                is_preview=False,
                message_kind=message_kind,
            )
        await self.repository.record_delivered_signal(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            alert_id=alert_id,
            content_kind=content_kind,
            message_kind=record_message_kind or message_kind,
            telegram_message_id=delivery.telegram_message_id,
            metadata={"sent": delivery.sent, **(record_metadata or {})},
        )

    async def run_delivery_maintenance(self) -> None:
        recipients = await self.repository.list_private_signal_recipients(
            bot_kind=self.bot_kind,
            access_levels=self._recipient_access_levels(),
            require_direct_enabled=False,
        )
        now = utc_now()
        for user, settings in recipients:
            if self.bot_kind == "premium" and not await self._has_premium_access(user):
                continue
            if self.bot_kind == "premium":
                shell_settings = settings or await self.repository.get_user_settings(
                    user.telegram_user_id,
                    bot_kind=self.bot_kind,
                )
                if shell_settings is None:
                    shell_settings = await self._ensure_user_settings(user.telegram_user_id)
                for strategy_key in self._enabled_strategy_keys(shell_settings):
                    effective_settings = await self._load_strategy_settings(
                        user.telegram_user_id,
                        shell_settings=shell_settings,
                        strategy_key=strategy_key,
                    )
                    if (
                        not effective_settings.direct_signal_delivery_enabled
                        and not effective_settings.followup_delivery_enabled
                        and str(effective_settings.delivery_mode or "instant").strip().lower() == "instant"
                    ):
                        continue
                    if (
                        effective_settings.snooze_until is not None
                        and effective_settings.snooze_started_at is not None
                        and effective_settings.snooze_until <= now
                        and (
                            effective_settings.last_resume_summary_at is None
                            or effective_settings.last_resume_summary_at < effective_settings.snooze_until
                        )
                    ):
                        snooze_started_at = effective_settings.snooze_started_at
                        await self._save_strategy_runtime_state(
                            user=user,
                            current_settings=effective_settings,
                            snooze_until=None,
                            snooze_started_at=None,
                            snooze_label=None,
                        )
                        await self._send_resume_summary(
                            user,
                            since=snooze_started_at,
                            current_settings=effective_settings,
                        )
                    if str(effective_settings.delivery_mode or "instant") == "digest":
                        await self._send_hourly_digest_if_due(user, current_settings=effective_settings)
                    await self._send_evening_followup_tops_if_due(user, current_settings=effective_settings, now=now)
                    await self._send_scheduled_recap_if_due(user, current_settings=effective_settings, period="daily")
                    await self._send_scheduled_recap_if_due(user, current_settings=effective_settings, period="weekly")
                continue

            effective_settings = settings or await self._ensure_user_settings(user.telegram_user_id)
            if (
                effective_settings.snooze_until is not None
                and effective_settings.snooze_started_at is not None
                and effective_settings.snooze_until <= now
                and (
                    effective_settings.last_resume_summary_at is None
                    or effective_settings.last_resume_summary_at < effective_settings.snooze_until
                )
            ):
                await self._save_user_settings(
                    user=user,
                    current_settings=effective_settings,
                    snooze_until=None,
                    snooze_started_at=None,
                    snooze_label=None,
                )
                await self._send_resume_summary(user, since=effective_settings.snooze_started_at)
                effective_settings = await self._ensure_user_settings(user.telegram_user_id)
            if str(effective_settings.delivery_mode or "instant") == "digest":
                await self._send_hourly_digest_if_due(user, current_settings=effective_settings)
                effective_settings = await self._ensure_user_settings(user.telegram_user_id)
            await self._send_evening_followup_tops_if_due(user, current_settings=effective_settings, now=now)
            await self._send_scheduled_recap_if_due(user, current_settings=effective_settings, period="daily")
            effective_settings = await self._ensure_user_settings(user.telegram_user_id)
            await self._send_scheduled_recap_if_due(user, current_settings=effective_settings, period="weekly")

    async def _save_strategy_runtime_state(
        self,
        *,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        delivery_mode=...,
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
    ) -> UserSettingsRecord:
        if self.bot_kind != "premium":
            return await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                delivery_mode=current_settings.delivery_mode if delivery_mode is Ellipsis else delivery_mode,
                delivery_mode_changed_at=delivery_mode_changed_at,
                quiet_hours_start_minute=quiet_hours_start_minute,
                quiet_hours_end_minute=quiet_hours_end_minute,
                snooze_until=snooze_until,
                snooze_started_at=snooze_started_at,
                snooze_label=snooze_label,
                last_resume_summary_at=last_resume_summary_at,
                last_digest_sent_at=last_digest_sent_at,
                last_daily_recap_at=last_daily_recap_at,
                last_weekly_recap_at=last_weekly_recap_at,
            )

        shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
        assert shell_settings is not None
        strategy_key = str(current_settings.active_strategy_key or "").strip().lower() or "rsi"
        strategy_settings = await self._ensure_premium_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        await self.repository.upsert_premium_strategy_settings(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
            direct_signal_delivery_enabled=strategy_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=strategy_settings.followup_delivery_enabled,
            signal_profile=strategy_settings.signal_profile,
            base_signal_profile=strategy_settings.base_signal_profile,
            preferred_min_score=strategy_settings.preferred_min_score,
            min_quote_volume=strategy_settings.min_quote_volume,
            rsi_oversold=strategy_settings.rsi_oversold,
            rsi_overbought=strategy_settings.rsi_overbought,
            direction_filter=strategy_settings.direction_filter,
            watchlist_only=strategy_settings.watchlist_only,
            delivery_mode=strategy_settings.delivery_mode if delivery_mode is Ellipsis else delivery_mode,
            delivery_mode_changed_at=(
                strategy_settings.delivery_mode_changed_at
                if delivery_mode_changed_at is Ellipsis
                else delivery_mode_changed_at
            ),
            quiet_hours_start_minute=(
                strategy_settings.quiet_hours_start_minute
                if quiet_hours_start_minute is Ellipsis
                else quiet_hours_start_minute
            ),
            quiet_hours_end_minute=(
                strategy_settings.quiet_hours_end_minute
                if quiet_hours_end_minute is Ellipsis
                else quiet_hours_end_minute
            ),
            snooze_until=strategy_settings.snooze_until if snooze_until is Ellipsis else snooze_until,
            snooze_started_at=(
                strategy_settings.snooze_started_at
                if snooze_started_at is Ellipsis
                else snooze_started_at
            ),
            snooze_label=strategy_settings.snooze_label if snooze_label is Ellipsis else snooze_label,
            last_resume_summary_at=(
                strategy_settings.last_resume_summary_at
                if last_resume_summary_at is Ellipsis
                else last_resume_summary_at
            ),
            last_digest_sent_at=(
                strategy_settings.last_digest_sent_at
                if last_digest_sent_at is Ellipsis
                else last_digest_sent_at
            ),
            last_daily_recap_at=(
                strategy_settings.last_daily_recap_at
                if last_daily_recap_at is Ellipsis
                else last_daily_recap_at
            ),
            last_weekly_recap_at=(
                strategy_settings.last_weekly_recap_at
                if last_weekly_recap_at is Ellipsis
                else last_weekly_recap_at
            ),
            active_watchlist_theme=strategy_settings.active_watchlist_theme,
            active_custom_theme_name=strategy_settings.active_custom_theme_name,
            strategy_preferences=strategy_settings.strategy_preferences,
        )
        return await self._load_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )

    async def _send_evening_followup_tops_if_due(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        now: datetime | None = None,
    ) -> None:
        if not current_settings.followup_delivery_enabled:
            return

        effective_now = now or utc_now()
        local_now = effective_now.astimezone(self.settings.timezone)
        day_start, _ = local_day_bounds(local_now.date(), self.settings.timezone)
        active_strategy_key = str(current_settings.active_strategy_key or "").strip().lower() or "rsi"
        sent_today = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            message_kind_prefix="followup:top",
            since=day_start,
            limit=8,
        )
        if self.bot_kind == "premium":
            sent_today = [
                record
                for record in sent_today
                if str(record.metadata.get("strategy_key") or "").strip().lower() == active_strategy_key
            ]
        slot_delivery_counts = {
            slot_hour: 0
            for slot_hour in self.EVENING_FOLLOWUP_TOP_SLOT_HOURS
        }
        for record in sent_today:
            slot_hour = record.metadata.get("slot_hour")
            if not isinstance(slot_hour, (int, float)):
                continue
            normalized_slot = int(slot_hour)
            if normalized_slot not in slot_delivery_counts or not bool(record.metadata.get("sent", True)):
                continue
            slot_delivery_counts[normalized_slot] += 1
        sent_alert_ids = {
            int(record.alert_id)
            for record in sent_today
            if record.alert_id is not None and bool(record.metadata.get("sent", True))
        }

        for slot_hour in self.EVENING_FOLLOWUP_TOP_SLOT_HOURS:
            remaining_slot_capacity = self.EVENING_FOLLOWUP_TOPS_PER_SLOT - slot_delivery_counts.get(slot_hour, 0)
            if local_now.hour < slot_hour or remaining_slot_capacity <= 0:
                continue
            candidates = await self._select_evening_followup_top_candidates(
                user,
                current_settings=current_settings,
                start=day_start,
                end=effective_now + timedelta(minutes=1),
                exclude_alert_ids=sent_alert_ids,
            )
            if not candidates:
                continue
            for alert, followup in candidates[:remaining_slot_capacity]:
                try:
                    delivery = await self._send_followup_card(user.telegram_user_id, alert, followup)
                except Exception:
                    LOGGER.exception(
                        "Failed to send PRIVATE evening follow-up top user=%s slot=%s alert_id=%s symbol=%s",
                        user.telegram_user_id,
                        slot_hour,
                        alert.id,
                        followup.symbol,
                    )
                    continue
                if delivery is None or not getattr(delivery, "sent", False):
                    continue
                slot_delivery_counts[slot_hour] = slot_delivery_counts.get(slot_hour, 0) + 1
                sent_alert_ids.add(alert.id)
                await self.repository.record_delivered_signal(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    alert_id=alert.id,
                    content_kind=self.content_kind,
                    message_kind="followup:top",
                    telegram_message_id=delivery.telegram_message_id,
                    metadata={
                        "sent": True,
                        "slot_hour": slot_hour,
                        "slot_position": slot_delivery_counts[slot_hour],
                        "strategy_key": active_strategy_key,
                        "symbol": normalize_symbol(followup.symbol),
                        "stage": followup.stage,
                        "score": followup.score,
                        "move_pct": followup.move_pct,
                        "favorable_move_pct": float(followup.metadata.get("favorable_move_pct") or 0.0),
                    },
                )

    async def _send_admin_audit_digest_if_due(
        self,
        user: PrivateBotUserRecord,
        *,
        shell_settings: UserSettingsRecord,
        now: datetime,
    ) -> None:
        if self.bot_kind != "premium" or not self.role_guard.is_admin(user):
            return

        language = self._language_code(shell_settings)
        recent_digests = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            message_kind_prefix="admin:audit:digest",
            since=now - timedelta(minutes=self.ADMIN_AUDIT_DIGEST_COOLDOWN_MINUTES),
            limit=2,
        )
        if recent_digests:
            return

        window_start = now - timedelta(hours=24)
        summary = await self.admin_monitoring_service.build_summary(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            enabled_strategy_keys=self._enabled_strategy_keys(shell_settings),
            start=window_start,
            end=now + timedelta(minutes=1),
        )
        candidates = list(
            self.admin_monitoring_service.select_digest_items(
                summary,
                limit=self.ADMIN_AUDIT_DIGEST_ITEM_LIMIT,
            )
        )
        if not candidates:
            return

        unsent: list = []
        for item in candidates:
            if item.alert_id is None:
                continue
            if await self.repository.delivered_signal_exists(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=item.alert_id,
                content_kind=self.content_kind,
                message_kind=f"admin:audit:{item.event_type}",
            ):
                continue
            unsent.append(item)
        if not unsent:
            return

        await self.repository.record_telemetry_event(
            event_name="admin_audit_digest_opened",
            created_at=now,
            telegram_user_id=user.telegram_user_id,
            context="digest",
            payload={
                "items": len(unsent),
                "symbols": [item.symbol for item in unsent],
            },
        )
        delivery = await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=self.admin_monitoring_service.render_digest(tuple(unsent), language_code=language),
            parse_mode="HTML",
            reply_markup=build_results_hub_keyboard(is_admin=True, language_code=language),
        )
        message_id = None
        if isinstance(delivery, dict):
            raw_message_id = delivery.get("message_id")
            message_id = int(raw_message_id) if isinstance(raw_message_id, int) else None
        for item in unsent:
            if item.alert_id is None:
                continue
            await self.repository.record_delivered_signal(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=item.alert_id,
                content_kind=self.content_kind,
                message_kind=f"admin:audit:{item.event_type}",
                telegram_message_id=message_id,
                metadata={
                    "sent": True,
                    "symbol": item.symbol,
                    "strategy_key": item.strategy_code,
                    "hidden_strategy": item.hidden_strategy,
                    "delivered_alert": item.delivered_alert,
                    "event_at": item.event_at.isoformat(),
                },
            )
        await self.repository.record_delivered_signal(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            alert_id=None,
            content_kind=self.content_kind,
            message_kind="admin:audit:digest",
            telegram_message_id=message_id,
            metadata={
                "sent": True,
                "symbols": [item.symbol for item in unsent],
                "count": len(unsent),
                "hidden_count": sum(1 for item in unsent if item.hidden_strategy),
            },
        )

    async def _select_evening_followup_top_candidates(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        start: datetime,
        end: datetime,
        exclude_alert_ids: set[int],
    ) -> list[tuple[AlertRecord, FollowUpResultRecord]]:
        ranked = self._select_recap_followups(
            await self.repository.list_followup_results_between(start=start, end=end, limit=80),
            period="daily",
        )
        active_strategy_key = str(current_settings.active_strategy_key or "").strip().lower() or "rsi"
        include_gold = self._gold_alerts_enabled_for_settings(current_settings)
        followup_priority = strategy_followup_priority(
            active_strategy_key,
            self._strategy_preferences(current_settings, strategy_key=active_strategy_key),
        )
        watchlist_symbols = {
            normalize_symbol(symbol)
            for symbol in await self._watchlist_symbols_for_strategy(
                user.telegram_user_id,
                strategy_key=active_strategy_key,
                settings=current_settings,
            )
        }
        selections: list[tuple[AlertRecord, FollowUpResultRecord]] = []
        for followup in ranked:
            if followup.alert_id in exclude_alert_ids:
                continue
            alert = await self.repository.get_alert(followup.alert_id)
            if alert is None:
                continue
            if self._alert_strategy_key(alert) != active_strategy_key:
                continue
            if self._is_gold_alert_record(alert) and not include_gold:
                continue
            if not await self.repository.delivered_signal_exists(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=alert.id,
                content_kind=self.content_kind,
                message_kind="alert",
            ):
                continue
            result = self._followup_result_from_record(alert, followup)
            if result.thesis_result_state != "favorable" or float(result.favorable_move_pct or 0.0) <= 0.0:
                continue
            if not self._evaluate_private_followup(self._reference_signal_for_followup(alert, followup), result).eligible:
                continue
            selections.append((alert, followup))
        selections.sort(
            key=lambda item: self._followup_top_priority_key(
                item[1],
                priority=followup_priority,
                watchlist_symbols=watchlist_symbols,
            ),
            reverse=True,
        )
        return selections

    def _followup_top_priority_key(
        self,
        followup: FollowUpResultRecord,
        *,
        priority: str,
        watchlist_symbols: set[str],
    ) -> tuple[float, float, float, float]:
        favorable_move = float(followup.metadata.get("favorable_move_pct") or 0.0)
        watchlist_hit = 1.0 if normalize_symbol(followup.symbol) in watchlist_symbols else 0.0
        score = float(followup.score or 0)
        freshness = followup.observed_at.timestamp()
        if priority == "score":
            return (score, favorable_move, watchlist_hit, freshness)
        if priority == "watchlist":
            return (watchlist_hit, favorable_move, score, freshness)
        return (favorable_move, score, watchlist_hit, freshness)

    async def _send_hourly_digest_if_due(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
    ) -> None:
        now = utc_now()
        rules = self._delivery_rules_state(current_settings)
        digest_frequency_hours = max(1, int(rules.get("digest_frequency_hours", 1) or 1))
        last_digest_at = current_settings.last_digest_sent_at or current_settings.delivery_mode_changed_at
        if last_digest_at is not None and (now - last_digest_at).total_seconds() < digest_frequency_hours * 3600:
            return
        since = last_digest_at or (now - timedelta(hours=digest_frequency_hours))
        queued = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            message_kind_prefix="queued:",
            since=since,
            limit=200,
        )
        active_strategy_key = str(current_settings.active_strategy_key or "").strip().lower() or "rsi"
        if self.bot_kind == "premium":
            queued = [
                record
                for record in queued
                if str(record.metadata.get("strategy_key") or "").strip().lower() == active_strategy_key
            ]
        alerts: list[AlertRecord] = []
        watchlist_alerts: list[AlertRecord] = []
        followups: list[FollowUpResultRecord] = []
        seen_alert_ids: set[int] = set()
        for record in queued:
            if record.alert_id is None or record.alert_id in seen_alert_ids:
                continue
            if record.message_kind == "queued:alert":
                alert = await self.repository.get_alert(record.alert_id)
                if alert is None:
                    continue
                alerts.append(alert)
                seen_alert_ids.add(record.alert_id)
                if record.metadata.get("watchlist_hit"):
                    watchlist_alerts.append(alert)
                continue
            if record.message_kind.startswith("queued:followup:"):
                result = await self.repository.get_followup_result(record.alert_id)
                if result is not None:
                    followups.append(result)
                    seen_alert_ids.add(record.alert_id)
        if self.bot_kind == "premium":
            await self._save_strategy_runtime_state(
                user=user,
                current_settings=current_settings,
                last_digest_sent_at=now,
            )
        else:
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                last_digest_sent_at=now,
            )
        if not alerts and not watchlist_alerts and not followups:
            return
        language = self._language_code(current_settings)
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=format_digest_message(
                alerts=alerts[:4],
                watchlist_alerts=watchlist_alerts[:3],
                followups=followups[:3],
                language_code=language,
            ),
            parse_mode="HTML",
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="signals",
                include_gold_button=self.settings.gold_alerts_enabled,
                premium=self.bot_kind == "premium",
                back_callback_data=self._strategy_hub_callback_data(current_settings),
            ),
        )
        await self.repository.record_delivered_signal(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            alert_id=None,
            content_kind=self.content_kind,
            message_kind="digest:hourly",
            telegram_message_id=None,
            metadata={
                "sent": True,
                "strategy_key": active_strategy_key,
                "alerts_count": len(alerts),
                "watchlist_hits": len(watchlist_alerts),
                "followups_count": len(followups),
            },
        )

    async def _record_funnel_event(
        self,
        event_name: str,
        telegram_user_id: int,
        *,
        context: str | None = None,
        language_code: str | None = None,
        screen: str | None = None,
    ) -> None:
        normalized_event = str(event_name or "").strip()
        if normalized_event not in self.FUNNEL_EVENT_NAMES:
            return
        safe_context = re.sub(r"[^a-z0-9_:-]+", "_", str(context or "").strip().lower())[:48] or None
        safe_screen = re.sub(r"[^a-z0-9_:-]+", "_", str(screen or "").strip().lower())[:48] or None
        payload: dict[str, object] = {
            "bot_kind": self.bot_kind,
            "language": normalize_language(language_code),
        }
        if safe_screen:
            payload["screen"] = safe_screen
        try:
            await self.repository.record_telemetry_event(
                event_name=normalized_event,
                created_at=utc_now(),
                telegram_user_id=telegram_user_id,
                context=safe_context,
                payload=payload,
            )
        except Exception:
            LOGGER.warning(
                "Funnel telemetry write failed event=%s bot=%s",
                normalized_event,
                self.bot_kind,
                exc_info=True,
            )

    async def _send_start(self, user_id: int, payload: str | None, *, first_time: bool) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        if first_time:
            text = format_first_start_message(
                trial_hours=self.settings.onboarding_trial_hours,
                language_code=language,
            )
        else:
            access_state_line = None
            user = await self._get_private_user(user_id)
            if user is not None:
                access_state = await self._effective_access_state_for_user(user)
                access_state_line = self._access_state_line(access_state, language_code=language)
            text = format_start_message(
                variant=payload,
                access_state_line=access_state_line,
                language_code=language,
            )
        await self._send_chat_message(
            chat_id=str(user_id),
            text=text,
            parse_mode="HTML",
            reply_markup=build_guided_start_keyboard(language_code=language),
        )

    async def _send_onboarding_example(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_example_signal_message(language_code=language),
            reply_markup=build_example_signal_keyboard(language_code=language),
            edit_message_id=edit_message_id,
            cleanup_branch="help",
        )
        await self._record_funnel_event(
            "example_signal_opened",
            user_id,
            context="onboarding",
            language_code=language,
            screen="example_signal",
        )

    async def _send_signal_reading_guide(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_signal_reading_guide_message(language_code=language),
            reply_markup=build_signal_reading_keyboard(language_code=language),
            edit_message_id=edit_message_id,
            cleanup_branch="help",
        )
        await self._record_funnel_event(
            "how_to_read_opened",
            user_id,
            context="onboarding",
            language_code=language,
            screen="how_to_read",
        )

    async def _send_help(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        visible_strategy_keys = self._visible_strategy_keys(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user_id,
            chat_id=chat_id or str(user_id),
        )
        back_callback_data = self._screen_back_callback(
            user_id,
            screen="help",
            default="ux:menu",
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_help_message(language_code=language),
            reply_markup=build_help_inline_keyboard(
                language_code=language,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="help",
        )
        await self._record_funnel_event(
            "help_opened",
            user_id,
            context="help_center",
            language_code=language,
            screen="help",
        )

    async def _send_help_page(
        self,
        user_id: int,
        *,
        page: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_help_page_message(
                page,
                language_code=language,
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                support_target=self._community_target() or None,
            ),
            reply_markup=(
                build_help_more_inline_keyboard(language_code=language)
                if str(page or "").strip().lower() == "more"
                else build_help_inline_keyboard(
                    language_code=language,
                    back_callback_data="main:help",
                )
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="help",
        )
        event_name = {
            "compare": "classic_vs_pro_opened",
            "support": "support_opened",
            "risk": "risk_seen",
        }.get(str(page or "").strip().lower())
        if event_name is not None:
            await self._record_funnel_event(
                event_name,
                user_id,
                context="help_center",
                language_code=language,
                screen=page,
            )

    async def _send_strategy_selector(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        visible_strategy_keys = self._visible_strategy_keys(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user_id,
            chat_id=chat_id or str(user_id),
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=(
                "<b>📐 Стратегии</b>\n\n"
                "Выберите стратегию, чтобы открыть её отдельное рабочее пространство.\n\n"
                "Внутри каждой стратегии можно смотреть сигналы, настраивать фильтры, управлять уведомлениями, смотреть результаты и запускать AI-анализ."
                if language == "ru"
                else "<b>📐 Strategies</b>\n\n"
                "Choose a strategy to open its dedicated workspace.\n\n"
                "Inside each strategy you can view signals, adjust filters, manage alerts, review results and run AI-assisted analysis."
            ),
            reply_markup=build_strategies_hub_keyboard(
                is_admin=self.role_guard.is_admin(await self._get_private_user(user_id)),
                language_code=language,
                visible_strategy_keys=visible_strategy_keys,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_menu(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        if self.bot_kind == "premium":
            await self.repository.upsert_user_settings(
                telegram_user_id=user_id,
                bot_kind=self.bot_kind,
                direct_signal_delivery_enabled=settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=settings.followup_delivery_enabled,
                gold_alerts_enabled=settings.gold_alerts_enabled,
                signal_profile=settings.signal_profile,
                preferred_min_score=settings.preferred_min_score,
                min_quote_volume=settings.min_quote_volume,
                rsi_oversold=settings.rsi_oversold,
                rsi_overbought=settings.rsi_overbought,
                direction_filter=settings.direction_filter,
                watchlist_only=settings.watchlist_only,
                menu_collapsed=False,
                language_code=settings.language_code,
                enabled_strategy_keys=self._enabled_strategy_keys(settings),
                active_strategy_key=self._resolved_active_strategy_key(settings),
                strategy_selector_completed_at=settings.strategy_selector_completed_at,
            )
            self._store_cached_settings(replace(settings, menu_collapsed=False))
            await self._hide_reply_keyboard_if_needed(chat_id=str(user_id))
            await self._send_menu_hub(user_id)
            return
        await self.repository.upsert_user_settings(
            telegram_user_id=user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=settings.followup_delivery_enabled,
            gold_alerts_enabled=settings.gold_alerts_enabled,
            signal_profile=settings.signal_profile,
            preferred_min_score=settings.preferred_min_score,
            min_quote_volume=settings.min_quote_volume,
            rsi_oversold=settings.rsi_oversold,
            rsi_overbought=settings.rsi_overbought,
            direction_filter=settings.direction_filter,
            watchlist_only=settings.watchlist_only,
            menu_collapsed=False,
            language_code=settings.language_code,
        )
        self._store_cached_settings(replace(settings, menu_collapsed=False))
        language = self._language_code(settings)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=format_menu_panel_message(bot_kind=self.bot_kind, language_code=language),
            parse_mode="HTML",
            reply_markup=await self._main_menu_keyboard_for_user(user_id),
        )

    async def _send_v2_home(
        self,
        user: PrivateBotUserRecord,
        *,
        is_pro: bool,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        """Render the product home without exposing storage implementation terms."""

        started = monotonic()
        if self.bot_kind != "premium":
            await self._send_menu_hub(user.telegram_user_id, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        self._v2_home_route_by_user[user.telegram_user_id] = "home_pro" if is_pro else "home_simple"
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_home_message(
                language_code=language,
                first_name=user.first_name,
                is_pro=is_pro,
            ),
            reply_markup=build_v2_home_keyboard(
                language_code=language,
                is_pro=is_pro,
                include_gold=self.settings.gold_alerts_enabled and self._gold_alerts_enabled_for_settings(shell_settings),
            ),
            edit_message_id=edit_message_id,
        )
        self.performance_telemetry_service.record(RouteTiming("home.pro" if is_pro else "home.simple", user.telegram_user_id, (monotonic() - started) * 1000, True, cache="user-cache"))

    def _v2_open_route(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str,
        message_id: int,
        route: str,
        params: dict[str, object] | None = None,
        root: bool = False,
        fallback_home: str | None = None,
    ) -> None:
        self.navigation_service.open(
            bot_kind=self.bot_kind,
            user_id=user.telegram_user_id,
            chat_id=chat_id,
            message_id=message_id,
            route=route,
            params=params,
            root=root,
            fallback_root=fallback_home or self._v2_home_route_by_user.get(user.telegram_user_id, "home_simple"),
        )

    async def _send_v2_strategies(
        self,
        user: PrivateBotUserRecord,
        *,
        enabled_only: bool = False,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        started = monotonic()
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        visible = self._visible_strategy_keys(settings)
        enabled = set(self._enabled_strategy_keys(settings))
        keys = tuple(key for key in visible if not enabled_only or key in enabled)
        strategy_rows = [
            (
                key,
                self._strategy_label(key, language_code=language),
                key in enabled,
                not self._strategy_accessible_for_user_id(user.telegram_user_id, key),
            )
            for key in keys
        ]
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_strategies_message(
                language_code=language,
                active_count=len(enabled.intersection(visible)),
                total_count=len(visible),
            ),
            reply_markup=build_v2_strategies_keyboard(language_code=language, strategies=strategy_rows),
            edit_message_id=edit_message_id,
        )
        self.performance_telemetry_service.record(RouteTiming("strategies", user.telegram_user_id, (monotonic() - started) * 1000, True))

    async def _send_v2_strategy(
        self,
        user: PrivateBotUserRecord,
        *,
        strategy_key: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        normalized = str(strategy_key or "").strip().lower()
        if normalized not in self.STRATEGY_KEYS or not self._strategy_accessible_for_user_id(user.telegram_user_id, normalized):
            await self._send_v2_strategies(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        profile = self.compare_service.get_profile(normalized, language_code=language)
        now = utc_now()
        recent = await self.repository.list_alerts_between(start=now - timedelta(days=7), end=now + timedelta(minutes=1), limit=300)
        signals_7d = sum(self._alert_strategy_key(alert) == normalized for alert in recent)
        active_now = len(await self._pick_signal_for_user(user, strong_only=False, limit=50, strategy_key=normalized))
        timeframes = ", ".join(strategy_allowed_timeframes(normalized, None)[:4]) or self.settings.scan_timeframe
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_strategy_message(
                language_code=language,
                label=self._strategy_label(normalized, language_code=language),
                summary=profile.short_explanation,
                enabled=self._strategy_enabled_for_settings(settings, strategy_key=normalized),
                signals_7d=signals_7d,
                active_now=active_now,
                timeframes=timeframes,
                is_pro=str(settings.display_mode or "simple").lower() == "pro",
            ),
            reply_markup=build_v2_strategy_keyboard(
                language_code=language,
                strategy_key=normalized,
                enabled=self._strategy_enabled_for_settings(settings, strategy_key=normalized),
                is_pro=str(settings.display_mode or "simple").lower() == "pro",
            ),
            edit_message_id=edit_message_id,
        )

    async def _toggle_v2_strategy(self, user: PrivateBotUserRecord, *, strategy_key: str) -> UserSettingsRecord | None:
        normalized = str(strategy_key or "").strip().lower()
        if normalized not in self.STRATEGY_KEYS or not self._strategy_accessible_for_user_id(user.telegram_user_id, normalized):
            return None
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        enabled = list(self._enabled_strategy_keys(settings))
        if normalized in enabled:
            enabled.remove(normalized)
        else:
            if self._is_gold_substrategy(normalized) and GOLD_MASTER_STRATEGY_KEY not in enabled:
                enabled.append(GOLD_MASTER_STRATEGY_KEY)
            enabled.append(normalized)
            await self._ensure_premium_strategy_settings(user.telegram_user_id, shell_settings=settings, strategy_key=normalized)
        active = self._resolved_active_strategy_key(settings)
        if active not in enabled:
            active = enabled[0] if enabled else None
        return await self._save_user_settings(
            user=user,
            current_settings=settings,
            enabled_strategy_keys=tuple(enabled),
            active_strategy_key=active,
            strategy_selector_completed_at=utc_now() if enabled else None,
        )

    async def _send_v2_strategy_settings(
        self,
        user: PrivateBotUserRecord,
        *,
        strategy_key: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        normalized = str(strategy_key or "").strip().lower()
        if normalized not in self.STRATEGY_KEYS or not self._strategy_accessible_for_user_id(user.telegram_user_id, normalized):
            await self._send_v2_strategies(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        strategy_settings = await self._ensure_premium_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=normalized,
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_strategy_settings_message(
                language_code=language,
                label=self._strategy_label(normalized, language_code=language),
                direct_delivery_enabled=strategy_settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=strategy_settings.followup_delivery_enabled,
                preferred_min_score=strategy_settings.preferred_min_score,
            ),
            reply_markup=build_v2_strategy_settings_keyboard(
                language_code=language,
                strategy_key=normalized,
                direct_delivery_enabled=strategy_settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=strategy_settings.followup_delivery_enabled,
                preferred_min_score=strategy_settings.preferred_min_score,
            ),
            edit_message_id=edit_message_id,
        )

    async def _update_v2_strategy_settings(
        self,
        user: PrivateBotUserRecord,
        *,
        strategy_key: str,
        change: str,
    ) -> PremiumStrategySettingsRecord | None:
        normalized = str(strategy_key or "").strip().lower()
        if normalized not in self.STRATEGY_KEYS or not self._strategy_accessible_for_user_id(user.telegram_user_id, normalized):
            return None
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        strategy_settings = await self._ensure_premium_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=normalized,
        )
        if change == "signals":
            updated = await self._save_premium_strategy_settings_record(
                strategy_settings,
                direct_signal_delivery_enabled=not strategy_settings.direct_signal_delivery_enabled,
            )
        elif change == "followups":
            updated = await self._save_premium_strategy_settings_record(
                strategy_settings,
                followup_delivery_enabled=not strategy_settings.followup_delivery_enabled,
            )
        elif change in {"strict", "standard"}:
            default_score, _, _, _ = self._profile_defaults("balanced")
            base_score = PREMIUM_STRATEGY_DEFAULT_MIN_SCORES.get(normalized, default_score)
            strict = change == "strict"
            updated = await self._save_premium_strategy_settings_record(
                strategy_settings,
                preferred_min_score=max(80, base_score) if strict else base_score,
                signal_profile="conservative" if strict else "balanced",
                base_signal_profile="conservative" if strict else "balanced",
            )
        else:
            return None
        if self._resolved_active_strategy_key(shell_settings) == normalized:
            await self._sync_shell_to_strategy(
                user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=normalized,
            )
        return updated

    async def _send_v2_market_sets(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        strategy_key = self._resolved_active_strategy_key(shell_settings) or "rsi"
        strategy_settings = await self._load_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        symbols = await self._watchlist_symbols_for_strategy(
            user.telegram_user_id,
            strategy_key=strategy_key,
            settings=strategy_settings,
        )
        saved_sets = await self.repository.list_premium_strategy_watchlist_themes(
            user.telegram_user_id,
            bot_kind=self.bot_kind,
            strategy_key=strategy_key,
        )
        theme_key = str(strategy_settings.active_watchlist_theme or "custom").strip().lower()
        active_label = (
            "Все отслеживаемые монеты" if theme_key == "watchlist" and language == "ru"
            else "All tracked coins" if theme_key == "watchlist"
            else self._active_watchlist_theme_label(strategy_settings, language_code=language)
        )
        builtin_sets = [
            (key, watchlist_theme_label(key, language_code=language))
            for key in BUILTIN_WATCHLIST_THEMES
        ]
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_market_sets_message(
                language_code=language,
                active_label=active_label,
                symbols=symbols,
            ),
            reply_markup=build_market_sets_keyboard(
                language_code=language,
                builtin_sets=builtin_sets,
                saved_sets=[(item.id, item.theme_name) for item in saved_sets],
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_v2_results(
        self,
        user: PrivateBotUserRecord,
        *,
        days: int = 7,
        strategy_key: str | None = None,
        view: str = "hub",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        started = monotonic()
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        summary = await self.results_service.summary(
            days=days,
            strategy_code=strategy_key,
            include_records=view in {"strategies", "lifecycle", "recent"},
        )
        if view == "strategies":
            by_strategy: dict[str, list[SignalLifecycleRecord]] = {}
            for record in summary.records:
                by_strategy.setdefault(record.strategy_code, []).append(record)
            lines = ["<b>📈 Результаты по стратегиям</b>" if language == "ru" else "<b>📈 Results by strategy</b>", ""]
            for key, records in sorted(by_strategy.items()):
                wins = sum(item.status == "hit_tp" for item in records)
                losses = sum(item.status == "invalidated" for item in records)
                lines.append(f"• <b>{escape_html(self._strategy_label(key, language_code=language))}</b>: {len(records)} · ✅ {wins} · ❌ {losses}")
            text = "\n".join(lines) if len(lines) > 2 else ("<b>📈 По стратегиям</b>\n\nНет сохранённых lifecycle-данных." if language == "ru" else "<b>📈 By strategy</b>\n\nNo persisted lifecycle data.")
        elif view == "lifecycle":
            text = ("<b>🔄 Жизненный цикл</b>\n\n" if language == "ru" else "<b>🔄 Lifecycle</b>\n\n") + "\n".join(
                f"• {normalize_symbol(item.symbol)} · {item.timeframe} · <b>{item.status}</b>" for item in summary.records[:12]
            )
        elif view == "recent":
            text = ("<b>🧾 Последние результаты</b>\n\n" if language == "ru" else "<b>🧾 Latest results</b>\n\n") + "\n".join(
                f"• {normalize_symbol(item.symbol)} · {item.direction.upper()} · <b>{item.status}</b> · MFE {item.mfe_percent:+.1f}%" for item in summary.records[:12]
            )
        elif view == "methodology":
            text = (
                "<b>📐 Методология</b>\n\n"
                f"Results читает <b>{summary.total}</b> сохранённых lifecycle-записей и <b>{summary.followups}</b> последних follow-up записей из БД. Telegram-сообщения не являются источником истины."
                if language == "ru"
                else "<b>📐 Methodology</b>\n\n"
                f"Results reads <b>{summary.total}</b> persisted lifecycle records and <b>{summary.followups}</b> latest follow-up records from the database. Telegram messages are not the source of truth."
            )
        else:
            updated = summary.updated_at.astimezone(self.settings.timezone).strftime("%d.%m %H:%M") if summary.updated_at else None
            text = format_v2_results_message(language_code=language, total=summary.total, confirmed=summary.confirmed, broken=summary.broken, open_count=summary.open, insufficient=summary.insufficient, followups=summary.followups, updated_at=updated, days=days)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_v2_results_keyboard(language_code=language, include_diagnostics=user.is_admin),
            edit_message_id=edit_message_id,
        )
        self.performance_telemetry_service.record(RouteTiming("results." + view, user.telegram_user_id, (monotonic() - started) * 1000, True))

    async def _dispatch_v2_back(self, user: PrivateBotUserRecord, *, chat_id: str, message_id: int) -> bool:
        target = self.navigation_service.back(bot_kind=self.bot_kind, user_id=user.telegram_user_id, chat_id=chat_id, message_id=message_id)
        if target is None:
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_v2_home(user, is_pro=str(settings.display_mode).lower() == "pro", chat_id=chat_id, edit_message_id=message_id)
            await self._send_inline_error(chat_id, "Экран устарел. Открыта актуальная версия раздела." if language == "ru" else "This screen is outdated. The current section was opened.")
            return False
        if target.name == "strategies":
            await self._send_v2_strategies(user, enabled_only=bool(target.params.get("enabled_only")), chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "strategy":
            await self._send_v2_strategy(user, strategy_key=str(target.params.get("strategy_key") or "rsi"), chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "strategy_settings":
            await self._send_v2_strategy_settings(user, strategy_key=str(target.params.get("strategy_key") or "rsi"), chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "signals":
            await self._send_v2_signals(user, view=str(target.params.get("view") or "all"), strategy_key=target.params.get("strategy_key"), chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "results":
            await self._send_v2_results(user, days=int(target.params.get("days") or 7), strategy_key=target.params.get("strategy_key"), view=str(target.params.get("view") or "hub"), chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "flow":
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "flow_profiles":
            await self._send_saved_setups_list(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
                back_callback_data_override="v2:nav:back",
            )
        elif target.name == "flows":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_v2_hub_message("flows", language_code=self._language_code(settings)),
                reply_markup=build_flows_keyboard(language_code=self._language_code(settings)),
                edit_message_id=message_id,
            )
        elif target.name == "notifications":
            await self._send_v2_notifications(user, chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "settings":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_settings_message(language_code=self._language_code(settings)),
                reply_markup=build_v2_settings_keyboard(language_code=self._language_code(settings)),
                edit_message_id=message_id,
            )
        elif target.name == "watchlist":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("watchlist", language_code=self._language_code(settings)), reply_markup=build_v2_watchlist_keyboard(language_code=self._language_code(settings)), edit_message_id=message_id)
        elif target.name == "watchlist_manage":
            await self._send_watchlist(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
                back_callback_data_override="v2:nav:back",
            )
        elif target.name == "market_sets":
            await self._send_v2_market_sets(user, chat_id=chat_id, edit_message_id=message_id)
        elif target.name == "access":
            await self._send_access(user, chat_id=chat_id, edit_message_id=message_id, back_callback_data_override="v2:nav:back")
        elif target.name in {"help", "strategy_guide"}:
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            if target.name == "strategy_guide":
                await self._send_or_edit_text(chat_id=chat_id, text=("<b>📖 Как работают стратегии</b>\n\nСтратегия описывает условия поиска идеи. Сигналы и результаты основаны на сохранённых данных; включение меняет только доставку и ваш профиль." if language == "ru" else "<b>📖 How strategies work</b>\n\nA strategy defines how an idea is found. Signals and results use persisted data; enabling only changes delivery and your profile."), reply_markup=build_v2_help_keyboard(language_code=language), edit_message_id=message_id)
            else:
                await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("help", language_code=language), reply_markup=build_v2_help_keyboard(language_code=language), edit_message_id=message_id)
        elif target.name == "analytics":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("analytics", language_code=language), reply_markup=build_analytics_keyboard(language_code=language, include_gold=self.settings.gold_alerts_enabled), edit_message_id=message_id)
        elif target.name == "analysis":
            await self._send_analyze_symbol_help(
                user,
                chat_id=chat_id,
                edit_message_id=message_id,
                back_callback_data_override="v2:nav:back",
            )
        elif target.name == "market":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("market", language_code=language), reply_markup=build_market_keyboard(language_code=language, include_gold=self.settings.gold_alerts_enabled), edit_message_id=message_id)
        elif target.name == "gold":
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("gold", language_code=language), reply_markup=build_gold_keyboard(language_code=language), edit_message_id=message_id)
        else:
            await self._send_v2_home(user, is_pro=target.name == "home_pro", chat_id=chat_id, edit_message_id=message_id)
        return True

    @staticmethod
    def _v2_style_profile(style_key: str) -> tuple[str, tuple[str, ...]]:
        mapping = {
            "scalp": ("aggressive", ("rsi", "bollinger", "vwap")),
            "intraday": ("balanced", ("breakout", "trend_pullback", "vwap")),
            "swing": ("conservative", ("breakout", "trend_pullback", "daily_rsi_80")),
            "balanced": ("balanced", ("rsi", "breakout", "trend_pullback")),
        }
        return mapping.get(style_key, mapping["balanced"])

    @staticmethod
    def _v2_market_symbols(market_key: str) -> list[str]:
        mapping = {
            "btc_eth": ["BTCUSDT", "ETHUSDT"],
            "majors": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
            "all": [],
        }
        return mapping.get(market_key, [])[:]

    @staticmethod
    def _v2_quality_profile(quality_key: str) -> str:
        return {"best": "conservative", "balanced": "balanced", "more": "aggressive"}.get(quality_key, "balanced")

    async def _sync_v2_active_flow(
        self,
        user: PrivateBotUserRecord,
        *,
        preferred_name: str | None = None,
    ) -> UserSavedSetupRecord:
        """Persist the current effective settings under the existing saved-flow entity."""

        active_flow = await self._active_saved_setup(user.telegram_user_id)
        payload = await self._build_current_setup_payload(user.telegram_user_id)
        if active_flow is None:
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(shell_settings)
            active_flow = await self.repository.create_user_saved_setup(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                name=preferred_name or ("Активный профиль" if language == "ru" else "Active profile"),
                payload=payload,
                is_default=True,
            )
            await self._save_user_settings(
                user=user,
                current_settings=shell_settings,
                current_set_id=active_flow.id,
                current_context="flow",
            )
            return active_flow
        refreshed = await self.repository.update_user_saved_setup(
            active_flow.id,
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            payload=payload,
        )
        assert refreshed is not None
        return refreshed

    async def _apply_v2_style(
        self,
        user: PrivateBotUserRecord,
        *,
        style_key: str,
        sync_flow: bool,
    ) -> UserSettingsRecord:
        profile, enabled_strategy_keys = self._v2_style_profile(style_key)
        current_settings = await self._ensure_user_settings(user.telegram_user_id)
        min_score, min_quote_volume, rsi_oversold, rsi_overbought = self._profile_defaults(profile)
        personalization = self._personalization_state(current_settings)
        personalization["v2_style"] = style_key
        updated = await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile=profile,
            base_signal_profile=profile,
            preferred_min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            enabled_strategy_keys=enabled_strategy_keys,
            active_strategy_key=enabled_strategy_keys[0],
            display_mode="simple",
            current_context="flow",
            personalization=personalization,
        )
        if sync_flow:
            await self._sync_v2_active_flow(user)
        return updated

    async def _apply_v2_quality(
        self,
        user: PrivateBotUserRecord,
        *,
        quality_key: str,
        sync_flow: bool,
    ) -> UserSettingsRecord:
        profile = self._v2_quality_profile(quality_key)
        current_settings = await self._ensure_user_settings(user.telegram_user_id)
        min_score, min_quote_volume, rsi_oversold, rsi_overbought = self._profile_defaults(profile)
        personalization = self._personalization_state(current_settings)
        personalization["v2_quality"] = quality_key
        updated = await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile=profile,
            base_signal_profile=profile,
            preferred_min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            current_context="flow",
            personalization=personalization,
        )
        if sync_flow:
            await self._sync_v2_active_flow(user)
        return updated

    async def _apply_v2_assets(
        self,
        user: PrivateBotUserRecord,
        *,
        market_key: str,
        custom_symbols: list[str] | None = None,
        sync_flow: bool,
    ) -> UserSettingsRecord:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        symbols = [normalize_symbol(item) for item in (custom_symbols if market_key == "manual" else self._v2_market_symbols(market_key))]
        symbols = [symbol for symbol in symbols if symbol][: self.WATCHLIST_LIMIT]
        scope_type = "all" if market_key == "all" else "custom"
        scope_payload = None if scope_type == "all" else {"symbols": symbols}
        if self.bot_kind == "premium":
            for strategy_key in self._enabled_strategy_keys(shell_settings):
                await self.repository.replace_premium_strategy_watchlist_symbols(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    symbols=symbols,
                )
        else:
            await self.repository.replace_user_watchlist_symbols(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                symbols=symbols,
            )
        personalization = self._personalization_state(shell_settings)
        personalization["asset_scope_type"] = scope_type
        personalization["asset_scope_payload"] = scope_payload
        updated = await self._save_user_settings(
            user=user,
            current_settings=shell_settings,
            watchlist_only=scope_type != "all",
            active_watchlist_theme="custom",
            active_custom_theme_name=None,
            personalization=personalization,
            current_context="flow",
        )
        if sync_flow:
            await self._sync_v2_active_flow(user)
        return updated

    async def _validate_v2_symbols(self, symbols: list[str]) -> list[str]:
        """Accept only currently tradable USDT perpetual symbols when available."""

        normalized = list(dict.fromkeys(normalize_symbol(item) for item in symbols if normalize_symbol(item)))
        if not normalized:
            return []
        try:
            active_symbols = set(await self.binance_client.get_active_usdt_symbols())
        except Exception:
            # A temporary exchange outage must not make an already typed setup
            # impossible. The normal signal pipeline still handles bad symbols.
            LOGGER.warning("Unable to validate V2 watchlist symbols against exchange", exc_info=True)
            return normalized
        return [symbol for symbol in normalized if symbol in active_symbols]

    async def _send_v2_onboarding_step(
        self,
        user: PrivateBotUserRecord,
        *,
        step: str,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_onboarding_message(language_code=language, step=step, draft=draft),
            reply_markup=build_v2_onboarding_keyboard(language_code=language, step=step),
            edit_message_id=edit_message_id,
        )

    async def _start_v2_onboarding(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        draft: dict[str, object] = {
            "v2": True,
            "language_code": language,
            "style": "balanced",
            "market": "all",
            "quality": "balanced",
            "delivery": "instant",
            "style_label": v2_choice_label("style", "balanced", language_code=language),
            "market_label": v2_choice_label("market", "all", language_code=language),
            "quality_label": v2_choice_label("quality", "balanced", language_code=language),
            "delivery_label": v2_choice_label("delivery", "instant", language_code=language),
        }
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            step="v2_style",
            draft=draft,
        )
        await self._record_funnel_event(
            "onboarding_started",
            user.telegram_user_id,
            context="v2",
            language_code=language,
            screen="onboarding_style",
        )
        await self._send_v2_onboarding_step(user, step="style", draft=draft, chat_id=chat_id, edit_message_id=edit_message_id)

    async def _send_v2_signals(
        self,
        user: PrivateBotUserRecord,
        *,
        view: str,
        strategy_key: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        started = monotonic()
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if self.bot_kind == "premium" and not await self._has_premium_access(user):
            await self._send_payment_offer(user)
            return
        selections = await self._pick_signal_for_user(
            user,
            strong_only=view == "best",
            limit=12,
            strategy_key=strategy_key if strategy_key else "__active__",
        )
        if view == "watchlist":
            watchlist_symbols = set(await self._watchlist_symbols(user.telegram_user_id))
            selections = [item for item in selections if normalize_symbol(item.alert.symbol) in watchlist_symbols]
        entries = [
            (
                selection.alert.id,
                f"{normalize_symbol(selection.alert.symbol)} · {selection.alert.direction.title()} · {selection.alert.timeframe}",
            )
            for selection in selections
        ]
        if not entries:
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=format_v2_signal_empty_message(language_code=language),
                reply_markup=build_signal_empty_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_signal_list_message(language_code=language, view=view, count=len(entries)),
            reply_markup=build_signal_list_keyboard(language_code=language, entries=entries),
            edit_message_id=edit_message_id,
        )
        self.performance_telemetry_service.record(RouteTiming("signals." + view, user.telegram_user_id, (monotonic() - started) * 1000, True))

    async def _send_v2_flow(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        active_flow = await self._active_saved_setup(user.telegram_user_id)
        symbols = await self._watchlist_symbols(user.telegram_user_id)
        scope = ("Весь рынок" if language == "ru" else "Whole market") if not settings.watchlist_only else (", ".join(symbols[:5]) or ("Ручной список" if language == "ru" else "Manual list"))
        personalization = self._personalization_state(settings)
        style = v2_choice_label("style", str(personalization.get("v2_style") or "balanced"), language_code=language)
        quality = v2_choice_label("quality", str(personalization.get("v2_quality") or "balanced"), language_code=language)
        summary = "\n".join(
            (
                f"🎛 {'Стиль' if language == 'ru' else 'Style'}: <b>{style}</b>",
                f"📈 {'Стратегий' if language == 'ru' else 'Strategies'}: <b>{len(self._enabled_strategy_keys(settings))}</b>",
                f"🪙 {'Активы' if language == 'ru' else 'Assets'}: <b>{scope}</b>",
                f"🔥 {'Качество' if language == 'ru' else 'Quality'}: <b>{quality}</b>",
                f"🔔 {'Доставка' if language == 'ru' else 'Delivery'}: <b>{delivery_mode_label(settings.delivery_mode, language_code=language)}</b>",
            )
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_flow_message(
                language_code=language,
                flow_name=active_flow.name if active_flow is not None else ("Активный профиль" if language == "ru" else "Active profile"),
                summary=summary,
            ),
            reply_markup=build_flow_keyboard(language_code=language),
            edit_message_id=edit_message_id,
        )

    async def _send_v2_notifications(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_v2_notifications_message(
                language_code=language,
                signals_on=settings.direct_signal_delivery_enabled,
                followups_on=settings.followup_delivery_enabled,
                gold_on=self._gold_alerts_enabled_for_settings(settings),
                delivery=delivery_mode_label(settings.delivery_mode, language_code=language),
            ),
            reply_markup=build_notifications_keyboard(
                language_code=language,
                gold_available=self.settings.gold_alerts_enabled,
            ),
            edit_message_id=edit_message_id,
        )

    async def _complete_v2_onboarding(self, user: PrivateBotUserRecord, *, draft: dict[str, object]) -> None:
        style = str(draft.get("style") or "balanced")
        market = str(draft.get("market") or "all")
        quality = str(draft.get("quality") or "balanced")
        delivery = str(draft.get("delivery") or "instant")
        await self._apply_v2_style(user, style_key=style, sync_flow=False)
        await self._apply_v2_assets(
            user,
            market_key=market,
            custom_symbols=[str(item) for item in draft.get("symbols", []) if str(item)] if market == "manual" else None,
            sync_flow=False,
        )
        current_settings = await self._apply_v2_quality(user, quality_key=quality, sync_flow=False)
        quiet_start, quiet_end = (23 * 60, 7 * 60) if delivery == "quiet" else (current_settings.quiet_hours_start_minute, current_settings.quiet_hours_end_minute)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            delivery_mode="digest" if delivery == "digest" else "instant",
            quiet_hours_start_minute=quiet_start,
            quiet_hours_end_minute=quiet_end,
            onboarding_completed_at=utc_now(),
            display_mode="simple",
            current_context="flow",
        )
        await self._sync_v2_active_flow(user, preferred_name="Активный профиль" if self._language_code(current_settings) == "ru" else "Active profile")
        await self.repository.delete_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
        await self._record_funnel_event(
            "onboarding_completed",
            user.telegram_user_id,
            context="v2",
            language_code=self._language_code(current_settings),
            screen="onboarding_review",
        )

    async def _handle_v2_action(
        self,
        user: PrivateBotUserRecord,
        *,
        action: UserBotCallbackAction,
        query_id: str,
        chat_id: str,
        edit_message_id: int,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._answer_callback_query(query_id, text=ui_text(language, "callback_done"))
        if action.kind == "v2_nav_back":
            await self._dispatch_v2_back(user, chat_id=chat_id, message_id=edit_message_id)
            return
        if action.kind == "v2_home_simple":
            await self._save_user_settings(user=user, current_settings=settings, display_mode="simple")
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="home_simple", root=True)
            await self._send_v2_home(user, is_pro=False, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_home_pro":
            await self._save_user_settings(user=user, current_settings=settings, display_mode="pro")
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="home_pro", root=True)
            await self._send_v2_home(user, is_pro=True, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_onboarding_cancel":
            await self.repository.delete_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
            await self._send_v2_home(user, is_pro=False, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind.startswith("v2_onboarding_"):
            state = await self.repository.get_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
            if state is None or not bool(state.draft.get("v2")):
                await self._start_v2_onboarding(user, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            draft = dict(state.draft)
            if action.kind == "v2_onboarding_back":
                target = str(action.value or "style")
                await self.repository.upsert_user_onboarding_state(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    step=f"v2_{target}",
                    draft=draft,
                )
                await self._send_v2_onboarding_step(user, step=target, draft=draft, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            if action.kind == "v2_onboarding_confirm":
                await self._complete_v2_onboarding(user, draft=draft)
                if action.value == "signals":
                    await self._send_v2_signals(user, view="best", chat_id=chat_id, edit_message_id=edit_message_id)
                else:
                    await self._send_v2_home(user, is_pro=False, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            category = action.kind.removeprefix("v2_onboarding_")
            value = str(action.value or "")
            if category == "market" and value == "manual":
                draft["market"] = "manual"
                draft["market_label"] = v2_choice_label("market", value, language_code=language)
                await self.repository.upsert_user_onboarding_state(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    step="v2_symbols",
                    draft=draft,
                )
                await self._send_v2_onboarding_step(user, step="symbols", draft=draft, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            if category not in {"style", "market", "quality", "delivery"} or not value:
                return
            draft[category] = value
            draft[f"{category}_label"] = v2_choice_label(category, value, language_code=language)
            next_step = {"style": "market", "market": "quality", "quality": "delivery", "delivery": "review"}[category]
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                step=f"v2_{next_step}",
                draft=draft,
            )
            await self._record_funnel_event(
                "onboarding_step_completed",
                user.telegram_user_id,
                context=f"v2:{category}",
                language_code=language,
                screen=f"onboarding_{category}",
            )
            await self._send_v2_onboarding_step(user, step=next_step, draft=draft, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_strategies_hub":
            enabled_only = str(action.value or "").lower() == "enabled" or str(action.extra or "").lower() == "enabled"
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="strategies", params={"enabled_only": enabled_only})
            await self._send_v2_strategies(user, enabled_only=enabled_only, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_strategies_open" and action.value:
            strategy_key = str(action.value).strip().lower()
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="strategy", params={"strategy_key": strategy_key})
            await self._send_v2_strategy(user, strategy_key=strategy_key, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_strategies_toggle" and action.value:
            strategy_key = str(action.value).strip().lower()
            if await self._toggle_v2_strategy(user, strategy_key=strategy_key) is None:
                await self._send_inline_error(chat_id, ui_text(language, "unknown_action"))
                return
            await self._send_v2_strategy(user, strategy_key=strategy_key, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_strategies_settings" and action.value:
            strategy_key = str(action.value).strip().lower()
            self._v2_open_route(
                user,
                chat_id=chat_id,
                message_id=edit_message_id,
                route="strategy_settings",
                params={"strategy_key": strategy_key},
            )
            await self._send_v2_strategy_settings(
                user,
                strategy_key=strategy_key,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        if action.kind in {"v2_strategies_delivery", "v2_strategies_quality"} and action.value and action.extra:
            strategy_key = str(action.value).strip().lower()
            change = str(action.extra).strip().lower()
            if await self._update_v2_strategy_settings(user, strategy_key=strategy_key, change=change) is None:
                await self._send_inline_error(chat_id, ui_text(language, "unknown_action"))
                return
            await self._send_v2_strategy_settings(
                user,
                strategy_key=strategy_key,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        if action.kind == "v2_strategies_compare":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="results", params={"view": "strategies", "days": 7})
            await self._send_v2_results(user, view="strategies", chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_strategies_guide":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="strategy_guide")
            await self._send_or_edit_text(chat_id=chat_id, text=("<b>📖 Как работают стратегии</b>\n\nСтратегия описывает условия поиска идеи. Сигналы и результаты основаны на сохранённых данных; включение меняет только доставку и ваш профиль." if language == "ru" else "<b>📖 How strategies work</b>\n\nA strategy defines how an idea is found. Signals and results use persisted data; enabling only changes delivery and your profile."), reply_markup=build_v2_help_keyboard(language_code=language), edit_message_id=edit_message_id)
            return
        if action.kind in {"v2_signals_best", "v2_signals_new", "v2_signals_watchlist", "v2_signals_all", "v2_signals_strategy"}:
            view = action.kind.removeprefix("v2_signals_")
            strategy_key = str(action.value).strip().lower() if action.kind == "v2_signals_strategy" and action.value else None
            if action.kind == "v2_signals_strategy":
                view = "new" if str(action.extra or "").lower() == "recent" else "all"
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="signals", params={"view": view, "strategy_key": strategy_key})
            await self._send_v2_signals(user, view=view, strategy_key=strategy_key, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_signal_open" and action.value and action.value.isdigit():
            alert = await self.repository.get_alert(int(action.value))
            if alert is None:
                await self._send_inline_error(chat_id, ui_text(language, "interactive_stale"))
                return
            await self._send_selection_card(user.telegram_user_id, _PrivateSelection(alert=alert, followup=None))
            return
        if action.kind == "v2_flow_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="flow")
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flow_style":
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_style_choice_message(language_code=language),
                reply_markup=build_style_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        if action.kind == "v2_flow_style_preview" and action.value:
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_v2_style_preview(language_code=language, style_label=v2_choice_label("style", action.value, language_code=language), summary=v2_style_preview_summary(action.value, language_code=language)),
                reply_markup=build_style_preview_keyboard(language_code=language, style_key=action.value),
                edit_message_id=edit_message_id,
            )
            return
        if action.kind == "v2_flow_style_apply" and action.value:
            await self._apply_v2_style(user, style_key=action.value, sync_flow=True)
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flow_assets":
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_assets_choice_message(language_code=language),
                reply_markup=build_assets_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        if action.kind == "v2_flow_assets_apply" and action.value:
            await self._apply_v2_assets(user, market_key=action.value, sync_flow=True)
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flow_assets_manual":
            draft = {"v2": True, "context": "flow_assets"}
            await self.repository.upsert_user_onboarding_state(telegram_user_id=user.telegram_user_id, bot_kind=self.bot_kind, step="v2_symbols", draft=draft)
            await self._send_v2_onboarding_step(user, step="symbols", draft=draft, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flow_quality":
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_quality_choice_message(language_code=language),
                reply_markup=build_quality_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        if action.kind == "v2_flow_quality_apply" and action.value:
            await self._apply_v2_quality(user, quality_key=action.value, sync_flow=True)
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flow_reset":
            await self._apply_v2_style(user, style_key="balanced", sync_flow=False)
            await self._apply_v2_assets(user, market_key="all", sync_flow=False)
            await self._apply_v2_quality(user, quality_key="balanced", sync_flow=True)
            await self._send_v2_flow(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flows_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="flows")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("flows", language_code=language), reply_markup=build_flows_keyboard(language_code=language), edit_message_id=edit_message_id)
            return
        if action.kind == "v2_flows_list":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="flow_profiles")
            await self._send_saved_setups_list(
                user,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
                back_callback_data_override="v2:nav:back",
            )
            return
        if action.kind == "v2_notifications_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="notifications")
            await self._send_v2_notifications(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_notifications_toggle" and action.value:
            updates = {
                "signals": {"direct_signal_delivery_enabled": not settings.direct_signal_delivery_enabled},
                "followups": {"followup_delivery_enabled": not settings.followup_delivery_enabled},
                "gold": {"gold_alerts_enabled": not settings.gold_alerts_enabled},
            }
            if action.value in updates:
                await self._save_user_settings(user=user, current_settings=settings, **updates[action.value])
            await self._send_v2_notifications(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_notifications_delivery" and action.value in {"instant", "digest"}:
            await self._save_user_settings(user=user, current_settings=settings, delivery_mode=action.value, delivery_mode_changed_at=utc_now())
            await self._send_v2_notifications(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_notifications_snooze" and action.value:
            until = None if action.value == "resume" else utc_now() + timedelta(hours=1 if action.value == "1h" else 8)
            await self._save_user_settings(
                user=user,
                current_settings=settings,
                snooze_until=until,
                snooze_started_at=None if until is None else utc_now(),
                snooze_label=None if until is None else action.value,
            )
            await self._send_v2_notifications(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_settings_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="settings")
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=format_settings_message(language_code=language),
                reply_markup=build_v2_settings_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        if action.kind in {"v2_results_hub", "v2_results_today", "v2_results_week", "v2_results_strategies", "v2_results_lifecycle", "v2_results_recent", "v2_results_methodology", "v2_results_diagnostics"}:
            view_map = {
                "v2_results_hub": "hub", "v2_results_today": "hub", "v2_results_week": "hub",
                "v2_results_strategies": "strategies", "v2_results_lifecycle": "lifecycle",
                "v2_results_recent": "recent", "v2_results_methodology": "methodology", "v2_results_diagnostics": "diagnostics",
            }
            view = view_map[action.kind]
            days = 1 if action.kind == "v2_results_today" else 7
            strategy_key = str(action.value).strip().lower() if action.value else None
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="results", params={"view": view, "days": days, "strategy_key": strategy_key})
            if view == "diagnostics" and not user.is_admin:
                await self._send_inline_error(chat_id, "Этот экран доступен только администратору." if language == "ru" else "This screen is available to administrators only.")
                return
            if view == "diagnostics":
                diagnostics = await self.results_service.diagnostics()
                diagnostic_labels = (
                    {
                        "signals": "Lifecycle-записей",
                        "signals_without_lifecycle": "Сигналов без lifecycle",
                        "signals_without_followup": "Сигналов без follow-up",
                        "orphan_followups": "Follow-up без сигнала",
                        "duplicate_followups": "Дубли stage follow-up",
                        "results_without_signal": "Результатов без lifecycle",
                        "stale_active": "Зависших активных",
                        "last_lifecycle_job_at": "Последний lifecycle job",
                        "last_lifecycle_duration_ms": "Длительность job, мс",
                        "last_market_update_at": "Последнее обновление рынка",
                        "market_errors_24h": "Ошибок рынка за 24 ч",
                    }
                    if language == "ru"
                    else {
                        "signals": "Lifecycle records",
                        "signals_without_lifecycle": "Signals without lifecycle",
                        "signals_without_followup": "Signals without follow-up",
                        "orphan_followups": "Orphan follow-ups",
                        "duplicate_followups": "Duplicate staged follow-ups",
                        "results_without_signal": "Results without lifecycle",
                        "stale_active": "Stale active signals",
                        "last_lifecycle_job_at": "Last lifecycle job",
                        "last_lifecycle_duration_ms": "Job duration, ms",
                        "last_market_update_at": "Last market update",
                        "market_errors_24h": "Market errors, 24h",
                    }
                )
                none_value = "—"
                text = ("<b>🩺 Диагностика Results</b>\n\n" if language == "ru" else "<b>🩺 Results diagnostics</b>\n\n") + "\n".join(
                    f"{diagnostic_labels.get(key, key)}: <b>{none_value if value is None else value}</b>"
                    for key, value in diagnostics.items()
                )
                await self._send_or_edit_text(chat_id=chat_id, text=text, reply_markup=build_v2_results_keyboard(language_code=language, include_diagnostics=True), edit_message_id=edit_message_id)
                return
            await self._send_v2_results(user, days=days, strategy_key=strategy_key, view=view, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_watchlist_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="watchlist")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("watchlist", language_code=language), reply_markup=build_v2_watchlist_keyboard(language_code=language), edit_message_id=edit_message_id)
            return
        if action.kind == "v2_watchlist_manage":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="watchlist_manage")
            await self._send_watchlist(
                user,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
                back_callback_data_override="v2:nav:back",
            )
            return
        if action.kind == "v2_access_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="access")
            await self._send_access(
                user,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
                back_callback_data_override="v2:nav:back",
            )
            return
        if action.kind == "v2_help_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="help")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("help", language_code=language), reply_markup=build_v2_help_keyboard(language_code=language), edit_message_id=edit_message_id)
            return
        if action.kind == "v2_analytics_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="analytics")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("analytics", language_code=language), reply_markup=build_analytics_keyboard(language_code=language, include_gold=self.settings.gold_alerts_enabled), edit_message_id=edit_message_id)
            return
        if action.kind == "v2_analytics_analyze":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="analysis")
            await self._send_analyze_symbol_help(
                user,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
                back_callback_data_override="v2:nav:back",
            )
            return
        if action.kind == "v2_market_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="market")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("market", language_code=language), reply_markup=build_market_keyboard(language_code=language, include_gold=self.settings.gold_alerts_enabled), edit_message_id=edit_message_id)
            return
        if action.kind == "v2_market_sets":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="market_sets")
            await self._send_v2_market_sets(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_market_set" and action.value:
            shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
            kind = str(action.value).strip().lower()
            if kind == "tracked":
                await self._save_user_settings(
                    user=user,
                    current_settings=shell_settings,
                    active_watchlist_theme="watchlist",
                    active_custom_theme_name=None,
                    watchlist_only=True,
                )
            elif kind == "builtin" and action.extra in BUILTIN_WATCHLIST_THEMES:
                await self._activate_builtin_theme(user, shell_settings, str(action.extra))
            elif kind == "saved" and str(action.extra or "").isdigit():
                if not await self._activate_saved_theme(user, shell_settings, int(str(action.extra))):
                    await self._send_inline_error(chat_id, "Набор больше не существует." if language == "ru" else "This set no longer exists.")
                    return
            else:
                await self._send_inline_error(chat_id, ui_text(language, "unknown_action"))
                return
            await self._send_v2_market_sets(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        if action.kind == "v2_gold_hub":
            self._v2_open_route(user, chat_id=chat_id, message_id=edit_message_id, route="gold")
            await self._send_or_edit_text(chat_id=chat_id, text=format_v2_hub_message("gold", language_code=language), reply_markup=build_gold_keyboard(language_code=language), edit_message_id=edit_message_id)
            return

    async def _send_menu_hub(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user_id)
        if self.bot_kind == "premium":
            user = await self.repository.get_private_user(user_id)
            if user is not None:
                user = self._store_cached_user(user)
                settings = await self._enable_v2_navigation(user, settings)
                await self._send_v2_home(
                    user,
                    is_pro=str(settings.display_mode or "simple").strip().lower() == "pro",
                    chat_id=chat_id,
                    edit_message_id=edit_message_id,
                )
                return
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user_id,
            chat_id=chat_id or str(user_id),
        )
        self._remember_screen_back_callback(user_id, screen="language_picker", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="access", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="referral", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="deliveryhub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="watchhub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="statshub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="aihub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="settingshub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="workspacehub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="setupshub", callback_data="ux:menu")
        self._remember_screen_back_callback(user_id, screen="filtershub", callback_data="ux:menu")
        user = await self.repository.get_private_user(user_id)
        strong_count = 0
        fresh_count = 0
        if user is not None:
            strong_count = len(await self._pick_signal_for_user(user, strong_only=True, limit=6))
            fresh_count = len(await self._pick_signal_for_user(user, strong_only=False, limit=8))
        access_label = await self._access_label_for_user(user, language_code=language) if user is not None else ("Unknown" if language == "en" else "Неизвестно")
        watchlist_count = len(await self._watchlist_symbols(user_id))
        active_setup = await self._active_saved_setup(user_id)
        quick_launch = await self._primary_quick_launch_setup(user_id)
        now = utc_now()
        if is_snoozed(settings, now=now):
            quiet_state = "Snoozed" if language == "en" else "На паузе"
        elif is_within_quiet_hours(settings, now=now, timezone_obj=self.settings.timezone):
            quiet_state = "Active" if language == "en" else "Активно"
        else:
            quiet_state = "Off" if language == "en" else "Выкл"
        market_label = (
            "Quiet"
            if strong_count <= 0 and fresh_count <= 1
            else "Selective"
            if strong_count <= 2
            else "Active"
        )
        if language == "ru":
            market_label = {"Quiet": "Спокойно", "Selective": "Выборочно", "Active": "Активно"}[market_label]
        enabled_notifications_summary = self._compact_home_labels(
            await self._home_enabled_notification_labels(user_id, settings, language_code=language),
            language_code=language,
            empty_label=("Off" if language == "en" else "Выкл"),
        )
        enabled_strategies_summary = self._compact_home_labels(
            [self._strategy_label(strategy_key, language_code=language) for strategy_key in self._enabled_strategy_keys(settings)],
            language_code=language,
            empty_label=("Nothing selected yet" if language == "en" else "Пока не выбрано"),
        )
        if str(settings.display_mode or "").strip().lower() == "simple":
            summary_lines = [
                f"• {'Market' if language == 'en' else 'Рынок'}: <b>{market_label}</b>",
                f"• {'Strong setups' if language == 'en' else 'Сильные сетапы'}: <b>{strong_count}</b>",
                f"• {'Fresh signals' if language == 'en' else 'Свежие сигналы'}: <b>{fresh_count}</b>",
                f"• {'Access' if language == 'en' else 'Доступ'}: <b>{escape_html(access_label)}</b>",
                f"• {'Notifications' if language == 'en' else 'Уведомления'}: <b>{escape_html(enabled_notifications_summary)}</b>",
                "",
                (
                    "Start with an example, the reading guide, or strong setups. Pro Mode opens the advanced desks."
                    if language == "en"
                    else "Начни с примера, инструкции или сильных сетапов. Pro-режим открывает расширенные разделы."
                ),
            ]
        else:
            summary_lines = [
                f"• {'Market' if language == 'en' else 'Рынок'}: <b>{market_label}</b>",
                f"• {'Matches now' if language == 'en' else 'Совпадений сейчас'}: <b>{strong_count} {'strong setups' if language == 'en' else 'сильных сетапа'}</b>",
                f"• {'Setup' if language == 'en' else 'Сетап'}: <b>{escape_html(active_setup.name if active_setup is not None else ('Adaptive' if language == 'en' else 'Адаптивный'))}</b>",
                f"• {'Workspace' if language == 'en' else 'Профиль'}: <b>{escape_html(self._workspace_label(settings.active_workspace, language_code=language))}</b>",
                f"• {'Delivery' if language == 'en' else 'Доставка'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language))}</b>",
                f"• {'Notifications' if language == 'en' else 'Уведомления'}: <b>{escape_html(enabled_notifications_summary)}</b>",
                f"• {'Strategy flow' if language == 'en' else 'Стратегии в потоке'}: <b>{escape_html(enabled_strategies_summary)}</b>",
                f"• {'Watchlist' if language == 'en' else 'Вотчлист'}: <b>{watchlist_count} {'active symbols' if language == 'en' else 'активных символов'}</b>",
            ]
            if quiet_state != ("Off" if language == "en" else "Выкл"):
                summary_lines.append(f"• {'Quiet mode' if language == 'en' else 'Тихий режим'}: <b>{quiet_state}</b>")
            summary_lines.extend(
                [
                    "",
                    (
                        "Advanced tools are grouped below so the home screen stays readable."
                        if language == "en"
                        else "Расширенные инструменты сгруппированы ниже, чтобы главный экран оставался понятным."
                    ),
                ]
            )
        hub_text = f"{self._main_hub_text(settings, language_code=language)}\n\n" + "\n".join(summary_lines)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=hub_text if self.bot_kind == "premium" else format_menu_panel_message(bot_kind=self.bot_kind, language_code=language),
            reply_markup=build_personalized_menu_hub_keyboard(
                language_code=language,
                display_mode=settings.display_mode,
                payment_label=await self._payment_menu_label_for_user(user_id),
                quick_launch_label=(
                    f"▶ {quick_launch.name}"
                    if quick_launch is not None
                    else None
                ),
                quick_launch_callback_data=(
                    f"ux:setup:activate:{quick_launch.id}"
                    if quick_launch is not None
                    else None
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_pro_submenu(
        self,
        user: PrivateBotUserRecord,
        *,
        hub: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_pro_submenu_message(hub=hub, language_code=language),
            reply_markup=build_pro_submenu_keyboard(
                hub=hub,
                language_code=language,
                payment_label=await self._payment_menu_label_for_user(user.telegram_user_id),
                is_admin=self.role_guard.is_admin(user),
            ),
            edit_message_id=edit_message_id,
        )

    def _setup_builder_delivery_profile_from_rules(self, rules: dict[str, object]) -> str:
        normalized = normalize_delivery_rules(rules)
        if (
            normalized.get("strong_signals") == "instant"
            and normalized.get("watchlist_matches") == "instant"
            and normalized.get("medium_signals") == "digest"
            and normalized.get("overnight") == "quiet"
        ):
            return "balanced"
        if (
            normalized.get("strong_signals") == "instant"
            and normalized.get("watchlist_matches") == "instant"
            and normalized.get("medium_signals") == "off"
        ):
            return "focused_instant"
        if normalized.get("watchlist_matches") == "instant" and normalized.get("medium_signals") == "digest":
            return "watchlist_priority"
        if normalized.get("strong_signals") == "digest" or normalized.get("overnight") == "quiet":
            return "quiet_digest"
        return "balanced"

    def _setup_builder_delivery_rules(self, profile_key: str) -> dict[str, object]:
        rules = default_delivery_rules()
        if profile_key == "focused_instant":
            rules.update(
                {
                    "strong_signals": "instant",
                    "watchlist_matches": "instant",
                    "medium_signals": "off",
                    "followups": "important",
                    "gold_signals": "digest",
                    "overnight": "quiet",
                }
            )
        elif profile_key == "watchlist_priority":
            rules.update(
                {
                    "strong_signals": "digest",
                    "watchlist_matches": "instant",
                    "medium_signals": "digest",
                    "followups": "important",
                    "gold_signals": "instant",
                    "overnight": "quiet",
                }
            )
        elif profile_key == "quiet_digest":
            rules.update(
                {
                    "strong_signals": "digest",
                    "watchlist_matches": "digest",
                    "medium_signals": "digest",
                    "followups": "digest",
                    "gold_signals": "digest",
                    "overnight": "quiet",
                    "digest_frequency_hours": 4,
                }
            )
        else:
            rules.update(
                {
                    "strong_signals": "instant",
                    "watchlist_matches": "instant",
                    "medium_signals": "digest",
                    "followups": "important",
                    "gold_signals": "instant",
                    "overnight": "quiet",
                }
            )
        return rules

    async def _setup_builder_theme_options(self, telegram_user_id: int) -> list[dict[str, object]]:
        return [
            {"id": theme_id, "name": theme_name}
            for theme_id, theme_name in await self._saved_watchlist_themes(telegram_user_id)
        ]

    def _setup_builder_scope_state_from_draft(self, draft: dict[str, object]) -> tuple[str, dict[str, object] | None]:
        scope_type = normalize_asset_scope_type(draft.get("asset_scope_type") or draft.get("asset_scope"))
        payload = draft.get("asset_scope_payload")
        if scope_type == "custom" and not isinstance(payload, dict):
            payload = {"symbols": draft.get("custom_symbols", [])}
        elif scope_type == "theme" and not isinstance(payload, dict):
            payload = {
                "theme_name": draft.get("theme_name"),
                "theme_id": draft.get("theme_id"),
                "symbols": draft.get("theme_symbols", []),
            }
        return scope_type, normalize_asset_scope_payload(scope_type, payload)

    def _write_setup_builder_scope(
        self,
        draft: dict[str, object],
        *,
        scope_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        normalized_type = normalize_asset_scope_type(scope_type)
        normalized_payload = normalize_asset_scope_payload(normalized_type, payload)
        draft["asset_scope_type"] = normalized_type
        draft["asset_scope"] = normalized_type
        draft["asset_scope_payload"] = normalized_payload
        draft["custom_symbols"] = list((normalized_payload or {}).get("symbols", [])) if normalized_type == "custom" else []
        if normalized_type == "theme" and normalized_payload is not None:
            draft["theme_name"] = normalized_payload.get("theme_name")
            draft["theme_id"] = normalized_payload.get("theme_id")
            draft["theme_symbols"] = list(normalized_payload.get("symbols", []))
        else:
            draft.pop("theme_name", None)
            draft.pop("theme_id", None)
            draft["theme_symbols"] = []

    async def _current_asset_scope_state(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord | None = None,
        active_strategy_key: str | None = None,
        active_strategy_settings: UserSettingsRecord | None = None,
    ) -> tuple[str, dict[str, object] | None]:
        shell = shell_settings or await self._ensure_shell_settings(telegram_user_id)
        raw_personalization = shell.personalization if isinstance(shell.personalization, dict) else {}
        if "asset_scope_type" in raw_personalization or "asset_scope_payload" in raw_personalization:
            return (
                normalize_asset_scope_type(raw_personalization.get("asset_scope_type")),
                normalize_asset_scope_payload(
                    raw_personalization.get("asset_scope_type"),
                    raw_personalization.get("asset_scope_payload"),
                ),
            )
        strategy_key = active_strategy_key or self._resolved_active_strategy_key(shell) or "rsi"
        strategy_settings = active_strategy_settings or await self._load_strategy_settings(
            telegram_user_id,
            shell_settings=shell,
            strategy_key=strategy_key,
        )
        if not strategy_settings.watchlist_only:
            return "all", None
        theme_key = str(strategy_settings.active_watchlist_theme or "custom").strip().lower()
        if strategy_settings.active_custom_theme_name:
            theme = await self.repository.get_premium_strategy_watchlist_theme(
                telegram_user_id=telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                theme_name=str(strategy_settings.active_custom_theme_name),
            )
            payload: dict[str, object] = {"theme_name": str(strategy_settings.active_custom_theme_name)}
            if theme is not None:
                payload["theme_id"] = theme.id
                payload["symbols"] = await self.repository.list_premium_strategy_watchlist_theme_symbols(theme.id)
            return "theme", normalize_asset_scope_payload("theme", payload)
        if theme_key in {"majors", "gold", "memes", "favorites", "watchlist"}:
            return theme_key, None
        strategy_symbols = await self._favorite_symbols_for_strategy(telegram_user_id, strategy_key)
        if strategy_symbols:
            return "custom", normalize_asset_scope_payload("custom", {"symbols": strategy_symbols})
        return "watchlist", None

    async def _setup_builder_draft_from_payload(
        self,
        telegram_user_id: int,
        *,
        language_code: str,
        payload: dict[str, object],
        mode: str,
        parent_callback: str = "main:setups",
        preferred_name: str | None = None,
        editing_setup_id: int | None = None,
    ) -> dict[str, object]:
        shell_payload = payload.get("shell") if isinstance(payload.get("shell"), dict) else payload
        strategies_payload = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
        enabled_strategy_keys = self._normalize_enabled_strategy_keys(
            shell_payload.get("enabled_strategy_keys") or tuple(strategies_payload.keys())
        )
        active_strategy_key = str(
            shell_payload.get("active_strategy_key")
            or next(iter(enabled_strategy_keys or ("rsi",)), "rsi")
        ).strip().lower()
        if active_strategy_key not in enabled_strategy_keys:
            active_strategy_key = next(iter(enabled_strategy_keys or ("rsi",)), "rsi")
        active_strategy_payload = strategies_payload.get(active_strategy_key) if isinstance(strategies_payload.get(active_strategy_key), dict) else {}
        raw_personalization = shell_payload.get("personalization") if isinstance(shell_payload.get("personalization"), dict) else {}
        personalization = normalize_personalization(raw_personalization)
        hidden = dict(personalization.get("hidden") or {})
        selected_timeframes = [
            timeframe
            for timeframe in self.SETUP_BUILDER_TIMEFRAMES
            if timeframe not in set(hidden.get("timeframes", []))
        ] or ["15m", "1h"]
        asset_scope_type = normalize_asset_scope_type(
            raw_personalization.get("asset_scope_type") if isinstance(raw_personalization, dict) else shell_payload.get("asset_scope_type")
        )
        asset_scope_payload = normalize_asset_scope_payload(
            asset_scope_type,
            raw_personalization.get("asset_scope_payload") if isinstance(raw_personalization, dict) and "asset_scope_payload" in raw_personalization else shell_payload.get("asset_scope_payload"),
        )
        if asset_scope_type == "all" and "asset_scope_type" not in raw_personalization and "asset_scope_type" not in shell_payload:
            asset_scope_type, asset_scope_payload = infer_asset_scope_from_payload(payload)
        draft: dict[str, object] = {
            "entry_mode": mode,
            "template_key": None,
            "parent_callback": parent_callback,
            "name": str(preferred_name or "New Setup"),
            "selected_strategies": list(enabled_strategy_keys) or [active_strategy_key],
            "selected_timeframes": selected_timeframes,
            "direction": str(active_strategy_payload.get("direction_filter") or "both"),
            "session": str(personalization.get("session_filter") or "all_day"),
            "noise_level": str(personalization.get("noise_level") or "balanced"),
            "score_filter": str(personalization.get("score_filter") or "all"),
            "delivery_profile": self._setup_builder_delivery_profile_from_rules(
                normalize_delivery_rules(shell_payload.get("delivery_rules"))
            ),
            "display_mode": str(shell_payload.get("display_mode") or "pro"),
            "active_workspace": shell_payload.get("active_workspace"),
            "base_payload": payload,
            "available_themes": await self._setup_builder_theme_options(telegram_user_id),
        }
        if editing_setup_id is not None:
            draft["editing_setup_id"] = editing_setup_id
        self._write_setup_builder_scope(draft, scope_type=asset_scope_type, payload=asset_scope_payload)
        return draft

    async def _current_setup_builder_draft(
        self,
        telegram_user_id: int,
        *,
        language_code: str,
        mode: str,
        template_key: str | None = None,
        parent_callback: str = "main:setups",
    ) -> dict[str, object]:
        shell_settings = await self._ensure_shell_settings(telegram_user_id)
        active_strategy_key = self._resolved_active_strategy_key(shell_settings) or "rsi"
        active_strategy_settings = await self._load_strategy_settings(
            telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=active_strategy_key,
        )
        personalization = normalize_personalization(self._personalization_state(shell_settings))
        hidden = dict(personalization.get("hidden") or {})
        selected_timeframes = [
            timeframe
            for timeframe in self.SETUP_BUILDER_TIMEFRAMES
            if timeframe not in set(hidden.get("timeframes", []))
        ] or ["15m", "1h"]
        global_favorites = await self._global_favorite_symbols(telegram_user_id)
        asset_scope_type, asset_scope_payload = await self._current_asset_scope_state(
            telegram_user_id,
            shell_settings=shell_settings,
            active_strategy_key=active_strategy_key,
            active_strategy_settings=active_strategy_settings,
        )
        selected_strategies = list(self._normalize_enabled_strategy_keys(self._enabled_strategy_keys(shell_settings)))
        if not selected_strategies:
            selected_strategies = [active_strategy_key]
        draft: dict[str, object] = {
            "entry_mode": mode,
            "template_key": template_key,
            "parent_callback": parent_callback,
            "name": await self._ensure_unique_setup_name(
                telegram_user_id,
                preferred_name="New Setup" if language_code == "en" else "Новый сетап",
            ),
            "selected_strategies": selected_strategies,
            "selected_timeframes": selected_timeframes,
            "direction": str(active_strategy_settings.direction_filter or "both"),
            "session": str(personalization.get("session_filter") or "all_day"),
            "noise_level": str(personalization.get("noise_level") or "balanced"),
            "score_filter": str(personalization.get("score_filter") or "all"),
            "delivery_profile": self._setup_builder_delivery_profile_from_rules(self._delivery_rules_state(shell_settings)),
            "display_mode": shell_settings.display_mode,
            "active_workspace": shell_settings.active_workspace,
            "base_payload": await self._build_current_setup_payload(telegram_user_id),
            "available_themes": await self._setup_builder_theme_options(telegram_user_id),
        }
        self._write_setup_builder_scope(draft, scope_type=asset_scope_type, payload=asset_scope_payload)
        if mode == "blank":
            draft.update(
                {
                    "name": await self._ensure_unique_setup_name(
                        telegram_user_id,
                        preferred_name="New Setup" if language_code == "en" else "Новый сетап",
                    ),
                    "selected_strategies": ["breakout", "trend_pullback"],
                    "selected_timeframes": ["15m", "1h"],
                    "direction": "both",
                    "session": "all_day",
                    "noise_level": "balanced",
                    "score_filter": "all",
                    "delivery_profile": "balanced",
                }
            )
            self._write_setup_builder_scope(draft, scope_type="all")
        if mode == "template":
            template_map: dict[str, dict[str, object]] = {
                "low_noise_majors": {
                    "name": "Low Noise Majors",
                    "asset_scope_type": "majors",
                    "selected_strategies": ["trend_pullback", "false_breakout", "bollinger"],
                    "selected_timeframes": ["15m", "1h", "4h"],
                    "noise_level": "minimal",
                    "score_filter": "strong",
                    "delivery_profile": "quiet_digest",
                },
                "gold_london": {
                    "name": "Gold London Session",
                    "asset_scope_type": "gold",
                    "selected_strategies": ["gold_breakout", "gold_pullback", "gold_liquidity"],
                    "selected_timeframes": ["15m", "1h"],
                    "session": "london",
                    "noise_level": "balanced",
                    "score_filter": "strong",
                    "delivery_profile": "focused_instant",
                },
                "fast_intraday": {
                    "name": "Fast Intraday",
                    "asset_scope_type": "majors",
                    "selected_strategies": ["breakout", "vwap", "false_breakout"],
                    "selected_timeframes": ["5m", "15m"],
                    "noise_level": "active",
                    "score_filter": "all",
                    "delivery_profile": "focused_instant",
                },
                "watchlist_only": {
                    "name": "Watchlist Only",
                    "asset_scope_type": "favorites" if global_favorites else "watchlist",
                    "selected_strategies": selected_strategies,
                    "selected_timeframes": selected_timeframes,
                    "noise_level": "balanced",
                    "score_filter": "strong",
                    "delivery_profile": "watchlist_priority",
                },
                "high_score_only": {
                    "name": "High Score Only",
                    "asset_scope_type": "all",
                    "selected_strategies": ["breakout", "trend_pullback", "vwap"],
                    "selected_timeframes": ["15m", "1h"],
                    "noise_level": "minimal",
                    "score_filter": "high",
                    "delivery_profile": "focused_instant",
                },
            }
            draft.update(template_map.get(template_key or "", {}))
            self._write_setup_builder_scope(
                draft,
                scope_type=str(draft.get("asset_scope_type") or draft.get("asset_scope") or "all"),
                payload=draft.get("asset_scope_payload") if isinstance(draft.get("asset_scope_payload"), dict) else None,
            )
            draft["name"] = await self._ensure_unique_setup_name(
                telegram_user_id,
                preferred_name=str(draft.get("name") or "New Setup"),
            )
        return draft

    async def _send_create_setup_entry(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._clear_setup_builder_state(user.telegram_user_id)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_create_setup_entry_message(language_code=language),
            reply_markup=build_create_setup_entry_keyboard(
                language_code=language,
                back_callback_data="main:setups",
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_setup_template_picker(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_setup_template_picker_message(language_code=language),
            reply_markup=build_setup_template_picker_keyboard(
                language_code=language,
                back_callback_data="ux:setup:create",
            ),
            edit_message_id=edit_message_id,
        )

    async def _begin_setup_builder(
        self,
        user: PrivateBotUserRecord,
        *,
        mode: str,
        template_key: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        parent_callback: str = "main:setups",
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        draft = await self._current_setup_builder_draft(
            user.telegram_user_id,
            language_code=language,
            mode=mode,
            template_key=template_key,
            parent_callback=parent_callback,
        )
        await self._save_setup_builder_state(
            user.telegram_user_id,
            step="name",
            draft=draft,
        )
        await self._send_setup_builder_step(
            user,
            step="name",
            draft=draft,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _send_setup_builder_step(
        self,
        user: PrivateBotUserRecord,
        *,
        step: str,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        parent_callback = str(draft.get("parent_callback") or "main:setups")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_setup_builder_message(
                language_code=language,
                draft=draft,
                step=step,
            ),
            reply_markup=build_setup_builder_keyboard(
                language_code=language,
                draft=draft,
                step=step,
                parent_callback_data=parent_callback,
            ),
            edit_message_id=edit_message_id,
        )

    def _validate_setup_builder_step(self, step: str, draft: dict[str, object], *, language_code: str) -> str | None:
        scope_type, scope_payload = self._setup_builder_scope_state_from_draft(draft)
        if step == "scope" and scope_type == "custom" and not (scope_payload or {}).get("symbols"):
            return "Add at least one symbol first." if language_code == "en" else "Сначала добавь хотя бы один символ."
        if step == "scope" and scope_type == "theme" and not str((scope_payload or {}).get("theme_name") or "").strip():
            return "Choose a saved set first." if language_code == "en" else "Сначала выбери сохранённый сет."
        if step == "strategies" and not draft.get("selected_strategies"):
            return "Select at least one strategy." if language_code == "en" else "Выбери хотя бы одну стратегию."
        if step == "timeframes" and not draft.get("selected_timeframes"):
            return "Select at least one timeframe." if language_code == "en" else "Выбери хотя бы один таймфрейм."
        return None

    async def _send_setup_builder_parent(
        self,
        user: PrivateBotUserRecord,
        *,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        editing_setup_id = draft.get("editing_setup_id")
        if isinstance(editing_setup_id, int):
            await self._send_saved_setup_detail(
                user,
                setup_id=editing_setup_id,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        parent_callback = str(draft.get("parent_callback") or "main:setups")
        if parent_callback == "ux:setup:list":
            await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        await self._send_setups_hub(user, chat_id=chat_id, edit_message_id=edit_message_id)

    async def _setup_builder_back_target(
        self,
        user: PrivateBotUserRecord,
        *,
        step: str,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        if step == "name":
            if str(draft.get("entry_mode") or "") == "template":
                await self._send_setup_template_picker(user, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            if draft.get("editing_setup_id"):
                await self._clear_setup_builder_state(user.telegram_user_id)
                await self._send_setup_builder_parent(
                    user,
                    draft=draft,
                    chat_id=chat_id,
                    edit_message_id=edit_message_id,
                )
                return
            await self._send_create_setup_entry(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        current_index = self.SETUP_BUILDER_STEPS.index(step)
        previous_step = self.SETUP_BUILDER_STEPS[max(current_index - 1, 0)]
        await self._save_setup_builder_state(user.telegram_user_id, step=previous_step, draft=draft)
        await self._send_setup_builder_step(
            user,
            step=previous_step,
            draft=draft,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _build_setup_payload_from_draft(
        self,
        telegram_user_id: int,
        *,
        draft: dict[str, object],
    ) -> dict[str, object]:
        base_payload = draft.get("base_payload") if isinstance(draft.get("base_payload"), dict) else await self._build_current_setup_payload(telegram_user_id)
        payload = {
            "shell": dict(base_payload.get("shell") if isinstance(base_payload.get("shell"), dict) else {}),
            "strategies": dict(base_payload.get("strategies") if isinstance(base_payload.get("strategies"), dict) else {}),
        }
        shell = payload["shell"]
        strategies_payload = payload["strategies"]
        selected_strategy_keys = self._normalize_enabled_strategy_keys(draft.get("selected_strategies") or ())
        if not selected_strategy_keys:
            selected_strategy_keys = ("breakout",)
        selected_timeframes = [
            str(item)
            for item in draft.get("selected_timeframes", [])
            if str(item) in self.SETUP_BUILDER_TIMEFRAMES
        ] or ["15m", "1h"]
        personalization = normalize_personalization(shell.get("personalization") if isinstance(shell, dict) else {})
        hidden = dict(personalization.get("hidden") or {})
        hidden["timeframes"] = [
            timeframe
            for timeframe in self.SETUP_BUILDER_TIMEFRAMES
            if timeframe not in selected_timeframes
        ]
        personalization["hidden"] = hidden
        personalization["noise_level"] = str(draft.get("noise_level") or "balanced")
        personalization["score_filter"] = str(draft.get("score_filter") or "all")
        personalization["session_filter"] = str(draft.get("session") or "all_day")
        personalization["quick_filters"] = []
        delivery_profile = str(draft.get("delivery_profile") or "balanced")
        delivery_rules = self._setup_builder_delivery_rules(delivery_profile)
        enable_direct_delivery = delivery_profile != "quiet_digest"
        scope_type, scope_payload = self._setup_builder_scope_state_from_draft(draft)
        personalization["asset_scope_type"] = scope_type
        personalization["asset_scope_payload"] = scope_payload
        shell["enabled_strategy_keys"] = list(selected_strategy_keys)
        shell["active_strategy_key"] = selected_strategy_keys[0]
        shell["display_mode"] = str(draft.get("display_mode") or shell.get("display_mode") or "pro")
        shell["active_workspace"] = draft.get("active_workspace")
        shell["personalization"] = personalization
        shell["delivery_rules"] = delivery_rules
        shell["gold_alerts_enabled"] = any(key in GOLD_SUBSTRATEGY_KEY_SET or key == GOLD_MASTER_STRATEGY_KEY for key in selected_strategy_keys)
        shell["asset_scope_type"] = scope_type
        shell["asset_scope_payload"] = scope_payload
        current_global_favorites = [normalize_symbol(str(item)) for item in shell.get("global_favorites", []) if str(item).strip()]
        current_custom_symbols = [
            normalize_symbol(str(item))
            for item in (scope_payload or {}).get("symbols", [])
            if str(item).strip()
        ]
        theme_name = str((scope_payload or {}).get("theme_name") or "").strip()
        theme_symbols = [
            normalize_symbol(str(item))
            for item in (scope_payload or {}).get("symbols", [])
            if str(item).strip()
        ]
        for strategy_key in selected_strategy_keys:
            if strategy_key not in strategies_payload:
                strategies_payload[strategy_key] = await self._strategy_setup_snapshot(
                    telegram_user_id,
                    shell_settings=await self._ensure_shell_settings(telegram_user_id),
                    strategy_key=strategy_key,
                )
            strategy_payload = dict(strategies_payload.get(strategy_key) or {})
            strategy_payload["direction_filter"] = str(draft.get("direction") or "both")
            strategy_payload["delivery_mode"] = "digest" if delivery_profile == "quiet_digest" else "instant"
            strategy_payload["direct_signal_delivery_enabled"] = enable_direct_delivery
            strategy_payload["followup_delivery_enabled"] = delivery_rules.get("followups") != "off"
            if scope_type == "all":
                strategy_payload["watchlist_only"] = False
                strategy_payload["active_watchlist_theme"] = "custom"
                strategy_payload["active_custom_theme_name"] = None
            elif scope_type in {"majors", "memes", "gold"}:
                strategy_payload["watchlist_only"] = True
                strategy_payload["active_watchlist_theme"] = scope_type
                strategy_payload["active_custom_theme_name"] = None
                strategy_payload["favorite_symbols"] = []
            elif scope_type == "favorites":
                strategy_payload["watchlist_only"] = True
                strategy_payload["active_watchlist_theme"] = "favorites"
                strategy_payload["active_custom_theme_name"] = None
                strategy_payload["favorite_symbols"] = []
            elif scope_type == "watchlist":
                strategy_payload["watchlist_only"] = True
                strategy_payload["active_watchlist_theme"] = "watchlist"
                strategy_payload["active_custom_theme_name"] = None
            elif scope_type == "theme":
                strategy_payload["watchlist_only"] = True
                strategy_payload["active_watchlist_theme"] = "custom"
                strategy_payload["active_custom_theme_name"] = theme_name or None
                strategy_payload["favorite_symbols"] = theme_symbols
            else:
                strategy_payload["watchlist_only"] = True
                strategy_payload["active_watchlist_theme"] = "custom"
                strategy_payload["active_custom_theme_name"] = None
                strategy_payload["favorite_symbols"] = current_custom_symbols or current_global_favorites
            strategies_payload[strategy_key] = strategy_payload
        payload["strategies"] = {key: strategies_payload[key] for key in selected_strategy_keys}
        return payload

    async def _save_setup_from_builder(
        self,
        user: PrivateBotUserRecord,
        *,
        draft: dict[str, object],
        activate: bool,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        payload = await self._build_setup_payload_from_draft(user.telegram_user_id, draft=draft)
        editing_setup_id = draft.get("editing_setup_id")
        unique_name = await self._ensure_unique_setup_name(
            user.telegram_user_id,
            preferred_name=str(draft.get("name") or "New Setup"),
            exclude_setup_id=int(editing_setup_id) if isinstance(editing_setup_id, int) else None,
        )
        if isinstance(editing_setup_id, int):
            created = await self.repository.update_user_saved_setup(
                editing_setup_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                name=unique_name,
                payload=payload,
            )
            if created is None:
                await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=edit_message_id)
                return
        else:
            created = await self.repository.create_user_saved_setup(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                name=unique_name,
                payload=payload,
                is_default=False,
                is_pinned=False,
            )
        await self._clear_setup_builder_state(user.telegram_user_id)
        if activate:
            await self._apply_saved_setup_payload(user, setup=created)
        await self._send_saved_setup_detail(
            user,
            setup_id=created.id,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _send_setups_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        active_setup = await self._active_saved_setup(user.telegram_user_id)
        default_setup = await self._default_saved_setup(user.telegram_user_id)
        setups = await self.repository.list_user_saved_setups(user.telegram_user_id, bot_kind=self.bot_kind)
        self._remember_screen_back_callback(user.telegram_user_id, screen="setup_list", callback_data="main:setups")
        self._remember_screen_back_callback(user.telegram_user_id, screen="setup_detail", callback_data="ux:setup:list")
        active_summary = summarize_setup_payload(
            active_setup.payload if active_setup is not None else await self._build_current_setup_payload(user.telegram_user_id),
            language_code=language,
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=format_setups_hub_message(
                language_code=language,
                active_setup_name=active_setup.name if active_setup is not None else None,
                active_summary=active_summary,
                setups_count=len(setups),
                pinned_count=sum(1 for item in setups if item.is_pinned),
                default_setup_name=default_setup.name if default_setup is not None else None,
            ),
            reply_markup=build_truthful_setups_hub_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="setupshub",
                    default="main:today",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_saved_setups_list(
        self,
        user: PrivateBotUserRecord,
        *,
        only_pinned: bool = False,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        back_callback_data_override: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        setups = await self.repository.list_user_saved_setups(user.telegram_user_id, bot_kind=self.bot_kind)
        if only_pinned:
            setups = [setup for setup in setups if setup.is_pinned]
        active_setup = await self._active_saved_setup(user.telegram_user_id)
        if back_callback_data_override is None:
            self._remember_screen_back_callback(user.telegram_user_id, screen="setup_detail", callback_data="ux:setup:list")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_saved_setups_message(
                language_code=language,
                setups=setups,
                active_setup_id=active_setup.id if active_setup is not None else None,
            ),
            reply_markup=build_saved_setups_keyboard(
                language_code=language,
                setups=setups,
                only_pinned=only_pinned,
                back_callback_data=back_callback_data_override or "main:setups",
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_saved_setup_detail(
        self,
        user: PrivateBotUserRecord,
        *,
        setup_id: int,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        back_callback_data_override: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        setup = await self.repository.get_user_saved_setup(
            setup_id,
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
        )
        if setup is None:
            await self._send_chat_message(
                chat_id=chat_id or str(user.telegram_user_id),
                text="Setup not found." if language == "en" else "Сетап не найден.",
                parse_mode=None,
            )
            await self._send_saved_setups_list(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        active_setup = await self._active_saved_setup(user.telegram_user_id)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_setup_detail_message(
                language_code=language,
                setup=setup,
                summary=summarize_setup_payload(setup.payload, language_code=language),
                is_active=active_setup is not None and active_setup.id == setup.id,
            ),
            reply_markup=build_setup_detail_keyboard(
                language_code=language,
                setup_id=setup.id,
                is_active=active_setup is not None and active_setup.id == setup.id,
                is_pinned=setup.is_pinned,
                back_callback_data=back_callback_data_override or "ux:setup:list",
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_quick_filters_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        active_filters = [item.replace("_", " ").title() for item in personalization.get("quick_filters", [])]
        self._remember_screen_back_callback(user.telegram_user_id, screen="noisehub", callback_data="ux:quickfiltershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="scorehub", callback_data="ux:quickfiltershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="sessionhub", callback_data="ux:quickfiltershub")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_quick_filters_message(
                language_code=language,
                active_filters=active_filters,
                summary=summarize_setup_payload(await self._build_current_setup_payload(user.telegram_user_id), language_code=language),
            ),
            reply_markup=build_quick_filters_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="quickfiltershub",
                    default="main:today",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_custom_filters_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        active_setup = await self._active_saved_setup(user.telegram_user_id)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="filtershub",
            default="main:today",
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="quickfiltershub", callback_data="ux:filtershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="noisehub", callback_data="ux:filtershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="scorehub", callback_data="ux:filtershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="sessionhub", callback_data="ux:filtershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryrules", callback_data="ux:filtershub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="hidemute", callback_data="ux:filtershub")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_custom_filters_hub_message(
                language_code=language,
                current_summary=summarize_setup_payload(
                    await self._build_current_setup_payload(user.telegram_user_id),
                    language_code=language,
                ),
                active_setup_name=active_setup.name if active_setup is not None else None,
            ),
            reply_markup=build_custom_filters_hub_keyboard(
                language_code=language,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_noise_level_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        selected = str(personalization.get("noise_level") or "balanced")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_noise_level_message(language_code=language, selected=selected),
            reply_markup=build_noise_level_keyboard(
                language_code=language,
                selected=selected,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="noisehub",
                    default="ux:quickfiltershub",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_score_filter_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        selected = str(personalization.get("score_filter") or "all")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_score_filter_message(language_code=language, selected=selected),
            reply_markup=build_score_filter_keyboard(
                language_code=language,
                selected=selected,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="scorehub",
                    default="ux:quickfiltershub",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_session_filter_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        selected = str(personalization.get("session_filter") or "all_day")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_session_filter_message(language_code=language, selected=selected),
            reply_markup=build_session_filter_keyboard(
                language_code=language,
                selected=selected,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="sessionhub",
                    default="ux:quickfiltershub",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_delivery_rules_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        rules = self._delivery_rules_state(settings)
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryruleview", callback_data="ux:deliveryrules")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_delivery_rules_message(language_code=language, rules=rules),
            reply_markup=build_delivery_rules_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="deliveryrules",
                    default="main:settings",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_delivery_rule_view(
        self,
        user: PrivateBotUserRecord,
        *,
        rule_key: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        rules = self._delivery_rules_state(settings)
        current_value = str(rules.get(rule_key) or "")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_delivery_rule_options_message(
                language_code=language,
                rule_key=rule_key,
                current_value=current_value,
            ),
            reply_markup=build_delivery_rule_options_keyboard(
                language_code=language,
                rule_key=rule_key,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="deliveryruleview",
                    default="ux:deliveryrules",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_hide_mute_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        self._remember_screen_back_callback(user.telegram_user_id, screen="hide_strategy", callback_data="ux:hidemute")
        self._remember_screen_back_callback(user.telegram_user_id, screen="hide_timeframe", callback_data="ux:hidemute")
        self._remember_screen_back_callback(user.telegram_user_id, screen="hide_repeats", callback_data="ux:hidemute")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_hide_mute_message(language_code=language, personalization=personalization),
            reply_markup=build_hide_mute_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="hidemute",
                    default="main:settings",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_hide_strategy_view(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        hidden = personalization.get("hidden") if isinstance(personalization.get("hidden"), dict) else {}
        hidden_strategies = [self._strategy_label(item, language_code=language) for item in hidden.get("strategies", [])]
        summary = ", ".join(hidden_strategies) if hidden_strategies else ("None" if language == "en" else "Нет")
        text = (
            "<b>🚫 Hide Strategy</b>\n\nChoose the strategies you want to suppress.\n\n"
            f"Hidden now: <b>{escape_html(summary)}</b>"
            if language == "en"
            else "<b>🚫 Скрыть стратегию</b>\n\nВыбери стратегии, которые нужно приглушить.\n\n"
            f"Скрыто сейчас: <b>{escape_html(summary)}</b>"
        )
        strategy_keys = list(self._visible_strategy_keys(settings))
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_hide_strategy_keyboard(
                language_code=language,
                strategy_keys=strategy_keys,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="hide_strategy",
                    default="ux:hidemute",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_hide_timeframe_view(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        hidden = personalization.get("hidden") if isinstance(personalization.get("hidden"), dict) else {}
        hidden_timeframes = ", ".join(hidden.get("timeframes", [])) or ("None" if language == "en" else "Нет")
        text = (
            "<b>🚫 Hide Timeframe</b>\n\nMute timeframes that do not fit your rhythm.\n\n"
            f"Hidden now: <b>{escape_html(hidden_timeframes)}</b>"
            if language == "en"
            else "<b>🚫 Скрыть таймфрейм</b>\n\nОтключи ТФ, которые не подходят под твой ритм.\n\n"
            f"Скрыто сейчас: <b>{escape_html(hidden_timeframes)}</b>"
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_hide_timeframe_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="hide_timeframe",
                    default="ux:hidemute",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_repeat_mute_view(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        personalization = self._personalization_state(settings)
        hidden = personalization.get("hidden") if isinstance(personalization.get("hidden"), dict) else {}
        repeat_hours = int(hidden.get("mute_repeats_hours", 0) or 0)
        text = (
            "<b>🔁 Repeat Cooldown</b>\n\nLimit how often the same asset can reappear.\n\n"
            f"Current cooldown: <b>{repeat_hours}h</b>"
            if language == "en"
            else "<b>🔁 Кулдаун повторов</b>\n\nОграничь, как часто один и тот же актив может появляться снова.\n\n"
            f"Текущий кулдаун: <b>{repeat_hours}h</b>"
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_repeat_mute_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="hide_repeats",
                    default="ux:hidemute",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_style_hub(self, user: PrivateBotUserRecord, *, chat_id: str | None = None, edit_message_id: int | None = None) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        profile = await self.repository.get_user_style_profile(user.telegram_user_id, bot_kind=self.bot_kind)
        preferences = normalize_style_preferences(profile.preferences if profile is not None else default_style_preferences())
        title, summary = build_style_title_summary(preferences, language_code=language)
        self._remember_screen_back_callback(user.telegram_user_id, screen="style_dimension", callback_data="ux:stylehub")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_style_profile_message(language_code=language, profile=profile, title=title, summary=summary),
            reply_markup=build_style_profile_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="stylehub",
                    default="main:settings",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    def _style_dimension_options(
        self,
        *,
        dimension: str,
        language_code: str,
    ) -> tuple[str, list[tuple[str, str]]]:
        is_ru = language_code == "ru"
        mapping: dict[str, tuple[str, list[tuple[str, str]]]] = {
            "speed_preference": (
                "Speed" if not is_ru else "Скорость",
                [("fast", "⚡ Fast" if not is_ru else "⚡ Быстро"), ("balanced", "⚖️ Balanced" if not is_ru else "⚖️ Баланс"), ("patient", "🧘 Patient" if not is_ru else "🧘 Терпеливо")],
            ),
            "noise_tolerance": (
                "Noise" if not is_ru else "Шум",
                [("low", "🔕 Low" if not is_ru else "🔕 Низкий"), ("balanced", "⚖️ Balanced" if not is_ru else "⚖️ Баланс"), ("high", "⚡ High" if not is_ru else "⚡ Высокий")],
            ),
            "market_preference": (
                "Market" if not is_ru else "Рынок",
                [("majors", "🪙 Majors" if not is_ru else "🪙 Мейджоры"), ("broad_crypto", "🌐 Broad" if not is_ru else "🌐 Широко"), ("gold", "🥇 Gold" if not is_ru else "🥇 Золото"), ("mixed", "🔀 Mixed" if not is_ru else "🔀 Смешанный")],
            ),
            "signal_style": (
                "Signal Style" if not is_ru else "Тип сигналов",
                [("breakout", "💥 Breakout" if not is_ru else "💥 Пробои"), ("pullback", "🌊 Pullback" if not is_ru else "🌊 Откаты"), ("mean_reversion", "↔️ Mean Rev" if not is_ru else "↔️ Возврат"), ("mixed", "🔀 Mixed" if not is_ru else "🔀 Смешанный")],
            ),
            "confirmation_style": (
                "Confirmation" if not is_ru else "Подтверждение",
                [("early", "⚡ Early" if not is_ru else "⚡ Рано"), ("balanced", "⚖️ Balanced" if not is_ru else "⚖️ Баланс"), ("confirmed", "✅ Confirmed" if not is_ru else "✅ Подтверждённо")],
            ),
            "interaction_mode": (
                "Display" if not is_ru else "Режим",
                [("simple", "🖥 Simple" if not is_ru else "🖥 Просто"), ("pro", "🖥 Pro" if not is_ru else "🖥 Pro")],
            ),
            "trading_rhythm": (
                "Rhythm" if not is_ru else "Ритм",
                [("asia", "🌏 Asia" if not is_ru else "🌏 Азия"), ("london", "🇬🇧 London"), ("new_york", "🇺🇸 New York"), ("all_day", "🕓 All Day" if not is_ru else "🕓 Весь день")],
            ),
            "delivery_preference": (
                "Delivery" if not is_ru else "Доставка",
                [("instant", "📬 Instant" if not is_ru else "📬 Сразу"), ("digest", "🗂 Digest" if not is_ru else "🗂 Дайджест"), ("mixed", "🔀 Mixed" if not is_ru else "🔀 Смешанно")],
            ),
            "followup_preference": (
                "Follow-Ups" if not is_ru else "Фоллоу-апы",
                [("yes", "🔄 Yes" if not is_ru else "🔄 Да"), ("important_only", "⭐ Important" if not is_ru else "⭐ Важные"), ("no", "🚫 Off" if not is_ru else "🚫 Нет")],
            ),
            "risk_style": (
                "Risk" if not is_ru else "Риск",
                [("conservative", "🛡 Conservative" if not is_ru else "🛡 Консервативно"), ("balanced", "⚖️ Balanced" if not is_ru else "⚖️ Баланс"), ("aggressive", "🚀 Aggressive" if not is_ru else "🚀 Агрессивно")],
            ),
        }
        return mapping.get(dimension, ("Style" if not is_ru else "Стиль", [("balanced", "⚖️ Balanced" if not is_ru else "⚖️ Баланс")]))

    async def _send_style_dimension_view(
        self,
        user: PrivateBotUserRecord,
        *,
        dimension: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        profile = await self.repository.get_user_style_profile(user.telegram_user_id, bot_kind=self.bot_kind)
        preferences = normalize_style_preferences(profile.preferences if profile is not None else default_style_preferences())
        if dimension not in preferences:
            await self._send_style_hub(user, chat_id=chat_id, edit_message_id=edit_message_id)
            return
        dimension_label, options = self._style_dimension_options(dimension=dimension, language_code=language)
        current_label = next((label for value, label in options if value == preferences[dimension]), preferences[dimension].replace("_", " ").title())
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_style_dimension_message(
                language_code=language,
                dimension_label=dimension_label,
                current_value=current_label,
            ),
            reply_markup=build_style_dimension_keyboard(
                language_code=language,
                dimension=dimension,
                options=options,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="style_dimension",
                    default="ux:stylehub",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_personal_summary(
        self,
        user: PrivateBotUserRecord,
        *,
        period_label: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        summary = await self._build_personal_summary_data(user, period_label=period_label)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_personal_summary_message(language_code=language, summary=summary),
            reply_markup=build_personal_summary_keyboard(
                language_code=language,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="personal_summary",
                    default="results:hub",
                ),
            ),
            edit_message_id=edit_message_id,
        )

    def _period_window_start(self, *, now: datetime, period_label: str) -> datetime:
        normalized = str(period_label or "daily").strip().lower()
        if normalized in {"weekly", "7d"}:
            return now - timedelta(days=7)
        if normalized == "30d":
            return now - timedelta(days=30)
        if normalized == "all_time":
            return now - timedelta(days=3650)
        return now - timedelta(days=1)

    def _top_count_label(self, counts: dict[str, int]) -> str | None:
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    def _average_rr_for_lifecycle(self, records: list[SignalLifecycleRecord]) -> float | None:
        values: list[float] = []
        for record in records:
            if record.invalidation_price is None or record.tp_price_primary is None:
                continue
            risk = abs(record.entry_price - float(record.invalidation_price))
            reward = abs(float(record.tp_price_primary) - record.entry_price)
            if risk > 0:
                values.append(reward / risk)
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    def _drawdown_profile_for_lifecycle(self, records: list[SignalLifecycleRecord]) -> str | None:
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

    async def _collect_user_period_flow(
        self,
        user: PrivateBotUserRecord,
        *,
        start: datetime,
        end: datetime,
        include_disabled_strategy_matches: bool = False,
    ) -> dict[str, object]:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        enabled_keys = set(self._normalize_enabled_strategy_keys(self._enabled_strategy_keys(shell_settings)))
        alerts = await self.repository.list_recent_alerts(
            start=start,
            end=end,
            min_score=0,
            min_quote_volume=0.0,
            limit=5000,
        )
        delivered_records = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            since=start,
            limit=5000,
        )
        delivered_alert_ids = sorted(
            {
                int(record.alert_id)
                for record in delivered_records
                if record.message_kind == "alert"
                and record.alert_id is not None
                and bool(record.metadata.get("sent", True))
            }
        )
        tracked_records = await self.repository.list_recent_tracked_signals(since=start, limit=6000)
        tracked_by_alert_id: dict[int, SignalLifecycleRecord] = {}
        for record in tracked_records:
            if record.alert_id is None:
                continue
            tracked_by_alert_id.setdefault(int(record.alert_id), record)

        alerts_by_id = {int(alert.id): alert for alert in alerts}
        missing_delivered_ids = [alert_id for alert_id in delivered_alert_ids if alert_id not in alerts_by_id]
        if missing_delivered_ids:
            for alert in await self.repository.list_alerts_by_ids(missing_delivered_ids):
                alerts_by_id[int(alert.id)] = alert

        global_favorites = set(await self._global_favorite_symbols(user.telegram_user_id))
        strategy_settings_cache: dict[str, UserSettingsRecord] = {}
        strategy_watchlists: dict[str, set[str]] = {}
        strategy_favorites: dict[str, set[str]] = {}
        matched_by_strategy: dict[str, list[AlertRecord]] = {}
        disabled_by_strategy: dict[str, list[AlertRecord]] = {}
        matched_alert_ids: set[int] = set()
        matched_symbols: dict[str, int] = {}
        matched_strategies: dict[str, int] = {}
        strong_matches = 0
        watchlist_matches = 0
        gold_matches = 0
        filtered_out = 0
        filtered_reasons: dict[str, int] = {}

        for alert in alerts:
            strategy_key = self._alert_strategy_key(alert)
            if strategy_key not in strategy_settings_cache:
                strategy_settings_cache[strategy_key] = await self._load_strategy_settings(
                    user.telegram_user_id,
                    shell_settings=shell_settings,
                    strategy_key=strategy_key,
                )
                strategy_watchlists[strategy_key] = set(
                    await self._watchlist_symbols_for_strategy(
                        user.telegram_user_id,
                        strategy_key=strategy_key,
                        settings=strategy_settings_cache[strategy_key],
                    )
                )
                strategy_favorites[strategy_key] = set(global_favorites).union(
                    await self._favorite_symbols_for_strategy(user.telegram_user_id, strategy_key)
                )
            effective_settings = strategy_settings_cache[strategy_key]
            watchlist_symbols = strategy_watchlists[strategy_key]
            favorite_symbols = strategy_favorites[strategy_key]
            matches_filters, reason = self._alert_record_matches_user_settings(
                alert,
                effective_settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                strong_only=False,
            )
            if strategy_key in enabled_keys:
                if not matches_filters:
                    filtered_out += 1
                    filtered_reasons[reason] = filtered_reasons.get(reason, 0) + 1
                    continue
                matched_by_strategy.setdefault(strategy_key, []).append(alert)
                matched_alert_ids.add(int(alert.id))
                symbol = normalize_symbol(alert.symbol)
                matched_symbols[symbol] = matched_symbols.get(symbol, 0) + 1
                matched_strategies[strategy_key] = matched_strategies.get(strategy_key, 0) + 1
                if alert.score >= 88:
                    strong_matches += 1
                if symbol in watchlist_symbols or symbol in favorite_symbols:
                    watchlist_matches += 1
                if strategy_key in GOLD_SUBSTRATEGY_KEY_SET or strategy_key == GOLD_MASTER_STRATEGY_KEY:
                    gold_matches += 1
                continue
            if include_disabled_strategy_matches and matches_filters:
                disabled_by_strategy.setdefault(strategy_key, []).append(alert)

        delivered_alerts = [alerts_by_id[alert_id] for alert_id in delivered_alert_ids if alert_id in alerts_by_id]
        delivered_by_strategy: dict[str, list[AlertRecord]] = {}
        delivered_symbols: dict[str, int] = {}
        delivered_strategies: dict[str, int] = {}
        delivered_watchlist_matches = 0
        delivered_gold_matches = 0
        strong_delivered = 0
        for alert in delivered_alerts:
            strategy_key = self._alert_strategy_key(alert)
            delivered_by_strategy.setdefault(strategy_key, []).append(alert)
            symbol = normalize_symbol(alert.symbol)
            delivered_symbols[symbol] = delivered_symbols.get(symbol, 0) + 1
            delivered_strategies[strategy_key] = delivered_strategies.get(strategy_key, 0) + 1
            if alert.score >= 88:
                strong_delivered += 1
            watchlist_symbols = strategy_watchlists.get(strategy_key, set())
            favorite_symbols = strategy_favorites.get(strategy_key, global_favorites)
            if symbol in watchlist_symbols or symbol in favorite_symbols:
                delivered_watchlist_matches += 1
            if strategy_key in GOLD_SUBSTRATEGY_KEY_SET or strategy_key == GOLD_MASTER_STRATEGY_KEY:
                delivered_gold_matches += 1

        return {
            "shell_settings": shell_settings,
            "matched_by_strategy": matched_by_strategy,
            "disabled_by_strategy": disabled_by_strategy,
            "matched_alert_ids": matched_alert_ids,
            "matched_symbols": matched_symbols,
            "matched_strategies": matched_strategies,
            "strong_matches": strong_matches,
            "watchlist_matches": watchlist_matches,
            "gold_matches": gold_matches,
            "filtered_out": filtered_out,
            "filtered_reasons": filtered_reasons,
            "delivered_alert_ids": set(delivered_alert_ids),
            "delivered_alerts": delivered_alerts,
            "delivered_by_strategy": delivered_by_strategy,
            "delivered_symbols": delivered_symbols,
            "delivered_strategies": delivered_strategies,
            "strong_delivered": strong_delivered,
            "delivered_watchlist_matches": delivered_watchlist_matches,
            "delivered_gold_matches": delivered_gold_matches,
            "tracked_by_alert_id": tracked_by_alert_id,
        }

    async def _build_user_admin_strategy_stats(
        self,
        user: PrivateBotUserRecord,
        *,
        period_type: str,
    ) -> list[StrategyStatsSnapshotRecord]:
        now = utc_now()
        start = self._period_window_start(now=now, period_label=period_type)
        flow = await self._collect_user_period_flow(
            user,
            start=start,
            end=now + timedelta(minutes=1),
            include_disabled_strategy_matches=True,
        )
        matched_by_strategy = flow["matched_by_strategy"]
        disabled_by_strategy = flow["disabled_by_strategy"]
        delivered_alert_ids = flow["delivered_alert_ids"]
        tracked_by_alert_id = flow["tracked_by_alert_id"]
        assert isinstance(matched_by_strategy, dict)
        assert isinstance(disabled_by_strategy, dict)
        assert isinstance(delivered_alert_ids, set)
        assert isinstance(tracked_by_alert_id, dict)

        relevant_strategy_keys = {
            str(strategy_key)
            for strategy_key in set(matched_by_strategy.keys()) | set(disabled_by_strategy.keys())
            if str(strategy_key) in self.STRATEGY_KEYS
        }
        if start.year <= 1975:
            window_days = 1.0
        else:
            window_days = max((now - start).total_seconds() / 86400.0, 1.0)

        snapshots: list[StrategyStatsSnapshotRecord] = []
        for strategy_key in relevant_strategy_keys:
            relevant_alerts = [
                *list(matched_by_strategy.get(strategy_key, [])),
                *list(disabled_by_strategy.get(strategy_key, [])),
            ]
            if not relevant_alerts:
                continue
            relevant_alert_ids = {int(alert.id) for alert in relevant_alerts}
            delivered_alerts = [alert for alert in relevant_alerts if int(alert.id) in delivered_alert_ids]
            lifecycle_records = [
                tracked_by_alert_id[int(alert.id)]
                for alert in relevant_alerts
                if int(alert.id) in tracked_by_alert_id
            ]
            delivered_lifecycle_records = [
                tracked_by_alert_id[int(alert.id)]
                for alert in delivered_alerts
                if int(alert.id) in tracked_by_alert_id
            ]
            wins = [record for record in lifecycle_records if record.result_type == "win"]
            losses = [record for record in lifecycle_records if record.result_type == "loss"]
            ambiguous = [record for record in lifecycle_records if record.ambiguous_resolution]
            expired = [record for record in lifecycle_records if record.result_type == "neutral" and not record.ambiguous_resolution]
            sent_wins = [record for record in delivered_lifecycle_records if record.result_type == "win"]
            sent_losses = [record for record in delivered_lifecycle_records if record.result_type == "loss"]
            sent_ambiguous = [record for record in delivered_lifecycle_records if record.ambiguous_resolution]
            sent_expired = [
                record
                for record in delivered_lifecycle_records
                if record.result_type == "neutral" and not record.ambiguous_resolution
            ]
            win_tf_counts: dict[str, int] = {}
            win_asset_counts: dict[str, int] = {}
            win_regime_counts: dict[str, int] = {}
            for record in wins:
                win_tf_counts[record.timeframe] = win_tf_counts.get(record.timeframe, 0) + 1
                asset_tag = str(record.metadata.get("asset_cluster_tag") or ("gold" if record.is_gold else "crypto"))
                win_asset_counts[asset_tag] = win_asset_counts.get(asset_tag, 0) + 1
                regime = str(record.market_regime_tag or "Mixed")
                win_regime_counts[regime] = win_regime_counts.get(regime, 0) + 1
            sent_win_tf_counts: dict[str, int] = {}
            sent_win_asset_counts: dict[str, int] = {}
            sent_win_regime_counts: dict[str, int] = {}
            for record in sent_wins:
                sent_win_tf_counts[record.timeframe] = sent_win_tf_counts.get(record.timeframe, 0) + 1
                asset_tag = str(record.metadata.get("asset_cluster_tag") or ("gold" if record.is_gold else "crypto"))
                sent_win_asset_counts[asset_tag] = sent_win_asset_counts.get(asset_tag, 0) + 1
                regime = str(record.market_regime_tag or "Mixed")
                sent_win_regime_counts[regime] = sent_win_regime_counts.get(regime, 0) + 1
            snapshots.append(
                StrategyStatsSnapshotRecord(
                    snapshot_id=0,
                    strategy_code=strategy_key,
                    timeframe_bucket=None,
                    market_regime_bucket=None,
                    asset_cluster_bucket=None,
                    period_type=period_type,
                    total_signals=len(relevant_alert_ids),
                    wins=len(wins),
                    losses=len(losses),
                    expired_neutral=len(expired),
                    invalidated_count=sum(1 for record in lifecycle_records if str(record.status) == "invalidated"),
                    avg_rr=self._average_rr_for_lifecycle(lifecycle_records),
                    avg_time_to_win_minutes=None,
                    avg_time_to_invalidation_minutes=None,
                    signals_per_day=round(len(relevant_alert_ids) / max(window_days, 1.0), 2),
                    best_tf=self._top_count_label(win_tf_counts),
                    best_assets=self._top_count_label(win_asset_counts),
                    best_regime=self._top_count_label(win_regime_counts),
                    drawdown_profile=self._drawdown_profile_for_lifecycle(lifecycle_records),
                    calculated_at=now,
                    delivered_count=len(delivered_alerts),
                    suppressed_count=len(disabled_by_strategy.get(strategy_key, [])),
                    ambiguous_count=len(ambiguous),
                    sent_wins=len(sent_wins),
                    sent_losses=len(sent_losses),
                    sent_expired_neutral=len(sent_expired),
                    sent_ambiguous_count=len(sent_ambiguous),
                    sent_avg_rr=self._average_rr_for_lifecycle(delivered_lifecycle_records),
                    sent_signals_per_day=round(len(delivered_alerts) / max(window_days, 1.0), 2),
                    sent_best_tf=self._top_count_label(sent_win_tf_counts),
                    sent_best_assets=self._top_count_label(sent_win_asset_counts),
                    sent_best_regime=self._top_count_label(sent_win_regime_counts),
                )
            )
        return snapshots

    async def _send_referral_screen(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        self._remember_screen_back_callback(
            user.telegram_user_id,
            screen="referral",
            callback_data="ux:menu",
        )
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="referral",
            default="ux:menu",
        )
        if back_callback_data == "ux:menu":
            back_callback_data = None
        dashboard = await self.referral_service.get_dashboard(user.telegram_user_id)
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.referral_service.format_referral_message(
                dashboard,
                language_code=language,
            ),
            reply_markup=build_referral_inline_keyboard(
                language_code=language,
                referral_link=dashboard.referral_link,
                share_url=dashboard.share_url,
                back_callback_data=back_callback_data,
                home_callback_data="ux:menu",
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_strategy_hub(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user_id,
            chat_id=chat_id or str(user_id),
        )
        active_strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        strategy_enabled = active_strategy_key in self._enabled_strategy_keys(settings)
        strategy_callback = self._strategy_hub_callback_data(settings)
        self._remember_screen_back_callback(user_id, screen="setup", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="analyze", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="goldhub", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="deliveryhub", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="watchhub", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="statshub", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="aihub", callback_data=strategy_callback)
        self._remember_screen_back_callback(user_id, screen="settingshub", callback_data=strategy_callback)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=self.message_render_service.render_strategy_hub(
                self.compare_service.get_profile(active_strategy_key, language_code=language),
                enabled=strategy_enabled,
                language_code=language,
            ),
            reply_markup=build_product_strategy_hub_keyboard(
                strategy_key=active_strategy_key,
                strategy_enabled=strategy_enabled,
                include_gold_shortcut=active_strategy_key == "gold",
                language_code=language,
            ),
            edit_message_id=edit_message_id,
        )

    async def _activate_strategy_context(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        strategy_key: str,
    ) -> UserSettingsRecord:
        shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
        assert shell_settings is not None
        await self._ensure_premium_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        return await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            active_strategy_key=strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at,
            onboarding_completed_at=current_settings.onboarding_completed_at,
            current_context=f"strategy_{strategy_key}",
            current_strategy_context=strategy_key,
        )

    async def _send_strategy_guide(
        self,
        user_id: int,
        *,
        chat_id: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        active_strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        target_chat_id = chat_id or str(user_id)
        await self._cleanup_strategy_guide_message(
            telegram_user_id=user_id,
            chat_id=target_chat_id,
        )
        result = await self._send_chat_message(
            chat_id=target_chat_id,
            text=self._strategy_guide_text(active_strategy_key, language_code=language),
            parse_mode="HTML",
            reply_markup=build_strategy_guide_inline_keyboard(
                language_code=language,
                home_callback_data="ux:menu",
            ),
            cleanup=True,
        )
        message_id = result.get("message_id")
        if isinstance(message_id, int) and message_id > 0:
            self._strategy_guide_message_ids[user_id] = message_id

    async def _send_section_hub(
        self,
        user_id: int,
        *,
        section: str,
        origin: str = "menu",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user_id)
        settings, origin = await self._settings_for_hub_section(
            user_id,
            section=section,
            origin=origin,
            shell_settings=shell_settings,
        )
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user_id,
            chat_id=chat_id or str(user_id),
        )
        active_strategy_key = self._resolved_active_strategy_key(settings)
        origin = self._remember_hub_origin(user_id, section=section, origin=origin)
        screen_name = {
            "signals": "signalshub",
            "watchlists": "watchhub",
            "delivery": "deliveryhub",
            "stats": "statshub",
            "ai": "aihub",
            "settings": "settingshub",
        }.get(section, "signalshub")
        back_callback_data = self._hub_back_callback_data(settings, origin=origin)
        self._remember_screen_back_callback(user_id, screen=screen_name, callback_data=back_callback_data)
        if section == "signals":
            self._remember_screen_back_callback(
                user_id,
                screen="analyze",
                callback_data=self._hub_callback_data("signalshub", origin=origin),
            )
        elif section == "watchlists":
            hub_callback_data = self._hub_callback_data("watchhub", origin=origin)
            self._remember_screen_back_callback(user_id, screen="watchlist", callback_data=hub_callback_data)
            self._remember_screen_back_callback(user_id, screen="themes", callback_data=hub_callback_data)
            self._remember_screen_back_callback(user_id, screen="setup", callback_data=hub_callback_data)
        elif section == "settings":
            settings_callback_data = self._hub_callback_data("settingshub", origin=origin)
            self._remember_screen_back_callback(user_id, screen="setup", callback_data=settings_callback_data)
            self._remember_screen_back_callback(user_id, screen="watchlist", callback_data=settings_callback_data)
            self._remember_screen_back_callback(user_id, screen="language_picker", callback_data=settings_callback_data)
        title, body = self._section_hub_copy(
            section=section,
            settings=settings,
            origin=origin,
            language_code=language,
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_section_hub(title, body),
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section=section,
                include_gold_button=active_strategy_key == "gold",
                premium=self.bot_kind == "premium",
                direct_delivery_enabled=settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=settings.followup_delivery_enabled,
                gold_alerts_enabled=settings.gold_alerts_enabled,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_settings_center(
        self,
        user: PrivateBotUserRecord,
        *,
        origin: str = "menu",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id) if self.bot_kind == "premium" else await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        origin = self._remember_hub_origin(user.telegram_user_id, section="settings", origin=origin)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="settingshub",
            default=self._hub_back_callback_data(settings, origin=origin),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="language_picker", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="workspacehub", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="filtershub", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryrules", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="noisehub", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="scorehub", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="sessionhub", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="hidemute", callback_data="ux:settingshub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="stylehub", callback_data="ux:settingshub")
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=format_settings_center_message(
                settings=settings,
                language_code=language,
                workspace_label=self._workspace_label(settings.active_workspace, language_code=language),
                has_saved_workspace=self._saved_workspace_available(settings),
            ),
            reply_markup=build_personalized_settings_keyboard(
                language_code=language,
                display_mode=settings.display_mode,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_workspace_center(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id) if self.bot_kind == "premium" else await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="workspacehub",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=settings,
                screen="workspacehub",
                section="settings",
            ),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="setup", callback_data="ux:workspacehub")
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=format_workspace_center_message(
                settings=settings,
                language_code=language,
                workspace_label=self._workspace_label(settings.active_workspace, language_code=language),
                has_saved_workspace=self._saved_workspace_available(settings),
            ),
            reply_markup=build_workspace_center_keyboard(
                language_code=language,
                active_workspace=settings.active_workspace,
                has_saved_workspace=self._saved_workspace_available(settings),
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    def _workspace_snapshot(self, settings: UserSettingsRecord) -> dict[str, object]:
        return {
            "enabled_strategy_keys": list(self._enabled_strategy_keys(settings)),
            "active_strategy_key": self._resolved_active_strategy_key(settings),
            "signal_profile": settings.signal_profile,
            "base_signal_profile": settings.base_signal_profile,
            "preferred_min_score": settings.preferred_min_score,
            "min_quote_volume": settings.min_quote_volume,
            "direction_filter": settings.direction_filter,
            "watchlist_only": settings.watchlist_only,
            "delivery_mode": settings.delivery_mode,
            "active_watchlist_theme": settings.active_watchlist_theme,
            "display_mode": settings.display_mode,
        }

    def _workspace_preset(self, workspace_key: str) -> dict[str, object] | None:
        presets: dict[str, dict[str, object]] = {
            "scalp": {
                "enabled_strategy_keys": ("breakout", "vwap", "false_breakout", "rsi"),
                "active_strategy_key": "vwap",
                "signal_profile": "aggressive",
                "base_signal_profile": "aggressive",
                "preferred_min_score": 68,
                "delivery_mode": "instant",
                "watchlist_only": False,
                "active_watchlist_theme": "majors",
            },
            "intraday": {
                "enabled_strategy_keys": ("breakout", "trend_pullback", "vwap", "false_breakout"),
                "active_strategy_key": "breakout",
                "signal_profile": "balanced",
                "base_signal_profile": "balanced",
                "preferred_min_score": 70,
                "delivery_mode": "instant",
                "watchlist_only": False,
                "active_watchlist_theme": "majors",
            },
            "swing": {
                "enabled_strategy_keys": ("trend_pullback", "breakout", "bollinger"),
                "active_strategy_key": "trend_pullback",
                "signal_profile": "conservative",
                "base_signal_profile": "conservative",
                "preferred_min_score": 72,
                "delivery_mode": "digest",
                "watchlist_only": False,
                "active_watchlist_theme": "majors",
            },
            "gold_focus": {
                "enabled_strategy_keys": ("gold", *GOLD_SUBSTRATEGY_KEYS),
                "active_strategy_key": "gold",
                "signal_profile": "balanced",
                "base_signal_profile": "balanced",
                "preferred_min_score": 70,
                "delivery_mode": "instant",
                "watchlist_only": False,
                "active_watchlist_theme": "gold",
            },
            "low_noise": {
                "enabled_strategy_keys": ("trend_pullback", "false_breakout", "bollinger"),
                "active_strategy_key": "trend_pullback",
                "signal_profile": "conservative",
                "base_signal_profile": "conservative",
                "preferred_min_score": 76,
                "delivery_mode": "digest",
                "watchlist_only": False,
                "active_watchlist_theme": "majors",
            },
            "aggressive": {
                "enabled_strategy_keys": ("breakout", "rsi", "vwap", "false_breakout"),
                "active_strategy_key": "breakout",
                "signal_profile": "aggressive",
                "base_signal_profile": "aggressive",
                "preferred_min_score": 65,
                "delivery_mode": "instant",
                "watchlist_only": False,
                "active_watchlist_theme": "custom",
            },
        }
        return presets.get(str(workspace_key or "").strip().lower())

    async def _apply_display_mode(
        self,
        user: PrivateBotUserRecord,
        *,
        mode: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        normalized_mode = "simple" if str(mode or "").strip().lower() == "simple" else "pro"
        await self._save_user_settings(
            user=user,
            current_settings=settings,
            display_mode=normalized_mode,
            current_context="menu",
        )
        await self._send_menu_hub(
            user.telegram_user_id,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _save_current_workspace_snapshot(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        payload = {
            "saved_at": utc_now().isoformat(),
            "snapshot": self._workspace_snapshot(settings),
        }
        await self._save_user_settings(
            user=user,
            current_settings=settings,
            saved_workspace_payload=payload,
            current_context="settingshub",
        )
        await self._send_workspace_center(user, chat_id=chat_id, edit_message_id=edit_message_id)

    async def _apply_workspace_profile(
        self,
        user: PrivateBotUserRecord,
        *,
        workspace_key: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id) if self.bot_kind == "premium" else await self._ensure_user_settings(user.telegram_user_id)
        normalized_workspace = str(workspace_key or "").strip().lower()
        if normalized_workspace == "saved":
            payload = shell_settings.saved_workspace_payload if isinstance(shell_settings.saved_workspace_payload, dict) else {}
            snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
            if not isinstance(snapshot, dict):
                await self._send_workspace_center(user, chat_id=chat_id, edit_message_id=edit_message_id)
                return
            config = snapshot
        else:
            config = self._workspace_preset(normalized_workspace)
            if config is None:
                await self._send_workspace_center(user, chat_id=chat_id, edit_message_id=edit_message_id)
                return
        target_strategy_key = str(config.get("active_strategy_key") or self._resolved_active_strategy_key(shell_settings) or "rsi")
        current_settings = await self._load_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=target_strategy_key,
        ) if self.bot_kind == "premium" else shell_settings
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            enabled_strategy_keys=tuple(config.get("enabled_strategy_keys") or self._enabled_strategy_keys(shell_settings)),
            active_strategy_key=target_strategy_key,
            signal_profile=str(config.get("signal_profile") or current_settings.signal_profile),
            base_signal_profile=str(config.get("base_signal_profile") or current_settings.base_signal_profile),
            preferred_min_score=config.get("preferred_min_score"),
            min_quote_volume=config.get("min_quote_volume"),
            direction_filter=str(config.get("direction_filter") or current_settings.direction_filter),
            watchlist_only=bool(config.get("watchlist_only", current_settings.watchlist_only)),
            delivery_mode=str(config.get("delivery_mode") or current_settings.delivery_mode),
            delivery_mode_changed_at=utc_now(),
            active_watchlist_theme=str(config.get("active_watchlist_theme") or current_settings.active_watchlist_theme),
            display_mode=str(config.get("display_mode") or shell_settings.display_mode),
            active_workspace=normalized_workspace,
            current_context="settingshub",
        )
        await self._send_workspace_center(user, chat_id=chat_id, edit_message_id=edit_message_id)

    async def _global_favorite_symbols(self, telegram_user_id: int) -> list[str]:
        entries = await self.repository.list_user_watchlist(telegram_user_id, bot_kind=self.bot_kind)
        return [entry.symbol for entry in entries]

    def _normalized_setup_name(self, name: str | None, *, fallback: str = "Setup") -> str:
        cleaned = re.sub(r"\s+", " ", str(name or "").strip())
        return cleaned[:48] or fallback

    async def _ensure_unique_setup_name(
        self,
        telegram_user_id: int,
        *,
        preferred_name: str,
        exclude_setup_id: int | None = None,
    ) -> str:
        setups = await self.repository.list_user_saved_setups(telegram_user_id, bot_kind=self.bot_kind)
        existing = {
            setup.name.casefold()
            for setup in setups
            if exclude_setup_id is None or setup.id != exclude_setup_id
        }
        base = self._normalized_setup_name(preferred_name)
        if base.casefold() not in existing:
            return base
        suffix = 2
        while True:
            candidate = f"{base} {suffix}"
            if candidate.casefold() not in existing:
                return candidate
            suffix += 1

    def _normalize_enabled_strategy_keys(self, raw_keys) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in raw_keys or ():
            key = str(item or "").strip().lower()
            if key in self.STRATEGY_KEYS and key not in normalized:
                normalized.append(key)
        if any(self._is_gold_substrategy(key) for key in normalized) and GOLD_MASTER_STRATEGY_KEY not in normalized:
            normalized.insert(0, GOLD_MASTER_STRATEGY_KEY)
        return tuple(normalized)

    async def _strategy_setup_snapshot(
        self,
        telegram_user_id: int,
        *,
        shell_settings: UserSettingsRecord,
        strategy_key: str,
    ) -> dict[str, object]:
        strategy_settings = await self._load_strategy_settings(
            telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=strategy_key,
        )
        return {
            "direct_signal_delivery_enabled": strategy_settings.direct_signal_delivery_enabled,
            "followup_delivery_enabled": strategy_settings.followup_delivery_enabled,
            "signal_profile": strategy_settings.signal_profile,
            "base_signal_profile": strategy_settings.base_signal_profile,
            "preferred_min_score": strategy_settings.preferred_min_score,
            "min_quote_volume": strategy_settings.min_quote_volume,
            "rsi_oversold": strategy_settings.rsi_oversold,
            "rsi_overbought": strategy_settings.rsi_overbought,
            "direction_filter": strategy_settings.direction_filter,
            "watchlist_only": strategy_settings.watchlist_only,
            "delivery_mode": strategy_settings.delivery_mode,
            "quiet_hours_start_minute": strategy_settings.quiet_hours_start_minute,
            "quiet_hours_end_minute": strategy_settings.quiet_hours_end_minute,
            "active_watchlist_theme": strategy_settings.active_watchlist_theme,
            "active_custom_theme_name": strategy_settings.active_custom_theme_name,
            "strategy_preferences": self._strategy_preferences(strategy_settings, strategy_key=strategy_key),
            "favorite_symbols": await self._favorite_symbols_for_strategy(telegram_user_id, strategy_key),
        }

    async def _build_current_setup_payload(self, telegram_user_id: int) -> dict[str, object]:
        shell_settings = await self._ensure_shell_settings(telegram_user_id)
        enabled_strategy_keys = self._normalize_enabled_strategy_keys(self._enabled_strategy_keys(shell_settings))
        strategies: dict[str, object] = {}
        for strategy_key in enabled_strategy_keys:
            strategies[strategy_key] = await self._strategy_setup_snapshot(
                telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
        asset_scope_type, asset_scope_payload = await self._current_asset_scope_state(
            telegram_user_id,
            shell_settings=shell_settings,
        )
        personalization = self._personalization_state(shell_settings)
        personalization["asset_scope_type"] = asset_scope_type
        personalization["asset_scope_payload"] = asset_scope_payload
        return {
            "shell": {
                "enabled_strategy_keys": list(enabled_strategy_keys),
                "active_strategy_key": self._resolved_active_strategy_key(shell_settings),
                "gold_alerts_enabled": shell_settings.gold_alerts_enabled,
                "display_mode": shell_settings.display_mode,
                "active_workspace": shell_settings.active_workspace,
                "personalization": personalization,
                "delivery_rules": self._delivery_rules_state(shell_settings),
                "global_favorites": await self._global_favorite_symbols(telegram_user_id),
                "asset_scope_type": asset_scope_type,
                "asset_scope_payload": asset_scope_payload,
            },
            "strategies": strategies,
        }

    async def _save_setup_snapshot(
        self,
        telegram_user_id: int,
        *,
        name: str,
        is_pinned: bool = False,
        is_default: bool = False,
    ) -> UserSavedSetupRecord:
        payload = await self._build_current_setup_payload(telegram_user_id)
        unique_name = await self._ensure_unique_setup_name(telegram_user_id, preferred_name=name)
        return await self.repository.create_user_saved_setup(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            name=unique_name,
            payload=payload,
            is_default=is_default,
            is_pinned=is_pinned,
        )

    async def _apply_saved_setup_payload(
        self,
        user: PrivateBotUserRecord,
        *,
        setup: UserSavedSetupRecord,
    ) -> UserSettingsRecord:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        payload = setup.payload if isinstance(setup.payload, dict) else {}
        shell_payload = payload.get("shell") if isinstance(payload.get("shell"), dict) else payload
        strategies_payload = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
        enabled_strategy_keys = self._normalize_enabled_strategy_keys(
            shell_payload.get("enabled_strategy_keys") or tuple(strategies_payload.keys())
        )
        if not enabled_strategy_keys:
            enabled_strategy_keys = self._normalize_enabled_strategy_keys(self._enabled_strategy_keys(shell_settings)) or ("rsi",)
        active_strategy_key = str(
            shell_payload.get("active_strategy_key") or self._resolved_active_strategy_key(shell_settings) or enabled_strategy_keys[0]
        ).strip().lower()
        if active_strategy_key not in enabled_strategy_keys:
            active_strategy_key = enabled_strategy_keys[0]
        raw_personalization = shell_payload.get("personalization") if isinstance(shell_payload.get("personalization"), dict) else {}
        personalization = normalize_personalization(raw_personalization)
        asset_scope_type = normalize_asset_scope_type(
            raw_personalization.get("asset_scope_type") if isinstance(raw_personalization, dict) else shell_payload.get("asset_scope_type")
        )
        asset_scope_payload = normalize_asset_scope_payload(
            asset_scope_type,
            raw_personalization.get("asset_scope_payload") if isinstance(raw_personalization, dict) and "asset_scope_payload" in raw_personalization else shell_payload.get("asset_scope_payload"),
        )
        if asset_scope_type == "all" and "asset_scope_type" not in raw_personalization and "asset_scope_type" not in shell_payload:
            asset_scope_type, asset_scope_payload = infer_asset_scope_from_payload(payload)
        personalization["asset_scope_type"] = asset_scope_type
        personalization["asset_scope_payload"] = asset_scope_payload

        for strategy_key in enabled_strategy_keys:
            existing = await self._ensure_premium_strategy_settings(
                user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            strategy_payload = strategies_payload.get(strategy_key) if isinstance(strategies_payload.get(strategy_key), dict) else {}
            await self.repository.upsert_premium_strategy_settings(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                direct_signal_delivery_enabled=bool(strategy_payload.get("direct_signal_delivery_enabled", existing.direct_signal_delivery_enabled)),
                followup_delivery_enabled=bool(strategy_payload.get("followup_delivery_enabled", existing.followup_delivery_enabled)),
                signal_profile=str(strategy_payload.get("signal_profile") or existing.signal_profile),
                base_signal_profile=str(strategy_payload.get("base_signal_profile") or existing.base_signal_profile),
                preferred_min_score=(
                    int(strategy_payload["preferred_min_score"])
                    if isinstance(strategy_payload.get("preferred_min_score"), (int, float))
                    else existing.preferred_min_score
                ),
                min_quote_volume=(
                    float(strategy_payload["min_quote_volume"])
                    if isinstance(strategy_payload.get("min_quote_volume"), (int, float))
                    else existing.min_quote_volume
                ),
                rsi_oversold=(
                    float(strategy_payload["rsi_oversold"])
                    if isinstance(strategy_payload.get("rsi_oversold"), (int, float))
                    else existing.rsi_oversold
                ),
                rsi_overbought=(
                    float(strategy_payload["rsi_overbought"])
                    if isinstance(strategy_payload.get("rsi_overbought"), (int, float))
                    else existing.rsi_overbought
                ),
                direction_filter=str(strategy_payload.get("direction_filter") or existing.direction_filter),
                watchlist_only=bool(strategy_payload.get("watchlist_only", existing.watchlist_only)),
                delivery_mode=str(strategy_payload.get("delivery_mode") or existing.delivery_mode),
                delivery_mode_changed_at=utc_now(),
                quiet_hours_start_minute=(
                    int(strategy_payload["quiet_hours_start_minute"])
                    if isinstance(strategy_payload.get("quiet_hours_start_minute"), int)
                    else existing.quiet_hours_start_minute
                ),
                quiet_hours_end_minute=(
                    int(strategy_payload["quiet_hours_end_minute"])
                    if isinstance(strategy_payload.get("quiet_hours_end_minute"), int)
                    else existing.quiet_hours_end_minute
                ),
                active_watchlist_theme=str(strategy_payload.get("active_watchlist_theme") or existing.active_watchlist_theme),
                active_custom_theme_name=(
                    strategy_payload.get("active_custom_theme_name")
                    if "active_custom_theme_name" in strategy_payload
                    else existing.active_custom_theme_name
                ),
                strategy_preferences=normalize_strategy_preferences(
                    strategy_key,
                    strategy_payload.get("strategy_preferences") or existing.strategy_preferences,
                ),
            )
            should_restore_strategy_symbols = asset_scope_type in {"custom", "theme"} or (
                "asset_scope_type" not in raw_personalization and "asset_scope_type" not in shell_payload
            )
            if should_restore_strategy_symbols and isinstance(strategy_payload.get("favorite_symbols"), list):
                await self.repository.replace_premium_strategy_watchlist_symbols(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    symbols=[
                        normalize_symbol(str(symbol))
                        for symbol in strategy_payload.get("favorite_symbols", [])
                        if str(symbol).strip()
                    ][: self.WATCHLIST_LIMIT],
                )

        active_strategy_settings = await self._ensure_premium_strategy_settings(
            user.telegram_user_id,
            shell_settings=shell_settings,
            strategy_key=active_strategy_key,
        )
        await self.repository.upsert_user_settings(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=active_strategy_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=active_strategy_settings.followup_delivery_enabled,
            gold_alerts_enabled=bool(shell_payload.get("gold_alerts_enabled", shell_settings.gold_alerts_enabled))
            or GOLD_MASTER_STRATEGY_KEY in enabled_strategy_keys
            or any(key in GOLD_SUBSTRATEGY_KEY_SET for key in enabled_strategy_keys),
            language_code=shell_settings.language_code,
            signal_profile=active_strategy_settings.signal_profile,
            base_signal_profile=active_strategy_settings.base_signal_profile,
            preferred_min_score=active_strategy_settings.preferred_min_score,
            min_quote_volume=active_strategy_settings.min_quote_volume,
            rsi_oversold=active_strategy_settings.rsi_oversold,
            rsi_overbought=active_strategy_settings.rsi_overbought,
            direction_filter=active_strategy_settings.direction_filter,
            watchlist_only=active_strategy_settings.watchlist_only,
            menu_collapsed=shell_settings.menu_collapsed,
            delivery_mode=active_strategy_settings.delivery_mode,
            delivery_mode_changed_at=utc_now(),
            quiet_hours_start_minute=active_strategy_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=active_strategy_settings.quiet_hours_end_minute,
            snooze_until=shell_settings.snooze_until,
            snooze_started_at=shell_settings.snooze_started_at,
            snooze_label=shell_settings.snooze_label,
            last_resume_summary_at=shell_settings.last_resume_summary_at,
            last_digest_sent_at=shell_settings.last_digest_sent_at,
            last_daily_recap_at=shell_settings.last_daily_recap_at,
            last_weekly_recap_at=shell_settings.last_weekly_recap_at,
            active_watchlist_theme=active_strategy_settings.active_watchlist_theme,
            active_custom_theme_name=active_strategy_settings.active_custom_theme_name,
            onboarding_completed_at=shell_settings.onboarding_completed_at or utc_now(),
            enabled_strategy_keys=enabled_strategy_keys,
            active_strategy_key=active_strategy_key,
            strategy_selector_completed_at=shell_settings.strategy_selector_completed_at or utc_now(),
            current_context="setupshub",
            current_strategy_context=active_strategy_key,
            current_set_id=setup.id,
            timezone_name=shell_settings.timezone_name,
            display_mode=str(shell_payload.get("display_mode") or shell_settings.display_mode),
            active_workspace=shell_payload.get("active_workspace") if "active_workspace" in shell_payload else shell_settings.active_workspace,
            saved_workspace_payload=shell_settings.saved_workspace_payload,
            strategy_preferences=active_strategy_settings.strategy_preferences,
            personalization=personalization,
            delivery_rules=normalize_delivery_rules(shell_payload.get("delivery_rules")),
        )
        await self.repository.update_user_saved_setup(
            setup.id,
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            last_used_at=utc_now(),
        )
        refreshed_shell = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
        assert refreshed_shell is not None
        return self._store_cached_settings(await self._load_strategy_settings(
            user.telegram_user_id,
            shell_settings=refreshed_shell,
            strategy_key=active_strategy_key,
        ))

    async def _active_saved_setup(self, telegram_user_id: int) -> UserSavedSetupRecord | None:
        shell_settings = await self._ensure_shell_settings(telegram_user_id)
        if shell_settings.current_set_id is None:
            return None
        return await self.repository.get_user_saved_setup(
            int(shell_settings.current_set_id),
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
        )

    async def _default_saved_setup(self, telegram_user_id: int) -> UserSavedSetupRecord | None:
        setups = await self.repository.list_user_saved_setups(telegram_user_id, bot_kind=self.bot_kind)
        return next((setup for setup in setups if setup.is_default), None)

    async def _primary_quick_launch_setup(self, telegram_user_id: int) -> UserSavedSetupRecord | None:
        setups = await self.repository.list_user_saved_setups(telegram_user_id, bot_kind=self.bot_kind)
        return next((setup for setup in setups if setup.is_pinned), None) or next((setup for setup in setups if setup.is_default), None)

    async def _save_personalization_state(
        self,
        user: PrivateBotUserRecord,
        settings: UserSettingsRecord,
        *,
        personalization: dict[str, object] | None = None,
        delivery_rules: dict[str, object] | None = None,
    ) -> UserSettingsRecord:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        target_settings = settings if self._resolved_active_strategy_key(settings) else shell_settings
        return await self._save_user_settings(
            user=user,
            current_settings=target_settings,
            personalization=normalize_personalization(personalization if personalization is not None else self._personalization_state(shell_settings)),
            delivery_rules=normalize_delivery_rules(delivery_rules if delivery_rules is not None else self._delivery_rules_state(shell_settings)),
            current_context="settingshub",
            current_set_id=None,
        )

    def _clear_personalization_prompt_session(self, telegram_user_id: int) -> None:
        self._personalization_prompt_sessions.pop(telegram_user_id, None)

    async def _prompt_personalization_action(
        self,
        user: PrivateBotUserRecord,
        *,
        action: str,
        target_id: int | None = None,
        name: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        self._personalization_prompt_sessions[user.telegram_user_id] = _PersonalizationPromptSession(
            action=action,
            target_id=target_id,
            name=name,
        )
        text_map = {
            "setup_savecurrent": (
                "Send a name for the current setup."
                if language == "en"
                else "Отправь название для текущего сетапа."
            ),
            "setup_rename": (
                f"Send a new name for <b>{escape_html(name or 'Setup')}</b>."
                if language == "en"
                else f"Отправь новое имя для <b>{escape_html(name or 'Setup')}</b>."
            ),
            "setup_duplicate": (
                f"Send a name for the copy of <b>{escape_html(name or 'Setup')}</b>."
                if language == "en"
                else f"Отправь имя для копии <b>{escape_html(name or 'Setup')}</b>."
            ),
            "hide_asset": (
                "Send a symbol to hide, for example BTC or XAUUSD."
                if language == "en"
                else "Отправь символ, который нужно скрыть, например BTC или XAUUSD."
            ),
        }
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=text_map.get(action, "Send the required value."),
            parse_mode="HTML",
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _handle_personalization_prompt_message(self, user: PrivateBotUserRecord, text: str) -> bool:
        session = self._personalization_prompt_sessions.get(user.telegram_user_id)
        if session is None:
            return False
        payload = text.strip()
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not payload:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text="Please send a non-empty value." if language == "en" else "Пришли непустое значение.",
                parse_mode=None,
            )
            return True
        self._clear_personalization_prompt_session(user.telegram_user_id)
        if session.action == "setup_savecurrent":
            created = await self._save_setup_snapshot(user.telegram_user_id, name=payload)
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=(f"Setup <b>{escape_html(created.name)}</b> was saved." if language == "en" else f"Сетап <b>{escape_html(created.name)}</b> сохранён."),
                parse_mode="HTML",
            )
            await self._send_saved_setups_list(user)
            return True
        if session.action == "setup_rename" and session.target_id is not None:
            unique_name = await self._ensure_unique_setup_name(
                user.telegram_user_id,
                preferred_name=payload,
                exclude_setup_id=session.target_id,
            )
            await self.repository.update_user_saved_setup(
                session.target_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                name=unique_name,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=(f"Setup renamed to <b>{escape_html(unique_name)}</b>." if language == "en" else f"Сетап переименован в <b>{escape_html(unique_name)}</b>."),
                parse_mode="HTML",
            )
            await self._send_saved_setup_detail(user, setup_id=session.target_id)
            return True
        if session.action == "setup_duplicate" and session.target_id is not None:
            existing = await self.repository.get_user_saved_setup(
                session.target_id,
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
            )
            if existing is None:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text="Setup no longer exists." if language == "en" else "Сетап больше не существует.",
                    parse_mode=None,
                )
                return True
            unique_name = await self._ensure_unique_setup_name(user.telegram_user_id, preferred_name=payload)
            duplicated = await self.repository.create_user_saved_setup(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                name=unique_name,
                payload=existing.payload,
                is_default=False,
                is_pinned=existing.is_pinned,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=(f"Copy saved as <b>{escape_html(duplicated.name)}</b>." if language == "en" else f"Копия сохранена как <b>{escape_html(duplicated.name)}</b>."),
                parse_mode="HTML",
            )
            await self._send_saved_setup_detail(user, setup_id=duplicated.id)
            return True
        if session.action == "hide_asset":
            symbol = await self._resolve_symbol_input(payload)
            if not symbol:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "symbol_not_recognized"),
                    parse_mode=None,
                )
                return True
            personalization = self._personalization_state(await self._ensure_shell_settings(user.telegram_user_id))
            hidden = personalization.get("hidden", {})
            symbols = [normalize_symbol(str(item)) for item in hidden.get("symbols", []) if str(item).strip()]
            normalized_symbol = normalize_symbol(symbol)
            if normalized_symbol not in symbols:
                symbols.append(normalized_symbol)
            hidden["symbols"] = sorted(set(symbols))
            personalization["hidden"] = hidden
            await self._save_personalization_state(user, settings, personalization=personalization)
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=(f"{normalized_symbol} is now hidden." if language == "en" else f"{normalized_symbol} теперь скрыт."),
                parse_mode=None,
            )
            await self._send_hide_mute_hub(user)
            return True
        return False

    async def _handle_setup_builder_text(self, user: PrivateBotUserRecord, text: str) -> bool:
        state = await self._get_setup_builder_state(user.telegram_user_id)
        if state is None or state.completed_at is not None:
            return False
        draft = dict(state.draft or {})
        awaiting_input = str(draft.get("awaiting_input") or "").strip().lower()
        payload = text.strip()
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not awaiting_input:
            return False
        if not payload:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text="Please send a value." if language == "en" else "Пришли значение.",
                parse_mode=None,
            )
            return True
        if awaiting_input == "name":
            draft["name"] = await self._ensure_unique_setup_name(
                user.telegram_user_id,
                preferred_name=payload,
                exclude_setup_id=int(draft.get("editing_setup_id")) if isinstance(draft.get("editing_setup_id"), int) else None,
            )
            draft.pop("awaiting_input", None)
        elif awaiting_input in {"symbols", "symbols_add", "symbols_remove"}:
            symbols = parse_favorite_symbols_input(payload)
            if not symbols:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text="Send symbols like BTC, ETH, SOL." if language == "en" else "Отправь символы вроде BTC, ETH, SOL.",
                    parse_mode=None,
                )
                return True
            current_scope_type, current_scope_payload = self._setup_builder_scope_state_from_draft(draft)
            current_symbols = [
                normalize_symbol(str(item))
                for item in (current_scope_payload or {}).get("symbols", [])
                if str(item).strip()
            ] if current_scope_type == "custom" else []
            if awaiting_input == "symbols_remove":
                next_symbols = [item for item in current_symbols if item not in set(symbols)]
                if not next_symbols:
                    self._write_setup_builder_scope(draft, scope_type="all")
                    await self._send_chat_message(
                        chat_id=str(user.telegram_user_id),
                        text="Custom selection is empty. All Coins is now active." if language == "en" else "Свой список пуст. Теперь активны все монеты.",
                        parse_mode=None,
                    )
                else:
                    self._write_setup_builder_scope(draft, scope_type="custom", payload={"symbols": next_symbols})
            else:
                next_symbols = symbols if awaiting_input == "symbols" else sorted(set(current_symbols).union(symbols))
                self._write_setup_builder_scope(draft, scope_type="custom", payload={"symbols": next_symbols})
            draft.pop("awaiting_input", None)
        else:
            return False
        await self._save_setup_builder_state(user.telegram_user_id, step=state.step, draft=draft)
        await self._send_setup_builder_step(user, step=state.step, draft=draft)
        return True

    async def _build_personal_summary_data(
        self,
        user: PrivateBotUserRecord,
        *,
        period_label: str,
    ) -> PersonalSummaryData:
        now = utc_now()
        start = self._period_window_start(now=now, period_label=period_label)
        flow = await self._collect_user_period_flow(
            user,
            start=start,
            end=now + timedelta(minutes=1),
            include_disabled_strategy_matches=False,
        )
        shell_settings = flow["shell_settings"]
        assert isinstance(shell_settings, UserSettingsRecord)
        active_setup = await self._active_saved_setup(user.telegram_user_id)
        setup_name = active_setup.name if active_setup is not None else self._workspace_label(shell_settings.active_workspace, language_code=self._language_code(shell_settings))
        matched_by_strategy = flow["matched_by_strategy"]
        matched_alert_ids = flow["matched_alert_ids"]
        matched_symbols = flow["matched_symbols"]
        matched_strategies = flow["matched_strategies"]
        filtered_out = int(flow["filtered_out"])
        filtered_reasons = dict(flow["filtered_reasons"])
        delivered_alerts = list(flow["delivered_alerts"])
        delivered_symbols = dict(flow["delivered_symbols"])
        delivered_strategies = dict(flow["delivered_strategies"])
        tracked_by_alert_id = flow["tracked_by_alert_id"]
        assert isinstance(matched_by_strategy, dict)
        assert isinstance(matched_alert_ids, set)
        assert isinstance(matched_symbols, dict)
        assert isinstance(matched_strategies, dict)
        assert isinstance(delivered_alerts, list)
        assert isinstance(delivered_symbols, dict)
        assert isinstance(delivered_strategies, dict)
        assert isinstance(tracked_by_alert_id, dict)

        matched = len(matched_alert_ids)
        delivered = len(delivered_alerts)
        strong_matches = int(flow["strong_matches"])
        strong_delivered = int(flow["strong_delivered"])
        watchlist_matches = int(flow["delivered_watchlist_matches"] or flow["watchlist_matches"])
        gold_matches = int(flow["delivered_gold_matches"] or flow["gold_matches"])
        tracked = [
            tracked_by_alert_id[int(alert_id)]
            for alert_id in matched_alert_ids
            if int(alert_id) in tracked_by_alert_id
        ]
        confirmed = sum(1 for record in tracked if str(record.status) in {"confirmed", "near_tp", "hit_tp"})
        invalidated = sum(1 for record in tracked if str(record.status) == "invalidated")
        top_strategy_key = self._top_count_label(delivered_strategies or matched_strategies)
        top_strategy = self._strategy_label(top_strategy_key, language_code=self._language_code(shell_settings)) if top_strategy_key else None
        most_active_asset = self._top_count_label(delivered_symbols or matched_symbols)
        gold_activity = "Quiet" if gold_matches <= 0 else f"{gold_matches} matches"
        if self._language_code(shell_settings) == "ru":
            gold_activity = "Тихо" if gold_matches <= 0 else f"{gold_matches} совп."
        previous_start = start - (timedelta(days=1) if period_label == "daily" else timedelta(days=7))
        previous_records = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            since=previous_start,
            limit=3000,
        )
        previous_delivered = sum(
            1
            for record in previous_records
            if record.message_kind == "alert"
            and record.alert_id is not None
            and record.delivered_at < start
            and bool(record.metadata.get("sent", True))
        )
        delta = delivered - previous_delivered
        change_note = None
        if delta != 0:
            if self._language_code(shell_settings) == "ru":
                change_note = f"Доставлено {'больше' if delta > 0 else 'меньше'} на {abs(delta)} по сравнению с прошлым периодом."
            else:
                change_note = f"{'More' if delta > 0 else 'Fewer'} delivered signals by {abs(delta)} versus the previous period."
        top_filtered_reason = max(filtered_reasons.items(), key=lambda item: item[1])[0] if filtered_reasons else "ok"
        if filtered_out <= max(delivered, 1):
            top_recommendation = (
                "Your setup stayed selective. Keep it as-is for a clean flow."
                if self._language_code(shell_settings) == "en"
                else "Твой режим остался избирательным. Можно оставить его как есть."
            )
        else:
            top_recommendation = (
                f"Most filtered signals were blocked by {humanize_filter_reason(top_filtered_reason, language_code=self._language_code(shell_settings)).lower()}. Loosen that rule if you want more flow."
                if self._language_code(shell_settings) == "en"
                else f"Больше всего сигналов отсеял фильтр: {humanize_filter_reason(top_filtered_reason, language_code=self._language_code(shell_settings)).lower()}. Ослабь его, если нужен более широкий поток."
            )
        quick_read = (
            f"{delivered} delivered from {matched} matched ideas. Top focus: {top_strategy or '—'} and {most_active_asset or '—'}."
            if self._language_code(shell_settings) == "en"
            else f"{delivered} доставлено из {matched} совпавших идей. Главный фокус: {top_strategy or '—'} и {most_active_asset or '—'}."
        )
        return PersonalSummaryData(
            period_label=period_label,
            setup_name=setup_name,
            matched=matched,
            delivered=delivered,
            strong_delivered=strong_delivered or min(strong_matches, delivered),
            watchlist_matches=watchlist_matches,
            filtered_out=filtered_out,
            top_strategy=top_strategy,
            most_active_asset=most_active_asset,
            gold_activity=gold_activity,
            confirmed=confirmed,
            invalidated=invalidated,
            filtered_reasons=filtered_reasons,
            top_recommendation=top_recommendation,
            quick_read=quick_read,
            change_note=change_note,
        )

    async def _send_delivery_center(
        self,
        user: PrivateBotUserRecord,
        *,
        origin: str = "menu",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        settings, origin = await self._settings_for_hub_section(
            user.telegram_user_id,
            section="delivery",
            origin=origin,
            shell_settings=shell_settings,
        )
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        access_state = await self._effective_access_state_for_user(user)
        now = utc_now()
        mixed_global_delivery = False
        if self.bot_kind == "premium" and not self._is_strategy_origin(origin):
            settings, mixed_global_delivery = await self._global_delivery_display_settings(
                user.telegram_user_id,
                shell_settings=shell_settings,
                now=now,
            )
        active_strategy_key = self._resolved_active_strategy_key(settings)
        origin = self._remember_hub_origin(user.telegram_user_id, section="delivery", origin=origin)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="deliveryhub",
            default=self._hub_back_callback_data(settings, origin=origin),
        )
        self._remember_screen_back_callback(
            user.telegram_user_id,
            screen="goldhub",
            callback_data=self._hub_callback_data("deliveryhub", origin=origin),
        )
        strategy_label = (
            self._strategy_label(active_strategy_key, language_code=language)
            if self.bot_kind == "premium" and self._is_strategy_origin(origin) and active_strategy_key is not None
            else None
        )
        if self._is_strategy_origin(origin):
            scope_note = (
                "Эти уведомления относятся только к этой стратегии."
                if language == "ru"
                else "These alerts apply only to this strategy."
            )
        else:
            scope_note = (
                "Эти уведомления управляют общим потоком по всем включённым стратегиям."
                if language == "ru"
                else "These alerts control the overall flow across all enabled strategies."
            )
            if mixed_global_delivery:
                scope_note += (
                    " У части стратегий сейчас свои отдельные настройки."
                    if language == "ru"
                    else " Some strategies currently use their own separate settings."
                )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_scoped_delivery_center_message(
                settings=settings,
                access_state=access_state,
                language_code=language,
                timezone_obj=self.settings.timezone,
                now=now,
                strategy_label=strategy_label,
                scope_note=scope_note,
            ),
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="delivery",
                include_gold_button=active_strategy_key == "gold",
                premium=self.bot_kind == "premium",
                direct_delivery_enabled=settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=settings.followup_delivery_enabled,
                gold_alerts_enabled=settings.gold_alerts_enabled,
                snoozed=is_snoozed(settings, now=now),
                quiet_hours_active=(
                    settings.quiet_hours_start_minute is not None
                    and settings.quiet_hours_end_minute is not None
                ),
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_gold_center(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        if not self.settings.gold_alerts_enabled:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "symbol_unavailable"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        gold_master_enabled = self._gold_alerts_enabled_for_settings(shell_settings)
        strategy_cards = []
        strategy_states: list[tuple[str, bool]] = []
        for strategy_key in GOLD_SUBSTRATEGY_KEYS:
            strategy_enabled = self._strategy_enabled_for_settings(shell_settings, strategy_key=strategy_key)
            copy = self._strategy_copy(strategy_key, language_code=language)
            strategy_cards.append(
                {
                    "label": self._strategy_label(strategy_key, language_code=language),
                    "enabled": strategy_enabled,
                    "summary": str(copy.get("summary") or ""),
                }
            )
            strategy_states.append((strategy_key, strategy_enabled))
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="goldhub",
            default=self._strategy_hub_callback_data(shell_settings),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="setup", callback_data="ux:goldhub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryhub", callback_data="ux:goldhub")
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryrules", callback_data="ux:goldhub")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_gold_center_message(
                gold_alerts_enabled=gold_master_enabled,
                language_code=language,
                market_note=(
                    self._gold_weekend_note(language_code=language)
                    if self._gold_market_closed_for_weekend()
                    else None
                ),
                strategies=strategy_cards,
            ),
            reply_markup=build_gold_hub_keyboard(
                language_code=language,
                gold_alerts_enabled=gold_master_enabled,
                gold_web_url=self.settings.gold_web_base_url,
                strategy_states=strategy_states,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="goldhub",
        )

    async def _send_gold_wizard_step(
        self,
        user: PrivateBotUserRecord,
        *,
        step: str,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_gold_wizard_message(language_code=language, draft=draft, step=step),
            reply_markup=build_gold_wizard_keyboard(
                language_code=language,
                draft=draft,
                step=step,
                back_callback_data="ux:goldhub",
            ),
            edit_message_id=edit_message_id,
        )

    async def _start_gold_wizard(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        draft = {
            "mode": "balanced",
            "direction": "both",
            "tempo": "balanced",
            "session": "all",
            "followups": True,
            "delivery": "instant",
        }
        await self._save_gold_wizard_state(user.telegram_user_id, step="mode", draft=draft)
        await self._send_gold_wizard_step(
            user,
            step="mode",
            draft=draft,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _apply_gold_wizard(
        self,
        user: PrivateBotUserRecord,
        *,
        draft: dict[str, object],
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        mode = str(draft.get("mode") or "balanced")
        direction = str(draft.get("direction") or "both")
        tempo = str(draft.get("tempo") or "balanced")
        session = str(draft.get("session") or "all")
        followups_enabled = bool(draft.get("followups", True))
        delivery = str(draft.get("delivery") or "instant")
        profile_map = {"macro": "conservative", "balanced": "balanced", "reactive": "aggressive"}
        breakout_tempo = {"fast": "fast", "balanced": "desk", "macro": "macro"}[tempo]
        pullback_tempo = {"fast": "fast", "balanced": "trend", "macro": "macro"}[tempo]
        liquidity_tempo = {"fast": "fast", "balanced": "balanced", "macro": "patient"}[tempo]
        session_focus = {"all": "all", "london": "london", "new_york": "newyork"}[session]
        enabled_keys = self._normalize_enabled_strategy_keys((GOLD_MASTER_STRATEGY_KEY, *GOLD_SUBSTRATEGY_KEYS))
        for strategy_key in GOLD_SUBSTRATEGY_KEYS:
            existing = await self._ensure_premium_strategy_settings(
                user.telegram_user_id,
                shell_settings=shell_settings,
                strategy_key=strategy_key,
            )
            prefs = normalize_strategy_preferences(strategy_key, existing.strategy_preferences)
            prefs["timeframe_focus"] = {
                "gold_breakout": breakout_tempo,
                "gold_pullback": pullback_tempo,
                "gold_liquidity": liquidity_tempo,
            }[strategy_key]
            prefs["session_focus"] = session_focus
            await self.repository.upsert_premium_strategy_settings(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                direct_signal_delivery_enabled=existing.direct_signal_delivery_enabled,
                followup_delivery_enabled=followups_enabled,
                signal_profile=profile_map[mode],
                base_signal_profile=profile_map[mode],
                preferred_min_score=existing.preferred_min_score,
                min_quote_volume=existing.min_quote_volume,
                rsi_oversold=existing.rsi_oversold,
                rsi_overbought=existing.rsi_overbought,
                direction_filter=direction,
                watchlist_only=False,
                delivery_mode="digest" if delivery in {"digest", "quiet"} else "instant",
                delivery_mode_changed_at=utc_now(),
                quiet_hours_start_minute=existing.quiet_hours_start_minute,
                quiet_hours_end_minute=existing.quiet_hours_end_minute,
                active_watchlist_theme="gold",
                active_custom_theme_name=None,
                strategy_preferences=prefs,
            )
        rules = self._delivery_rules_state(shell_settings)
        rules["gold_signals"] = "digest" if delivery in {"digest", "quiet"} else "instant"
        if delivery == "quiet":
            rules["overnight"] = "quiet"
        await self._save_user_settings(
            user=user,
            current_settings=shell_settings,
            enabled_strategy_keys=enabled_keys,
            active_strategy_key=GOLD_MASTER_STRATEGY_KEY,
            gold_alerts_enabled=True,
            current_context="goldhub",
            current_strategy_context=GOLD_MASTER_STRATEGY_KEY,
            delivery_rules=rules,
        )
        await self._clear_gold_wizard_state(user.telegram_user_id)
        await self._send_gold_center(user, chat_id=chat_id, edit_message_id=edit_message_id)

    async def _send_control_center(
        self,
        user: PrivateBotUserRecord,
        *,
        origin: str = "menu",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        settings, origin = await self._settings_for_hub_section(
            user.telegram_user_id,
            section="stats",
            origin=origin,
            shell_settings=shell_settings,
        )
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        access_state = await self._effective_access_state_for_user(user)
        origin = self._remember_hub_origin(user.telegram_user_id, section="stats", origin=origin)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="statshub",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=settings,
                screen="statshub",
                section="stats",
            ),
        )
        now = utc_now()
        bundle = await self._load_delivered_alert_bundle(
            user,
            settings=settings,
            since=now - timedelta(days=30),
            limit=3000,
            filter_to_active_strategy=self._is_strategy_origin(origin),
        )
        deliveries = [
            self._enrich_delivered_record(
                record,
                alerts_by_id=bundle.alerts_by_id,
                followups_by_alert_id=bundle.followups_by_alert_id,
            )
            for record in bundle.deliveries
        ]
        metrics = build_control_center_metrics(deliveries, now=now, language_code=language)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_control_center_message(
                metrics=metrics,
                settings=settings,
                access_state=access_state,
                language_code=language,
                strategy_label=(
                    self._strategy_label(self._resolved_active_strategy_key(settings), language_code=language)
                    if self.bot_kind == "premium" and self._is_strategy_origin(origin)
                    else None
                ),
            ),
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="stats",
                include_gold_button=self.settings.gold_alerts_enabled,
                premium=self.bot_kind == "premium",
                gold_alerts_enabled=settings.gold_alerts_enabled,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_product_results_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        strategy_code: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        strategy_label = self._strategy_label(strategy_code, language_code=language) if strategy_code else None
        self._remember_screen_back_callback(user.telegram_user_id, screen="personal_summary", callback_data="results:hub")
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_results_hub(
                strategy_label=strategy_label,
                is_admin=self.role_guard.is_admin(user),
                language_code=language,
            ),
            reply_markup=build_personalized_results_keyboard(
                is_admin=self.role_guard.is_admin(user),
                strategy_code=strategy_code,
                language_code=language,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_compare_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_compare_hub(
                is_admin=self.role_guard.is_admin(user),
                language_code=language,
            ),
            reply_markup=build_compare_hub_keyboard(
                is_admin=self.role_guard.is_admin(user),
                language_code=language,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_compare_view(
        self,
        user: PrivateBotUserRecord,
        *,
        view: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        intro, profiles = self.compare_service.get_user_compare_cards(view, language_code=language)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self.repository.record_telemetry_event(
            event_name="compare_view_opened",
            created_at=utc_now(),
            context=view,
            payload={"user_id": user.telegram_user_id},
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_compare_view(intro, profiles, language_code=language),
            reply_markup=build_compare_hub_keyboard(
                is_admin=self.role_guard.is_admin(user),
                language_code=language,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_learn_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_learn_hub(language_code=language),
            reply_markup=build_learn_hub_keyboard(language_code=language),
            edit_message_id=edit_message_id,
        )

    async def _send_learn_page(
        self,
        user: PrivateBotUserRecord,
        *,
        page: str,
        strategy_code: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self.repository.record_telemetry_event(
            event_name="learn_page_opened",
            created_at=utc_now(),
            context=page,
            payload={"user_id": user.telegram_user_id, "strategy_code": strategy_code},
        )
        if page == "guides" and strategy_code is None:
            await self._send_or_edit_text(
                chat_id=target_chat_id,
                text=(
                    "<b>📘 Гайды по стратегиям</b>\n\n"
                    "Этот раздел помогает понять базовую идею каждой стратегии, где она работает лучше всего и чего стоит избегать.\n\n"
                    "Открой любой гайд ниже, чтобы спокойно разобрать логику сетапа перед настройкой фильтров или уведомлений."
                    if language == "ru"
                    else "<b>📘 Strategy Guides</b>\n\n"
                    "Use this section to understand the core idea behind each strategy, where it fits best and what to avoid.\n\n"
                    "Open any guide below to review the setup in plain language before adjusting filters or alerts."
                ),
                reply_markup=build_strategy_guides_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.learn_service.learn_page(page, strategy_code=strategy_code, language_code=language),
            reply_markup=build_learn_hub_keyboard(language_code=language),
            edit_message_id=edit_message_id,
        )

    async def _send_lifecycle_hub(
        self,
        user: PrivateBotUserRecord,
        *,
        strategy_code: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        strategy_label = self._strategy_label(strategy_code, language_code=language) if strategy_code else None
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_lifecycle_hub(strategy_label=strategy_label, language_code=language),
            reply_markup=build_lifecycle_hub_keyboard(strategy_code=strategy_code, language_code=language),
            edit_message_id=edit_message_id,
        )

    async def _send_lifecycle_view(
        self,
        user: PrivateBotUserRecord,
        *,
        view: str,
        strategy_code: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        view_map = {
            "open": (
                "Открытые сигналы" if language == "ru" else "Open Signals",
                ("fresh", "active", "near_tp"),
                "📭 Нет открытых сигналов" if language == "ru" else "📭 No open signals",
                "В этом срезе сейчас нет открытых сигналов.\n\nТы можешь переключиться на подтверждённые сигналы или вернуться в результаты."
                if language == "ru"
                else "There are no open signals in this scope right now.\n\nYou can switch to Confirmed Signals or return to Results.",
            ),
            "confirmed": (
                "Подтверждённые сигналы" if language == "ru" else "Confirmed Signals",
                ("confirmed",),
                "📭 Нет подтверждённых сигналов" if language == "ru" else "📭 No confirmed signals",
                "В этом срезе сейчас нет подтверждённых сигналов.\n\nТы можешь посмотреть открытые сигналы или вернуться в результаты."
                if language == "ru"
                else "There are no confirmed signals in this scope right now.\n\nYou can check Open Signals or return to Results.",
            ),
            "invalidated": (
                "Сломанные сигналы" if language == "ru" else "Invalidated Signals",
                ("invalidated",),
                "📭 Нет сломанных сигналов" if language == "ru" else "📭 No invalidated signals",
                "В этом срезе сейчас нет сломанных сигналов.\n\nТы можешь переключиться на открытые сигналы или вернуться в результаты."
                if language == "ru"
                else "There are no invalidated signals in this scope right now.\n\nYou can switch to Open Signals or return to Results.",
            ),
            "closed": (
                "Закрытые результаты" if language == "ru" else "Closed Results",
                ("hit_tp", "expired", "invalidated"),
                "📭 Нет закрытых результатов" if language == "ru" else "📭 No closed results",
                "В этом срезе сейчас нет закрытых сигналов.\n\nТы можешь вернуться в жизненный цикл сигналов или открыть другой срез результатов."
                if language == "ru"
                else "There are no closed signals in this scope right now.\n\nYou can return to Signal Lifecycle or Results for another slice.",
            ),
            "expired": (
                "Истёкшие сигналы" if language == "ru" else "Expired Signals",
                ("expired",),
                "📭 Нет истёкших сигналов" if language == "ru" else "📭 No expired signals",
                "В этом срезе сейчас нет истёкших сигналов.\n\nТы можешь переключиться на открытые сигналы или вернуться в результаты."
                if language == "ru"
                else "There are no expired signals in this scope right now.\n\nYou can switch to Open Signals or return to Results.",
            ),
        }
        title, statuses, empty_title, empty_body = view_map.get(view, view_map["open"])
        records = await self.signal_lifecycle_service.list_lifecycle_signals(
            strategy_code=strategy_code,
            statuses=statuses,
            limit=20,
        )
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_lifecycle_list(
                title=title,
                records=records,
                empty_title=empty_title,
                empty_body=empty_body,
                language_code=language,
            ),
            reply_markup=build_lifecycle_hub_keyboard(strategy_code=strategy_code, language_code=language),
            edit_message_id=edit_message_id,
        )

    async def _send_admin_stats(
        self,
        user: PrivateBotUserRecord,
        *,
        period: str = "7d",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not self.role_guard.is_admin(user):
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=self.role_guard.restricted_message(admin_only=True, language_code=language),
                reply_markup=build_results_hub_keyboard(is_admin=False, language_code=language),
                edit_message_id=edit_message_id,
            )
            return
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        normalized_period = str(period or "7d").strip().lower()
        if normalized_period not in {"1d", "7d", "30d", "all_time"}:
            normalized_period = "7d"
        focus_period = normalized_period if normalized_period in {"1d", "7d"} else "1d"
        compare_period = "7d" if focus_period == "1d" else "1d"
        snapshots = await self._build_user_admin_strategy_stats(user, period_type=focus_period)
        compare_snapshots = await self._build_user_admin_strategy_stats(user, period_type=compare_period)
        extra_snapshots = None
        extra_period_label = None
        if normalized_period not in {"1d", "7d"}:
            extra_snapshots = await self._build_user_admin_strategy_stats(user, period_type=normalized_period)
            extra_period_label = normalized_period
        await self.repository.record_telemetry_event(
            event_name="admin_stats_opened",
            created_at=utc_now(),
            context=normalized_period,
            payload={"user_id": user.telegram_user_id},
        )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=self.message_render_service.render_admin_stats(
                snapshots,
                period_label=focus_period,
                compare_snapshots=compare_snapshots,
                extra_snapshots=extra_snapshots,
                extra_period_label=extra_period_label,
                language_code=language,
            ),
            reply_markup=build_admin_stats_keyboard(back_callback_data="results:hub", language_code=language),
            edit_message_id=edit_message_id,
        )

    @staticmethod
    def _format_storage_size(size_bytes: int | None) -> str:
        if size_bytes is None or size_bytes < 0:
            return "not available"
        value = float(size_bytes)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024.0 or unit == "TiB":
                precision = 0 if unit in {"B", "KiB"} else 1
                return f"{value:.{precision}f} {unit}"
            value /= 1024.0
        return "not available"

    async def _send_admin_health(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not self.role_guard.is_admin(user):
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=self.role_guard.restricted_message(admin_only=True, language_code=language),
                reply_markup=build_results_hub_keyboard(is_admin=False, language_code=language),
                edit_message_id=edit_message_id,
            )
            return

        now = utc_now()
        local_now = now.astimezone(self.settings.timezone)
        day_start, _ = local_day_bounds(local_now.date(), self.settings.timezone)
        query_end = now + timedelta(minutes=1)
        stale_before = now - timedelta(minutes=15)
        funnel_event_names = (
            "start_seen",
            "language_selected",
            "welcome_seen",
            "example_signal_opened",
            "how_to_read_opened",
            "strong_setups_opened",
            "no_signals_empty_seen",
            "my_access_opened",
            "classic_vs_pro_opened",
            "help_opened",
            "support_opened",
        )
        metric_names = (
            "pending_followups",
            "processing_followups",
            "stale_followups",
            "funnel_counts",
        )
        metric_results = await asyncio.gather(
            self.repository.count_followup_tasks_by_status("pending"),
            self.repository.count_followup_tasks_by_status("processing"),
            self.repository.count_followup_tasks_due_before(before=stale_before),
            self.repository.count_telemetry_events(
                start=day_start,
                end=query_end,
                event_names=funnel_event_names,
            ),
            return_exceptions=True,
        )
        metrics: dict[str, object | None] = {}
        unavailable_metrics: list[str] = []
        for metric_name, result in zip(metric_names, metric_results, strict=True):
            if isinstance(result, Exception):
                metrics[metric_name] = None
                unavailable_metrics.append(metric_name)
            else:
                metrics[metric_name] = result
        if unavailable_metrics:
            LOGGER.warning(
                "Admin health metrics unavailable bot=%s metrics=%s",
                self.bot_kind,
                ",".join(unavailable_metrics),
            )
        metrics["signals_generated"] = None
        metrics["premium_delivery_records"] = None
        metrics["classic_delivery_records"] = None

        try:
            database_size = Path(self.repository.sqlite_path).stat().st_size
        except OSError:
            database_size = None
        target_chat_id = chat_id or str(user.telegram_user_id)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=target_chat_id,
        )
        try:
            await self.repository.record_telemetry_event(
                event_name="admin_health_opened",
                created_at=now,
                telegram_user_id=user.telegram_user_id,
                context=self.bot_kind,
                payload={"bot_kind": self.bot_kind, "language": language},
            )
        except Exception:
            LOGGER.warning(
                "Admin health telemetry write failed bot=%s",
                self.bot_kind,
                exc_info=True,
            )
        await self._send_or_edit_text(
            chat_id=target_chat_id,
            text=format_admin_health_message(
                generated_at_label=local_now.strftime("%Y-%m-%d %H:%M %Z"),
                signals_generated=metrics["signals_generated"] if isinstance(metrics["signals_generated"], int) else None,
                premium_delivery_records=(
                    metrics["premium_delivery_records"] if isinstance(metrics["premium_delivery_records"], int) else None
                ),
                classic_delivery_records=(
                    metrics["classic_delivery_records"] if isinstance(metrics["classic_delivery_records"], int) else None
                ),
                pending_followups=metrics["pending_followups"] if isinstance(metrics["pending_followups"], int) else None,
                processing_followups=(
                    metrics["processing_followups"] if isinstance(metrics["processing_followups"], int) else None
                ),
                stale_followups=metrics["stale_followups"] if isinstance(metrics["stale_followups"], int) else None,
                database_size_label=self._format_storage_size(database_size),
                funnel_counts=metrics["funnel_counts"] if isinstance(metrics["funnel_counts"], dict) else None,
                language_code=language,
            ),
            reply_markup=build_admin_health_keyboard(language_code=language),
            edit_message_id=edit_message_id,
            cleanup_branch="admin_health",
        )

    async def _send_watchlists_center(
        self,
        user: PrivateBotUserRecord,
        *,
        origin: str = "menu",
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        favorite_symbols = await self._favorite_symbols(user.telegram_user_id)
        active_symbols = await self._watchlist_symbols(user.telegram_user_id)
        saved_themes = await self._saved_watchlist_themes(user.telegram_user_id)
        origin = self._remember_hub_origin(user.telegram_user_id, section="watchlists", origin=origin)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="watchhub",
            default=self._hub_back_callback_data(settings, origin=origin),
        )
        hub_callback = self._hub_callback_data("watchhub", origin=origin)
        self._remember_screen_back_callback(user.telegram_user_id, screen="watchlist", callback_data=hub_callback)
        self._remember_screen_back_callback(user.telegram_user_id, screen="themes", callback_data=hub_callback)
        self._remember_screen_back_callback(user.telegram_user_id, screen="setup", callback_data=hub_callback)
        self._remember_screen_back_callback(user.telegram_user_id, screen="deliveryruleview", callback_data=hub_callback)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_watchlists_message(
                active_theme_label=self._active_watchlist_theme_label(settings, language_code=language),
                active_symbols=active_symbols,
                saved_theme_names=[name for _, name in saved_themes],
                tracking_label=tracking_scope_label(settings, language_code=language),
                watchlist_only=settings.watchlist_only,
                favorites_count=len(favorite_symbols),
                active_watchlist_count=len(active_symbols),
                alerts_enabled=settings.direct_signal_delivery_enabled,
                language_code=language,
            ),
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="watchlists",
                include_gold_button=self.settings.gold_alerts_enabled,
                premium=self.bot_kind == "premium",
                gold_alerts_enabled=settings.gold_alerts_enabled,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_watchlist_themes_manager(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        saved_themes = await self._saved_watchlist_themes(user.telegram_user_id)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="themes",
            default=self._hub_callback_data(
                "watchhub",
                origin=self._hub_origin_for(user.telegram_user_id, section="watchlists"),
            ),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="watchlist", callback_data="ux:themes")
        self._remember_screen_back_callback(user.telegram_user_id, screen="analyze", callback_data="ux:themes")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_section_hub(
                premium_text(language, "watchlists_themes_title"),
                premium_text(language, "watchlists_themes_body"),
            ),
            reply_markup=build_watchlist_themes_keyboard(
                language_code=language,
                saved_themes=saved_themes,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    def _clear_theme_prompt_session(self, telegram_user_id: int) -> None:
        self._theme_prompt_sessions.pop(telegram_user_id, None)

    async def _prompt_theme_action(
        self,
        user: PrivateBotUserRecord,
        *,
        action: str,
        theme_id: int | None = None,
        theme_name: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        self._theme_prompt_sessions[user.telegram_user_id] = _ThemePromptSession(
            action=action,
            theme_id=theme_id,
            theme_name=theme_name,
        )
        prompt_key = {
            "save": "watchlists_prompt_save",
            "rename": "watchlists_prompt_rename",
            "add": "watchlists_prompt_add",
        }.get(action, "watchlists_prompt_save")
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=premium_text(language, prompt_key, theme=theme_name or ""),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _handle_theme_prompt_message(self, user: PrivateBotUserRecord, text: str) -> bool:
        session = self._theme_prompt_sessions.get(user.telegram_user_id)
        if session is None:
            return False
        payload = text.strip()
        if not payload or len(payload) > 24 and session.action in {"save", "rename"}:
            settings = await self._ensure_user_settings(user.telegram_user_id)
            language = self._language_code(settings)
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=premium_text(language, "watchlists_prompt_invalid"),
                parse_mode=None,
            )
            return True
        self._clear_theme_prompt_session(user.telegram_user_id)
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        if session.action == "save":
            symbols = await self._watchlist_symbols(user.telegram_user_id)
            if self.bot_kind == "premium":
                await self.repository.save_premium_strategy_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    theme_name=payload,
                    symbols=symbols,
                    metadata={"source": "manual_theme_save"},
                )
            else:
                await self.repository.save_user_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    theme_name=payload,
                    symbols=symbols,
                    metadata={"source": "manual_theme_save"},
                )
            await self._send_watchlist_themes_manager(user)
            return True
        if session.action == "add" and session.theme_name and session.theme_id is not None:
            if self.bot_kind == "premium":
                theme = await self.repository.get_premium_strategy_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    theme_name=session.theme_name,
                )
            else:
                theme = await self.repository.get_user_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    theme_name=session.theme_name,
                )
            if theme is None:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=premium_text(language, "watchlists_theme_missing"),
                    parse_mode=None,
                )
                return True
            requested_symbols = parse_favorite_symbols_input(payload)
            resolved_symbols: list[str] = []
            for raw_symbol in requested_symbols:
                resolved = await self._resolve_symbol_input(raw_symbol)
                if resolved and resolved not in resolved_symbols:
                    resolved_symbols.append(resolved)
            if not resolved_symbols:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "symbol_not_recognized"),
                    parse_mode=None,
                )
                return True
            if self.bot_kind == "premium":
                current_symbols = await self.repository.list_premium_strategy_watchlist_theme_symbols(theme.id)
            else:
                current_symbols = await self.repository.list_user_watchlist_theme_symbols(theme.id)
            merged_symbols = current_symbols[:]
            for symbol in resolved_symbols:
                if symbol not in merged_symbols:
                    merged_symbols.append(symbol)
            if self.bot_kind == "premium":
                await self.repository.save_premium_strategy_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    theme_name=theme.theme_name,
                    symbols=merged_symbols[: self.WATCHLIST_LIMIT],
                    metadata={"source": "manual_theme_add"},
                )
            else:
                await self.repository.save_user_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    theme_name=theme.theme_name,
                    symbols=merged_symbols[: self.WATCHLIST_LIMIT],
                    metadata={"source": "manual_theme_add"},
                )
            await self._send_watchlist_themes_manager(user)
            return True
        if session.action == "rename" and session.theme_name:
            if self.bot_kind == "premium":
                renamed = await self.repository.rename_premium_strategy_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=strategy_key,
                    old_name=session.theme_name,
                    new_name=payload,
                )
            else:
                renamed = await self.repository.rename_user_watchlist_theme(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    old_name=session.theme_name,
                    new_name=payload,
                )
            if renamed and settings.active_custom_theme_name == session.theme_name:
                await self._save_user_settings(
                    user=user,
                    current_settings=settings,
                    active_custom_theme_name=payload,
                )
            await self._send_watchlist_themes_manager(user)
            return True
        return False

    async def _activate_builtin_theme(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        theme_key: str,
    ) -> None:
        if theme_key == "custom":
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                active_watchlist_theme="custom",
                active_custom_theme_name=None,
                watchlist_only=True,
            )
            return
        if theme_key not in BUILTIN_WATCHLIST_THEMES:
            return
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            active_watchlist_theme=theme_key,
            active_custom_theme_name=None,
            watchlist_only=True,
        )

    async def _activate_saved_theme(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        theme_id: int,
    ) -> bool:
        if self.bot_kind == "premium":
            themes = await self.repository.list_premium_strategy_watchlist_themes(
                user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=self._resolved_active_strategy_key(current_settings) or "rsi",
            )
        else:
            themes = await self.repository.list_user_watchlist_themes(user.telegram_user_id, bot_kind=self.bot_kind)
        theme = next((item for item in themes if item.id == theme_id), None)
        if theme is None:
            return False
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            active_watchlist_theme="custom",
            active_custom_theme_name=theme.theme_name,
            watchlist_only=True,
        )
        return True

    async def _change_delivery_mode(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        mode: str,
        *,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        if mode not in {"instant", "digest", "quiet"}:
            return
        previous_mode = current_settings.delivery_mode
        now = utc_now()
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            delivery_mode=mode,
            delivery_mode_changed_at=now,
        )
        if previous_mode in {"digest", "quiet"} and mode == "instant":
            since = current_settings.delivery_mode_changed_at or (now - timedelta(hours=24))
            await self._send_resume_summary(user, since=since)
        else:
            await self._send_delivery_center(
                user,
                origin=origin or self._hub_origin_for(user.telegram_user_id, section="delivery"),
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )

    async def _apply_quiet_hours_preset(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        preset_key: str,
        *,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        draft = apply_quiet_hours_preset({}, preset_key)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            quiet_hours_start_minute=draft.get("quiet_hours_start_minute"),
            quiet_hours_end_minute=draft.get("quiet_hours_end_minute"),
        )
        await self._send_delivery_center(
            user,
            origin=origin or self._hub_origin_for(user.telegram_user_id, section="delivery"),
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _apply_snooze_action(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        action: str,
        *,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        now = utc_now()
        if action == "resume":
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                snooze_until=now,
                snooze_started_at=None,
                snooze_label=None,
            )
            since = current_settings.snooze_started_at or (now - timedelta(hours=24))
            await self._send_resume_summary(user, since=since)
            return
        local_now = now.astimezone(self.settings.timezone)
        if action == "1h":
            snooze_until = now + timedelta(hours=1)
        elif action == "8h":
            snooze_until = now + timedelta(hours=8)
        elif action == "tomorrow":
            tomorrow = (local_now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
            snooze_until = tomorrow.astimezone(now.tzinfo)
        else:
            tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            snooze_until = tomorrow.astimezone(now.tzinfo)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            snooze_until=snooze_until,
            snooze_started_at=now,
            snooze_label=action,
        )
        await self._send_delivery_center(
            user,
            origin=origin or self._hub_origin_for(user.telegram_user_id, section="delivery"),
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    def _delivered_record_strategy_key(
        self,
        record: DeliveredSignalRecord,
        *,
        alerts_by_id: dict[int, AlertRecord],
    ) -> str:
        strategy_key = str(record.metadata.get("strategy_key") or "").strip().lower()
        if strategy_key in self.STRATEGY_KEYS:
            return strategy_key
        if record.alert_id is not None:
            alert = alerts_by_id.get(int(record.alert_id))
            if alert is not None:
                return self._alert_strategy_key(alert)
        return "rsi"

    async def _load_delivered_alert_bundle(
        self,
        user: PrivateBotUserRecord,
        *,
        settings: UserSettingsRecord,
        since: datetime | None = None,
        limit: int = 300,
        filter_to_active_strategy: bool = True,
    ) -> _DeliveredAlertBundle:
        deliveries = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            since=since,
            limit=limit,
        )
        alert_ids = [
            int(record.alert_id)
            for record in deliveries
            if record.alert_id is not None
        ]
        alerts = await self.repository.list_alerts_by_ids(alert_ids)
        alerts_by_id = {alert.id: alert for alert in alerts}
        followups = await self.repository.list_latest_followup_results_for_alert_ids(alert_ids)
        followups_by_alert_id = {item.alert_id: item for item in followups}
        if self.bot_kind == "premium" and filter_to_active_strategy:
            active_strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
            deliveries = [
                record
                for record in deliveries
                if not record.message_kind.startswith(("alert", "followup:"))
                or self._delivered_record_strategy_key(record, alerts_by_id=alerts_by_id) == active_strategy_key
            ]
        return _DeliveredAlertBundle(
            deliveries=deliveries,
            alerts_by_id=alerts_by_id,
            followups_by_alert_id=followups_by_alert_id,
        )

    def _enrich_delivered_record(
        self,
        record: DeliveredSignalRecord,
        *,
        alerts_by_id: dict[int, AlertRecord],
        followups_by_alert_id: dict[int, FollowUpResultRecord],
    ) -> DeliveredSignalRecord:
        metadata = dict(record.metadata)
        if record.alert_id is not None:
            alert = alerts_by_id.get(int(record.alert_id))
            if alert is not None:
                metadata.setdefault("symbol", normalize_symbol(alert.symbol))
                metadata.setdefault("score", alert.score)
                metadata.setdefault("strategy_key", self._alert_strategy_key(alert))
            followup = followups_by_alert_id.get(int(record.alert_id))
            if followup is not None:
                metadata.setdefault("stage", followup.stage)
                metadata.setdefault("move_pct", followup.move_pct)
                metadata.setdefault("favorable_move_pct", self._followup_favorable_move(followup))
        return replace(record, metadata=metadata)

    async def _collect_window_activity(
        self,
        user: PrivateBotUserRecord,
        *,
        settings: UserSettingsRecord,
        start,
        end,
        alert_limit: int,
        followup_limit: int,
    ) -> tuple[list[AlertRecord], list[AlertRecord], list[FollowUpResultRecord]]:
        language = self._language_code(settings)
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        active_strategy_key = self._resolved_active_strategy_key(settings) or "rsi"
        watchlist_symbols = set(
            await self._watchlist_symbols_for_strategy(
                user.telegram_user_id,
                strategy_key=active_strategy_key,
                settings=settings,
            )
        )
        favorite_symbols = set(await self._global_favorite_symbols(user.telegram_user_id))
        alerts = await self.repository.list_alerts_between(
            start=start,
            end=end,
            min_score=setup_state.min_score,
            min_quote_volume=setup_state.min_quote_volume,
            limit=alert_limit,
        )
        filtered_alerts = [
            alert
            for alert in alerts
            if self._alert_strategy_key(alert) == active_strategy_key and self._alert_record_matches_user_settings(
                alert,
                settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                strong_only=False,
            )[0]
        ]
        watchlist_alerts = [
            alert for alert in filtered_alerts if normalize_symbol(alert.symbol) in watchlist_symbols
        ]
        followups = await self.repository.list_followup_results_between(
            start=start,
            end=end,
            limit=followup_limit,
        )
        filtered_followups = [
            item
            for item in followups
            if self._followup_strategy_key(item) == active_strategy_key
            and (normalize_symbol(item.symbol) in watchlist_symbols or item.score >= setup_state.min_score)
        ]
        return filtered_alerts, watchlist_alerts, filtered_followups

    async def _collect_recap_activity(
        self,
        user: PrivateBotUserRecord,
        *,
        settings: UserSettingsRecord | None = None,
        strategy_scoped: bool = False,
        start: datetime,
        end: datetime,
        alert_limit: int,
        followup_limit: int,
    ) -> tuple[list[AlertRecord], list[FollowUpResultRecord]]:
        effective_settings = settings or await self._ensure_user_settings(user.telegram_user_id)
        bundle = await self._load_delivered_alert_bundle(
            user,
            settings=effective_settings,
            since=start,
            limit=max(alert_limit * 16, 1500),
            filter_to_active_strategy=strategy_scoped,
        )
        delivered_alerts: list[tuple[datetime, AlertRecord]] = []
        followups: list[FollowUpResultRecord] = []
        seen_alert_ids: set[int] = set()
        for record in bundle.deliveries:
            if record.message_kind != "alert":
                continue
            if record.alert_id is None or not bool(record.metadata.get("sent", True)):
                continue
            alert_id = int(record.alert_id)
            if alert_id in seen_alert_ids:
                continue
            alert = bundle.alerts_by_id.get(alert_id)
            if alert is None:
                continue
            seen_alert_ids.add(alert_id)
            delivered_alerts.append((record.delivered_at, alert))
            followup = bundle.followups_by_alert_id.get(alert_id)
            if followup is None or followup.observed_at >= end:
                continue
            followups.append(followup)

        delivered_alerts.sort(
            key=lambda item: (
                item[0].timestamp(),
                item[1].score,
            ),
            reverse=True,
        )
        followups.sort(
            key=lambda item: (
                self._followup_favorable_move(item),
                item.score,
                item.observed_at.timestamp(),
            ),
            reverse=True,
        )
        return [alert for _, alert in delivered_alerts[:alert_limit]], followups[:followup_limit]

    async def _maybe_send_return_summary(
        self,
        user: PrivateBotUserRecord,
        *,
        previous_last_seen_at,
    ) -> None:
        if previous_last_seen_at is None:
            return
        now = utc_now()
        settings = await self._ensure_user_settings(user.telegram_user_id)
        if settings.onboarding_completed_at is None:
            return
        if is_snoozed(settings, now=now):
            return
        if now - previous_last_seen_at < timedelta(hours=8):
            return
        if settings.last_resume_summary_at is not None and settings.last_resume_summary_at >= previous_last_seen_at:
            return
        since = max(previous_last_seen_at, now - timedelta(days=7))
        await self._send_resume_summary(user, since=since)

    async def _send_scheduled_recap_if_due(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        period: str,
    ) -> None:
        mode = str(current_settings.delivery_mode or "instant").strip().lower()
        if mode == "instant":
            return
        now = utc_now()
        local_now = now.astimezone(self.settings.timezone)
        if period == "daily":
            if local_now.hour < 21:
                return
            last_sent_at = current_settings.last_daily_recap_at
            if last_sent_at is not None and last_sent_at.astimezone(self.settings.timezone).date() == local_now.date():
                return
        else:
            if local_now.weekday() != 6 or local_now.hour < 20:
                return
            last_sent_at = current_settings.last_weekly_recap_at
            if last_sent_at is not None:
                last_week = last_sent_at.astimezone(self.settings.timezone).isocalendar()[:2]
                current_week = local_now.isocalendar()[:2]
                if last_week == current_week:
                    return
        await self._send_recap(
            user,
            period=period,
            skip_if_empty=True,
            current_settings=current_settings,
            strategy_scoped=self.bot_kind == "premium",
        )

    async def _send_resume_summary(
        self,
        user: PrivateBotUserRecord,
        *,
        since,
        current_settings: UserSettingsRecord | None = None,
    ) -> None:
        now = utc_now()
        settings = current_settings or await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        filtered_alerts, watchlist_alerts, filtered_followups = await self._collect_window_activity(
            user,
            settings=settings,
            start=since,
            end=now + timedelta(minutes=1),
            alert_limit=40,
            followup_limit=20,
        )
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=format_resume_message(
                alert_count=len(filtered_alerts),
                strongest_alerts=filtered_alerts[:3],
                watchlist_alerts=watchlist_alerts[:2],
                followups=filtered_followups[:2],
                language_code=language,
            ),
            parse_mode="HTML",
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="stats",
                include_gold_button=self.settings.gold_alerts_enabled,
                premium=self.bot_kind == "premium",
                gold_alerts_enabled=settings.gold_alerts_enabled,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="statshub",
                    default=self._strategy_hub_callback_data(settings),
                ),
            ),
        )
        if self.bot_kind == "premium":
            await self._save_strategy_runtime_state(
                user=user,
                current_settings=settings,
                last_resume_summary_at=now,
            )
        else:
            await self._save_user_settings(
                user=user,
                current_settings=settings,
                last_resume_summary_at=now,
            )

    async def _send_recap(
        self,
        user: PrivateBotUserRecord,
        *,
        period: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        skip_if_empty: bool = False,
        current_settings: UserSettingsRecord | None = None,
        strategy_scoped: bool | None = None,
    ) -> bool:
        now = utc_now()
        start = now - (timedelta(days=1) if period == "daily" else timedelta(days=7))
        if current_settings is None:
            settings, resolved_origin = await self._settings_for_hub_section(
                user.telegram_user_id,
                section="stats",
            )
        else:
            settings = current_settings
            resolved_origin = self._hub_origin_for(user.telegram_user_id, section="stats")
        if strategy_scoped is None:
            strategy_scoped = self.bot_kind == "premium" and self._is_strategy_origin(resolved_origin)
        language = self._language_code(settings)
        recap_alerts, recap_followups = await self._collect_recap_activity(
            user,
            settings=settings,
            strategy_scoped=strategy_scoped,
            start=start,
            end=now + timedelta(minutes=1),
            alert_limit=50,
            followup_limit=20,
        )
        recap_followups = self._select_recap_followups(recap_followups, period=period)
        if skip_if_empty and not recap_alerts and not recap_followups:
            return False
        title = premium_text(language, "daily_recap_title" if period == "daily" else "weekly_recap_title")
        no_winners_text = premium_text(language, "daily_recap_empty" if period == "daily" else "recap_waiting_followups")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_recap_message(
                title=title,
                recent_alerts=recap_alerts[:3],
                followups=recap_followups,
                language_code=language,
                delivered_alerts_count=len(recap_alerts),
                followups_title=(
                    premium_text(language, "recap_best_followups")
                    if recap_followups
                    else None
                ),
                recent_alerts_title=premium_text(language, "recap_recent_alerts"),
                followups_as_winners=True,
                empty_text=premium_text(language, "recap_no_deliveries"),
                no_winners_text=no_winners_text,
                strategy_label=(
                    self._strategy_label(self._resolved_active_strategy_key(settings), language_code=language)
                    if self.bot_kind == "premium" and strategy_scoped
                    else None
                ),
            ),
            reply_markup=build_section_hub_keyboard(
                language_code=language,
                section="stats",
                include_gold_button=self.settings.gold_alerts_enabled,
                premium=self.bot_kind == "premium",
                gold_alerts_enabled=settings.gold_alerts_enabled,
                back_callback_data=self._screen_back_callback(
                    user.telegram_user_id,
                    screen="statshub",
                    default=self._navigation_back_callback(
                        user.telegram_user_id,
                        settings=settings,
                        screen="statshub",
                        section="stats",
                    ),
                ),
            ),
            edit_message_id=edit_message_id,
        )
        if self.bot_kind == "premium":
            await self._save_strategy_runtime_state(
                user=user,
                current_settings=settings,
                last_daily_recap_at=now if period == "daily" else ...,
                last_weekly_recap_at=now if period == "weekly" else ...,
            )
        else:
            await self._save_user_settings(
                user=user,
                current_settings=settings,
                last_daily_recap_at=now if period == "daily" else ...,
                last_weekly_recap_at=now if period == "weekly" else ...,
            )
        return True

    def _followup_state(self, result: FollowUpResultRecord) -> str:
        state = str(result.metadata.get("thesis_result_state") or "").strip().lower()
        if state:
            return state
        return evaluate_thesis_result(result.direction, result.move_pct).thesis_result_state

    def _followup_favorable_move(self, result: FollowUpResultRecord) -> float:
        favorable = result.metadata.get("favorable_move_pct")
        if isinstance(favorable, (int, float)):
            return float(favorable)
        return evaluate_thesis_result(result.direction, result.move_pct).favorable_move_pct

    def _select_recap_followups(
        self,
        followups: list[FollowUpResultRecord],
        *,
        period: str,
    ) -> list[FollowUpResultRecord]:
        best_by_symbol: dict[str, FollowUpResultRecord] = {}
        for result in followups:
            if self._followup_state(result) != "favorable":
                continue
            favorable_move = self._followup_favorable_move(result)
            if favorable_move <= 0.0:
                continue
            symbol = normalize_symbol(result.symbol)
            current_best = best_by_symbol.get(symbol)
            if current_best is None:
                best_by_symbol[symbol] = result
                continue
            current_best_move = self._followup_favorable_move(current_best)
            if favorable_move > current_best_move:
                best_by_symbol[symbol] = result
                continue
            if favorable_move == current_best_move and result.observed_at > current_best.observed_at:
                best_by_symbol[symbol] = result

        return sorted(
            best_by_symbol.values(),
            key=lambda item: (
                self._followup_favorable_move(item),
                item.score,
                item.observed_at.timestamp(),
            ),
            reverse=True,
        )[:4]

    def _onboarding_included_gold(self) -> bool:
        return self.bot_kind == "premium" and self.settings.gold_alerts_enabled

    async def _load_onboarding_state(
        self,
        telegram_user_id: int,
        *,
        preferred_language: str | None = None,
        restart: bool = False,
    ) -> tuple[str, dict[str, object]]:
        include_gold = self._onboarding_included_gold()
        current_settings = await self._ensure_user_settings(
            telegram_user_id,
            preferred_language=preferred_language,
        )
        strategy_key = resolve_quick_setup_strategy_key(
            self._resolved_active_strategy_key(current_settings) or "rsi",
        )
        base_draft = empty_onboarding_draft(
            preferred_language or current_settings.language_code or "en",
            strategy_key=strategy_key,
        )
        base_draft.update(
            {
                "language_code": normalize_language(preferred_language or current_settings.language_code),
                "signal_profile": str(current_settings.base_signal_profile or current_settings.signal_profile or "balanced"),
                "rsi_mode": self._rsi_mode_for_values(
                    float(current_settings.rsi_oversold or 30.0),
                    float(current_settings.rsi_overbought or 70.0),
                ),
                "min_quote_volume": float(current_settings.min_quote_volume)
                if current_settings.min_quote_volume is not None
                else None,
                "direction_filter": str(current_settings.direction_filter or "both"),
                "favorite_symbols": await self._favorite_symbols(telegram_user_id),
                "watchlist_only": bool(current_settings.watchlist_only),
                "delivery_mode": str(current_settings.delivery_mode or "instant"),
                "followup_delivery_enabled": bool(current_settings.followup_delivery_enabled),
                "gold_alerts_enabled": bool(current_settings.gold_alerts_enabled),
                "quiet_hours_start_minute": current_settings.quiet_hours_start_minute,
                "quiet_hours_end_minute": current_settings.quiet_hours_end_minute,
            }
        )
        first_step = onboarding_steps(include_gold=include_gold, strategy_key=strategy_key)[0]
        if restart:
            draft = {**base_draft}
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=telegram_user_id,
                bot_kind=self.bot_kind,
                step=first_step,
                draft=draft,
            )
            return first_step, draft
        state = await self.repository.get_user_onboarding_state(telegram_user_id, bot_kind=self.bot_kind)
        if state is None:
            draft = {**base_draft}
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=telegram_user_id,
                bot_kind=self.bot_kind,
                step=first_step,
                draft=draft,
            )
            return first_step, draft
        draft = {**base_draft, **state.draft}
        strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
        step = state.step if state.step in onboarding_steps(include_gold=include_gold, strategy_key=strategy_key) else first_step
        return step, draft

    def _onboarding_thread_message_ids(self, draft: dict[str, object] | None) -> list[int]:
        raw_ids = draft.get("_thread_message_ids") if isinstance(draft, dict) else None
        if not isinstance(raw_ids, list):
            return []
        seen: set[int] = set()
        message_ids: list[int] = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, int) or raw_id <= 0 or raw_id in seen:
                continue
            seen.add(raw_id)
            message_ids.append(raw_id)
        return message_ids[-12:]

    async def _delete_cleanup_records_for_messages(
        self,
        *,
        telegram_user_id: int,
        message_ids: list[int],
    ) -> None:
        normalized_ids = {int(message_id) for message_id in message_ids if int(message_id) > 0}
        if not normalized_ids:
            return
        history = await self.repository.list_delivered_signals(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.CHAT_CLEANUP_CONTENT_KIND,
            message_kind_prefix=self.CHAT_CLEANUP_MESSAGE_KIND,
            limit=max(self._chat_cleanup_keep_messages() + len(normalized_ids) + 30, 100),
        )
        record_ids = [record.id for record in history if record.telegram_message_id in normalized_ids]
        if record_ids:
            await self.repository.delete_delivered_signal_records(record_ids)

    async def _cleanup_onboarding_thread(
        self,
        *,
        telegram_user_id: int,
        chat_id: str,
        draft: dict[str, object] | None,
        keep_message_id: int | None = None,
    ) -> list[int]:
        tracked_ids = self._onboarding_thread_message_ids(draft)
        if not tracked_ids:
            return []
        delete_ids = [message_id for message_id in tracked_ids if message_id != keep_message_id]
        for message_id in delete_ids:
            with suppress(Exception):
                await self.telegram_client.delete_message(chat_id=chat_id, message_id=message_id)
        await self._delete_cleanup_records_for_messages(
            telegram_user_id=telegram_user_id,
            message_ids=delete_ids,
        )
        return [message_id for message_id in tracked_ids if message_id == keep_message_id]

    async def _remember_onboarding_message(
        self,
        *,
        telegram_user_id: int,
        step: str,
        draft: dict[str, object],
        message_id: int | None,
    ) -> dict[str, object]:
        if message_id is None or message_id <= 0:
            return draft
        tracked_ids = self._onboarding_thread_message_ids(draft)
        if message_id in tracked_ids:
            return draft
        updated_draft = {**draft, "_thread_message_ids": [*tracked_ids, message_id][-12:]}
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            step=step,
            draft=updated_draft,
        )
        return updated_draft

    async def _send_onboarding_step(
        self,
        telegram_user_id: int,
        *,
        step: str | None = None,
        draft: dict[str, object] | None = None,
        preferred_language: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        include_gold = self._onboarding_included_gold()
        loaded_step, loaded_draft = await self._load_onboarding_state(
            telegram_user_id,
            preferred_language=preferred_language,
        )
        effective_step = step or loaded_step
        effective_draft = {**loaded_draft, **(draft or {})}
        language = normalize_language(str(effective_draft.get("language_code") or preferred_language or "en"))
        strategy_key = resolve_quick_setup_strategy_key(effective_draft.get("strategy_key"))
        message_ref = await self._send_or_edit_text(
            chat_id=chat_id or str(telegram_user_id),
            text=format_onboarding_message(
                step=effective_step,
                draft=effective_draft,
                language_code=language,
                include_gold=include_gold,
            ),
            reply_markup=build_onboarding_step_keyboard(
                language_code=language,
                step=effective_step,
                include_gold=include_gold,
                strategy_key=strategy_key,
                draft=effective_draft,
            ),
            edit_message_id=edit_message_id,
        )
        await self._remember_onboarding_message(
            telegram_user_id=telegram_user_id,
            step=effective_step,
            draft=effective_draft,
            message_id=message_ref,
        )

    async def _start_or_resume_onboarding(
        self,
        telegram_user_id: int,
        *,
        preferred_language: str | None = None,
        restart: bool = False,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        if restart:
            existing_state = await self.repository.get_user_onboarding_state(telegram_user_id, bot_kind=self.bot_kind)
            if existing_state is not None and existing_state.completed_at is None:
                await self._cleanup_onboarding_thread(
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id or str(telegram_user_id),
                    draft=existing_state.draft,
                    keep_message_id=edit_message_id,
                )
        step, draft = await self._load_onboarding_state(
            telegram_user_id,
            preferred_language=preferred_language,
            restart=restart,
        )
        await self._send_onboarding_step(
            telegram_user_id,
            step=step,
            draft=draft,
            preferred_language=preferred_language,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _apply_onboarding_choice(
        self,
        user: PrivateBotUserRecord,
        *,
        step: str,
        value: str,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        include_gold = self._onboarding_included_gold()
        current_step, draft = await self._load_onboarding_state(
            user.telegram_user_id,
            preferred_language=None,
        )
        updated = {**draft}
        strategy_key = resolve_quick_setup_strategy_key(updated.get("strategy_key"))
        available_steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy_key)
        if step == "back":
            target_step = value if value in available_steps else previous_onboarding_step(
                current_step,
                include_gold=include_gold,
                strategy_key=strategy_key,
            )
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                step=target_step,
                draft=updated,
            )
            await self._send_onboarding_step(
                user.telegram_user_id,
                step=target_step,
                draft=updated,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        advance = True
        if step == "preset":
            updated["signal_profile"] = value
        elif step == "rsi_mode":
            updated["rsi_mode"] = value
        elif step == "volume":
            try:
                updated["min_quote_volume"] = max(float(value), 0.0)
            except ValueError:
                advance = False
        elif step == "direction":
            updated["direction_filter"] = value
        elif step == "symbols":
            symbols = [str(item) for item in updated.get("favorite_symbols", []) if str(item)]
            if value in {"skip", "done"}:
                pass
            elif value == "clear":
                updated["favorite_symbols"] = []
                advance = False
            elif value == "use-defaults":
                updated["favorite_symbols"] = list(strategy_symbol_suggestions(strategy_key))
                advance = False
            else:
                normalized = normalize_symbol(value)
                if normalized and normalized not in symbols:
                    symbols.append(normalized)
                updated["favorite_symbols"] = symbols[:12]
                advance = False
        elif step == "universe":
            updated["watchlist_only"] = value == "watchlist"
        elif step == "delivery":
            updated["delivery_mode"] = value
        elif step == "followups":
            updated["followup_delivery_enabled"] = value == "on"
        elif step == "summary":
            await self._complete_onboarding(user, draft=updated, enable_delivery=value == "start")
            return
        elif step == "gold":
            updated["gold_alerts_enabled"] = value == "on"
        elif step == "quiet_hours":
            updated = apply_quiet_hours_preset(updated, value)
        elif step == "done":
            await self._complete_onboarding(user, draft=updated, enable_delivery=value == "start")
            return
        next_step_name = (
            next_onboarding_step(step, include_gold=include_gold, strategy_key=strategy_key)
            if advance
            else step
        )
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            step=next_step_name,
            draft=updated,
        )
        await self._send_onboarding_step(
            user.telegram_user_id,
            step=next_step_name,
            draft=updated,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _handle_onboarding_text(
        self,
        user: PrivateBotUserRecord,
        text: str,
    ) -> bool:
        state = await self.repository.get_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
        if state is None or state.completed_at is not None:
            return False
        if state.step == "v2_symbols" and bool(state.draft.get("v2")):
            symbols = parse_favorite_symbols_input(text)
            symbols = await self._validate_v2_symbols(symbols)
            if not symbols:
                settings = await self._ensure_shell_settings(user.telegram_user_id)
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=format_invalid_symbols_message(language_code=self._language_code(settings)),
                    parse_mode="HTML",
                )
                await self._send_v2_onboarding_step(user, step="symbols", draft=dict(state.draft))
                return True
            draft = dict(state.draft)
            if draft.get("context") == "flow_assets":
                await self._apply_v2_assets(
                    user,
                    market_key="manual",
                    custom_symbols=symbols,
                    sync_flow=True,
                )
                await self.repository.delete_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
                await self._send_v2_flow(user)
                return True
            settings = await self._ensure_shell_settings(user.telegram_user_id)
            language = self._language_code(settings)
            draft["symbols"] = symbols
            draft["market"] = "manual"
            draft["market_label"] = v2_choice_label("market", "manual", language_code=language)
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                step="v2_quality",
                draft=draft,
            )
            await self._record_funnel_event(
                "onboarding_step_completed",
                user.telegram_user_id,
                context="v2:market",
                language_code=language,
                screen="onboarding_market",
            )
            await self._send_v2_onboarding_step(user, step="quality", draft=draft)
            return True
        draft = {**empty_onboarding_draft(), **state.draft}
        strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
        if state.step == "symbols":
            symbols = parse_favorite_symbols_input(text)
            if not symbols:
                await self._send_onboarding_step(
                    user.telegram_user_id,
                    step="symbols",
                    draft=draft,
                )
                return True
            draft["favorite_symbols"] = symbols
            next_step_name = next_onboarding_step(
                "symbols",
                include_gold=self._onboarding_included_gold(),
                strategy_key=strategy_key,
            )
            await self.repository.upsert_user_onboarding_state(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                step=next_step_name,
                draft=draft,
            )
            await self._send_onboarding_step(
                user.telegram_user_id,
                step=next_step_name,
                draft=draft,
            )
            return True
        return False

    async def _complete_onboarding(
        self,
        user: PrivateBotUserRecord,
        *,
        draft: dict[str, object],
        enable_delivery: bool,
    ) -> None:
        language = normalize_language(str(draft.get("language_code") or "en"))
        strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
        base_profile = str(draft.get("signal_profile") or "balanced")
        min_score, default_min_quote_volume, default_rsi_oversold, default_rsi_overbought = self._profile_defaults(base_profile)
        min_quote_volume = (
            float(draft.get("min_quote_volume"))
            if isinstance(draft.get("min_quote_volume"), (int, float))
            else default_min_quote_volume
        )
        rsi_mode = str(draft.get("rsi_mode") or "balanced").strip().lower()
        rsi_oversold, rsi_overbought = self.RSI_MODE_THRESHOLDS.get(
            rsi_mode,
            (default_rsi_oversold, default_rsi_overbought),
        )
        direction_filter = str(draft.get("direction_filter") or "both")
        favorite_symbols = [normalize_symbol(str(symbol)) for symbol in draft.get("favorite_symbols", []) if str(symbol)]
        now = utc_now()
        current_settings = await self._ensure_user_settings(user.telegram_user_id)
        watchlist_only = (
            bool(draft.get("watchlist_only", False))
            if strategy_supports_universe(strategy_key)
            else bool(current_settings.watchlist_only)
        )
        if strategy_supports_universe(strategy_key) and self.bot_kind == "premium":
            await self.repository.replace_premium_strategy_watchlist_symbols(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                strategy_key=strategy_key,
                symbols=favorite_symbols,
            )
        elif strategy_supports_universe(strategy_key):
            await self.repository.replace_user_watchlist_symbols(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                symbols=favorite_symbols,
            )
        profile = base_profile
        if (
            (strategy_supports_volume(strategy_key) and abs(min_quote_volume - default_min_quote_volume) > 0.001)
            or (strategy_supports_rsi_mode(strategy_key) and rsi_mode != self._rsi_mode_for_values(default_rsi_oversold, default_rsi_overbought))
            or direction_filter != "both"
            or (strategy_supports_universe(strategy_key) and watchlist_only != (strategy_key == "gold"))
        ):
            profile = "custom"
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            direct_signal_delivery_enabled=enable_delivery or current_settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=bool(draft.get("followup_delivery_enabled", current_settings.followup_delivery_enabled)),
            gold_alerts_enabled=current_settings.gold_alerts_enabled,
            signal_profile=profile,
            base_signal_profile=base_profile,
            preferred_min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            direction_filter=direction_filter,
            watchlist_only=watchlist_only,
            delivery_mode=str(draft.get("delivery_mode") or current_settings.delivery_mode or "instant"),
            delivery_mode_changed_at=now,
            quiet_hours_start_minute=current_settings.quiet_hours_start_minute,
            quiet_hours_end_minute=current_settings.quiet_hours_end_minute,
            active_watchlist_theme="custom" if strategy_supports_universe(strategy_key) else current_settings.active_watchlist_theme,
            active_custom_theme_name=None,
            onboarding_completed_at=now,
            language_code=language,
        )
        await self.repository.upsert_user_onboarding_state(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            step="summary",
            draft=draft,
            completed_at=now,
        )
        await self._cleanup_onboarding_thread(
            telegram_user_id=user.telegram_user_id,
            chat_id=str(user.telegram_user_id),
            draft=draft,
        )
        await self.repository.delete_user_onboarding_state(user.telegram_user_id, bot_kind=self.bot_kind)
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=format_onboarding_summary_message(
                draft=draft,
                language_code=language,
                include_gold=self._onboarding_included_gold(),
            ),
            parse_mode="HTML",
            reply_markup=build_onboarding_step_keyboard(
                language_code=language,
                step="summary",
                include_gold=self._onboarding_included_gold(),
                strategy_key=strategy_key,
                draft=draft,
            ),
        )

    async def _hide_menu(self, user: PrivateBotUserRecord) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        await self._save_user_settings(
            user=user,
            current_settings=settings,
            menu_collapsed=True,
        )
        language = self._language_code(settings)
        if self.bot_kind == "premium":
            await self._hide_reply_keyboard_if_needed(chat_id=str(user.telegram_user_id))
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "menu_collapsed"),
                parse_mode=None,
                reply_markup=None,
            )
            return
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(language, "menu_collapsed"),
            parse_mode=None,
            reply_markup=build_collapsed_menu_keyboard(language_code=language),
        )

    async def _send_access(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        back_callback_data_override: str | None = None,
    ) -> None:
        started = monotonic()
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        access_state = await self._effective_access_state_for_user(user)
        active_profile = await self._active_saved_setup(user.telegram_user_id)
        text = build_access_view_model(
            access_state=access_state,
            is_gold_enabled=self._gold_alerts_enabled_for_settings(shell_settings),
            profile_label=active_profile.name if active_profile is not None else ("Не выбран" if language == "ru" else "Not selected"),
            delivery_label=delivery_mode_label(shell_settings.delivery_mode, language_code=language),
            language_code=language,
        ).render(language_code=language)
        back_callback_data = back_callback_data_override or self._screen_back_callback(
            user.telegram_user_id,
            screen="access",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=shell_settings,
                screen="access",
            ),
        )
        if back_callback_data_override is None:
            self._remember_screen_back_callback(user.telegram_user_id, screen="setup", callback_data="ux:access")
            self._remember_screen_back_callback(user.telegram_user_id, screen="watchlist", callback_data="ux:access")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_access_inline_keyboard(
                can_renew=self._can_offer_renewal(access_state),
                language_code=language,
                renew_label=ui_text(language, "menu_renew_pro") if access_state.is_paid else ui_text(language, "menu_pay_pro"),
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="access",
        )
        await self._record_funnel_event(
            "my_access_opened",
            user.telegram_user_id,
            context="access",
            language_code=language,
            screen="my_access",
        )
        self.performance_telemetry_service.record(RouteTiming("access", user.telegram_user_id, (monotonic() - started) * 1000, True))

    async def _send_status(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        now = utc_now()
        start = now - timedelta(hours=24)
        shell_settings = await self._ensure_shell_settings(user.telegram_user_id)
        language = self._language_code(shell_settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        recent_deliveries = await self.repository.list_delivered_signals(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            since=start,
            limit=200,
        )
        alerts_last_24h = sum(1 for record in recent_deliveries if record.message_kind == "alert")
        followups_last_24h = sum(1 for record in recent_deliveries if record.message_kind.startswith("followup:"))
        latest_delivery = recent_deliveries[0] if recent_deliveries else None
        if latest_delivery is None:
            history = await self.repository.list_delivered_signals(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                content_kind=self.content_kind,
                limit=20,
            )
            latest_delivery = history[0] if history else None
        last_signal_label = await self._describe_last_private_delivery(latest_delivery, language_code=language)
        access_label = await self._access_label_for_user(user, language_code=language)
        access_state = await self._effective_access_state_for_user(user)
        active_flow_label = ", ".join(
            self._strategy_label(strategy_key, language_code=language)
            for strategy_key in self._enabled_strategy_keys(shell_settings)
        )
        if not active_flow_label:
            active_flow_label = "не выбрано" if language == "ru" else "not selected"
        status_text = format_status_message(
            timeframe=self.settings.scan_timeframe,
            access_state_line=self._access_state_line(access_state, language_code=language),
            access_label=access_label,
            alerts_last_24h=alerts_last_24h,
            followups_last_24h=followups_last_24h,
            last_signal_label=last_signal_label,
            feed_label=active_flow_label,
            alerts_state_label=ui_text(language, "status_on" if shell_settings.direct_signal_delivery_enabled else "status_off"),
            followups_state_label=ui_text(language, "status_on" if shell_settings.followup_delivery_enabled else "status_off"),
            gold_state_label=ui_text(language, "status_on" if self._gold_alerts_enabled_for_settings(shell_settings) else "status_off"),
            language_code=language,
        )
        LOGGER.info(
            "PRIVATE status requested user=%s alerts_delivered_24h=%s followups_delivered_24h=%s last_signal=%s source=delivered_signals/%s bot_kind=%s",
            user.telegram_user_id,
            alerts_last_24h,
            followups_last_24h,
            last_signal_label,
            self.content_kind,
            self.bot_kind,
        )
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="status",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=shell_settings,
                screen="status",
            ),
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=status_text,
            reply_markup=build_status_inline_keyboard(
                language_code=language,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="status",
        )

    async def _send_signal_setup(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        active_strategy_key = resolve_quick_setup_strategy_key(self._resolved_active_strategy_key(settings) or "rsi")
        show_gold_controls = self.bot_kind == "premium" and active_strategy_key == "gold"
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="setup",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=settings,
                screen="setup",
            ),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="watchlist", callback_data="ux:setup")
        self._remember_screen_back_callback(user.telegram_user_id, screen="themes", callback_data="ux:setup")
        text = self._strategy_signal_setup_text(
            active_strategy_key,
            settings=settings,
            setup_state=setup_state,
            language_code=language,
            show_gold_controls=show_gold_controls,
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_signal_setup_inline_keyboard(
                language_code=language,
                strategy_key=active_strategy_key or "rsi",
                profile=setup_state.profile,
                rsi_mode=setup_state.rsi_mode,
                strategy_preferences=self._strategy_preferences(settings, strategy_key=active_strategy_key),
                min_quote_volume=setup_state.min_quote_volume,
                direction_filter=setup_state.direction_filter,
                watchlist_only=setup_state.watchlist_only,
                set_scope_active=self._set_scope_active(settings),
                set_button_label=self._set_scope_button_label(settings, language_code=language),
                include_gold_toggle=show_gold_controls,
                gold_alerts_enabled=settings.gold_alerts_enabled,
                show_reset_button=setup_state.profile == "custom",
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_watchlist(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        back_callback_data_override: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        symbols = await self._favorite_symbols(user.telegram_user_id)
        back_callback_data = back_callback_data_override or self._screen_back_callback(
            user.telegram_user_id,
            screen="watchlist",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=settings,
                screen="watchlist",
                section="watchlists",
            ),
        )
        if back_callback_data_override is None:
            self._remember_screen_back_callback(user.telegram_user_id, screen="analyze", callback_data="ux:watchlist")
            self._remember_screen_back_callback(user.telegram_user_id, screen="setup", callback_data="ux:watchlist")
        text = format_watchlist_message(
            symbols=symbols,
            watchlist_only=settings.watchlist_only,
            active_theme_label=self._active_watchlist_theme_label(settings, language_code=language),
            tracking_label=tracking_scope_label(settings, language_code=language),
            builtin_theme_active=self._set_scope_active(settings),
            language_code=language,
        )
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=text,
            reply_markup=build_watchlist_inline_keyboard(
                language_code=language,
                symbols=symbols,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )

    async def _send_analyze_symbol_help(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        back_callback_data_override: str | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=user.telegram_user_id,
            chat_id=chat_id or str(user.telegram_user_id),
        )
        ai_mode = self.bot_kind == "premium" and await self._has_premium_access(user)
        back_callback_data = back_callback_data_override or self._screen_back_callback(
            user.telegram_user_id,
            screen="analyze",
            default=self._navigation_back_callback(
                user.telegram_user_id,
                settings=settings,
                screen="analyze",
                section="signals",
            ),
        )
        self._remember_screen_back_callback(user.telegram_user_id, screen="watchlist", callback_data="ux:analyze")
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_analyze_symbol_message(
                examples=["BTC", "ETH 1h", "XAUUSD", "SOL 4h"],
                ai_mode=ai_mode,
                language_code=language,
            ),
            reply_markup=build_analyze_symbol_inline_keyboard(
                language_code=language,
                symbols=[],
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
            cleanup_branch="analyze",
        )

    async def _send_pro_link(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=format_pro_link_message(pro_channel=self.settings.pro_channel, language_code=language),
            parse_mode="HTML",
            reply_markup=self._build_onboarding_keyboard(language_code=language),
        )
        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "menu_updated"),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user_id),
        )

    async def _send_results_link(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "results_channel_message", target=self.settings.results_channel),
            parse_mode=None,
            reply_markup=build_channel_inline_keyboard(
                label=ui_text(language, "menu_results_channel"),
                target=self.settings.results_channel,
            ),
        )

    async def _send_public_link(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "public_channel_message", target=self.settings.public_channel),
            parse_mode=None,
            reply_markup=build_channel_inline_keyboard(
                label=ui_text(language, "menu_public_channel"),
                target=self.settings.public_channel,
            ),
        )

    async def _send_community_link(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        community_target = self._community_target()
        if not community_target:
            await self._send_chat_message(
                chat_id=str(user_id),
                text=ui_text(language, "community_not_configured"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user_id),
            )
            return
        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "community_chat"),
            parse_mode=None,
            reply_markup=build_channel_inline_keyboard(
                label=ui_text(language, "menu_community_chat"),
                target=community_target,
            ),
        )

    async def _send_ai_pick(self, user: PrivateBotUserRecord) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        selection = await self._pick_signal_for_user(
            user,
            strong_only=True,
            limit=max(self.settings.private_bot_strong_signals_limit * 3, 12),
        )
        selection = [item for item in selection if not self._is_gold_alert_record(item.alert)]
        if not selection:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "no_strong_ai_pick"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        choice = selection[0]
        loading_handle = await self.interactive_alert_service.start_chat_loading_indicator(
            chat_id=str(user.telegram_user_id),
            title=ui_text(language, "loading_ai_title"),
            subtitle=ui_text(language, "loading_ai_subtitle"),
            language_code=language,
        )
        try:
            progress_callback = self.interactive_alert_service.build_loading_progress_callback(loading_handle)
            analysis_text = await self.interactive_alert_service.generate_analysis_text(
                symbol=choice.alert.symbol,
                timeframe=choice.alert.timeframe,
                alert_id=choice.alert.id,
                destination_kind=self.destination_kind,
                language=language,
                progress_callback=progress_callback,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=format_interactive_analysis_message(
                    symbol=choice.alert.symbol,
                    timeframe=choice.alert.timeframe,
                    analysis_text=analysis_text,
                    language_code=language,
                ),
                parse_mode="HTML",
                reply_markup=build_detail_card_keyboard(include_delete=True, language_code=language),
            )
        except Exception:
            LOGGER.exception(
                "Failed to prepare private menu AI analysis user=%s symbol=%s alert_id=%s",
                user.telegram_user_id,
                choice.alert.symbol,
                choice.alert.id,
            )
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "ai_pick_failed"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
        finally:
            await self.interactive_alert_service.stop_loading_indicator(
                loading_handle,
                final_stage="Анализ готов" if language == "ru" else "Analysis ready",
            )

    async def _send_recent_signals(
        self,
        user: PrivateBotUserRecord,
        *,
        strong_only: bool,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        selections = await self._pick_signal_for_user(
            user,
            strong_only=strong_only,
            limit=self._signal_list_limit(strong_only=strong_only),
        )
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if strong_only:
            await self._record_funnel_event(
                "strong_setups_opened",
                user.telegram_user_id,
                context="signals",
                language_code=language,
                screen="strong_setups",
            )
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        watchlist_symbols = await self._watchlist_symbols(user.telegram_user_id)
        if settings.watchlist_only and not watchlist_symbols:
            watchlist_back_callback = self._hub_callback_data(
                "signalshub",
                origin=self._hub_origin_for(user.telegram_user_id, section="signals", default="menu"),
            )
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=ui_text(language, "watchlist_only_empty"),
                reply_markup=build_watchlist_inline_keyboard(
                    language_code=language,
                    symbols=[],
                    back_callback_data=watchlist_back_callback,
                ),
                edit_message_id=edit_message_id,
            )
            return
        if not selections:
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=format_empty_signals_message(strong_only=strong_only, language_code=language),
                reply_markup=build_empty_signals_keyboard(language_code=language),
                edit_message_id=edit_message_id,
            )
            await self._record_funnel_event(
                "no_signals_empty_seen",
                user.telegram_user_id,
                context="strong" if strong_only else "recent",
                language_code=language,
                screen="signals_empty",
            )
            return
        sent_count = 0
        for selection in selections[:3]:
            try:
                await self._send_selection_card(user.telegram_user_id, selection)
                sent_count += 1
            except Exception:
                LOGGER.exception(
                    "Failed to send latest signal card user=%s bot=%s alert_id=%s symbol=%s",
                    user.telegram_user_id,
                    self.bot_kind,
                    selection.alert.id,
                    selection.alert.symbol,
                )
        if sent_count == 0:
            await self._send_or_edit_text(
                chat_id=chat_id or str(user.telegram_user_id),
                text=ui_text(language, "signals_delivery_failed"),
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
                edit_message_id=edit_message_id,
            )

    async def _toggle_direct_delivery(
        self,
        user: PrivateBotUserRecord,
        *,
        enable: bool,
        current_settings: UserSettingsRecord | None = None,
        refresh_hub: bool = False,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = current_settings or await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not self.settings.private_bot_signal_delivery_enabled:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "alerts_disabled_global"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        await self._save_user_settings(
            user=user,
            current_settings=settings,
            direct_signal_delivery_enabled=enable,
        )
        if refresh_hub:
            await self._send_delivery_center(
                user,
                origin=origin or self._hub_origin_for(user.telegram_user_id, section="delivery"),
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(
                language,
                "alerts_state_changed",
                state=ui_text(language, "status_enabled" if enable else "status_disabled"),
            ),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _toggle_followup_delivery(
        self,
        user: PrivateBotUserRecord,
        *,
        enable: bool,
        current_settings: UserSettingsRecord | None = None,
        refresh_hub: bool = False,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = current_settings or await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self._save_user_settings(
            user=user,
            current_settings=settings,
            followup_delivery_enabled=enable,
        )
        if refresh_hub:
            await self._send_delivery_center(
                user,
                origin=origin or self._hub_origin_for(user.telegram_user_id, section="delivery"),
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(
                language,
                "followups_state_changed",
                state=ui_text(language, "status_enabled" if enable else "status_disabled"),
            ),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _toggle_gold_alert_delivery(
        self,
        user: PrivateBotUserRecord,
        *,
        enable: bool,
        refresh_hub: bool = False,
        origin: str | None = None,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if self.bot_kind == "premium":
            shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            assert shell_settings is not None
            enabled_keys = list(self._enabled_strategy_keys(shell_settings))
            if enable and GOLD_MASTER_STRATEGY_KEY not in enabled_keys:
                enabled_keys.append(GOLD_MASTER_STRATEGY_KEY)
                await self._ensure_premium_strategy_settings(
                    user.telegram_user_id,
                    shell_settings=shell_settings,
                    strategy_key=GOLD_MASTER_STRATEGY_KEY,
                )
            if enable:
                for strategy_key in GOLD_SUBSTRATEGY_KEYS:
                    if strategy_key not in enabled_keys:
                        enabled_keys.append(strategy_key)
                        await self._ensure_premium_strategy_settings(
                            user.telegram_user_id,
                            shell_settings=shell_settings,
                            strategy_key=strategy_key,
                        )
            if not enable and GOLD_MASTER_STRATEGY_KEY in enabled_keys:
                enabled_keys = [key for key in enabled_keys if key != GOLD_MASTER_STRATEGY_KEY]
            next_active = self._resolved_active_strategy_key(shell_settings)
            if next_active == GOLD_MASTER_STRATEGY_KEY and not enable:
                next_active = enabled_keys[0] if enabled_keys else None
            await self._save_user_settings(
                user=user,
                current_settings=settings,
                gold_alerts_enabled=enable,
                enabled_strategy_keys=tuple(enabled_keys),
                active_strategy_key=next_active,
                strategy_selector_completed_at=settings.strategy_selector_completed_at if enabled_keys else None,
            )
        else:
            await self.repository.upsert_user_settings(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                direct_signal_delivery_enabled=settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=settings.followup_delivery_enabled,
                gold_alerts_enabled=enable,
                signal_profile=settings.signal_profile,
                preferred_min_score=settings.preferred_min_score,
                min_quote_volume=settings.min_quote_volume,
                rsi_oversold=settings.rsi_oversold,
                rsi_overbought=settings.rsi_overbought,
                direction_filter=settings.direction_filter,
                watchlist_only=settings.watchlist_only,
                menu_collapsed=settings.menu_collapsed,
            )
            self._store_cached_settings(replace(settings, gold_alerts_enabled=enable))
        if refresh_hub:
            if origin == "delivery":
                await self._send_delivery_center(
                    user,
                    origin=self._hub_origin_for(user.telegram_user_id, section="delivery"),
                    chat_id=chat_id,
                    edit_message_id=edit_message_id,
                )
            else:
                await self._send_gold_center(
                    user,
                    chat_id=chat_id,
                    edit_message_id=edit_message_id,
                )
            return
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(
                language,
                "gold_state_changed",
                state=ui_text(language, "status_enabled" if enable else "status_disabled"),
            ),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _resolve_direct_delivery_target(
        self,
        user: PrivateBotUserRecord,
        normalized_text: str,
        command_token: str,
    ) -> bool:
        if self._matches_ui_label(normalized_text, "menu_alerts_on"):
            return False
        if self._matches_ui_label(normalized_text, "menu_alerts_off"):
            return True
        if command_token in {"/alerts", "/notify"}:
            settings = await self._ensure_user_settings(user.telegram_user_id)
            return not settings.direct_signal_delivery_enabled
        return True

    async def _resolve_followup_delivery_target(
        self,
        user: PrivateBotUserRecord,
        normalized_text: str,
        command_token: str,
    ) -> bool:
        if self._matches_ui_label(normalized_text, "menu_followups_on"):
            return False
        if self._matches_ui_label(normalized_text, "menu_followups_off"):
            return True
        if command_token == "/followups":
            settings = await self._ensure_user_settings(user.telegram_user_id)
            return not settings.followup_delivery_enabled
        return True

    async def _resolve_gold_delivery_target(
        self,
        user: PrivateBotUserRecord,
        normalized_text: str,
        command_token: str,
    ) -> bool:
        if normalized_text in {
            "gold alerts on",
            "gold alerts: off",
            "золото: выкл",
        }:
            return True
        if normalized_text in {
            "gold alerts off",
            "gold alerts: on",
            "золото: вкл",
        }:
            return False
        if command_token == "/gold":
            settings = await self._ensure_user_settings(user.telegram_user_id)
            return not settings.gold_alerts_enabled
        return True

    async def _main_menu_keyboard_for_user(self, telegram_user_id: int) -> dict[str, object]:
        settings = await self._ensure_user_settings(telegram_user_id)
        if self.bot_kind == "premium":
            return build_hidden_menu_keyboard()
        language = self._language_code(settings)
        if settings.menu_collapsed:
            return build_collapsed_menu_keyboard(language_code=language)
        payment_label = await self._payment_menu_label_for_user(telegram_user_id)
        return build_main_menu_keyboard(
            direct_delivery_enabled=settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=settings.followup_delivery_enabled,
            include_community_button=bool(self._community_target()),
            include_gold_button=self.settings.gold_alerts_enabled,
            language_code=language,
            payment_label=payment_label,
        )

    async def _hide_reply_keyboard_if_needed(self, *, chat_id: str) -> None:
        if self.bot_kind != "premium":
            return
        try:
            result = await self.telegram_client.send_message(
                chat_id=chat_id,
                text="\u2060",
                disable_web_page_preview=True,
                parse_mode=None,
                reply_markup=build_hidden_menu_keyboard(),
            )
        except Exception:
            return
        message_id = result.get("message_id")
        if isinstance(message_id, int):
            with suppress(Exception):
                await self.telegram_client.delete_message(
                    chat_id=chat_id,
                    message_id=message_id,
                )

    async def _send_or_edit_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, object] | None,
        edit_message_id: int | None = None,
        cleanup_branch: str | None = None,
        cleanup_group: str | None = None,
    ) -> int | None:
        if edit_message_id is not None:
            try:
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=edit_message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return edit_message_id
            except Exception as exc:
                if "not modified" in str(exc).lower():
                    return edit_message_id
                LOGGER.debug(
                    "Falling back to send_message for bot=%s chat_id=%s message_id=%s",
                    self.bot_kind,
                    chat_id,
                    edit_message_id,
                    exc_info=True,
                )
        result = await self._send_chat_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            cleanup_branch=cleanup_branch,
            cleanup_group=cleanup_group,
        )
        message_id = result.get("message_id")
        return int(message_id) if isinstance(message_id, int) else None

    def _split_html_message_blocks(self, text: str, *, limit: int = 3500) -> list[str]:
        content = str(text or "").strip()
        if len(content) <= limit:
            return [content]
        chunks: list[str] = []
        current = ""
        blocks = [block for block in content.split("\n\n") if block.strip()]
        for block in blocks:
            candidate = block if not current else f"{current}\n\n{block}"
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(block) <= limit:
                current = block
                continue
            lines = [line for line in block.split("\n") if line.strip()]
            current = ""
            for line in lines:
                line_candidate = line if not current else f"{current}\n{line}"
                if len(line_candidate) <= limit:
                    current = line_candidate
                else:
                    if current:
                        chunks.append(current)
                    current = line
            if len(current) > limit:
                while len(current) > limit:
                    chunks.append(current[:limit])
                    current = current[limit:]
        if current:
            chunks.append(current)
        return chunks or [content[:limit]]

    async def _send_or_edit_text_chunks(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, object] | None,
        edit_message_id: int | None = None,
        cleanup_branch: str | None = None,
        language_code: str = "en",
    ) -> int | None:
        chunks = self._split_html_message_blocks(text)
        cleanup_group = None
        if cleanup_branch and len(chunks) > 1:
            cleanup_group = f"{cleanup_branch}:{utc_now().isoformat()}:{int(monotonic() * 1_000_000)}"
        first_message_id = await self._send_or_edit_text(
            chat_id=chat_id,
            text=chunks[0],
            reply_markup=reply_markup,
            edit_message_id=edit_message_id,
            cleanup_branch=cleanup_branch,
            cleanup_group=cleanup_group,
        )
        if len(chunks) == 1:
            return first_message_id
        total = len(chunks)
        for index, chunk in enumerate(chunks[1:], start=2):
            header = (
                f"<b>Продолжение {index}/{total}</b>\n\n"
                if normalize_language(language_code) == "ru"
                else f"<b>Continued {index}/{total}</b>\n\n"
            )
            await self._send_chat_message(
                chat_id=chat_id,
                text=f"{header}{chunk}",
                parse_mode="HTML",
                reply_markup=None,
                cleanup_branch=cleanup_branch,
                cleanup_group=cleanup_group,
            )
        return first_message_id

    def _chat_cleanup_keep_messages(self) -> int:
        raw_value = (
            self.settings.classic_bot_chat_cleanup_keep_messages
            if self.bot_kind == "classic"
            else self.settings.private_bot_chat_cleanup_keep_messages
        )
        return max(int(raw_value), 0)

    def _cleanup_candidate_user_id(
        self,
        *,
        chat_id: str,
        reply_to_message_id: int | None,
    ) -> int | None:
        if reply_to_message_id is not None:
            return None
        cleaned = str(chat_id or "").strip()
        if not cleaned or not re.fullmatch(r"-?\d+", cleaned):
            return None
        user_id = int(cleaned)
        return user_id if user_id > 0 else None

    async def _track_cleanup_message(
        self,
        *,
        chat_id: str,
        telegram_message_id: int | None,
        cleanup_branch: str | None = None,
        cleanup_group: str | None = None,
    ) -> None:
        if telegram_message_id is None:
            return
        keep_messages = self._chat_cleanup_keep_messages()
        if keep_messages <= 0:
            return
        user_id = self._cleanup_candidate_user_id(chat_id=chat_id, reply_to_message_id=None)
        if user_id is None:
            return
        await self.repository.record_delivered_signal(
            telegram_user_id=user_id,
            bot_kind=self.bot_kind,
            alert_id=None,
            content_kind=self.CHAT_CLEANUP_CONTENT_KIND,
            message_kind=self.CHAT_CLEANUP_MESSAGE_KIND,
            telegram_message_id=telegram_message_id,
            metadata={"cleanup_managed": True, "branch": cleanup_branch, "group": cleanup_group},
        )
        history = await self.repository.list_delivered_signals(
            telegram_user_id=user_id,
            bot_kind=self.bot_kind,
            content_kind=self.CHAT_CLEANUP_CONTENT_KIND,
            message_kind_prefix=self.CHAT_CLEANUP_MESSAGE_KIND,
            limit=keep_messages + 30,
        )
        stale_records: list = []
        if cleanup_branch:
            current_branch_records = []
            for record in history:
                record_branch = str(record.metadata.get("branch") or "").strip()
                if record_branch != cleanup_branch:
                    stale_records.append(record)
                    continue
                current_branch_records.append(record)
            latest_group = ""
            for record in current_branch_records:
                candidate_group = str(record.metadata.get("group") or "").strip()
                if candidate_group:
                    latest_group = candidate_group
                    break
            if latest_group:
                stale_records.extend(
                    record
                    for record in current_branch_records
                    if str(record.metadata.get("group") or "").strip() != latest_group
                )
            else:
                stale_records.extend(current_branch_records[keep_messages:])
        else:
            stale_records = history[keep_messages:]
        if not stale_records:
            return
        stale_ids: list[int] = []
        for record in stale_records:
            stale_ids.append(record.id)
            if record.telegram_message_id is None:
                continue
            with suppress(Exception):
                await self.telegram_client.delete_message(
                    chat_id=chat_id,
                    message_id=record.telegram_message_id,
                )
        await self.repository.delete_delivered_signal_records(stale_ids)

    async def _send_chat_message(
        self,
        *,
        chat_id: str,
        text: str,
        disable_web_page_preview: bool = True,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, object] | None = None,
        reply_to_message_id: int | None = None,
        cleanup: bool = True,
        cleanup_branch: str | None = None,
        cleanup_group: str | None = None,
    ) -> dict[str, object]:
        result = await self.telegram_client.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=disable_web_page_preview,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
        should_cleanup = cleanup and self._cleanup_candidate_user_id(
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        ) is not None
        if should_cleanup:
            message_id = result.get("message_id")
            await self._track_cleanup_message(
                chat_id=chat_id,
                telegram_message_id=int(message_id) if isinstance(message_id, int) else None,
                cleanup_branch=cleanup_branch,
                cleanup_group=cleanup_group,
            )
        return result

    async def _answer_callback_query(self, query_id: str, *, text: str | None = None) -> None:
        if not query_id:
            return
        with suppress(Exception):
            payload = {"callback_query_id": query_id}
            if text:
                payload["text"] = text
            await self.telegram_client.answer_callback_query(**payload)

    def _optimistic_callback_text(self, action, *, language_code: str) -> str | None:
        if action.kind == "setup":
            return ui_text(language_code, "callback_opening_setup")
        if action.kind == "watchlist":
            return ui_text(language_code, "callback_opening_watchlist")
        if action.kind == "access":
            return ui_text(language_code, "callback_opening_access")
        if action.kind == "referral":
            return ui_text(language_code, "callback_opening_referral")
        if action.kind == "analyze":
            return ui_text(language_code, "callback_opening_analyze")
        if action.kind == "goldview":
            return ui_text(language_code, "callback_opening_gold")
        if action.kind == "custom":
            if action.value == "start":
                return ui_text(language_code, "callback_opening_custom")
            if action.value == "cancel":
                return ui_text(language_code, "callback_custom_cancelled")
        if action.kind in {
            "signalshub",
            "watchhub",
            "deliveryhub",
            "statshub",
            "results_hub",
            "results_view",
            "results_admin",
            "compare_hub",
            "compare_view",
            "compare_admin",
            "learn_hub",
            "learn_page",
            "learn_guide",
            "lifecycle_hub",
            "lifecycle_view",
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
            "aihub",
            "settingshub",
            "menu",
            "status",
            "help",
            "themes",
            "control",
            "strategy_toggle",
            "strategy_open",
            "strategy_pref",
            "profile",
            "rsi",
            "volume",
            "direction",
            "universe",
            "gold",
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
        }:
            return ui_text(language_code, "callback_done")
        return None

    async def _send_inline_error(self, chat_id: str, message: str) -> None:
        with suppress(Exception):
            await self._send_chat_message(
                chat_id=chat_id,
                text=message,
                parse_mode=None,
            )

    async def _save_user_settings(
        self,
        *,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        direct_signal_delivery_enabled: bool | None = None,
        followup_delivery_enabled: bool | None = None,
        gold_alerts_enabled: bool | None = None,
        signal_profile: str | None = None,
        base_signal_profile: str | None = None,
        preferred_min_score: int | None = None,
        min_quote_volume: float | None = None,
        rsi_oversold: float | None = None,
        rsi_overbought: float | None = None,
        direction_filter: str | None = None,
        watchlist_only: bool | None = None,
        menu_collapsed: bool | None = None,
        language_code: str | None = None,
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
        enabled_strategy_keys: tuple[str, ...] | None = None,
        active_strategy_key=...,
        strategy_selector_completed_at=...,
        current_context=...,
        current_strategy_context=...,
        current_set_id=...,
        timezone_name=...,
        display_mode: str | None = None,
        active_workspace=...,
        saved_workspace_payload: dict[str, object] | None = None,
        strategy_preferences: dict[str, object] | None = None,
        personalization: dict[str, object] | None = None,
        delivery_rules: dict[str, object] | None = None,
    ) -> UserSettingsRecord:
        effective_direct = (
            current_settings.direct_signal_delivery_enabled
            if direct_signal_delivery_enabled is None
            else direct_signal_delivery_enabled
        )
        effective_followups = (
            current_settings.followup_delivery_enabled
            if followup_delivery_enabled is None
            else followup_delivery_enabled
        )
        effective_profile = current_settings.signal_profile if signal_profile is None else signal_profile
        effective_base_profile = (
            current_settings.base_signal_profile
            if base_signal_profile is None
            else base_signal_profile
        )
        effective_min_score = (
            current_settings.preferred_min_score
            if preferred_min_score is None
            else preferred_min_score
        )
        effective_min_quote_volume = (
            current_settings.min_quote_volume
            if min_quote_volume is None
            else min_quote_volume
        )
        effective_rsi_oversold = current_settings.rsi_oversold if rsi_oversold is None else rsi_oversold
        effective_rsi_overbought = current_settings.rsi_overbought if rsi_overbought is None else rsi_overbought
        effective_direction_filter = current_settings.direction_filter if direction_filter is None else direction_filter
        effective_watchlist_only = current_settings.watchlist_only if watchlist_only is None else watchlist_only
        effective_menu_collapsed = current_settings.menu_collapsed if menu_collapsed is None else menu_collapsed
        effective_language_code = current_settings.language_code if language_code is None else language_code
        effective_delivery_mode = current_settings.delivery_mode if delivery_mode is None else delivery_mode
        effective_delivery_mode_changed_at = (
            current_settings.delivery_mode_changed_at
            if delivery_mode_changed_at is Ellipsis
            else delivery_mode_changed_at
        )
        effective_quiet_hours_start = (
            current_settings.quiet_hours_start_minute
            if quiet_hours_start_minute is Ellipsis
            else quiet_hours_start_minute
        )
        effective_quiet_hours_end = (
            current_settings.quiet_hours_end_minute
            if quiet_hours_end_minute is Ellipsis
            else quiet_hours_end_minute
        )
        effective_snooze_until = current_settings.snooze_until if snooze_until is Ellipsis else snooze_until
        effective_snooze_started_at = (
            current_settings.snooze_started_at if snooze_started_at is Ellipsis else snooze_started_at
        )
        effective_snooze_label = current_settings.snooze_label if snooze_label is Ellipsis else snooze_label
        effective_last_resume_summary_at = (
            current_settings.last_resume_summary_at
            if last_resume_summary_at is Ellipsis
            else last_resume_summary_at
        )
        effective_last_digest_sent_at = (
            current_settings.last_digest_sent_at if last_digest_sent_at is Ellipsis else last_digest_sent_at
        )
        effective_last_daily_recap_at = (
            current_settings.last_daily_recap_at if last_daily_recap_at is Ellipsis else last_daily_recap_at
        )
        effective_last_weekly_recap_at = (
            current_settings.last_weekly_recap_at
            if last_weekly_recap_at is Ellipsis
            else last_weekly_recap_at
        )
        effective_active_watchlist_theme = (
            current_settings.active_watchlist_theme
            if active_watchlist_theme is None
            else active_watchlist_theme
        )
        effective_active_custom_theme_name = (
            current_settings.active_custom_theme_name
            if active_custom_theme_name is Ellipsis
            else active_custom_theme_name
        )
        effective_onboarding_completed_at = (
            current_settings.onboarding_completed_at
            if onboarding_completed_at is Ellipsis
            else onboarding_completed_at
        )
        effective_current_context = (
            current_settings.current_context if current_context is Ellipsis else current_context
        )
        effective_current_strategy_context = (
            current_settings.current_strategy_context
            if current_strategy_context is Ellipsis
            else current_strategy_context
        )
        effective_current_set_id = (
            current_settings.current_set_id if current_set_id is Ellipsis else current_set_id
        )
        effective_timezone_name = (
            current_settings.timezone_name if timezone_name is Ellipsis else timezone_name
        )
        effective_display_mode = current_settings.display_mode if display_mode is None else display_mode
        effective_active_workspace = (
            current_settings.active_workspace if active_workspace is Ellipsis else active_workspace
        )
        effective_saved_workspace_payload = (
            current_settings.saved_workspace_payload
            if saved_workspace_payload is None
            else saved_workspace_payload
        )
        effective_personalization = (
            current_settings.personalization if personalization is None else personalization
        )
        effective_delivery_rules = (
            current_settings.delivery_rules if delivery_rules is None else delivery_rules
        )
        if self.bot_kind == "premium":
            shell_settings = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            assert shell_settings is not None
            source_strategy_key = self._resolved_active_strategy_key(current_settings)
            effective_enabled_strategy_keys = (
                self._enabled_strategy_keys(shell_settings)
                if enabled_strategy_keys is None
                else tuple(
                    key
                    for key in enabled_strategy_keys
                    if key in self.STRATEGY_KEYS and self._strategy_accessible_for_user_id(user.telegram_user_id, key)
                )
            )
            effective_active_strategy_key = (
                self._resolved_active_strategy_key(current_settings)
                if active_strategy_key is Ellipsis
                else str(active_strategy_key or "").strip().lower() or None
            )
            if (
                effective_active_strategy_key is not None
                and (
                    effective_active_strategy_key not in self.STRATEGY_KEYS
                    or not self._strategy_accessible_for_user_id(user.telegram_user_id, effective_active_strategy_key)
                )
            ):
                effective_active_strategy_key = None
            if effective_active_strategy_key is None and effective_enabled_strategy_keys:
                effective_active_strategy_key = effective_enabled_strategy_keys[0]
            if source_strategy_key is not None:
                stored_strategy_settings = await self._ensure_premium_strategy_settings(
                    user.telegram_user_id,
                    shell_settings=shell_settings,
                    strategy_key=source_strategy_key,
                )
                effective_strategy_preferences = (
                    normalize_strategy_preferences(source_strategy_key, strategy_preferences)
                    if strategy_preferences is not None
                    else (
                        self._strategy_preferences(current_settings, strategy_key=source_strategy_key)
                        if current_settings.strategy_preferences
                        else normalize_strategy_preferences(
                            source_strategy_key,
                            stored_strategy_settings.strategy_preferences,
                        )
                    )
                )
                await self.repository.upsert_premium_strategy_settings(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind=self.bot_kind,
                    strategy_key=source_strategy_key,
                    direct_signal_delivery_enabled=effective_direct,
                    followup_delivery_enabled=effective_followups,
                    signal_profile=effective_profile,
                    base_signal_profile=effective_base_profile,
                    preferred_min_score=effective_min_score,
                    min_quote_volume=effective_min_quote_volume,
                    rsi_oversold=effective_rsi_oversold,
                    rsi_overbought=effective_rsi_overbought,
                    direction_filter=effective_direction_filter,
                    watchlist_only=effective_watchlist_only,
                    delivery_mode=effective_delivery_mode,
                    delivery_mode_changed_at=effective_delivery_mode_changed_at,
                    quiet_hours_start_minute=effective_quiet_hours_start,
                    quiet_hours_end_minute=effective_quiet_hours_end,
                    snooze_until=effective_snooze_until,
                    snooze_started_at=effective_snooze_started_at,
                    snooze_label=effective_snooze_label,
                    last_resume_summary_at=effective_last_resume_summary_at,
                    last_digest_sent_at=effective_last_digest_sent_at,
                    last_daily_recap_at=effective_last_daily_recap_at,
                    last_weekly_recap_at=effective_last_weekly_recap_at,
                    active_watchlist_theme=effective_active_watchlist_theme,
                    active_custom_theme_name=effective_active_custom_theme_name,
                    strategy_preferences=effective_strategy_preferences,
                )
            effective_shell = replace(
                shell_settings,
                gold_alerts_enabled=(
                    ("gold" in effective_enabled_strategy_keys)
                    if gold_alerts_enabled is None
                    else gold_alerts_enabled
                ),
                language_code=effective_language_code,
                menu_collapsed=effective_menu_collapsed,
                onboarding_completed_at=effective_onboarding_completed_at,
                enabled_strategy_keys=effective_enabled_strategy_keys,
                active_strategy_key=effective_active_strategy_key,
                strategy_selector_completed_at=(
                    shell_settings.strategy_selector_completed_at
                    if strategy_selector_completed_at is Ellipsis
                    else strategy_selector_completed_at
                ),
                current_context=effective_current_context,
                current_strategy_context=effective_current_strategy_context,
                current_set_id=effective_current_set_id,
                timezone_name=effective_timezone_name,
                display_mode=effective_display_mode,
                active_workspace=effective_active_workspace,
                saved_workspace_payload=effective_saved_workspace_payload,
                strategy_preferences=(
                    normalize_strategy_preferences(
                        effective_active_strategy_key,
                        strategy_preferences,
                    )
                    if effective_active_strategy_key is not None and strategy_preferences is not None
                    else current_settings.strategy_preferences
                ),
                personalization=effective_personalization,
                delivery_rules=effective_delivery_rules,
            )
            if effective_active_strategy_key is not None:
                return await self._sync_shell_to_strategy(
                    user.telegram_user_id,
                    shell_settings=effective_shell,
                    strategy_key=effective_active_strategy_key,
                )
            await self.repository.upsert_user_settings(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                direct_signal_delivery_enabled=effective_direct,
                followup_delivery_enabled=effective_followups,
                gold_alerts_enabled=effective_shell.gold_alerts_enabled,
                signal_profile=effective_profile,
                base_signal_profile=effective_base_profile,
                preferred_min_score=effective_min_score,
                min_quote_volume=effective_min_quote_volume,
                rsi_oversold=effective_rsi_oversold,
                rsi_overbought=effective_rsi_overbought,
                direction_filter=effective_direction_filter,
                watchlist_only=effective_watchlist_only,
                menu_collapsed=effective_shell.menu_collapsed,
                language_code=effective_shell.language_code,
                delivery_mode=effective_delivery_mode,
                delivery_mode_changed_at=effective_delivery_mode_changed_at,
                quiet_hours_start_minute=effective_quiet_hours_start,
                quiet_hours_end_minute=effective_quiet_hours_end,
                snooze_until=effective_snooze_until,
                snooze_started_at=effective_snooze_started_at,
                snooze_label=effective_snooze_label,
                last_resume_summary_at=effective_last_resume_summary_at,
                last_digest_sent_at=effective_last_digest_sent_at,
                last_daily_recap_at=effective_last_daily_recap_at,
                last_weekly_recap_at=effective_last_weekly_recap_at,
                active_watchlist_theme=effective_active_watchlist_theme,
                active_custom_theme_name=effective_active_custom_theme_name,
                onboarding_completed_at=effective_shell.onboarding_completed_at,
                enabled_strategy_keys=effective_shell.enabled_strategy_keys,
                active_strategy_key=effective_shell.active_strategy_key,
                strategy_selector_completed_at=effective_shell.strategy_selector_completed_at,
                current_context=effective_shell.current_context,
                current_strategy_context=effective_shell.current_strategy_context,
                current_set_id=effective_shell.current_set_id,
                timezone_name=effective_shell.timezone_name,
                display_mode=effective_shell.display_mode,
                active_workspace=effective_shell.active_workspace,
                saved_workspace_payload=effective_shell.saved_workspace_payload,
                strategy_preferences=effective_shell.strategy_preferences,
                personalization=effective_shell.personalization,
                delivery_rules=effective_shell.delivery_rules,
            )
            refreshed = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
            assert refreshed is not None
            return self._store_cached_settings(refreshed)

        await self.repository.upsert_user_settings(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=effective_direct,
            followup_delivery_enabled=effective_followups,
            gold_alerts_enabled=(
                current_settings.gold_alerts_enabled
                if gold_alerts_enabled is None
                else gold_alerts_enabled
            ),
            signal_profile=effective_profile,
            base_signal_profile=effective_base_profile,
            preferred_min_score=effective_min_score,
            min_quote_volume=effective_min_quote_volume,
            rsi_oversold=effective_rsi_oversold,
            rsi_overbought=effective_rsi_overbought,
            direction_filter=effective_direction_filter,
            watchlist_only=effective_watchlist_only,
            menu_collapsed=effective_menu_collapsed,
            language_code=effective_language_code,
            delivery_mode=effective_delivery_mode,
            delivery_mode_changed_at=effective_delivery_mode_changed_at,
            quiet_hours_start_minute=effective_quiet_hours_start,
            quiet_hours_end_minute=effective_quiet_hours_end,
            snooze_until=effective_snooze_until,
            snooze_started_at=effective_snooze_started_at,
            snooze_label=effective_snooze_label,
            last_resume_summary_at=effective_last_resume_summary_at,
            last_digest_sent_at=effective_last_digest_sent_at,
            last_daily_recap_at=effective_last_daily_recap_at,
            last_weekly_recap_at=effective_last_weekly_recap_at,
            active_watchlist_theme=effective_active_watchlist_theme,
            active_custom_theme_name=effective_active_custom_theme_name,
            onboarding_completed_at=effective_onboarding_completed_at,
            current_context=effective_current_context,
            current_strategy_context=effective_current_strategy_context,
            current_set_id=effective_current_set_id,
            timezone_name=effective_timezone_name,
            display_mode=effective_display_mode,
            active_workspace=effective_active_workspace,
            saved_workspace_payload=effective_saved_workspace_payload,
            personalization=effective_personalization,
            delivery_rules=effective_delivery_rules,
        )
        updated = await self.repository.get_user_settings(user.telegram_user_id, bot_kind=self.bot_kind)
        assert updated is not None
        return self._store_cached_settings(updated)

    async def _send_language_picker(
        self,
        telegram_user_id: int,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
        preferred_language: str | None = None,
        context: str = "welcome",
        first_time: bool = False,
    ) -> None:
        settings = await self._ensure_user_settings(telegram_user_id, preferred_language=preferred_language)
        language = normalize_language(preferred_language or settings.language_code)
        await self._cleanup_temporary_navigation_messages(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id or str(telegram_user_id),
        )
        title_key = "language_picker_welcome_title" if context == "welcome" else "language_picker_settings_title"
        body_key = "language_picker_welcome_body" if context == "welcome" else "language_picker_settings_body"
        if context == "welcome" and self.bot_kind == "premium":
            body_key = "language_picker_premium_body"
        brand = ""
        if context == "welcome" and self.bot_kind == "premium":
            brand = "<b>RSI Syndicate · Syndicate PRO+</b>\n\n"
        text = (
            f"{brand}<b>🌍 {ui_text(language, title_key)}</b>\n\n"
            f"{ui_text(language, body_key)}\n\n"
            f"{ui_text(language, 'language_picker_hint')}"
        )
        back_callback_data = None
        if context != "welcome":
            default_back = "ux:menu" if context == "menu" else self._hub_callback_data(
                "settingshub",
                origin=self._hub_origin_for(telegram_user_id, section="settings"),
            )
            back_callback_data = self._screen_back_callback(
                telegram_user_id,
                screen="language_picker",
                default=self._navigation_back_callback(
                    telegram_user_id,
                    settings=settings,
                    screen="language_picker",
                    section="settings" if context != "menu" else None,
                ) if context != "menu" else default_back,
            )
        await self._send_or_edit_text(
            chat_id=chat_id or str(telegram_user_id),
            text=text,
            reply_markup=build_language_picker_inline_keyboard(
                language_code=language,
                selected_language=settings.language_code,
                context=context,
                back_callback_data=back_callback_data,
            ),
            edit_message_id=edit_message_id,
        )
        if context == "welcome":
            await self._record_funnel_event(
                "language_picker_seen",
                telegram_user_id,
                context="welcome",
                language_code=language,
                screen="language_picker",
            )

    async def _apply_language_choice(
        self,
        user: PrivateBotUserRecord,
        *,
        current_settings: UserSettingsRecord,
        language_code: str,
        chat_id: str,
        edit_message_id: int,
        context: str,
    ) -> None:
        normalized_language = normalize_language(language_code)
        if context == "welcome":
            updated_settings = await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                language_code=normalized_language,
                onboarding_completed_at=current_settings.onboarding_completed_at,
            )
            confirmation_key = (
                "classic_language_selected_confirmation"
                if str(getattr(self, "bot_kind", "") or "").strip().lower() == "classic"
                else "language_selected_confirmation"
            )
            confirmation = ui_text(
                normalized_language,
                confirmation_key,
                language_name=ui_text(normalized_language, "language_name"),
            )
            await self._send_or_edit_text(
                chat_id=chat_id,
                text=escape_html(confirmation),
                reply_markup=None,
                edit_message_id=edit_message_id,
            )
            await self._record_funnel_event(
                "language_selected",
                user.telegram_user_id,
                context="welcome",
                language_code=normalized_language,
                screen="language_picker",
            )
            if self.bot_kind == "premium":
                personalization = self._personalization_state(updated_settings)
                personalization["ux_v2_enabled"] = True
                updated_settings = await self._save_user_settings(
                    user=user,
                    current_settings=updated_settings,
                    personalization=personalization,
                    display_mode="simple",
                )
                await self._start_v2_onboarding(
                    user,
                    chat_id=chat_id,
                    edit_message_id=edit_message_id,
                )
                return
            await self._send_start(user.telegram_user_id, None, first_time=True)
            for event_name in ("welcome_seen", "risk_seen", "guided_menu_seen"):
                await self._record_funnel_event(
                    event_name,
                    user.telegram_user_id,
                    context="first_run",
                    language_code=normalized_language,
                    screen="guided_welcome",
                )
            if self.bot_kind == "premium":
                await self._record_funnel_event(
                    "trial_explained",
                    user.telegram_user_id,
                    context="first_run",
                    language_code=normalized_language,
                    screen="guided_welcome",
                )
            if updated_settings.onboarding_completed_at is None:
                await self._save_user_settings(
                    user=user,
                    current_settings=updated_settings,
                    onboarding_completed_at=utc_now(),
                )
            return
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            language_code=normalized_language,
            onboarding_completed_at=current_settings.onboarding_completed_at,
        )
        back_callback_data = self._screen_back_callback(
            user.telegram_user_id,
            screen="language_picker",
            default=self._hub_callback_data(
                "settingshub",
                origin=self._hub_origin_for(user.telegram_user_id, section="settings"),
            ),
        )
        if back_callback_data == "ux:menu":
            await self._send_menu_hub(
                user.telegram_user_id,
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        if back_callback_data in {"ux:settingshub", "ux:settingshub:strategy"}:
            await self._send_section_hub(
                user.telegram_user_id,
                section="settings",
                origin="strategy" if back_callback_data.endswith(":strategy") else "menu",
                chat_id=chat_id,
                edit_message_id=edit_message_id,
            )
            return
        await self._send_menu_hub(
            user.telegram_user_id,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _toggle_language_preference(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
    ) -> None:
        updated = await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            language_code=toggle_language(current_settings.language_code),
        )
        language = self._language_code(updated)
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(language, "language_switched", target_language=ui_text(language, "language_name")),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _apply_strategy_preference_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        *,
        key: str,
        value: str,
    ) -> None:
        strategy_key = resolve_quick_setup_strategy_key(self._resolved_active_strategy_key(current_settings) or "rsi")
        updated_preferences = self._strategy_preferences(current_settings, strategy_key=strategy_key)
        updated_preferences[str(key)] = str(value)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile="custom",
            strategy_preferences=normalize_strategy_preferences(strategy_key, updated_preferences),
        )

    async def _apply_profile_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        profile: str,
    ) -> None:
        min_score, min_quote_volume, rsi_oversold, rsi_overbought = self._profile_defaults(profile)
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile=profile,
            base_signal_profile=profile,
            preferred_min_score=min_score,
            min_quote_volume=min_quote_volume,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
        )

    async def _apply_rsi_mode_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        mode: str,
    ) -> None:
        oversold, overbought = self.RSI_MODE_THRESHOLDS.get(mode, self.RSI_MODE_THRESHOLDS["balanced"])
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile="custom",
            rsi_oversold=oversold,
            rsi_overbought=overbought,
        )

    async def _apply_volume_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        raw_value: str,
    ) -> None:
        try:
            min_quote_volume = max(float(raw_value), 0.0)
        except ValueError:
            return
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile="custom",
            min_quote_volume=min_quote_volume,
        )

    async def _apply_direction_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        direction_filter: str,
    ) -> None:
        if direction_filter not in self.DIRECTION_LABELS:
            return
        await self._save_user_settings(
            user=user,
            current_settings=current_settings,
            signal_profile="custom",
            direction_filter=direction_filter,
        )

    async def _apply_universe_choice(
        self,
        user: PrivateBotUserRecord,
        current_settings: UserSettingsRecord,
        universe_mode: str,
    ) -> None:
        if universe_mode == "all":
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                signal_profile="custom",
                watchlist_only=False,
            )
            return
        if universe_mode in {"watchlist", "favorites"}:
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                signal_profile="custom",
                watchlist_only=True,
                active_watchlist_theme="custom",
                active_custom_theme_name=None,
            )
            return
        if universe_mode == "set":
            await self._save_user_settings(
                user=user,
                current_settings=current_settings,
                signal_profile="custom",
                watchlist_only=True,
            )

    def _build_onboarding_keyboard(self, *, language_code: str = "en") -> dict[str, object]:
        return build_onboarding_inline_keyboard(
            public_channel=self.settings.public_channel,
            results_channel=self.settings.results_channel,
            language_code=language_code,
            community_target=self._community_target() or None,
            bot_target=self.settings.resolved_private_bot_share_link or None,
            channels_folder_target=self.settings.channels_folder_link.strip() or None,
        )

    def _community_target(self) -> str:
        link = self.settings.community_link.strip()
        if link:
            return link
        if self.settings.community_chat.strip().startswith("@"):
            return self.settings.community_chat.strip()
        return ""

    async def _access_label_for_user(self, user: PrivateBotUserRecord, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        state = await self._effective_access_state_for_user(user)
        status = (state.access_status or "free").strip().lower()
        if status == "admin":
            return ui_text(language, "status_admin")
        if status == "paid":
            return ui_text(language, "status_paid")
        if status == "trial":
            return ui_text(language, "status_trial")
        if status == "expired":
            return ui_text(language, "status_expired")
        level = (state.access_level or "free").strip().lower()
        if level == "admin":
            return ui_text(language, "status_admin")
        if level == "pro":
            return "PRO+"
        return ui_text(language, "status_free")

    def _localize_followup_result(
        self,
        result: FollowUpResult,
        settings: UserSettingsRecord | None,
    ) -> FollowUpResult:
        language = self._language_code(settings)
        summary = result.summary
        candle_move_pct = result.metadata.get("candle_move_pct")
        if isinstance(candle_move_pct, (int, float)):
            summary = summarize_followup(
                result.direction,
                stage=result.stage or str(result.metadata.get("followup_stage") or "2h"),
                market_move_pct=result.move_pct,
                candle_move_pct=float(candle_move_pct),
                current_rsi=result.current_rsi,
                alert_rsi=result.alert_rsi,
                language=language,
            )
        return replace(
            result,
            summary=summary,
            metadata={
                **result.metadata,
                "language_code": language,
                "text_layout": (
                    "v2_3_signal"
                    if self.bot_kind == "premium" and self.destination_kind == "private"
                    else str(result.metadata.get("text_layout") or "").strip()
                ),
            },
        )

    async def _effective_access_state_for_user(self, user: PrivateBotUserRecord) -> EffectiveAccessState:
        if self.onboarding_service is not None:
            return await self.onboarding_service.get_effective_access_state(
                user.telegram_user_id,
                user=user,
            )
        level = (user.access_level or "free").strip().lower()
        status = (user.access_status or level or "free").strip().lower()
        from src.payments.onboarding import EffectiveAccessState

        return EffectiveAccessState(
            telegram_user_id=user.telegram_user_id,
            access_level=level or "free",
            access_status=status or "free",
            starts_at=None,
            ends_at=None,
            metadata={},
            is_admin=bool(user.is_admin or level == "admin"),
        )

    async def _has_premium_access(self, user: PrivateBotUserRecord) -> bool:
        state = await self._effective_access_state_for_user(user)
        return state.has_premium_access

    async def _send_premium_access_required(self, user_id: int, *, feature_name: str) -> None:
        user = await self.repository.get_private_user(user_id)
        settings = await self.repository.get_user_settings(user_id, bot_kind=self.bot_kind)
        language = self._language_code(settings)
        if user is not None:
            state = await self._effective_access_state_for_user(user)
            if state.has_premium_access:
                access_label = ui_text(language, "status_trial") if state.access_status == "trial" else "PRO+"
                await self._send_chat_message(
                    chat_id=str(user_id),
                    text=ui_text(
                        language,
                        "premium_feature_included",
                        feature_name=feature_name,
                        access_label=access_label,
                    ),
                    parse_mode="HTML",
                    reply_markup=await self._main_menu_keyboard_for_user(user_id),
                )
                return
        pay_url: str | None = None
        campaign = await self.repository.get_onboarding_payment_campaign(
            telegram_user_id=user_id,
            bot_kind="premium",
            campaign_type="trial_48h",
        )
        if campaign is not None and campaign.invoice_id is not None:
            invoice = await self.repository.get_crypto_pay_invoice(invoice_id=campaign.invoice_id)
            if invoice is not None and invoice.activated_at is None:
                pay_url = invoice.pay_url
        message = ui_text(language, "premium_feature_locked", feature_name=feature_name)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=message,
            parse_mode="HTML",
            reply_markup=(
                build_detail_card_keyboard_with_action(
                    include_delete=False,
                    language_code=language,
                    action_label=ui_text(language, "menu_pay_pro"),
                    action_url=pay_url,
                )
                if pay_url
                else self._build_onboarding_keyboard(language_code=language)
            ),
        )

    async def _payment_menu_label_for_user(self, telegram_user_id: int) -> str | None:
        if self.bot_kind != "premium":
            return None
        settings = await self.repository.get_user_settings(telegram_user_id, bot_kind=self.bot_kind)
        language = self._language_code(settings)
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            return ui_text(language, "menu_try_pro")
        state = await self._effective_access_state_for_user(user)
        if state.is_admin:
            return None
        if state.is_paid:
            return ui_text(language, "menu_renew_pro")
        return ui_text(language, "menu_try_pro")

    async def _send_payment_offer(self, user: PrivateBotUserRecord, *, allow_renewal: bool = False) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if self.bot_kind != "premium":
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "payments_classic_only"),
                parse_mode=None,
                reply_markup=self._build_onboarding_keyboard(language_code=language),
            )
            return

        access_state = await self._effective_access_state_for_user(user)
        if access_state.is_admin:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "admin_access_active"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        if access_state.access_status == "trial" and not allow_renewal:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "trial_active_now"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        if access_state.is_paid and not allow_renewal:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "paid_active_now"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return

        campaign = None
        if self.onboarding_service is not None and self.settings.onboarding_payment_campaign_enabled:
            campaign = await self.onboarding_service.ensure_onboarding_trial(user.telegram_user_id)
        else:
            campaign = await self.repository.get_onboarding_payment_campaign(
                telegram_user_id=user.telegram_user_id,
                bot_kind="premium",
                campaign_type="trial_48h",
            )

        invoice = None
        pay_url: str | None = None
        if not allow_renewal and campaign is not None and campaign.invoice_id is not None:
            invoice = await self.repository.get_crypto_pay_invoice(invoice_id=campaign.invoice_id)
            if invoice is not None and invoice.activated_at is None:
                pay_url = invoice.pay_url
            if invoice is not None and invoice.activated_at is not None:
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "invoice_already_paid"),
                    parse_mode=None,
                    reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
                )
                return

        now = utc_now()
        if not pay_url:
            if (
                self.onboarding_service is None
                or self.onboarding_service.crypto_pay_service is None
                or not self.settings.crypto_pay_is_configured
            ):
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "payment_setup_not_ready"),
                    parse_mode=None,
                    reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
                )
                LOGGER.warning(
                    "PRIVATE payment menu unavailable user=%s: crypto pay not configured",
                    user.telegram_user_id,
                )
                return
            try:
                invoice_response = await self.onboarding_service.crypto_pay_service.create_subscription_invoice(
                    telegram_user_id=user.telegram_user_id,
                    bot_kind="premium",
                    access_level="pro",
                    duration_days=self.settings.crypto_pay_subscription_days,
                    amount_usd=self.settings.crypto_pay_invoice_amount_usd,
                    description="Extend Syndicate PRO+" if allow_renewal and access_state.is_paid else "Continue Syndicate PRO+",
                    purpose="manual_renewal_payment" if allow_renewal and access_state.is_paid else "manual_menu_payment",
                    campaign_type=None if allow_renewal and access_state.is_paid else "trial_48h",
                    referred_by_user_id=user.referred_by_user_id,
                    extra_payload={
                        "requested_from": "premium_access_screen" if allow_renewal else "premium_menu",
                        "requested_at": now.isoformat(),
                        "renewal": bool(allow_renewal),
                    },
                )
                invoice_id = int(invoice_response.get("invoice_id") or 0)
                if invoice_id <= 0:
                    raise RuntimeError(f"Crypto Pay returned invalid invoice_id: {invoice_response}")
                invoice = await self.repository.get_crypto_pay_invoice(invoice_id=invoice_id)
                pay_url = invoice.pay_url if invoice is not None else None
                if campaign is not None and not allow_renewal:
                    update_kwargs: dict[str, object] = {
                        "invoice_id": invoice_id,
                        "metadata": {
                            **campaign.metadata,
                            "manual_offer_requested_at": now.isoformat(),
                            "manual_invoice_created_at": now.isoformat(),
                        },
                    }
                    if campaign.trial_ends_at is not None and campaign.trial_ends_at <= now:
                        update_kwargs["status"] = "offer_sent"
                        update_kwargs["offer_sent_at"] = now
                    await self.repository.update_onboarding_payment_campaign(campaign.id, **update_kwargs)
                LOGGER.info(
                    "PRIVATE payment menu invoice prepared user=%s invoice_id=%s trial_status=%s",
                    user.telegram_user_id,
                    invoice_id,
                    access_state.access_status,
                )
            except Exception:
                LOGGER.exception("Failed to prepare PRIVATE payment menu invoice user=%s", user.telegram_user_id)
                await self._send_chat_message(
                    chat_id=str(user.telegram_user_id),
                    text=ui_text(language, "payment_link_failed"),
                    parse_mode=None,
                    reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
                )
                return

        if not pay_url:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "payment_link_not_ready"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            LOGGER.warning("PRIVATE payment menu missing pay_url user=%s", user.telegram_user_id)
            return

        if (
            campaign is not None
            and campaign.trial_ends_at is not None
            and campaign.trial_ends_at <= now
            and campaign.status in {"invoice_ready", "send_retry"}
        ):
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="offer_sent",
                offer_sent_at=now,
                metadata={**campaign.metadata, "manual_offer_sent_at": now.isoformat()},
            )

        message = ui_text(language, "payment_offer_message") if not allow_renewal else ui_text(language, "payment_continue")
        if allow_renewal and access_state.is_paid:
            message = ui_text(language, "payment_renew_title")
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=message,
            parse_mode="HTML",
            reply_markup=build_detail_card_keyboard_with_action(
                include_delete=False,
                language_code=language,
                action_label=ui_text(language, "menu_renew_pro") if allow_renewal and access_state.is_paid else ui_text(language, "menu_pay_pro"),
                action_url=pay_url,
            ),
        )
        LOGGER.info(
            "PRIVATE payment menu offer sent user=%s invoice_id=%s access=%s",
            user.telegram_user_id,
            invoice.invoice_id if invoice is not None else None,
            access_state.access_status,
        )

    def _recipient_access_levels(self) -> tuple[str, ...]:
        if self.bot_kind == "premium":
            return ("pro", "admin")
        return ("free", "pro", "admin")

    async def _describe_last_private_delivery(self, record, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        if record is None or record.alert_id is None:
            return ui_text(language, "last_signal_none")
        alert = await self.repository.get_alert(record.alert_id)
        if alert is None:
            return ui_text(language, "last_signal_none")
        symbol = normalize_symbol(alert.symbol)
        timestamp = record.delivered_at.astimezone(self.settings.timezone).strftime("%d %b %H:%M")
        if record.message_kind.startswith("followup:"):
            stage = record.message_kind.split(":", maxsplit=1)[1]
            return ui_text(language, "last_signal_followup", symbol=symbol, stage=stage, timestamp=timestamp)
        return ui_text(language, "last_signal_alert", symbol=symbol, timestamp=timestamp)

    async def _pick_signal_for_user(
        self,
        user: PrivateBotUserRecord,
        *,
        strong_only: bool,
        limit: int,
        strategy_key: str | None = "__active__",
    ) -> list[_PrivateSelection]:
        now = utc_now()
        start = now - timedelta(hours=24)
        settings = await self._ensure_user_settings(user.telegram_user_id)
        setup_state = self._resolve_signal_setup_state(settings)
        watchlist_symbols = set(await self._watchlist_symbols(user.telegram_user_id))
        favorite_symbols = set(await self._global_favorite_symbols(user.telegram_user_id))
        if setup_state.watchlist_only and not watchlist_symbols:
            return []
        active_strategy_key = (
            self._resolved_active_strategy_key(settings) or "rsi"
            if strategy_key == "__active__"
            else str(strategy_key or "").strip().lower()
        )
        fetch_limit = max(limit * 8, limit + 24)
        min_score = self._selection_min_score(setup_state, strong_only=strong_only)
        min_quote_volume = max(setup_state.min_quote_volume, 0.0)
        if strong_only:
            alerts = await self.repository.list_alerts_between(
                start=start,
                end=now + timedelta(minutes=1),
                min_score=min_score,
                min_quote_volume=min_quote_volume,
                limit=fetch_limit,
            )
        else:
            alerts = await self.repository.list_recent_alerts(
                start=start,
                end=now + timedelta(minutes=1),
                min_score=min_score,
                min_quote_volume=min_quote_volume,
                limit=fetch_limit,
            )
        selections: list[_PrivateSelection] = []
        for alert in alerts:
            if active_strategy_key and self._alert_strategy_key(alert) != active_strategy_key:
                continue
            matches_filters, _ = self._alert_record_matches_user_settings(
                alert,
                settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                strong_only=strong_only,
            )
            if not matches_filters:
                continue
            selections.append(
                _PrivateSelection(
                    alert=alert,
                    followup=None,
                )
            )
            if len(selections) >= limit:
                break
        return selections

    async def _send_selection_card(self, user_id: int, selection: _PrivateSelection) -> None:
        await self._send_alert_card(user_id, selection.alert)

    async def _send_alert_card(self, user_id: int, alert: AlertRecord) -> None:
        chart_path = None
        try:
            frame = await self.binance_client.get_klines(
                alert.symbol,
                alert.timeframe,
                self.settings.klines_limit,
                end_time=alert.candle_close_time,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            settings = await self._ensure_user_settings(user_id)
            watchlist_symbols = set(await self._watchlist_symbols_for_strategy(
                user_id,
                strategy_key=self._alert_strategy_key(alert),
                settings=settings,
            )) if self.bot_kind == "premium" else set(await self._watchlist_symbols(user_id))
            signal = self._apply_user_preferences_to_signal(
                self._signal_from_alert_record(alert),
                settings,
                watchlist_symbols=watchlist_symbols,
            )
            if bool(self._personalization_state(settings).get("ux_v2_enabled")):
                signal.metadata = {**signal.metadata, "text_layout": "v2_3_signal"}
            signal = await self._enrich_okak_signal_for_private_user(
                signal,
                user=await self._get_private_user(user_id),
            )
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal)
            signal.chart_path = chart_path
            delivery = await self.router.send_raw_alert_to_chat(
                signal,
                chat_id=str(user_id),
                destination_kind=self.destination_kind,
                preview=False,
            )
            if delivery.telegram_message_id is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind=self.destination_kind,
                    chat_id=str(user_id),
                    message_id=delivery.telegram_message_id,
                    signal=signal,
                    alert_id=alert.id,
                    is_preview=False,
                    message_kind="alert",
                )
        finally:
            self.chart_renderer.cleanup(chart_path)

    async def _send_followup_card(self, user_id: int, alert: AlertRecord, followup: FollowUpResultRecord):
        chart_path = None
        try:
            frame = await self.binance_client.get_klines(
                normalize_symbol(followup.symbol),
                followup.timeframe,
                self.settings.klines_limit,
                end_time=followup.observed_at,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            settings = await self._ensure_user_settings(user_id)
            watchlist_symbols = set(await self._watchlist_symbols_for_strategy(
                user_id,
                strategy_key=self._followup_strategy_key(followup),
                settings=settings,
            )) if self.bot_kind == "premium" else set(await self._watchlist_symbols(user_id))
            signal = self._apply_user_preferences_to_signal(
                self._reference_signal_for_followup(alert, followup),
                settings,
                watchlist_symbols=watchlist_symbols,
            )
            result = self._localize_followup_result(self._followup_result_from_record(alert, followup), settings)
            chart_path = await self.chart_renderer.render_result_chart(
                enriched,
                signal,
                result,
                label="Private Result",
            )
            result.chart_path = chart_path
            delivery = await self.router.send_followup_to_chat(
                result,
                chat_id=str(user_id),
                destination_kind=self.destination_kind,
            )
            if delivery.telegram_message_id is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind=self.destination_kind,
                    chat_id=str(user_id),
                    message_id=delivery.telegram_message_id,
                    signal=signal,
                    alert_id=alert.id,
                    is_preview=False,
                    message_kind="followup",
                )
            return delivery
        finally:
            self.chart_renderer.cleanup(chart_path)

    def _signal_from_alert_record(self, alert: AlertRecord) -> AlertSignal:
        return AlertSignal(
            symbol=normalize_symbol(alert.symbol),
            direction=alert.direction,
            timeframe=alert.timeframe,
            candle_open_time=alert.candle_open_time,
            candle_close_time=alert.candle_close_time,
            price=alert.alert_price,
            rsi=alert.alert_rsi,
            day_change_pct=alert.day_change_pct,
            day_volume=alert.day_volume,
            quote_volume=alert.metadata.get("quote_volume"),
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=alert.metadata.get("atr_pct", 0.0),
            ema20=0.0,
            ema50=0.0,
            score=alert.score,
            explanation=alert.metadata.get("explanation", ""),
            metadata={
                **alert.metadata,
                "strategy_key": self._alert_strategy_key(alert),
                "origin_timeframe": alert.timeframe,
                "rsi_mode": alert.metadata.get("rsi_mode", "closed_trigger"),
                "rsi_source": alert.metadata.get("rsi_source", "binance_futures_klines+wilder_rma"),
            },
        )

    def _reference_signal_for_followup(
        self,
        alert: AlertRecord,
        followup: FollowUpResultRecord,
    ) -> AlertSignal:
        signal = self._signal_from_alert_record(alert)
        signal.timeframe = followup.timeframe
        signal.metadata = {
            **signal.metadata,
            "origin_timeframe": alert.timeframe,
            "followup_stage": followup.stage,
            "latest_followup_stage": followup.stage,
        }
        return signal

    def _followup_result_from_record(self, alert: AlertRecord, followup: FollowUpResultRecord) -> FollowUpResult:
        elapsed_seconds = max((followup.observed_at - alert.alert_sent_at).total_seconds(), 0.0)
        return FollowUpResult(
            alert_id=followup.alert_id,
            stage=followup.stage,
            symbol=normalize_symbol(followup.symbol),
            direction=followup.direction,
            timeframe=followup.timeframe,
            alert_price=followup.alert_price,
            current_price=followup.current_price,
            alert_rsi=followup.alert_rsi,
            current_rsi=followup.current_rsi,
            move_pct=followup.move_pct,
            summary=followup.summary,
            score=followup.score,
            observed_at=followup.observed_at,
            thesis_direction=str(followup.metadata.get("thesis_direction", "")),
            favorable_move_pct=float(followup.metadata.get("favorable_move_pct", 0.0) or 0.0),
            adverse_move_pct=float(followup.metadata.get("adverse_move_pct", 0.0) or 0.0),
            thesis_result_state=str(followup.metadata.get("thesis_result_state", "neutral")),
            metadata={
                **followup.metadata,
                "strategy_key": self._alert_strategy_key(alert),
                "alert_timeframe": alert.timeframe,
                "elapsed_seconds": elapsed_seconds,
            },
        )

    def _gold_alerts_enabled_for_settings(self, settings) -> bool:
        if self.bot_kind != "premium":
            return False
        return self._strategy_enabled_for_settings(settings, strategy_key="gold")

    def _is_gold_signal(self, signal: AlertSignal) -> bool:
        return str(signal.metadata.get("asset_class") or "").lower() == "gold"

    def _is_gold_alert_record(self, alert: AlertRecord) -> bool:
        return str(alert.metadata.get("asset_class") or "").lower() == "gold"

    def _watchlist_hit(self, symbol: str, watchlist_symbols: set[str]) -> bool:
        return normalize_symbol(symbol) in watchlist_symbols

    async def _repeat_cooldown_hit(
        self,
        *,
        telegram_user_id: int,
        symbol: str,
        hours: int,
    ) -> bool:
        if hours <= 0:
            return False
        since = utc_now() - timedelta(hours=hours)
        recent = await self.repository.list_delivered_signals(
            telegram_user_id=telegram_user_id,
            bot_kind=self.bot_kind,
            content_kind=self.content_kind,
            since=since,
            limit=100,
        )
        normalized_symbol = normalize_symbol(symbol)
        for record in recent:
            if normalize_symbol(str(record.metadata.get("symbol") or "")) != normalized_symbol:
                continue
            if record.metadata.get("sent") or str(record.message_kind).startswith("queued:"):
                return True
        return False

    def _quiet_live_is_important(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord,
        *,
        watchlist_symbols: set[str],
    ) -> bool:
        if self._watchlist_hit(signal.symbol, watchlist_symbols):
            return True
        quiet_gate = max(self._resolve_signal_setup_state(settings).min_score + 8, 88)
        if signal.score >= quiet_gate:
            return True
        return self._is_gold_signal(signal)

    def _quiet_followup_is_important(
        self,
        result: FollowUpResult,
        settings: UserSettingsRecord,
        *,
        watchlist_symbols: set[str],
    ) -> bool:
        if self._watchlist_hit(result.symbol, watchlist_symbols):
            return True
        quiet_gate = max(self._resolve_signal_setup_state(settings).min_score + 4, 82)
        if result.score >= quiet_gate and result.thesis_result_state == "favorable":
            return True
        return result.thesis_result_state == "favorable" and abs(result.move_pct) >= 2.0

    async def _live_delivery_queue_reason(
        self,
        signal: AlertSignal,
        settings: UserSettingsRecord,
        *,
        watchlist_symbols: set[str],
        favorite_symbols: set[str],
        telegram_user_id: int,
        now,
    ) -> str | None:
        rules = self._delivery_rules_state(settings)
        repeat_hours = max(
            int(rules.get("repeat_cooldown_hours") or 0),
            int(self._personalization_state(settings).get("hidden", {}).get("mute_repeats_hours", 0) or 0),
        )
        repeat_hit = await self._repeat_cooldown_hit(
            telegram_user_id=telegram_user_id,
            symbol=signal.symbol,
            hours=repeat_hours,
        )
        return resolve_delivery_route(
            score=int(signal.score),
            watchlist_hit=self._watchlist_hit(signal.symbol, watchlist_symbols),
            favorite_hit=self._watchlist_hit(signal.symbol, favorite_symbols),
            is_gold=self._is_gold_signal(signal),
            is_followup=False,
            in_quiet_hours=is_within_quiet_hours(settings, now=now, timezone_obj=self.settings.timezone),
            snoozed=is_snoozed(settings, now=now),
            repeat_cooldown_hit=repeat_hit,
            delivery_rules=rules,
            base_mode=str(settings.delivery_mode or "instant"),
        )

    async def _followup_delivery_queue_reason(
        self,
        result: FollowUpResult,
        settings: UserSettingsRecord,
        *,
        watchlist_symbols: set[str],
        favorite_symbols: set[str],
        telegram_user_id: int,
        now,
    ) -> str | None:
        rules = self._delivery_rules_state(settings)
        repeat_hours = max(
            int(rules.get("repeat_cooldown_hours") or 0),
            int(self._personalization_state(settings).get("hidden", {}).get("mute_repeats_hours", 0) or 0),
        )
        repeat_hit = await self._repeat_cooldown_hit(
            telegram_user_id=telegram_user_id,
            symbol=result.symbol,
            hours=repeat_hours,
        )
        return resolve_delivery_route(
            score=int(result.score),
            watchlist_hit=self._watchlist_hit(result.symbol, watchlist_symbols),
            favorite_hit=self._watchlist_hit(result.symbol, favorite_symbols),
            is_gold=False,
            is_followup=True,
            in_quiet_hours=is_within_quiet_hours(settings, now=now, timezone_obj=self.settings.timezone),
            snoozed=is_snoozed(settings, now=now),
            repeat_cooldown_hit=repeat_hit,
            delivery_rules=rules,
            base_mode=str(settings.delivery_mode or "instant"),
        )

    async def _record_private_candidate(
        self,
        *,
        user: PrivateBotUserRecord,
        alert_id: int,
        message_kind: str,
        symbol: str,
        score: int,
        queue_reason: str,
        watchlist_hit: bool,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self.repository.record_delivered_signal(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            alert_id=alert_id,
            content_kind=self.content_kind,
            message_kind=message_kind,
            telegram_message_id=None,
            metadata={
                "sent": False,
                "symbol": normalize_symbol(symbol),
                "score": score,
                "watchlist_hit": watchlist_hit,
                "queue_reason": queue_reason,
                **(metadata or {}),
            },
        )

    def _qualifies_for_private_live(self, signal: AlertSignal) -> bool:
        return self._evaluate_private_live(signal).eligible

    def _qualifies_for_private_followup(self, signal: AlertSignal, result: FollowUpResult) -> bool:
        return self._evaluate_private_followup(signal, result).eligible

    def _evaluate_private_live(self, signal: AlertSignal) -> _PrivateDeliveryDecision:
        score_gate = self.settings.pro_live_min_score
        quote_volume = float(signal.quote_volume or signal.day_volume or 0.0)
        quote_gate = max(self.settings.x_min_quote_volume, 5_000_000.0)
        if signal.score < score_gate:
            return _PrivateDeliveryDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < quote_gate:
            return _PrivateDeliveryDecision(False, f"low quote_volume {quote_volume / 1_000_000:.2f}M < {quote_gate / 1_000_000:.2f}M")
        return _PrivateDeliveryDecision(
            True,
            f"score={signal.score}, quote_volume={quote_volume / 1_000_000:.2f}M",
        )

    def _evaluate_private_followup(self, signal: AlertSignal, result: FollowUpResult) -> _PrivateDeliveryDecision:
        score_gate = self.settings.pro_followup_min_score
        rsi_delta = abs(result.current_rsi - signal.rsi)
        move_gate = self.settings.pro_followup_min_move_pct
        if signal.score < score_gate:
            return _PrivateDeliveryDecision(False, f"low score {signal.score} < {score_gate}")
        if abs(result.move_pct) < move_gate and rsi_delta < 10.0:
            return _PrivateDeliveryDecision(
                False,
                f"weak follow-up result move={result.move_pct:+.2f}% < {move_gate:.2f}% and rsi_delta={rsi_delta:.2f} < 10.00",
            )
        return _PrivateDeliveryDecision(
            True,
            f"score={signal.score}, move={result.move_pct:+.2f}%, rsi_delta={rsi_delta:.2f}",
        )

    def _evaluate_private_followup_stage_policy(
        self,
        result: FollowUpResult,
        *,
        prior_followups,
        today_followups,
    ) -> _PrivateDeliveryDecision:
        state = result.thesis_result_state or "neutral"
        favorable_move = float(result.favorable_move_pct or 0.0)
        adverse_move = float(result.adverse_move_pct or 0.0)
        favorable_gate = float(self.settings.private_followup_min_favorable_move_pct)
        adverse_cap = float(self.settings.private_followup_max_adverse_move_pct)
        adverse_daily_cap = int(self.settings.private_followup_max_adverse_per_day)

        if state == "favorable":
            if favorable_move < favorable_gate:
                return _PrivateDeliveryDecision(
                    False,
                    f"waiting for stronger favorable follow-up {favorable_move:.2f}% < {favorable_gate:.2f}%",
                )
            previous_best = max(
                (
                    float(record.metadata.get("favorable_move_pct") or 0.0)
                    for record in prior_followups
                    if str(record.metadata.get("thesis_result_state") or "") == "favorable"
                ),
                default=0.0,
            )
            if previous_best >= favorable_gate and favorable_move <= previous_best + 0.05:
                return _PrivateDeliveryDecision(
                    False,
                    f"no improvement vs previous favorable follow-up {favorable_move:.2f}% <= {previous_best:.2f}%",
                )
            return _PrivateDeliveryDecision(
                True,
                f"favorable follow-up {favorable_move:.2f}% >= {favorable_gate:.2f}% and improved vs prior stage",
            )

        if state == "adverse":
            if adverse_move <= 0.0:
                return _PrivateDeliveryDecision(False, "no meaningful adverse move yet")
            if adverse_move > adverse_cap:
                return _PrivateDeliveryDecision(
                    False,
                    f"adverse move too large {adverse_move:.2f}% > {adverse_cap:.2f}%",
                )
            adverse_sent_today = sum(
                1
                for record in today_followups
                if str(record.metadata.get("thesis_result_state") or "") == "adverse"
            )
            if adverse_sent_today >= adverse_daily_cap:
                return _PrivateDeliveryDecision(
                    False,
                    f"daily adverse follow-up cap reached ({adverse_sent_today}/{adverse_daily_cap})",
                )
            return _PrivateDeliveryDecision(
                True,
                f"single adverse follow-up allowed for the day ({adverse_move:.2f}% <= {adverse_cap:.2f}%)",
            )

        return _PrivateDeliveryDecision(False, "waiting for a clearer thesis outcome")

