from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SymbolState:
    symbol: str
    timeframe: str
    last_rsi: float | None
    zone: str
    oversold_active: bool
    overbought_active: bool
    oversold_last_alert_at: datetime | None
    overbought_last_alert_at: datetime | None
    updated_at: datetime


@dataclass(slots=True)
class AlertRecord:
    id: int
    symbol: str
    direction: str
    timeframe: str
    candle_open_time: datetime
    candle_close_time: datetime
    alert_price: float
    alert_rsi: float
    day_change_pct: float | None
    day_volume: float | None
    score: int
    alert_sent_at: datetime
    followup_due_at: datetime
    followup_sent_at: datetime | None
    lab_message_id: int | None
    metadata: dict[str, Any]
    strategy_key: str


@dataclass(slots=True)
class FollowUpTaskRecord:
    id: int
    alert_id: int
    symbol: str
    direction: str
    stage: str
    due_at: datetime
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    executed_at: datetime | None


@dataclass(slots=True)
class FollowUpResultRecord:
    alert_id: int
    stage: str
    symbol: str
    direction: str
    timeframe: str
    alert_price: float
    alert_rsi: float
    score: int
    current_price: float
    current_rsi: float
    move_pct: float
    summary: str
    observed_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class InteractiveAlertState:
    id: int
    chat_id: str
    message_id: int
    alert_id: int | None
    destination_kind: str
    symbol: str
    original_timeframe: str
    displayed_timeframe: str
    direction: str
    is_preview: bool
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class CachedAnalysisRecord:
    id: int
    alert_id: int | None
    symbol: str
    timeframe: str
    analysis_type: str
    content: str
    model_name: str | None
    created_at: datetime
    expires_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class PreparedFeatureCardRecord:
    id: int
    alert_id: int | None
    symbol: str
    timeframe: str
    content_type: str
    source_data_hash: str
    text_payload: str
    json_payload: dict[str, Any]
    model_name: str | None
    is_ready: bool
    generated_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class ScheduledGeneratedPostRecord:
    id: int
    channel_kind: str
    destination: str
    content_type: str
    payload: dict[str, Any]
    due_at: datetime
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


@dataclass(slots=True)
class PrivateBotUserRecord:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
    access_level: str
    access_status: str
    is_admin: bool
    referral_code: str | None
    referred_by_user_id: int | None


@dataclass(slots=True)
class UserSettingsRecord:
    telegram_user_id: int
    bot_kind: str
    direct_signal_delivery_enabled: bool
    followup_delivery_enabled: bool
    gold_alerts_enabled: bool
    language_code: str
    signal_profile: str
    base_signal_profile: str
    preferred_min_score: int | None
    min_quote_volume: float | None
    rsi_oversold: float | None
    rsi_overbought: float | None
    direction_filter: str
    watchlist_only: bool
    menu_collapsed: bool
    delivery_mode: str
    delivery_mode_changed_at: datetime | None
    quiet_hours_start_minute: int | None
    quiet_hours_end_minute: int | None
    snooze_until: datetime | None
    snooze_started_at: datetime | None
    snooze_label: str | None
    last_resume_summary_at: datetime | None
    last_digest_sent_at: datetime | None
    last_daily_recap_at: datetime | None
    last_weekly_recap_at: datetime | None
    active_watchlist_theme: str
    active_custom_theme_name: str | None
    onboarding_completed_at: datetime | None
    updated_at: datetime
    enabled_strategy_keys: tuple[str, ...]
    active_strategy_key: str | None
    strategy_selector_completed_at: datetime | None
    current_context: str | None = None
    current_strategy_context: str | None = None
    current_set_id: int | None = None
    timezone_name: str | None = None
    display_mode: str = "pro"
    active_workspace: str | None = None
    saved_workspace_payload: dict[str, Any] = field(default_factory=dict)
    strategy_preferences: dict[str, Any] = field(default_factory=dict)
    personalization: dict[str, Any] = field(default_factory=dict)
    delivery_rules: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PremiumStrategySettingsRecord:
    telegram_user_id: int
    bot_kind: str
    strategy_key: str
    direct_signal_delivery_enabled: bool
    followup_delivery_enabled: bool
    signal_profile: str
    base_signal_profile: str
    preferred_min_score: int | None
    min_quote_volume: float | None
    rsi_oversold: float | None
    rsi_overbought: float | None
    direction_filter: str
    watchlist_only: bool
    delivery_mode: str
    delivery_mode_changed_at: datetime | None
    quiet_hours_start_minute: int | None
    quiet_hours_end_minute: int | None
    snooze_until: datetime | None
    snooze_started_at: datetime | None
    snooze_label: str | None
    last_resume_summary_at: datetime | None
    last_digest_sent_at: datetime | None
    last_daily_recap_at: datetime | None
    last_weekly_recap_at: datetime | None
    active_watchlist_theme: str
    active_custom_theme_name: str | None
    updated_at: datetime
    strategy_preferences: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserAccessRecord:
    id: int
    telegram_user_id: int
    access_level: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class WatchlistEntry:
    telegram_user_id: int
    bot_kind: str
    symbol: str
    created_at: datetime


@dataclass(slots=True)
class ChatMemberRosterRecord:
    chat_id: str
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_bot: bool
    created_at: datetime
    last_seen_at: datetime


