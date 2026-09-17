from __future__ import annotations

import aiosqlite

from src.core.strategy_keys import PREMIUM_STRATEGY_KEYS


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    strategy_key TEXT NOT NULL DEFAULT 'rsi',
    timeframe TEXT NOT NULL,
    candle_open_time TEXT NOT NULL,
    candle_close_time TEXT NOT NULL,
    alert_price REAL NOT NULL,
    alert_rsi REAL NOT NULL,
    day_change_pct REAL,
    day_volume REAL,
    score INTEGER NOT NULL,
    alert_sent_at TEXT NOT NULL,
    followup_due_at TEXT NOT NULL,
    followup_sent_at TEXT,
    lab_message_id INTEGER,
    metadata_json TEXT,
    UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)
);

CREATE TABLE IF NOT EXISTS symbol_state (
    symbol TEXT PRIMARY KEY,
    timeframe TEXT NOT NULL,
    last_rsi REAL,
    zone TEXT NOT NULL,
    oversold_active INTEGER NOT NULL DEFAULT 0,
    overbought_active INTEGER NOT NULL DEFAULT 0,
    oversold_last_alert_at TEXT,
    overbought_last_alert_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followup_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS followup_results (
    alert_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    alert_price REAL NOT NULL,
    alert_rsi REAL NOT NULL,
    score INTEGER NOT NULL,
    current_price REAL NOT NULL,
    current_rsi REAL NOT NULL,
    move_pct REAL NOT NULL,
    summary TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS followup_stage_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    stage TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT,
    UNIQUE(alert_id, stage),
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS followup_stage_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    alert_price REAL NOT NULL,
    alert_rsi REAL NOT NULL,
    score INTEGER NOT NULL,
    current_price REAL NOT NULL,
    current_rsi REAL NOT NULL,
    move_pct REAL NOT NULL,
    summary TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(alert_id, stage),
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS posts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    related_alert_id INTEGER,
    source_symbol TEXT,
    channel_kind TEXT NOT NULL,
    destination TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'unknown',
    content TEXT NOT NULL,
    generated_text TEXT,
    short_variant TEXT,
    reply_variant TEXT,
    status TEXT NOT NULL,
    ai_model TEXT,
    model_name TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS message_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination TEXT NOT NULL,
    message_type TEXT NOT NULL,
    status TEXT NOT NULL,
    telegram_message_id INTEGER,
    created_at TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS interactive_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    alert_id INTEGER,
    destination_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    original_timeframe TEXT NOT NULL,
    displayed_timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    is_preview INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(chat_id, message_id),
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    content TEXT NOT NULL,
    model_name TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS prepared_feature_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_data_hash TEXT NOT NULL,
    text_payload TEXT,
    json_payload TEXT,
    model_name TEXT,
    is_ready INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS scheduled_generated_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_kind TEXT NOT NULL,
    destination TEXT NOT NULL,
    content_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS bot_users (
    telegram_user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    access_level TEXT NOT NULL DEFAULT 'free',
    access_status TEXT NOT NULL DEFAULT 'free',
    is_admin INTEGER NOT NULL DEFAULT 0,
    referral_code TEXT UNIQUE,
    referred_by_user_id INTEGER,
    FOREIGN KEY(referred_by_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    telegram_user_id INTEGER PRIMARY KEY,
    direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    gold_alerts_enabled INTEGER NOT NULL DEFAULT 0,
    language_code TEXT NOT NULL DEFAULT 'en',
    signal_profile TEXT NOT NULL DEFAULT 'balanced',
    preferred_min_score INTEGER,
    min_quote_volume REAL,
    rsi_oversold REAL,
    rsi_overbought REAL,
    direction_filter TEXT NOT NULL DEFAULT 'both',
    watchlist_only INTEGER NOT NULL DEFAULT 0,
    menu_collapsed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    access_level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS crypto_pay_invoices (
    invoice_id INTEGER PRIMARY KEY,
    invoice_hash TEXT UNIQUE,
    telegram_user_id INTEGER,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    target_access_level TEXT NOT NULL DEFAULT 'pro',
    target_duration_days INTEGER NOT NULL DEFAULT 30,
    amount TEXT,
    asset TEXT,
    currency_type TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    pay_url TEXT,
    custom_payload TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    activated_at TEXT,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS crypto_pay_webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_hash TEXT NOT NULL UNIQUE,
    update_type TEXT NOT NULL,
    invoice_id INTEGER,
    request_date TEXT,
    status TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    last_error TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY(invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
);

CREATE TABLE IF NOT EXISTS onboarding_payment_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    campaign_type TEXT NOT NULL DEFAULT 'trial_48h',
    first_contact_at TEXT NOT NULL,
    trial_started_at TEXT,
    trial_ends_at TEXT,
    referred_by_user_id INTEGER,
    invoice_id INTEGER,
    offer_sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'trial_active',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(telegram_user_id, bot_kind, campaign_type),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(referred_by_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_user_id INTEGER NOT NULL,
    referred_user_id INTEGER NOT NULL UNIQUE,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    status TEXT NOT NULL DEFAULT 'registered',
    source_payload TEXT,
    created_at TEXT NOT NULL,
    converted_at TEXT,
    first_paid_conversion_at TEXT,
    counted_as_paid_referral INTEGER NOT NULL DEFAULT 0,
    conversion_invoice_id INTEGER,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(referred_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(conversion_invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
);

CREATE TABLE IF NOT EXISTS referral_cycle_stats (
    referrer_user_id INTEGER PRIMARY KEY,
    active_cycle_paid_referrals_count INTEGER NOT NULL DEFAULT 0,
    lifetime_paid_referrals_count INTEGER NOT NULL DEFAULT 0,
    current_cycle_number INTEGER NOT NULL DEFAULT 1,
    last_reward_milestone_reached INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS referral_reward_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_user_id INTEGER NOT NULL,
    referred_user_id INTEGER,
    reward_type TEXT NOT NULL DEFAULT 'premium_days',
    reward_days INTEGER NOT NULL,
    milestone_trigger INTEGER NOT NULL,
    cycle_number INTEGER NOT NULL,
    granted_at TEXT NOT NULL,
    access_extension_from TEXT,
    access_extension_to TEXT,
    metadata_json TEXT,
    UNIQUE(referrer_user_id, cycle_number, milestone_trigger),
    FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(referred_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS delivered_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    alert_id INTEGER,
    content_kind TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    telegram_message_id INTEGER,
    delivered_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(telegram_user_id, alert_id, content_kind, message_kind),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS user_bot_settings (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL,
    direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    gold_alerts_enabled INTEGER NOT NULL DEFAULT 0,
    language_code TEXT NOT NULL DEFAULT 'en',
    signal_profile TEXT NOT NULL DEFAULT 'balanced',
    base_signal_profile TEXT NOT NULL DEFAULT 'balanced',
    preferred_min_score INTEGER,
    min_quote_volume REAL,
    rsi_oversold REAL,
    rsi_overbought REAL,
    direction_filter TEXT NOT NULL DEFAULT 'both',
    watchlist_only INTEGER NOT NULL DEFAULT 0,
    menu_collapsed INTEGER NOT NULL DEFAULT 0,
    delivery_mode TEXT NOT NULL DEFAULT 'instant',
    delivery_mode_changed_at TEXT,
    quiet_hours_start_minute INTEGER,
    quiet_hours_end_minute INTEGER,
    snooze_until TEXT,
    snooze_started_at TEXT,
    snooze_label TEXT,
    last_resume_summary_at TEXT,
    last_digest_sent_at TEXT,
    last_daily_recap_at TEXT,
    last_weekly_recap_at TEXT,
    active_watchlist_theme TEXT NOT NULL DEFAULT 'custom',
    active_custom_theme_name TEXT,
    onboarding_completed_at TEXT,
    enabled_strategy_keys_json TEXT NOT NULL DEFAULT '[]',
    active_strategy_key TEXT,
    strategy_selector_completed_at TEXT,
    current_context TEXT,
    current_strategy_context TEXT,
    current_set_id INTEGER,
    timezone_name TEXT,
    display_mode TEXT NOT NULL DEFAULT 'pro',
    active_workspace TEXT,
    saved_workspace_payload_json TEXT NOT NULL DEFAULT '{}',
    strategy_preferences_json TEXT NOT NULL DEFAULT '{}',
    personalization_json TEXT NOT NULL DEFAULT '{}',
    delivery_rules_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, bot_kind),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS tracked_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER UNIQUE,
    source_signal_key TEXT NOT NULL UNIQUE,
    strategy_code TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    status TEXT NOT NULL,
    result_type TEXT NOT NULL DEFAULT 'open',
    entry_price REAL NOT NULL,
    entry_zone_low REAL,
    entry_zone_high REAL,
    invalidation_price REAL,
    tp_price_primary REAL,
    tp_price_secondary REAL,
    benchmark_win_percent REAL NOT NULL DEFAULT 7.0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    confirmed_at TEXT,
    near_tp_at TEXT,
    hit_tp_at TEXT,
    invalidated_at TEXT,
    expired_at TEXT,
    closed_at TEXT,
    expiry_at TEXT,
    last_price REAL,
    last_price_at TEXT,
    mfe_percent REAL NOT NULL DEFAULT 0,
    mae_percent REAL NOT NULL DEFAULT 0,
    market_regime_tag TEXT,
    liquidity_tag TEXT,
    confidence_score REAL,
    setup_quality TEXT,
    explanation_short TEXT,
    explanation_full TEXT,
    ai_analysis_available INTEGER NOT NULL DEFAULT 0,
    parent_alert_message_id INTEGER,
    source_type TEXT NOT NULL DEFAULT 'strategy_stream',
    is_gold INTEGER NOT NULL DEFAULT 0,
    ambiguous_resolution INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS signal_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    event_payload_json TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT,
    FOREIGN KEY(signal_id) REFERENCES tracked_signals(signal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tracked_signal_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    alert_id INTEGER,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle_open_time TEXT NOT NULL,
    candle_close_time TEXT NOT NULL,
    open_price REAL NOT NULL,
    high_price REAL NOT NULL,
    low_price REAL NOT NULL,
    close_price REAL NOT NULL,
    volume REAL,
    quote_volume REAL,
    source TEXT NOT NULL DEFAULT 'rest_backfill',
    collected_at TEXT NOT NULL,
    processed_at TEXT,
    UNIQUE(signal_id, candle_open_time),
    FOREIGN KEY(signal_id) REFERENCES tracked_signals(signal_id) ON DELETE CASCADE,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS strategy_stats_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_code TEXT NOT NULL,
    timeframe_bucket TEXT,
    market_regime_bucket TEXT,
    asset_cluster_bucket TEXT,
    period_type TEXT NOT NULL,
    total_signals INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    expired_neutral INTEGER NOT NULL DEFAULT 0,
    invalidated_count INTEGER NOT NULL DEFAULT 0,
    avg_rr REAL,
    avg_time_to_win_minutes REAL,
    avg_time_to_invalidation_minutes REAL,
    signals_per_day REAL,
    best_tf TEXT,
    best_assets TEXT,
    best_regime TEXT,
    drawdown_profile TEXT,
    delivered_count INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0,
    ambiguous_count INTEGER NOT NULL DEFAULT 0,
    calculated_at TEXT NOT NULL,
    UNIQUE(strategy_code, timeframe_bucket, market_regime_bucket, asset_cluster_bucket, period_type)
);

CREATE TABLE IF NOT EXISTS telemetry_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    telegram_user_id INTEGER,
    context TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_watchlist (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, bot_kind, symbol),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_onboarding_state (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL,
    step TEXT NOT NULL,
    draft_json TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (telegram_user_id, bot_kind),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_watchlist_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL,
    theme_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(telegram_user_id, bot_kind, theme_name),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_watchlist_theme_symbols (
    theme_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (theme_id, symbol),
    FOREIGN KEY(theme_id) REFERENCES user_watchlist_themes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_saved_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    UNIQUE(telegram_user_id, bot_kind, name),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS user_style_profiles (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    title TEXT NOT NULL DEFAULT 'Balanced Trader',
    summary TEXT,
    preferences_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, bot_kind),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS chat_member_roster (
    chat_id TEXT NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, telegram_user_id)
);

CREATE TABLE IF NOT EXISTS delivered_bot_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL,
    alert_id INTEGER,
    content_kind TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    telegram_message_id INTEGER,
    delivered_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(telegram_user_id, bot_kind, alert_id, content_kind, message_kind),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS premium_strategy_settings (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    strategy_key TEXT NOT NULL,
    direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
    signal_profile TEXT NOT NULL DEFAULT 'balanced',
    base_signal_profile TEXT NOT NULL DEFAULT 'balanced',
    preferred_min_score INTEGER,
    min_quote_volume REAL,
    rsi_oversold REAL,
    rsi_overbought REAL,
    direction_filter TEXT NOT NULL DEFAULT 'both',
    watchlist_only INTEGER NOT NULL DEFAULT 0,
    delivery_mode TEXT NOT NULL DEFAULT 'instant',
    delivery_mode_changed_at TEXT,
    quiet_hours_start_minute INTEGER,
    quiet_hours_end_minute INTEGER,
    snooze_until TEXT,
    snooze_started_at TEXT,
    snooze_label TEXT,
    last_resume_summary_at TEXT,
    last_digest_sent_at TEXT,
    last_daily_recap_at TEXT,
    last_weekly_recap_at TEXT,
    active_watchlist_theme TEXT NOT NULL DEFAULT 'custom',
    active_custom_theme_name TEXT,
    strategy_preferences_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, bot_kind, strategy_key),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS premium_strategy_watchlist (
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    strategy_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, bot_kind, strategy_key, symbol),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS premium_strategy_watchlist_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    bot_kind TEXT NOT NULL DEFAULT 'premium',
    strategy_key TEXT NOT NULL,
    theme_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(telegram_user_id, bot_kind, strategy_key, theme_name),
    FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS premium_strategy_watchlist_theme_symbols (
    theme_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (theme_id, symbol),
    FOREIGN KEY(theme_id) REFERENCES premium_strategy_watchlist_themes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol_direction ON alerts(symbol, direction, alert_sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_followup_due_at ON followup_tasks(status, due_at);
CREATE INDEX IF NOT EXISTS idx_followup_results_observed_at ON followup_results(observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_followup_stage_due_at ON followup_stage_tasks(status, due_at);
CREATE INDEX IF NOT EXISTS idx_followup_stage_results_observed_at ON followup_stage_results(observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_followup_stage_results_alert_observed ON followup_stage_results(alert_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_related_alert_id ON posts_history(related_alert_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_destination_created_at ON message_log(destination, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactive_alerts_chat_message ON interactive_alerts(chat_id, message_id);
CREATE INDEX IF NOT EXISTS idx_interactive_alerts_alert_id ON interactive_alerts(alert_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_lookup ON analysis_cache(symbol, timeframe, analysis_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prepared_feature_cards_lookup ON prepared_feature_cards(symbol, timeframe, content_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_generated_posts_due_at ON scheduled_generated_posts(status, due_at);
CREATE INDEX IF NOT EXISTS idx_bot_users_access_level ON bot_users(access_level, is_active);
CREATE INDEX IF NOT EXISTS idx_user_access_lookup ON user_access(telegram_user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_pay_invoices_user_status ON crypto_pay_invoices(telegram_user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_pay_invoices_hash ON crypto_pay_invoices(invoice_hash);
CREATE INDEX IF NOT EXISTS idx_crypto_pay_webhook_events_invoice ON crypto_pay_webhook_events(invoice_id, processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_onboarding_payment_campaigns_due ON onboarding_payment_campaigns(status, trial_ends_at, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_onboarding_payment_campaigns_invoice ON onboarding_payment_campaigns(invoice_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer_status ON referrals(referrer_user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_referral_reward_grants_referrer ON referral_reward_grants(referrer_user_id, granted_at DESC);
CREATE INDEX IF NOT EXISTS idx_delivered_signals_user_alert ON delivered_signals(telegram_user_id, alert_id, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_bot_settings_lookup ON user_bot_settings(telegram_user_id, bot_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_delivered_bot_signals_user_alert ON delivered_bot_signals(telegram_user_id, bot_kind, alert_id, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_watchlist_lookup ON user_watchlist(telegram_user_id, bot_kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_onboarding_state_lookup ON user_onboarding_state(telegram_user_id, bot_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_watchlist_themes_lookup ON user_watchlist_themes(telegram_user_id, bot_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_watchlist_theme_symbols_lookup ON user_watchlist_theme_symbols(theme_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_saved_setups_lookup ON user_saved_setups(telegram_user_id, bot_kind, is_pinned DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_style_profiles_lookup ON user_style_profiles(telegram_user_id, bot_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_strategy_settings_lookup ON premium_strategy_settings(telegram_user_id, bot_kind, strategy_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_lookup ON premium_strategy_watchlist(telegram_user_id, bot_kind, strategy_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_themes_lookup ON premium_strategy_watchlist_themes(telegram_user_id, bot_kind, strategy_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_theme_symbols_lookup ON premium_strategy_watchlist_theme_symbols(theme_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_signals_status ON tracked_signals(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_signals_strategy_status ON tracked_signals(strategy_code, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_signals_symbol_timeframe ON tracked_signals(symbol, timeframe, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_signals_expiry ON tracked_signals(status, expiry_at);
CREATE INDEX IF NOT EXISTS idx_tracked_signals_maintenance ON tracked_signals(status, last_price_at, created_at);
CREATE INDEX IF NOT EXISTS idx_signal_events_signal_created ON signal_events(signal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_signal_processed ON tracked_signal_candles(signal_id, processed_at, candle_close_time ASC);
CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_alert_time ON tracked_signal_candles(alert_id, candle_close_time ASC);
CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_symbol_timeframe ON tracked_signal_candles(symbol, timeframe, candle_open_time ASC);
CREATE INDEX IF NOT EXISTS idx_strategy_stats_snapshots_lookup ON strategy_stats_snapshots(strategy_code, period_type, calculated_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_lookup ON telemetry_events(event_name, created_at DESC);
"""


async def initialize_database(sqlite_path: str) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        connection.row_factory = aiosqlite.Row
        await connection.executescript(SCHEMA)
        await _migrate_posts_history(connection)
        await _migrate_message_log(connection)
        await _migrate_followup_results(connection)
        await _migrate_followup_stage_tables(connection)
        await _migrate_interactive_alerts(connection)
        await _migrate_analysis_cache(connection)
        await _migrate_prepared_feature_cards(connection)
        await _migrate_scheduled_generated_posts(connection)
        await _migrate_private_bot_tables(connection)
        await _migrate_scoped_user_tables(connection)
        await _migrate_user_watchlist(connection)
        await _migrate_user_experience_tables(connection)
        await _migrate_chat_member_roster(connection)
        await _migrate_premium_strategy_tables(connection)
        await _migrate_crypto_pay_tables(connection)
        await _migrate_onboarding_payment_tables(connection)
        await _migrate_referral_program_tables(connection)
        await _migrate_signal_lifecycle_tables(connection)
        await connection.commit()


async def _migrate_posts_history(connection: aiosqlite.Connection) -> None:
    cursor = await connection.execute("PRAGMA table_info(posts_history)")
    columns = {row[1] for row in await cursor.fetchall()}
    required_columns = {
        "related_alert_id": "ALTER TABLE posts_history ADD COLUMN related_alert_id INTEGER",
        "source_symbol": "ALTER TABLE posts_history ADD COLUMN source_symbol TEXT",
        "content_type": "ALTER TABLE posts_history ADD COLUMN content_type TEXT NOT NULL DEFAULT 'unknown'",
        "generated_text": "ALTER TABLE posts_history ADD COLUMN generated_text TEXT",
        "short_variant": "ALTER TABLE posts_history ADD COLUMN short_variant TEXT",
        "reply_variant": "ALTER TABLE posts_history ADD COLUMN reply_variant TEXT",
        "model_name": "ALTER TABLE posts_history ADD COLUMN model_name TEXT",
    }
    for name, statement in required_columns.items():
        if name not in columns:
            await connection.execute(statement)


async def _migrate_message_log(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS message_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            destination TEXT NOT NULL,
            message_type TEXT NOT NULL,
            status TEXT NOT NULL,
            telegram_message_id INTEGER,
            created_at TEXT NOT NULL,
            metadata_json TEXT
        )
        """
    )


async def _migrate_followup_results(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS followup_results (
            alert_id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            alert_price REAL NOT NULL,
            alert_rsi REAL NOT NULL,
            score INTEGER NOT NULL,
            current_price REAL NOT NULL,
            current_rsi REAL NOT NULL,
            move_pct REAL NOT NULL,
            summary TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )


async def _migrate_followup_stage_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS followup_stage_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            stage TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            executed_at TEXT,
            UNIQUE(alert_id, stage),
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS followup_stage_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            alert_price REAL NOT NULL,
            alert_rsi REAL NOT NULL,
            score INTEGER NOT NULL,
            current_price REAL NOT NULL,
            current_rsi REAL NOT NULL,
            move_pct REAL NOT NULL,
            summary TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(alert_id, stage),
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )
    await connection.execute(
        """
        INSERT OR IGNORE INTO followup_stage_tasks (
            alert_id,
            symbol,
            direction,
            stage,
            due_at,
            status,
            attempts,
            last_error,
            created_at,
            executed_at
        )
        SELECT
            alert_id,
            symbol,
            direction,
            '2h',
            due_at,
            status,
            attempts,
            last_error,
            created_at,
            executed_at
        FROM followup_tasks
        """
    )
    await connection.execute(
        """
        INSERT OR IGNORE INTO followup_stage_results (
            alert_id,
            stage,
            symbol,
            direction,
            timeframe,
            alert_price,
            alert_rsi,
            score,
            current_price,
            current_rsi,
            move_pct,
            summary,
            observed_at,
            metadata_json
        )
        SELECT
            alert_id,
            '2h',
            symbol,
            direction,
            timeframe,
            alert_price,
            alert_rsi,
            score,
            current_price,
            current_rsi,
            move_pct,
            summary,
            observed_at,
            metadata_json
        FROM followup_results
        """
    )


async def _migrate_interactive_alerts(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS interactive_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            alert_id INTEGER,
            destination_kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            original_timeframe TEXT NOT NULL,
            displayed_timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            is_preview INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(chat_id, message_id),
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )


async def _migrate_analysis_cache(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            analysis_type TEXT NOT NULL,
            content TEXT NOT NULL,
            model_name TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )


async def _migrate_prepared_feature_cards(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS prepared_feature_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            content_type TEXT NOT NULL,
            source_data_hash TEXT NOT NULL,
            text_payload TEXT,
            json_payload TEXT,
            model_name TEXT,
            is_ready INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )


async def _migrate_scheduled_generated_posts(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_generated_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_kind TEXT NOT NULL,
            destination TEXT NOT NULL,
            content_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_generated_posts_due_at ON scheduled_generated_posts(status, due_at)"
    )


async def _migrate_private_bot_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_users (
            telegram_user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            access_level TEXT NOT NULL DEFAULT 'free',
            access_status TEXT NOT NULL DEFAULT 'free',
            is_admin INTEGER NOT NULL DEFAULT 0,
            referred_by_user_id INTEGER,
            FOREIGN KEY(referred_by_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    cursor = await connection.execute("PRAGMA table_info(bot_users)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "access_status" not in columns:
        await connection.execute(
            "ALTER TABLE bot_users ADD COLUMN access_status TEXT NOT NULL DEFAULT 'free'"
        )
    if "is_admin" not in columns:
        await connection.execute(
            "ALTER TABLE bot_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
        )
    if "referred_by_user_id" not in columns:
        await connection.execute(
            "ALTER TABLE bot_users ADD COLUMN referred_by_user_id INTEGER"
        )
    if "referral_code" not in columns:
        await connection.execute(
            "ALTER TABLE bot_users ADD COLUMN referral_code TEXT"
        )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            telegram_user_id INTEGER PRIMARY KEY,
            direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            gold_alerts_enabled INTEGER NOT NULL DEFAULT 0,
            preferred_min_score INTEGER,
            menu_collapsed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    cursor = await connection.execute("PRAGMA table_info(user_settings)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "menu_collapsed" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN menu_collapsed INTEGER NOT NULL DEFAULT 0"
        )
    if "followup_delivery_enabled" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN followup_delivery_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "gold_alerts_enabled" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN gold_alerts_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "language_code" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN language_code TEXT NOT NULL DEFAULT 'en'"
        )
    if "signal_profile" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN signal_profile TEXT NOT NULL DEFAULT 'balanced'"
        )
    if "min_quote_volume" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN min_quote_volume REAL"
        )
    if "rsi_oversold" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN rsi_oversold REAL"
        )
    if "rsi_overbought" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN rsi_overbought REAL"
        )
    if "direction_filter" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN direction_filter TEXT NOT NULL DEFAULT 'both'"
        )
    if "watchlist_only" not in columns:
        await connection.execute(
            "ALTER TABLE user_settings ADD COLUMN watchlist_only INTEGER NOT NULL DEFAULT 0"
        )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            access_level TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            starts_at TEXT NOT NULL,
            ends_at TEXT,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS delivered_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            alert_id INTEGER,
            content_kind TEXT NOT NULL,
            message_kind TEXT NOT NULL,
            telegram_message_id INTEGER,
            delivered_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(telegram_user_id, alert_id, content_kind, message_kind),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )


async def _migrate_scoped_user_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_bot_settings (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL,
            direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            gold_alerts_enabled INTEGER NOT NULL DEFAULT 0,
            preferred_min_score INTEGER,
            menu_collapsed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, bot_kind),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    cursor = await connection.execute("PRAGMA table_info(user_bot_settings)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "gold_alerts_enabled" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN gold_alerts_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "language_code" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN language_code TEXT NOT NULL DEFAULT 'en'"
        )
    if "signal_profile" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN signal_profile TEXT NOT NULL DEFAULT 'balanced'"
        )
    if "base_signal_profile" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN base_signal_profile TEXT NOT NULL DEFAULT 'balanced'"
        )
        await connection.execute(
            """
            UPDATE user_bot_settings
            SET base_signal_profile = CASE
                WHEN LOWER(COALESCE(signal_profile, 'balanced')) IN ('conservative', 'balanced', 'aggressive')
                    THEN LOWER(COALESCE(signal_profile, 'balanced'))
                ELSE 'balanced'
            END
            """
        )
    if "min_quote_volume" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN min_quote_volume REAL"
        )
    if "rsi_oversold" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN rsi_oversold REAL"
        )
    if "rsi_overbought" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN rsi_overbought REAL"
        )
    if "direction_filter" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN direction_filter TEXT NOT NULL DEFAULT 'both'"
        )
    if "watchlist_only" not in columns:
        await connection.execute(
            "ALTER TABLE user_bot_settings ADD COLUMN watchlist_only INTEGER NOT NULL DEFAULT 0"
        )
    await connection.execute(
        """
        INSERT OR IGNORE INTO user_bot_settings (
            telegram_user_id,
            bot_kind,
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            gold_alerts_enabled,
            language_code,
            signal_profile,
            base_signal_profile,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            direction_filter,
            watchlist_only,
            menu_collapsed,
            updated_at
        )
        SELECT
            telegram_user_id,
            'premium',
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            COALESCE(gold_alerts_enabled, 0),
            COALESCE(language_code, 'en'),
            COALESCE(signal_profile, 'balanced'),
            CASE
                WHEN LOWER(COALESCE(signal_profile, 'balanced')) IN ('conservative', 'balanced', 'aggressive')
                    THEN LOWER(COALESCE(signal_profile, 'balanced'))
                ELSE 'balanced'
            END,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            COALESCE(direction_filter, 'both'),
            COALESCE(watchlist_only, 0),
            menu_collapsed,
            updated_at
        FROM user_settings
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS delivered_bot_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL,
            alert_id INTEGER,
            content_kind TEXT NOT NULL,
            message_kind TEXT NOT NULL,
            telegram_message_id INTEGER,
            delivered_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(telegram_user_id, bot_kind, alert_id, content_kind, message_kind),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )
    await connection.execute(
        """
        INSERT OR IGNORE INTO delivered_bot_signals (
            telegram_user_id,
            bot_kind,
            alert_id,
            content_kind,
            message_kind,
            telegram_message_id,
            delivered_at,
            metadata_json
        )
        SELECT
            telegram_user_id,
            'premium',
            alert_id,
            content_kind,
            message_kind,
            telegram_message_id,
            delivered_at,
            metadata_json
        FROM delivered_signals
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_bot_settings_lookup ON user_bot_settings(telegram_user_id, bot_kind, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_delivered_bot_signals_user_alert ON delivered_bot_signals(telegram_user_id, bot_kind, alert_id, delivered_at DESC)"
    )


async def _migrate_user_watchlist(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_watchlist (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, bot_kind, symbol),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_watchlist_lookup ON user_watchlist(telegram_user_id, bot_kind, created_at DESC)"
    )


async def _migrate_user_experience_tables(connection: aiosqlite.Connection) -> None:
    cursor = await connection.execute("PRAGMA table_info(user_bot_settings)")
    columns = {row[1] for row in await cursor.fetchall()}
    required_columns = {
        "base_signal_profile": "ALTER TABLE user_bot_settings ADD COLUMN base_signal_profile TEXT NOT NULL DEFAULT 'balanced'",
        "delivery_mode": "ALTER TABLE user_bot_settings ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'instant'",
        "delivery_mode_changed_at": "ALTER TABLE user_bot_settings ADD COLUMN delivery_mode_changed_at TEXT",
        "quiet_hours_start_minute": "ALTER TABLE user_bot_settings ADD COLUMN quiet_hours_start_minute INTEGER",
        "quiet_hours_end_minute": "ALTER TABLE user_bot_settings ADD COLUMN quiet_hours_end_minute INTEGER",
        "snooze_until": "ALTER TABLE user_bot_settings ADD COLUMN snooze_until TEXT",
        "snooze_started_at": "ALTER TABLE user_bot_settings ADD COLUMN snooze_started_at TEXT",
        "snooze_label": "ALTER TABLE user_bot_settings ADD COLUMN snooze_label TEXT",
        "last_resume_summary_at": "ALTER TABLE user_bot_settings ADD COLUMN last_resume_summary_at TEXT",
        "last_digest_sent_at": "ALTER TABLE user_bot_settings ADD COLUMN last_digest_sent_at TEXT",
        "last_daily_recap_at": "ALTER TABLE user_bot_settings ADD COLUMN last_daily_recap_at TEXT",
        "last_weekly_recap_at": "ALTER TABLE user_bot_settings ADD COLUMN last_weekly_recap_at TEXT",
        "active_watchlist_theme": "ALTER TABLE user_bot_settings ADD COLUMN active_watchlist_theme TEXT NOT NULL DEFAULT 'custom'",
        "active_custom_theme_name": "ALTER TABLE user_bot_settings ADD COLUMN active_custom_theme_name TEXT",
        "onboarding_completed_at": "ALTER TABLE user_bot_settings ADD COLUMN onboarding_completed_at TEXT",
        "current_context": "ALTER TABLE user_bot_settings ADD COLUMN current_context TEXT",
        "current_strategy_context": "ALTER TABLE user_bot_settings ADD COLUMN current_strategy_context TEXT",
        "current_set_id": "ALTER TABLE user_bot_settings ADD COLUMN current_set_id INTEGER",
        "timezone_name": "ALTER TABLE user_bot_settings ADD COLUMN timezone_name TEXT",
        "display_mode": "ALTER TABLE user_bot_settings ADD COLUMN display_mode TEXT NOT NULL DEFAULT 'pro'",
        "active_workspace": "ALTER TABLE user_bot_settings ADD COLUMN active_workspace TEXT",
        "saved_workspace_payload_json": "ALTER TABLE user_bot_settings ADD COLUMN saved_workspace_payload_json TEXT NOT NULL DEFAULT '{}'",
        "personalization_json": "ALTER TABLE user_bot_settings ADD COLUMN personalization_json TEXT NOT NULL DEFAULT '{}'",
        "delivery_rules_json": "ALTER TABLE user_bot_settings ADD COLUMN delivery_rules_json TEXT NOT NULL DEFAULT '{}'",
    }
    for name, statement in required_columns.items():
        if name not in columns:
            await connection.execute(statement)
    if "base_signal_profile" not in columns:
        await connection.execute(
            """
            UPDATE user_bot_settings
            SET base_signal_profile = CASE
                WHEN LOWER(COALESCE(signal_profile, 'balanced')) IN ('conservative', 'balanced', 'aggressive')
                    THEN LOWER(COALESCE(signal_profile, 'balanced'))
                ELSE 'balanced'
            END
            """
        )

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_onboarding_state (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL,
            step TEXT NOT NULL,
            draft_json TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            PRIMARY KEY (telegram_user_id, bot_kind),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_watchlist_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL,
            theme_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(telegram_user_id, bot_kind, theme_name),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_watchlist_theme_symbols (
            theme_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (theme_id, symbol),
            FOREIGN KEY(theme_id) REFERENCES user_watchlist_themes(id) ON DELETE CASCADE
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_onboarding_state_lookup ON user_onboarding_state(telegram_user_id, bot_kind, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_watchlist_themes_lookup ON user_watchlist_themes(telegram_user_id, bot_kind, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_watchlist_theme_symbols_lookup ON user_watchlist_theme_symbols(theme_id, created_at DESC)"
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_saved_setups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            name TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT,
            UNIQUE(telegram_user_id, bot_kind, name),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_style_profiles (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            title TEXT NOT NULL DEFAULT 'Balanced Trader',
            summary TEXT,
            preferences_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, bot_kind),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_saved_setups_lookup ON user_saved_setups(telegram_user_id, bot_kind, is_pinned DESC, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_style_profiles_lookup ON user_style_profiles(telegram_user_id, bot_kind, updated_at DESC)"
    )


async def _migrate_chat_member_roster(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_member_roster (
            chat_id TEXT NOT NULL,
            telegram_user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_bot INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_member_roster_chat_seen
        ON chat_member_roster(chat_id, last_seen_at DESC)
        """
    )


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _quoted_sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + str(value).replace("'", "''") + "'" for value in values)


async def _merge_alert_strategy_conflicts(
    connection: aiosqlite.Connection,
    *,
    alerts_table: str,
    target_strategy_sql: str,
) -> None:
    quoted_alerts_table = _quote_identifier(alerts_table)
    mapping_table = f"{alerts_table}_strategy_conflict_map"
    quoted_mapping_table = _quote_identifier(mapping_table)
    await connection.execute(f"DROP TABLE IF EXISTS {quoted_mapping_table}")
    await connection.execute(
        f"""
        CREATE TEMP TABLE {quoted_mapping_table} AS
        WITH alert_targets AS (
            SELECT
                id AS source_alert_id,
                symbol,
                direction,
                timeframe,
                candle_open_time,
                {target_strategy_sql} AS target_strategy_key
            FROM {quoted_alerts_table}
        ),
        grouped_targets AS (
            SELECT
                symbol,
                direction,
                timeframe,
                candle_open_time,
                target_strategy_key,
                MIN(source_alert_id) AS canonical_alert_id,
                COUNT(*) AS row_count
            FROM alert_targets
            GROUP BY symbol, direction, timeframe, candle_open_time, target_strategy_key
            HAVING COUNT(*) > 1
        )
        SELECT
            alert_targets.source_alert_id,
            grouped_targets.canonical_alert_id
        FROM alert_targets
        JOIN grouped_targets
          ON grouped_targets.symbol = alert_targets.symbol
         AND grouped_targets.direction = alert_targets.direction
         AND grouped_targets.timeframe = alert_targets.timeframe
         AND grouped_targets.candle_open_time = alert_targets.candle_open_time
         AND grouped_targets.target_strategy_key = alert_targets.target_strategy_key
        WHERE alert_targets.source_alert_id <> grouped_targets.canonical_alert_id
        """
    )
    cursor = await connection.execute(f"SELECT COUNT(*) FROM {quoted_mapping_table}")
    mapping_row = await cursor.fetchone()
    if mapping_row is None or int(mapping_row[0] or 0) <= 0:
        await connection.execute(f"DROP TABLE IF EXISTS {quoted_mapping_table}")
        return

    dependent_tables = (
        "followup_tasks",
        "followup_results",
        "followup_stage_tasks",
        "followup_stage_results",
        "interactive_alerts",
        "analysis_cache",
        "prepared_feature_cards",
        "delivered_signals",
        "delivered_bot_signals",
    )
    for table_name in dependent_tables:
        quoted_table_name = _quote_identifier(table_name)
        await connection.execute(
            f"""
            UPDATE OR IGNORE {quoted_table_name}
            SET alert_id = (
                SELECT canonical_alert_id
                FROM {quoted_mapping_table}
                WHERE source_alert_id = {quoted_table_name}.alert_id
            )
            WHERE alert_id IN (SELECT source_alert_id FROM {quoted_mapping_table})
            """
        )

    await connection.execute(
        f"""
        UPDATE posts_history
        SET alert_id = (
            SELECT canonical_alert_id
            FROM {quoted_mapping_table}
            WHERE source_alert_id = posts_history.alert_id
        )
        WHERE alert_id IN (SELECT source_alert_id FROM {quoted_mapping_table})
        """
    )
    await connection.execute(
        f"""
        UPDATE posts_history
        SET related_alert_id = (
            SELECT canonical_alert_id
            FROM {quoted_mapping_table}
            WHERE source_alert_id = posts_history.related_alert_id
        )
        WHERE related_alert_id IN (SELECT source_alert_id FROM {quoted_mapping_table})
        """
    )
    await connection.execute(
        f"""
        DELETE FROM {quoted_alerts_table}
        WHERE id IN (SELECT source_alert_id FROM {quoted_mapping_table})
        """
    )
    await connection.execute(f"DROP TABLE IF EXISTS {quoted_mapping_table}")


async def _repair_alert_foreign_key_targets(connection: aiosqlite.Connection) -> None:
    legacy_parent = "alerts_legacy_strategy_migration"
    dependent_tables: dict[str, tuple[str, ...]] = {
        "followup_tasks": (
            "CREATE INDEX IF NOT EXISTS idx_followup_due_at ON followup_tasks(status, due_at)",
        ),
        "followup_results": (
            "CREATE INDEX IF NOT EXISTS idx_followup_results_observed_at ON followup_results(observed_at DESC)",
        ),
        "followup_stage_tasks": (
            "CREATE INDEX IF NOT EXISTS idx_followup_stage_due_at ON followup_stage_tasks(status, due_at)",
        ),
        "followup_stage_results": (
            "CREATE INDEX IF NOT EXISTS idx_followup_stage_results_observed_at ON followup_stage_results(observed_at DESC)",
        ),
        "interactive_alerts": (
            "CREATE INDEX IF NOT EXISTS idx_interactive_alerts_chat_message ON interactive_alerts(chat_id, message_id)",
            "CREATE INDEX IF NOT EXISTS idx_interactive_alerts_alert_id ON interactive_alerts(alert_id, updated_at DESC)",
        ),
        "analysis_cache": (
            "CREATE INDEX IF NOT EXISTS idx_analysis_cache_lookup ON analysis_cache(symbol, timeframe, analysis_type, created_at DESC)",
        ),
        "prepared_feature_cards": (
            "CREATE INDEX IF NOT EXISTS idx_prepared_feature_cards_lookup ON prepared_feature_cards(symbol, timeframe, content_type, updated_at DESC)",
        ),
        "delivered_signals": (
            "CREATE INDEX IF NOT EXISTS idx_delivered_signals_user_alert ON delivered_signals(telegram_user_id, alert_id, delivered_at DESC)",
        ),
        "delivered_bot_signals": (
            "CREATE INDEX IF NOT EXISTS idx_delivered_bot_signals_user_alert ON delivered_bot_signals(telegram_user_id, bot_kind, alert_id, delivered_at DESC)",
        ),
    }
    await connection.execute("PRAGMA foreign_keys = OFF")
    try:
        for table_name, index_statements in dependent_tables.items():
            cursor = await connection.execute(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = ?
                """,
                (table_name,),
            )
            table_row = await cursor.fetchone()
            create_sql = str(table_row[0] or "") if table_row is not None else ""
            if legacy_parent not in create_sql:
                continue
            temp_table_name = f"{table_name}_fk_alert_repair"
            await connection.execute(
                f"ALTER TABLE {_quote_identifier(table_name)} RENAME TO {_quote_identifier(temp_table_name)}"
            )
            repaired_sql = create_sql.replace(legacy_parent, "alerts")
            await connection.execute(repaired_sql)
            columns_cursor = await connection.execute(f"PRAGMA table_info({_quote_identifier(temp_table_name)})")
            columns = [str(row[1]) for row in await columns_cursor.fetchall()]
            if columns:
                projected_columns = ", ".join(_quote_identifier(column) for column in columns)
                await connection.execute(
                    f"""
                    INSERT INTO {_quote_identifier(table_name)} ({projected_columns})
                    SELECT {projected_columns}
                    FROM {_quote_identifier(temp_table_name)}
                    """
                )
            await connection.execute(f"DROP TABLE {_quote_identifier(temp_table_name)}")
            for statement in index_statements:
                await connection.execute(statement)
    finally:
        await connection.execute("PRAGMA foreign_keys = ON")


async def _migrate_premium_strategy_tables(connection: aiosqlite.Connection) -> None:
    valid_strategy_keys = _quoted_sql_list(PREMIUM_STRATEGY_KEYS)
    source_columns_cursor = await connection.execute("PRAGMA table_info(alerts)")
    source_alert_columns = {row[1] for row in await source_columns_cursor.fetchall()}
    source_has_strategy_key = "strategy_key" in source_alert_columns
    target_strategy_sql = f"""
        CASE
            WHEN LOWER(COALESCE(json_extract(metadata_json, '$.strategy_key'), '')) IN ({valid_strategy_keys})
                THEN LOWER(COALESCE(json_extract(metadata_json, '$.strategy_key'), 'rsi'))
            WHEN LOWER(COALESCE(json_extract(metadata_json, '$.asset_class'), 'crypto')) = 'gold'
                THEN 'gold'
            ELSE 'rsi'
        END
    """
    table_cursor = await connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'alerts'
        """
    )
    alerts_table_sql_row = await table_cursor.fetchone()
    alerts_table_sql = str(alerts_table_sql_row[0] or "") if alerts_table_sql_row is not None else ""
    needs_alerts_rebuild = "UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)" not in alerts_table_sql
    if needs_alerts_rebuild:
        source_strategy_case = (
            f"""
                    WHEN LOWER(COALESCE(strategy_key, '')) IN ({valid_strategy_keys})
                        THEN LOWER(COALESCE(strategy_key, 'rsi'))
            """
            if source_has_strategy_key
            else ""
        )
        await connection.execute("PRAGMA foreign_keys = OFF")
        await connection.execute("ALTER TABLE alerts RENAME TO alerts_legacy_strategy_migration")
        legacy_target_strategy_sql = f"""
            CASE
                {source_strategy_case}
                WHEN LOWER(COALESCE(json_extract(metadata_json, '$.strategy_key'), '')) IN ({valid_strategy_keys})
                    THEN LOWER(COALESCE(json_extract(metadata_json, '$.strategy_key'), 'rsi'))
                WHEN LOWER(COALESCE(json_extract(metadata_json, '$.asset_class'), 'crypto')) = 'gold'
                    THEN 'gold'
                ELSE 'rsi'
            END
        """
        await _merge_alert_strategy_conflicts(
            connection,
            alerts_table="alerts_legacy_strategy_migration",
            target_strategy_sql=legacy_target_strategy_sql,
        )
        await connection.execute(
            """
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy_key TEXT NOT NULL DEFAULT 'rsi',
                timeframe TEXT NOT NULL,
                candle_open_time TEXT NOT NULL,
                candle_close_time TEXT NOT NULL,
                alert_price REAL NOT NULL,
                alert_rsi REAL NOT NULL,
                day_change_pct REAL,
                day_volume REAL,
                score INTEGER NOT NULL,
                alert_sent_at TEXT NOT NULL,
                followup_due_at TEXT NOT NULL,
                followup_sent_at TEXT,
                lab_message_id INTEGER,
                metadata_json TEXT,
                UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)
            )
            """
        )
        await connection.execute(
            f"""
            INSERT INTO alerts (
                id,
                symbol,
                direction,
                strategy_key,
                timeframe,
                candle_open_time,
                candle_close_time,
                alert_price,
                alert_rsi,
                day_change_pct,
                day_volume,
                score,
                alert_sent_at,
                followup_due_at,
                followup_sent_at,
                lab_message_id,
                metadata_json
            )
            SELECT
                id,
                symbol,
                direction,
                {legacy_target_strategy_sql},
                timeframe,
                candle_open_time,
                candle_close_time,
                alert_price,
                alert_rsi,
                day_change_pct,
                day_volume,
                score,
                alert_sent_at,
                followup_due_at,
                followup_sent_at,
                lab_message_id,
                metadata_json
            FROM alerts_legacy_strategy_migration
            """
        )
        await connection.execute("DROP TABLE alerts_legacy_strategy_migration")
        await connection.execute("PRAGMA foreign_keys = ON")

    cursor = await connection.execute("PRAGMA table_info(alerts)")
    alert_columns = {row[1] for row in await cursor.fetchall()}
    if "strategy_key" not in alert_columns:
        await connection.execute(
            "ALTER TABLE alerts ADD COLUMN strategy_key TEXT NOT NULL DEFAULT 'rsi'"
        )
    await _merge_alert_strategy_conflicts(
        connection,
        alerts_table="alerts",
        target_strategy_sql=target_strategy_sql,
    )
    await connection.execute(
        f"""
        UPDATE alerts
        SET strategy_key = {target_strategy_sql}
        WHERE LOWER(COALESCE(strategy_key, '')) NOT IN ({valid_strategy_keys})
           OR (
                strategy_key = 'rsi'
                AND LOWER(COALESCE(json_extract(metadata_json, '$.asset_class'), 'crypto')) = 'gold'
           )
        """
    )
    await _repair_alert_foreign_key_targets(connection)

    cursor = await connection.execute("PRAGMA table_info(user_bot_settings)")
    settings_columns = {row[1] for row in await cursor.fetchall()}
    required_columns = {
        "enabled_strategy_keys_json": "ALTER TABLE user_bot_settings ADD COLUMN enabled_strategy_keys_json TEXT NOT NULL DEFAULT '[]'",
        "active_strategy_key": "ALTER TABLE user_bot_settings ADD COLUMN active_strategy_key TEXT",
        "strategy_selector_completed_at": "ALTER TABLE user_bot_settings ADD COLUMN strategy_selector_completed_at TEXT",
        "strategy_preferences_json": "ALTER TABLE user_bot_settings ADD COLUMN strategy_preferences_json TEXT NOT NULL DEFAULT '{}'",
        "personalization_json": "ALTER TABLE user_bot_settings ADD COLUMN personalization_json TEXT NOT NULL DEFAULT '{}'",
        "delivery_rules_json": "ALTER TABLE user_bot_settings ADD COLUMN delivery_rules_json TEXT NOT NULL DEFAULT '{}'",
        "current_context": "ALTER TABLE user_bot_settings ADD COLUMN current_context TEXT",
        "current_strategy_context": "ALTER TABLE user_bot_settings ADD COLUMN current_strategy_context TEXT",
        "current_set_id": "ALTER TABLE user_bot_settings ADD COLUMN current_set_id INTEGER",
        "timezone_name": "ALTER TABLE user_bot_settings ADD COLUMN timezone_name TEXT",
        "display_mode": "ALTER TABLE user_bot_settings ADD COLUMN display_mode TEXT NOT NULL DEFAULT 'pro'",
        "active_workspace": "ALTER TABLE user_bot_settings ADD COLUMN active_workspace TEXT",
        "saved_workspace_payload_json": "ALTER TABLE user_bot_settings ADD COLUMN saved_workspace_payload_json TEXT NOT NULL DEFAULT '{}'",
    }
    for name, statement in required_columns.items():
        if name not in settings_columns:
            await connection.execute(statement)

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS premium_strategy_settings (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            strategy_key TEXT NOT NULL,
            direct_signal_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            followup_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            signal_profile TEXT NOT NULL DEFAULT 'balanced',
            base_signal_profile TEXT NOT NULL DEFAULT 'balanced',
            preferred_min_score INTEGER,
            min_quote_volume REAL,
            rsi_oversold REAL,
            rsi_overbought REAL,
            direction_filter TEXT NOT NULL DEFAULT 'both',
            watchlist_only INTEGER NOT NULL DEFAULT 0,
            delivery_mode TEXT NOT NULL DEFAULT 'instant',
            delivery_mode_changed_at TEXT,
            quiet_hours_start_minute INTEGER,
            quiet_hours_end_minute INTEGER,
            snooze_until TEXT,
            snooze_started_at TEXT,
            snooze_label TEXT,
            last_resume_summary_at TEXT,
            last_digest_sent_at TEXT,
            last_daily_recap_at TEXT,
            last_weekly_recap_at TEXT,
            active_watchlist_theme TEXT NOT NULL DEFAULT 'custom',
            active_custom_theme_name TEXT,
            strategy_preferences_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, bot_kind, strategy_key),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    cursor = await connection.execute("PRAGMA table_info(premium_strategy_settings)")
    premium_settings_columns = {row[1] for row in await cursor.fetchall()}
    if "strategy_preferences_json" not in premium_settings_columns:
        await connection.execute(
            "ALTER TABLE premium_strategy_settings ADD COLUMN strategy_preferences_json TEXT NOT NULL DEFAULT '{}'"
        )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS premium_strategy_watchlist (
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            strategy_key TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, bot_kind, strategy_key, symbol),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS premium_strategy_watchlist_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            strategy_key TEXT NOT NULL,
            theme_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(telegram_user_id, bot_kind, strategy_key, theme_name),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS premium_strategy_watchlist_theme_symbols (
            theme_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (theme_id, symbol),
            FOREIGN KEY(theme_id) REFERENCES premium_strategy_watchlist_themes(id) ON DELETE CASCADE
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_premium_strategy_settings_lookup ON premium_strategy_settings(telegram_user_id, bot_kind, strategy_key, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_lookup ON premium_strategy_watchlist(telegram_user_id, bot_kind, strategy_key, created_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_themes_lookup ON premium_strategy_watchlist_themes(telegram_user_id, bot_kind, strategy_key, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_premium_strategy_watchlist_theme_symbols_lookup ON premium_strategy_watchlist_theme_symbols(theme_id, created_at DESC)"
    )

    await connection.execute(
        """
        UPDATE user_bot_settings
        SET enabled_strategy_keys_json = CASE
                WHEN bot_kind = 'premium' AND gold_alerts_enabled = 1 THEN '["rsi","gold","gold_breakout","gold_pullback","gold_liquidity"]'
                WHEN bot_kind = 'premium' THEN '["rsi"]'
                ELSE '[]'
            END
        WHERE COALESCE(enabled_strategy_keys_json, '') IN ('', '[]')
        """
    )
    await connection.execute(
        f"""
        UPDATE user_bot_settings
        SET active_strategy_key = CASE
                WHEN bot_kind = 'premium' AND LOWER(COALESCE(active_strategy_key, '')) NOT IN ({valid_strategy_keys})
                    THEN 'rsi'
                WHEN bot_kind = 'classic' THEN NULL
                ELSE active_strategy_key
            END
        """
    )
    await connection.execute(
        """
        UPDATE user_bot_settings
        SET strategy_selector_completed_at = COALESCE(strategy_selector_completed_at, onboarding_completed_at, updated_at)
        WHERE bot_kind = 'premium'
          AND COALESCE(strategy_selector_completed_at, '') = ''
          AND COALESCE(enabled_strategy_keys_json, '[]') <> '[]'
        """
    )

    await connection.execute(
        """
        INSERT OR IGNORE INTO premium_strategy_settings (
            telegram_user_id,
            bot_kind,
            strategy_key,
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            signal_profile,
            base_signal_profile,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            direction_filter,
            watchlist_only,
            delivery_mode,
            delivery_mode_changed_at,
            quiet_hours_start_minute,
            quiet_hours_end_minute,
            snooze_until,
            snooze_started_at,
            snooze_label,
            last_resume_summary_at,
            last_digest_sent_at,
            last_daily_recap_at,
            last_weekly_recap_at,
            active_watchlist_theme,
            active_custom_theme_name,
            strategy_preferences_json,
            updated_at
        )
        SELECT
            telegram_user_id,
            bot_kind,
            'rsi',
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            signal_profile,
            base_signal_profile,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            direction_filter,
            watchlist_only,
            delivery_mode,
            delivery_mode_changed_at,
            quiet_hours_start_minute,
            quiet_hours_end_minute,
            snooze_until,
            snooze_started_at,
            snooze_label,
            last_resume_summary_at,
            last_digest_sent_at,
            last_daily_recap_at,
            last_weekly_recap_at,
            active_watchlist_theme,
            active_custom_theme_name,
            COALESCE(strategy_preferences_json, '{}'),
            updated_at
        FROM user_bot_settings
        WHERE bot_kind = 'premium'
        """
    )
    await connection.execute(
        """
        INSERT OR IGNORE INTO premium_strategy_settings (
            telegram_user_id,
            bot_kind,
            strategy_key,
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            signal_profile,
            base_signal_profile,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            direction_filter,
            watchlist_only,
            delivery_mode,
            delivery_mode_changed_at,
            quiet_hours_start_minute,
            quiet_hours_end_minute,
            snooze_until,
            snooze_started_at,
            snooze_label,
            last_resume_summary_at,
            last_digest_sent_at,
            last_daily_recap_at,
            last_weekly_recap_at,
            active_watchlist_theme,
            active_custom_theme_name,
            strategy_preferences_json,
            updated_at
        )
        SELECT
            telegram_user_id,
            bot_kind,
            'gold',
            direct_signal_delivery_enabled,
            followup_delivery_enabled,
            signal_profile,
            base_signal_profile,
            preferred_min_score,
            min_quote_volume,
            rsi_oversold,
            rsi_overbought,
            direction_filter,
            watchlist_only,
            delivery_mode,
            delivery_mode_changed_at,
            quiet_hours_start_minute,
            quiet_hours_end_minute,
            snooze_until,
            snooze_started_at,
            snooze_label,
            last_resume_summary_at,
            last_digest_sent_at,
            last_daily_recap_at,
            last_weekly_recap_at,
            active_watchlist_theme,
            active_custom_theme_name,
            COALESCE(strategy_preferences_json, '{}'),
            updated_at
        FROM user_bot_settings
        WHERE bot_kind = 'premium'
          AND gold_alerts_enabled = 1
        """
    )
    await connection.execute(
        """
        INSERT OR IGNORE INTO premium_strategy_watchlist (
            telegram_user_id,
            bot_kind,
            strategy_key,
            symbol,
            created_at
        )
        SELECT
            telegram_user_id,
            bot_kind,
            'rsi',
            symbol,
            created_at
        FROM user_watchlist
        WHERE bot_kind = 'premium'
        """
    )

    cursor = await connection.execute(
        """
        SELECT
            id,
            telegram_user_id,
            bot_kind,
            theme_name,
            created_at,
            updated_at,
            metadata_json
        FROM user_watchlist_themes
        WHERE bot_kind = 'premium'
        """
    )
    legacy_themes = await cursor.fetchall()
    for theme_row in legacy_themes:
        await connection.execute(
            """
            INSERT OR IGNORE INTO premium_strategy_watchlist_themes (
                telegram_user_id,
                bot_kind,
                strategy_key,
                theme_name,
                created_at,
                updated_at,
                metadata_json
            )
            VALUES (?, ?, 'rsi', ?, ?, ?, ?)
            """,
            (
                theme_row["telegram_user_id"],
                theme_row["bot_kind"],
                theme_row["theme_name"],
                theme_row["created_at"],
                theme_row["updated_at"],
                theme_row["metadata_json"],
            ),
        )
        new_theme_cursor = await connection.execute(
            """
            SELECT id
            FROM premium_strategy_watchlist_themes
            WHERE telegram_user_id = ?
              AND bot_kind = ?
              AND strategy_key = 'rsi'
              AND theme_name = ?
            """,
            (
                theme_row["telegram_user_id"],
                theme_row["bot_kind"],
                theme_row["theme_name"],
            ),
        )
        new_theme_row = await new_theme_cursor.fetchone()
        if new_theme_row is None:
            continue
        symbol_cursor = await connection.execute(
            """
            SELECT symbol, created_at
            FROM user_watchlist_theme_symbols
            WHERE theme_id = ?
            """,
            (theme_row["id"],),
        )
        for symbol_row in await symbol_cursor.fetchall():
            await connection.execute(
                """
                INSERT OR IGNORE INTO premium_strategy_watchlist_theme_symbols (
                    theme_id,
                    symbol,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (new_theme_row["id"], symbol_row["symbol"], symbol_row["created_at"]),
            )

async def _migrate_crypto_pay_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_pay_invoices (
            invoice_id INTEGER PRIMARY KEY,
            invoice_hash TEXT UNIQUE,
            telegram_user_id INTEGER,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            target_access_level TEXT NOT NULL DEFAULT 'pro',
            target_duration_days INTEGER NOT NULL DEFAULT 30,
            amount TEXT,
            asset TEXT,
            currency_type TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            pay_url TEXT,
            custom_payload TEXT,
            created_at TEXT NOT NULL,
            paid_at TEXT,
            activated_at TEXT,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_pay_webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_hash TEXT NOT NULL UNIQUE,
            update_type TEXT NOT NULL,
            invoice_id INTEGER,
            request_date TEXT,
            status TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            last_error TEXT,
            raw_payload_json TEXT,
            FOREIGN KEY(invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_crypto_pay_invoices_user_status ON crypto_pay_invoices(telegram_user_id, status, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_crypto_pay_invoices_hash ON crypto_pay_invoices(invoice_hash)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_crypto_pay_webhook_events_invoice ON crypto_pay_webhook_events(invoice_id, processed_at DESC)"
    )


async def _migrate_onboarding_payment_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_payment_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            campaign_type TEXT NOT NULL DEFAULT 'trial_48h',
            first_contact_at TEXT NOT NULL,
            trial_started_at TEXT,
            trial_ends_at TEXT,
            referred_by_user_id INTEGER,
            invoice_id INTEGER,
            offer_sent_at TEXT,
            status TEXT NOT NULL DEFAULT 'trial_active',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(telegram_user_id, bot_kind, campaign_type),
            FOREIGN KEY(telegram_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(referred_by_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_user_id INTEGER NOT NULL,
            referred_user_id INTEGER NOT NULL UNIQUE,
            bot_kind TEXT NOT NULL DEFAULT 'premium',
            status TEXT NOT NULL DEFAULT 'registered',
            source_payload TEXT,
            created_at TEXT NOT NULL,
            converted_at TEXT,
            first_paid_conversion_at TEXT,
            counted_as_paid_referral INTEGER NOT NULL DEFAULT 0,
            conversion_invoice_id INTEGER,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(referred_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(conversion_invoice_id) REFERENCES crypto_pay_invoices(invoice_id)
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_payment_campaigns_due ON onboarding_payment_campaigns(status, trial_ends_at, next_retry_at)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_payment_campaigns_invoice ON onboarding_payment_campaigns(invoice_id, updated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer_status ON referrals(referrer_user_id, status, updated_at DESC)"
    )


async def _migrate_referral_program_tables(connection: aiosqlite.Connection) -> None:
    cursor = await connection.execute("PRAGMA table_info(bot_users)")
    bot_user_columns = {row[1] for row in await cursor.fetchall()}
    if "referral_code" not in bot_user_columns:
        await connection.execute("ALTER TABLE bot_users ADD COLUMN referral_code TEXT")

    cursor = await connection.execute("PRAGMA table_info(referrals)")
    referral_columns = {row[1] for row in await cursor.fetchall()}
    if "first_paid_conversion_at" not in referral_columns:
        await connection.execute("ALTER TABLE referrals ADD COLUMN first_paid_conversion_at TEXT")
    if "counted_as_paid_referral" not in referral_columns:
        await connection.execute("ALTER TABLE referrals ADD COLUMN counted_as_paid_referral INTEGER NOT NULL DEFAULT 0")
    if "conversion_invoice_id" not in referral_columns:
        await connection.execute("ALTER TABLE referrals ADD COLUMN conversion_invoice_id INTEGER")

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_cycle_stats (
            referrer_user_id INTEGER PRIMARY KEY,
            active_cycle_paid_referrals_count INTEGER NOT NULL DEFAULT 0,
            lifetime_paid_referrals_count INTEGER NOT NULL DEFAULT 0,
            current_cycle_number INTEGER NOT NULL DEFAULT 1,
            last_reward_milestone_reached INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_reward_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_user_id INTEGER NOT NULL,
            referred_user_id INTEGER,
            reward_type TEXT NOT NULL DEFAULT 'premium_days',
            reward_days INTEGER NOT NULL,
            milestone_trigger INTEGER NOT NULL,
            cycle_number INTEGER NOT NULL,
            granted_at TEXT NOT NULL,
            access_extension_from TEXT,
            access_extension_to TEXT,
            metadata_json TEXT,
            UNIQUE(referrer_user_id, cycle_number, milestone_trigger),
            FOREIGN KEY(referrer_user_id) REFERENCES bot_users(telegram_user_id),
            FOREIGN KEY(referred_user_id) REFERENCES bot_users(telegram_user_id)
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_bot_users_referral_code ON bot_users(referral_code)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_conversion_invoice ON referrals(conversion_invoice_id)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_referral_reward_grants_referrer ON referral_reward_grants(referrer_user_id, granted_at DESC)"
    )


async def _migrate_signal_lifecycle_tables(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_signals (
            signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER UNIQUE,
            source_signal_key TEXT NOT NULL UNIQUE,
            strategy_code TEXT NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            status TEXT NOT NULL,
            result_type TEXT NOT NULL DEFAULT 'open',
            entry_price REAL NOT NULL,
            entry_zone_low REAL,
            entry_zone_high REAL,
            invalidation_price REAL,
            tp_price_primary REAL,
            tp_price_secondary REAL,
            benchmark_win_percent REAL NOT NULL DEFAULT 7.0,
            created_at TEXT NOT NULL,
            activated_at TEXT,
            confirmed_at TEXT,
            near_tp_at TEXT,
            hit_tp_at TEXT,
            invalidated_at TEXT,
            expired_at TEXT,
            closed_at TEXT,
            expiry_at TEXT,
            last_price REAL,
            last_price_at TEXT,
            mfe_percent REAL NOT NULL DEFAULT 0,
            mae_percent REAL NOT NULL DEFAULT 0,
            market_regime_tag TEXT,
            liquidity_tag TEXT,
            confidence_score REAL,
            setup_quality TEXT,
            explanation_short TEXT,
            explanation_full TEXT,
            ai_analysis_available INTEGER NOT NULL DEFAULT 0,
            parent_alert_message_id INTEGER,
            source_type TEXT NOT NULL DEFAULT 'strategy_stream',
            is_gold INTEGER NOT NULL DEFAULT 0,
            ambiguous_resolution INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            event_payload_json TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            FOREIGN KEY(signal_id) REFERENCES tracked_signals(signal_id) ON DELETE CASCADE
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_signal_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            alert_id INTEGER,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            candle_open_time TEXT NOT NULL,
            candle_close_time TEXT NOT NULL,
            open_price REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            close_price REAL NOT NULL,
            volume REAL,
            quote_volume REAL,
            source TEXT NOT NULL DEFAULT 'rest_backfill',
            collected_at TEXT NOT NULL,
            processed_at TEXT,
            UNIQUE(signal_id, candle_open_time),
            FOREIGN KEY(signal_id) REFERENCES tracked_signals(signal_id) ON DELETE CASCADE,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_stats_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_code TEXT NOT NULL,
            timeframe_bucket TEXT,
            market_regime_bucket TEXT,
            asset_cluster_bucket TEXT,
            period_type TEXT NOT NULL,
            total_signals INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            expired_neutral INTEGER NOT NULL DEFAULT 0,
            invalidated_count INTEGER NOT NULL DEFAULT 0,
            avg_rr REAL,
            avg_time_to_win_minutes REAL,
            avg_time_to_invalidation_minutes REAL,
            signals_per_day REAL,
            best_tf TEXT,
            best_assets TEXT,
            best_regime TEXT,
            drawdown_profile TEXT,
            delivered_count INTEGER NOT NULL DEFAULT 0,
            suppressed_count INTEGER NOT NULL DEFAULT 0,
            ambiguous_count INTEGER NOT NULL DEFAULT 0,
            sent_wins INTEGER NOT NULL DEFAULT 0,
            sent_losses INTEGER NOT NULL DEFAULT 0,
            sent_expired_neutral INTEGER NOT NULL DEFAULT 0,
            sent_ambiguous_count INTEGER NOT NULL DEFAULT 0,
            sent_avg_rr REAL,
            sent_signals_per_day REAL,
            sent_best_tf TEXT,
            sent_best_assets TEXT,
            sent_best_regime TEXT,
            calculated_at TEXT NOT NULL,
            UNIQUE(strategy_code, timeframe_bucket, market_regime_bucket, asset_cluster_bucket, period_type)
        )
        """
    )
    snapshot_columns_cursor = await connection.execute("PRAGMA table_info(strategy_stats_snapshots)")
    snapshot_columns = {row[1] for row in await snapshot_columns_cursor.fetchall()}
    snapshot_required_columns = {
        "delivered_count": "ALTER TABLE strategy_stats_snapshots ADD COLUMN delivered_count INTEGER NOT NULL DEFAULT 0",
        "suppressed_count": "ALTER TABLE strategy_stats_snapshots ADD COLUMN suppressed_count INTEGER NOT NULL DEFAULT 0",
        "ambiguous_count": "ALTER TABLE strategy_stats_snapshots ADD COLUMN ambiguous_count INTEGER NOT NULL DEFAULT 0",
        "sent_wins": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_wins INTEGER NOT NULL DEFAULT 0",
        "sent_losses": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_losses INTEGER NOT NULL DEFAULT 0",
        "sent_expired_neutral": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_expired_neutral INTEGER NOT NULL DEFAULT 0",
        "sent_ambiguous_count": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_ambiguous_count INTEGER NOT NULL DEFAULT 0",
        "sent_avg_rr": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_avg_rr REAL",
        "sent_signals_per_day": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_signals_per_day REAL",
        "sent_best_tf": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_best_tf TEXT",
        "sent_best_assets": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_best_assets TEXT",
        "sent_best_regime": "ALTER TABLE strategy_stats_snapshots ADD COLUMN sent_best_regime TEXT",
    }
    for name, statement in snapshot_required_columns.items():
        if name not in snapshot_columns:
            await connection.execute(statement)
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            telegram_user_id INTEGER,
            context TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_followup_stage_results_alert_observed ON followup_stage_results(alert_id, observed_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signals_status ON tracked_signals(status, created_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signals_strategy_status ON tracked_signals(strategy_code, status, created_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signals_symbol_timeframe ON tracked_signals(symbol, timeframe, created_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signals_expiry ON tracked_signals(status, expiry_at)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signals_maintenance ON tracked_signals(status, last_price_at, created_at)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_events_signal_created ON signal_events(signal_id, created_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_signal_processed ON tracked_signal_candles(signal_id, processed_at, candle_close_time ASC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_alert_time ON tracked_signal_candles(alert_id, candle_close_time ASC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_signal_candles_symbol_timeframe ON tracked_signal_candles(symbol, timeframe, candle_open_time ASC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_stats_snapshots_lookup ON strategy_stats_snapshots(strategy_code, period_type, calculated_at DESC)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_telemetry_events_lookup ON telemetry_events(event_name, created_at DESC)"
    )