@dataclass(slots=True)
class DeliveredSignalRecord:
    id: int
    telegram_user_id: int
    bot_kind: str
    alert_id: int | None
    content_kind: str
    message_kind: str
    telegram_message_id: int | None
    delivered_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class SignalLifecycleRecord:
    signal_id: int
    alert_id: int | None
    source_signal_key: str
    strategy_code: str
    symbol: str
    asset_type: str
    direction: str
    timeframe: str
    status: str
    result_type: str
    entry_price: float
    entry_zone_low: float | None
    entry_zone_high: float | None
    invalidation_price: float | None
    tp_price_primary: float | None
    tp_price_secondary: float | None
    benchmark_win_percent: float
    created_at: datetime
    activated_at: datetime | None
    confirmed_at: datetime | None
    near_tp_at: datetime | None
    hit_tp_at: datetime | None
    invalidated_at: datetime | None
    expired_at: datetime | None
    closed_at: datetime | None
    expiry_at: datetime | None
    last_price: float | None
    last_price_at: datetime | None
    mfe_percent: float
    mae_percent: float
    market_regime_tag: str | None
    liquidity_tag: str | None
    confidence_score: float | None
    setup_quality: str | None
    explanation_short: str | None
    explanation_full: str | None
    ai_analysis_available: bool
    parent_alert_message_id: int | None
    source_type: str
    is_gold: bool
    ambiguous_resolution: bool
    metadata: dict[str, Any]


@dataclass(slots=True)
class SignalCandleRecord:
    id: int
    signal_id: int
    alert_id: int | None
    symbol: str
    timeframe: str
    candle_open_time: datetime
    candle_close_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None
    quote_volume: float | None
    source: str
    collected_at: datetime
    processed_at: datetime | None


@dataclass(slots=True)
class SignalEventRecord:
    event_id: int
    signal_id: int
    event_type: str
    old_status: str | None
    new_status: str | None
    event_payload: dict[str, Any]
    created_at: datetime
    created_by: str | None


@dataclass(slots=True)
class StrategyStatsSnapshotRecord:
    snapshot_id: int
    strategy_code: str
    timeframe_bucket: str | None
    market_regime_bucket: str | None
    asset_cluster_bucket: str | None
    period_type: str
    total_signals: int
    wins: int
    losses: int
    expired_neutral: int
    invalidated_count: int
    avg_rr: float | None
    avg_time_to_win_minutes: float | None
    avg_time_to_invalidation_minutes: float | None
    signals_per_day: float | None
    best_tf: str | None
    best_assets: str | None
    best_regime: str | None
    drawdown_profile: str | None
    calculated_at: datetime
    delivered_count: int = 0
    suppressed_count: int = 0
    ambiguous_count: int = 0
    sent_wins: int = 0
    sent_losses: int = 0
    sent_expired_neutral: int = 0
    sent_ambiguous_count: int = 0
    sent_avg_rr: float | None = None
    sent_signals_per_day: float | None = None
    sent_best_tf: str | None = None
    sent_best_assets: str | None = None
    sent_best_regime: str | None = None


@dataclass(slots=True)
class OnboardingStateRecord:
    telegram_user_id: int
    bot_kind: str
    step: str
    draft: dict[str, Any]
    updated_at: datetime
    completed_at: datetime | None


@dataclass(slots=True)
class WatchlistThemeRecord:
    id: int
    telegram_user_id: int
    bot_kind: str
    theme_name: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class UserSavedSetupRecord:
    id: int
    telegram_user_id: int
    bot_kind: str
    name: str
    is_default: bool
    is_pinned: bool
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


@dataclass(slots=True)
class UserStyleProfileRecord:
    telegram_user_id: int
    bot_kind: str
    title: str
    summary: str | None
    preferences: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class CryptoPayInvoiceRecord:
    invoice_id: int
    invoice_hash: str | None
    telegram_user_id: int | None
    bot_kind: str
    target_access_level: str
    target_duration_days: int
    amount: str | None
    asset: str | None
    currency_type: str | None
    description: str | None
    status: str
    pay_url: str | None
    custom_payload: str | None
    created_at: datetime
    paid_at: datetime | None
    activated_at: datetime | None
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class CryptoPayWebhookEventRecord:
    id: int
    event_hash: str
    update_type: str
    invoice_id: int | None
    request_date: datetime | None
    status: str
    processed_at: datetime
    last_error: str | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class OnboardingCampaignRecord:
    id: int
    telegram_user_id: int
    bot_kind: str
    campaign_type: str
    first_contact_at: datetime
    trial_started_at: datetime | None
    trial_ends_at: datetime | None
    referred_by_user_id: int | None
    invoice_id: int | None
    offer_sent_at: datetime | None
    status: str
    attempt_count: int
    next_retry_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class ReferralRecord:
    id: int
    referrer_user_id: int
    referred_user_id: int
    bot_kind: str
    status: str
    source_payload: str | None
    created_at: datetime
    converted_at: datetime | None
    first_paid_conversion_at: datetime | None
    counted_as_paid_referral: bool
    conversion_invoice_id: int | None
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class ReferralCycleStatRecord:
    referrer_user_id: int
    active_cycle_paid_referrals_count: int
    lifetime_paid_referrals_count: int
    current_cycle_number: int
    last_reward_milestone_reached: int
    updated_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True)
class ReferralRewardGrantRecord:
    id: int
    referrer_user_id: int
    referred_user_id: int | None
    reward_type: str
    reward_days: int
    milestone_trigger: int
    cycle_number: int
    granted_at: datetime
    access_extension_from: datetime | None
    access_extension_to: datetime | None
    metadata: dict[str, Any]
