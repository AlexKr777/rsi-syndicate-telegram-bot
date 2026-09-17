from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_classic_bot_token: str = Field(default="", alias="TELEGRAM_CLASSIC_BOT_TOKEN")
    public_channel: str = Field(alias="PUBLIC_CHANNEL")
    pro_channel: str = Field(alias="PRO_CHANNEL")
    lab_channel: str = Field(alias="LAB_CHANNEL")
    community_chat: str = Field(alias="COMMUNITY_CHAT")
    results_channel: str = Field(alias="RESULTS_CHANNEL")
    twitter_drafts_chat: str = Field(alias="TWITTER_DRAFTS_CHAT")
    community_link: str = Field(default="", alias="COMMUNITY_LINK")
    channels_folder_link: str = Field(default="", alias="CHANNELS_FOLDER_LINK")
    private_bot_share_link: str = Field(default="", alias="PRIVATE_BOT_SHARE_LINK")
    classic_bot_share_link: str = Field(default="", alias="CLASSIC_BOT_SHARE_LINK")
    classic_bot_username: str = Field(default="@syndicateclassicbot", alias="CLASSIC_BOT_USERNAME")
    admin_telegram_user_ids_raw: str = Field(default="", alias="ADMIN_TELEGRAM_USER_IDS")
    admin_telegram_usernames_raw: str = Field(default="", alias="ADMIN_TELEGRAM_USERNAMES")
    runtime_dir: Path = Field(default=Path("runtime"), alias="RUNTIME_DIR")
    webhook_url_file: Path = Field(default=Path("runtime/webhook_url.txt"), alias="WEBHOOK_URL_FILE")
    local_webhook_url_file: Path = Field(default=Path("runtime/local_webhook_url.txt"), alias="LOCAL_WEBHOOK_URL_FILE")
    tunnel_url_file: Path = Field(default=Path("runtime/tunnel_url.txt"), alias="TUNNEL_URL_FILE")
    webhook_url_auto_open: bool = Field(default=True, alias="WEBHOOK_URL_AUTO_OPEN")

    app_timezone: str = Field(default="Europe/Chisinau", alias="APP_TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    binance_rest_base_url: str = Field(
        default="https://fapi.binance.com",
        alias="BINANCE_REST_BASE_URL",
    )
    binance_futures_web_base_url: str = Field(
        default="https://www.binance.com/en/futures",
        alias="BINANCE_FUTURES_WEB_BASE_URL",
    )
    binance_futures_app_base_url: str = Field(
        default="https://app.binance.com/en/futures",
        alias="BINANCE_FUTURES_APP_BASE_URL",
    )
    gold_alerts_enabled: bool = Field(default=True, alias="GOLD_ALERTS_ENABLED")
    gold_symbol: str = Field(default="XAUUSD", alias="GOLD_SYMBOL")
    gold_provider_symbol: str = Field(default="GC=F", alias="GOLD_PROVIDER_SYMBOL")
    gold_chart_api_base_url: str = Field(
        default="https://query1.finance.yahoo.com/v8/finance/chart",
        alias="GOLD_CHART_API_BASE_URL",
    )
    gold_web_base_url: str = Field(
        default="https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
        alias="GOLD_WEB_BASE_URL",
    )
    gold_data_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        alias="GOLD_DATA_USER_AGENT",
    )
    scan_timeframe: str = Field(default="15m", alias="SCAN_TIMEFRAME")
    scan_offset_seconds: int = Field(default=10, alias="SCAN_OFFSET_SECONDS")
    klines_limit: int = Field(default=150, alias="KLINES_LIMIT")
    scan_concurrency: int = Field(default=12, alias="SCAN_CONCURRENCY")
    http_timeout_seconds: int = Field(default=20, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")
    telegram_chat_min_interval_seconds: float = Field(
        default=1.1,
        alias="TELEGRAM_CHAT_MIN_INTERVAL_SECONDS",
    )
    symbols_refresh_minutes: int = Field(default=240, alias="SYMBOLS_REFRESH_MINUTES")

    rsi_length: int = Field(default=14, alias="RSI_LENGTH")
    rsi_oversold: float = Field(default=30.0, alias="RSI_OVERSOLD")
    rsi_overbought: float = Field(default=70.0, alias="RSI_OVERBOUGHT")
    cooldown_minutes: int = Field(default=180, alias="COOLDOWN_MINUTES")
    followup_delay_hours: int = Field(default=2, alias="FOLLOWUP_DELAY_HOURS")
    followup_stage_hours: str = Field(default="2,4,8", alias="FOLLOWUP_STAGE_HOURS")
    followup_max_lateness_minutes: int = Field(default=45, alias="FOLLOWUP_MAX_LATENESS_MINUTES")
    signal_tracking_batch_size: int = Field(default=1_000, alias="SIGNAL_TRACKING_BATCH_SIZE")
    signal_candle_archive_enabled: bool = Field(default=True, alias="SIGNAL_CANDLE_ARCHIVE_ENABLED")
    signal_candle_archive_hours: int = Field(default=8, alias="SIGNAL_CANDLE_ARCHIVE_HOURS")
    signal_candle_archive_batch_size: int = Field(default=24, alias="SIGNAL_CANDLE_ARCHIVE_BATCH_SIZE")
    signal_candle_archive_max_klines_per_request: int = Field(default=64, alias="SIGNAL_CANDLE_ARCHIVE_MAX_KLINES_PER_REQUEST")
    operational_cleanup_enabled: bool = Field(default=True, alias="OPERATIONAL_CLEANUP_ENABLED")
    operational_cleanup_interval_hours: int = Field(default=6, alias="OPERATIONAL_CLEANUP_INTERVAL_HOURS")
    operational_cleanup_batch_size: int = Field(default=5_000, alias="OPERATIONAL_CLEANUP_BATCH_SIZE")
    signal_candle_retention_days: int = Field(default=2, alias="SIGNAL_CANDLE_RETENTION_DAYS")
    telemetry_retention_days: int = Field(default=30, alias="TELEMETRY_RETENTION_DAYS")
    strategy_snapshot_retention_days: int = Field(default=2, alias="STRATEGY_SNAPSHOT_RETENTION_DAYS")
    public_min_score: int = Field(default=60, alias="PUBLIC_MIN_SCORE")
    pro_min_score: int = Field(default=78, alias="PRO_MIN_SCORE")
    community_min_score: int = Field(default=58, alias="COMMUNITY_MIN_SCORE")
    public_max_posts_per_day: int = Field(default=3, alias="PUBLIC_MAX_POSTS_PER_DAY")
    pro_max_posts_per_day: int = Field(default=8, alias="PRO_MAX_POSTS_PER_DAY")
    results_max_posts_per_day: int = Field(default=10, alias="RESULTS_MAX_POSTS_PER_DAY")
    public_result_posts_enabled: bool = Field(default=True, alias="PUBLIC_RESULT_POSTS_ENABLED")
    public_best_setups_enabled: bool = Field(default=True, alias="PUBLIC_BEST_SETUPS_ENABLED")
    public_market_takeaways_enabled: bool = Field(default=True, alias="PUBLIC_MARKET_TAKEAWAYS_ENABLED")
    pro_destination_enabled: bool = Field(default=False, alias="PRO_DESTINATION_ENABLED")
    pro_live_alerts_enabled: bool = Field(default=True, alias="PRO_LIVE_ALERTS_ENABLED")
    pro_followups_enabled: bool = Field(default=True, alias="PRO_FOLLOWUPS_ENABLED")
    results_channel_enabled: bool = Field(default=True, alias="RESULTS_CHANNEL_ENABLED")
    results_proof_posts_enabled: bool = Field(default=True, alias="RESULTS_PROOF_POSTS_ENABLED")
    results_all_followups_enabled: bool = Field(default=True, alias="RESULTS_ALL_FOLLOWUPS_ENABLED")
    result_chart_generation_enabled: bool = Field(default=True, alias="RESULT_CHART_GENERATION_ENABLED")
    public_best_setup_min_score: int = Field(default=78, alias="PUBLIC_BEST_SETUP_MIN_SCORE")
    public_result_min_score: int = Field(default=68, alias="PUBLIC_RESULT_MIN_SCORE")
    public_result_min_move_pct: float = Field(default=1.25, alias="PUBLIC_RESULT_MIN_MOVE_PCT")
    pro_live_min_score: int = Field(default=82, alias="PRO_LIVE_MIN_SCORE")
    pro_followup_min_move_pct: float = Field(default=1.0, alias="PRO_FOLLOWUP_MIN_MOVE_PCT")
    pro_followup_min_score: int = Field(default=74, alias="PRO_FOLLOWUP_MIN_SCORE")
    results_min_score: int = Field(default=68, alias="RESULTS_MIN_SCORE")
    results_min_favorable_move_pct: float = Field(default=5.0, alias="RESULTS_MIN_FAVORABLE_MOVE_PCT")
    public_signal_delay_minutes: int = Field(default=30, alias="PUBLIC_SIGNAL_DELAY_MINUTES")
    classic_bot_signal_delay_minutes: int = Field(default=30, alias="CLASSIC_BOT_SIGNAL_DELAY_MINUTES")
    public_delay_premium_note_enabled: bool = Field(default=True, alias="PUBLIC_DELAY_PREMIUM_NOTE_ENABLED")
    public_delay_premium_bot_link: str = Field(default="", alias="PUBLIC_DELAY_PREMIUM_BOT_LINK")
    public_delay_trial_days: int = Field(default=2, alias="PUBLIC_DELAY_TRIAL_DAYS")

    sqlite_path: Path = Field(default=Path("data/rsi_alerts.db"), alias="SQLITE_PATH")
    instance_lock_path: Path = Field(default=Path("data/rsi_bot.lock"), alias="INSTANCE_LOCK_PATH")
    log_file: Path = Field(default=Path("logs/rsi_bot.log"), alias="LOG_FILE")
    temp_chart_dir: Path = Field(default=Path("temp_charts"), alias="TEMP_CHART_DIR")

    ollama_enabled: bool = Field(default=True, alias="OLLAMA_ENABLED")
    ollama_model: str = Field(default="llama3:latest", alias="OLLAMA_MODEL")
    ollama_analysis_model: str | None = Field(
        default="deepseek-r1:14b-qwen-distill-q4_K_M",
        alias="OLLAMA_ANALYSIS_MODEL",
    )
    ollama_writer_model: str | None = Field(
        default="deepseek-r1:14b-qwen-distill-q4_K_M",
        alias="OLLAMA_WRITER_MODEL",
    )
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_timeout_seconds: int = Field(default=90, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_cooldown_seconds: int = Field(default=120, alias="OLLAMA_COOLDOWN_SECONDS")
    autopost_public: bool = Field(default=True, alias="AUTOPOST_PUBLIC")
    autopost_pro: bool = Field(default=False, alias="AUTOPOST_PRO")
    autopost_community: bool = Field(default=True, alias="AUTOPOST_COMMUNITY")
    telegram_destination_hourly_limit: int = Field(
        default=5,
        alias="TELEGRAM_DESTINATION_HOURLY_LIMIT",
    )
    interactive_alerts_enabled: bool = Field(default=True, alias="INTERACTIVE_ALERTS_ENABLED")
    interactive_alerts_lab: bool = Field(default=True, alias="INTERACTIVE_ALERTS_LAB")
    interactive_alerts_public: bool = Field(default=False, alias="INTERACTIVE_ALERTS_PUBLIC")
    interactive_alerts_pro: bool = Field(default=False, alias="INTERACTIVE_ALERTS_PRO")
    interactive_alerts_results: bool = Field(default=True, alias="INTERACTIVE_ALERTS_RESULTS")
    interactive_alerts_private: bool = Field(default=True, alias="INTERACTIVE_ALERTS_PRIVATE")
    interactive_alerts_classic: bool = Field(default=True, alias="INTERACTIVE_ALERTS_CLASSIC")
    interactive_alerts_twitter_drafts: bool = Field(
        default=True,
        alias="INTERACTIVE_ALERTS_TWITTER_DRAFTS",
    )
    interactive_alert_timeframes: str = Field(
        default="1m,5m,15m,1h",
        alias="INTERACTIVE_ALERT_TIMEFRAMES",
    )
    interactive_alert_timeframes_twitter_drafts: str = Field(
        default="1m,5m,15m",
        alias="INTERACTIVE_ALERT_TIMEFRAMES_TWITTER_DRAFTS",
    )
    interactive_callback_poll_timeout_seconds: int = Field(
        default=25,
        alias="INTERACTIVE_CALLBACK_POLL_TIMEOUT_SECONDS",
    )
    interactive_analysis_cache_minutes: int = Field(
        default=30,
        alias="INTERACTIVE_ANALYSIS_CACHE_MINUTES",
    )
    interactive_feature_cache_minutes: int = Field(
        default=90,
        alias="INTERACTIVE_FEATURE_CACHE_MINUTES",
    )
    prepared_feature_precompute_enabled: bool = Field(
        default=True,
        alias="PREPARED_FEATURE_PRECOMPUTE_ENABLED",
    )
    interactive_premium_buttons_lab: bool = Field(
        default=True,
        alias="INTERACTIVE_PREMIUM_BUTTONS_LAB",
    )
    interactive_premium_buttons_public: bool = Field(
        default=False,
        alias="INTERACTIVE_PREMIUM_BUTTONS_PUBLIC",
    )
    interactive_premium_buttons_pro: bool = Field(
        default=True,
        alias="INTERACTIVE_PREMIUM_BUTTONS_PRO",
    )
    interactive_premium_buttons_results: bool = Field(
        default=False,
        alias="INTERACTIVE_PREMIUM_BUTTONS_RESULTS",
    )
    interactive_premium_buttons_private: bool = Field(
        default=True,
        alias="INTERACTIVE_PREMIUM_BUTTONS_PRIVATE",
    )
    interactive_premium_buttons_classic: bool = Field(
        default=False,
        alias="INTERACTIVE_PREMIUM_BUTTONS_CLASSIC",
    )
    interactive_premium_buttons_twitter_drafts: bool = Field(
        default=False,
        alias="INTERACTIVE_PREMIUM_BUTTONS_TWITTER_DRAFTS",
    )
    lab_internal_summary_hourly_limit: int = Field(
        default=18,
        alias="LAB_INTERNAL_SUMMARY_HOURLY_LIMIT",
    )
    lab_review_copy_hourly_limit: int = Field(
        default=10,
        alias="LAB_REVIEW_COPY_HOURLY_LIMIT",
    )
    lab_batch_flush_seconds: int = Field(
        default=300,
        alias="LAB_BATCH_FLUSH_SECONDS",
    )
    lab_batch_max_items: int = Field(
        default=6,
        alias="LAB_BATCH_MAX_ITEMS",
    )
    curated_lab_only_mode: bool = Field(default=True, alias="CURATED_LAB_ONLY_MODE")
    x_drafts_enabled: bool = Field(default=True, alias="X_DRAFTS_ENABLED")
    x_signal_drafts: bool = Field(default=True, alias="X_SIGNAL_DRAFTS")
    x_followup_drafts: bool = Field(default=True, alias="X_FOLLOWUP_DRAFTS")
    x_daily_scan_draft: bool = Field(default=True, alias="X_DAILY_SCAN_DRAFT")
    x_daily_stats_draft: bool = Field(default=True, alias="X_DAILY_STATS_DRAFT")
    x_daily_recap_draft: bool = Field(default=True, alias="X_DAILY_RECAP_DRAFT")
    x_operator_posts: bool = Field(default=True, alias="X_OPERATOR_POSTS")
    twitter_proof_posts_enabled: bool = Field(default=True, alias="TWITTER_PROOF_POSTS_ENABLED")
    twitter_operator_posts_enabled: bool = Field(default=True, alias="TWITTER_OPERATOR_POSTS_ENABLED")
    twitter_all_followups_enabled: bool = Field(default=True, alias="TWITTER_ALL_FOLLOWUPS_ENABLED")
    x_min_score: int = Field(default=60, alias="X_MIN_SCORE")
    x_min_quote_volume: float = Field(default=5_000_000, alias="X_MIN_QUOTE_VOLUME")
    x_max_drafts_per_day: int = Field(default=3, alias="X_MAX_DRAFTS_PER_DAY")
    x_preview_all_types: bool = Field(default=False, alias="X_PREVIEW_ALL_TYPES")
    x_soft_promo_rate: float = Field(default=0.20, alias="X_SOFT_PROMO_RATE")
    x_emoji_rate: float = Field(default=0.18, alias="X_EMOJI_RATE")
    x_daily_scan_time: str = Field(default="13:00", alias="X_DAILY_SCAN_TIME")
    x_end_of_day_package_time: str = Field(default="22:00", alias="X_END_OF_DAY_PACKAGE_TIME")
    twitter_drafts_multi_version: bool = Field(default=False, alias="TWITTER_DRAFTS_MULTI_VERSION")
    public_startup_posts_enabled: bool = Field(default=False, alias="PUBLIC_STARTUP_POSTS_ENABLED")
    community_startup_posts_enabled: bool = Field(default=False, alias="COMMUNITY_STARTUP_POSTS_ENABLED")
    lab_startup_posts_enabled: bool = Field(default=True, alias="LAB_STARTUP_POSTS_ENABLED")
    pro_startup_posts_enabled: bool = Field(default=False, alias="PRO_STARTUP_POSTS_ENABLED")
    private_bot_enabled: bool = Field(default=True, alias="PRIVATE_BOT_ENABLED")
    private_bot_signal_delivery_enabled: bool = Field(default=False, alias="PRIVATE_BOT_SIGNAL_DELIVERY_ENABLED")
    private_bot_results_mirror_enabled: bool = Field(default=True, alias="PRIVATE_BOT_RESULTS_MIRROR_ENABLED")
    private_bot_results_mirror_admin_username: str = Field(
        default="dordo_dordo",
        alias="PRIVATE_BOT_RESULTS_MIRROR_ADMIN_USERNAME",
    )
    private_bot_results_mirror_channel: str = Field(default="", alias="PRIVATE_BOT_RESULTS_MIRROR_CHANNEL")
    private_bot_followups_default: bool = Field(default=False, alias="PRIVATE_BOT_FOLLOWUPS_DEFAULT")
    private_bot_gold_alerts_default: bool = Field(default=False, alias="PRIVATE_BOT_GOLD_ALERTS_DEFAULT")
    private_bot_trial_days: int = Field(default=2, alias="PRIVATE_BOT_TRIAL_DAYS")
    private_bot_chat_cleanup_keep_messages: int = Field(
        default=7,
        alias="PRIVATE_BOT_CHAT_CLEANUP_KEEP_MESSAGES",
    )
    onboarding_trial_hours: int = Field(default=48, alias="ONBOARDING_TRIAL_HOURS")
    onboarding_invoice_retry_minutes: int = Field(default=30, alias="ONBOARDING_INVOICE_RETRY_MINUTES")
    onboarding_payment_check_interval_seconds: int = Field(default=60, alias="ONBOARDING_PAYMENT_CHECK_INTERVAL_SECONDS")
    onboarding_payment_campaign_enabled: bool = Field(default=True, alias="ONBOARDING_PAYMENT_CAMPAIGN_ENABLED")
    classic_bot_enabled: bool = Field(default=True, alias="CLASSIC_BOT_ENABLED")
    classic_bot_signal_delivery_enabled: bool = Field(default=True, alias="CLASSIC_BOT_SIGNAL_DELIVERY_ENABLED")
    classic_bot_followups_default: bool = Field(default=False, alias="CLASSIC_BOT_FOLLOWUPS_DEFAULT")
    classic_bot_recent_signals_limit: int = Field(default=4, alias="CLASSIC_BOT_RECENT_SIGNALS_LIMIT")
    classic_bot_chat_cleanup_keep_messages: int = Field(
        default=7,
        alias="CLASSIC_BOT_CHAT_CLEANUP_KEEP_MESSAGES",
    )
    crypto_pay_api_token: str = Field(default="", alias="CRYPTO_PAY_API_TOKEN")
    crypto_pay_api_base_url: str = Field(default="https://pay.crypt.bot/api", alias="CRYPTO_PAY_API_BASE_URL")
    crypto_pay_webhook_path: str = Field(default="/payments/crypto/webhook", alias="CRYPTO_PAY_WEBHOOK_PATH")
    crypto_pay_enabled: bool = Field(default=True, alias="CRYPTO_PAY_ENABLED")
    crypto_pay_invoice_asset: str = Field(default="USDT", alias="CRYPTO_PAY_INVOICE_ASSET")
    crypto_pay_invoice_amount_usd: float = Field(default=30.0, alias="CRYPTO_PAY_INVOICE_AMOUNT_USD")
    crypto_pay_subscription_days: int = Field(default=30, alias="CRYPTO_PAY_SUBSCRIPTION_DAYS")
    referral_milestone_first_count: int = Field(default=3, alias="REFERRAL_MILESTONE_FIRST_COUNT")
    referral_milestone_first_reward_days: int = Field(default=30, alias="REFERRAL_MILESTONE_FIRST_REWARD_DAYS")
    referral_milestone_second_count: int = Field(default=5, alias="REFERRAL_MILESTONE_SECOND_COUNT")
    referral_milestone_second_reward_days: int = Field(default=30, alias="REFERRAL_MILESTONE_SECOND_REWARD_DAYS")
    crypto_pay_testnet: bool = Field(default=False, alias="CRYPTO_PAY_TESTNET")
    local_webhook_host: str = Field(default="127.0.0.1", alias="LOCAL_WEBHOOK_HOST")
    local_webhook_port: int = Field(default=8000, alias="LOCAL_WEBHOOK_PORT")
    local_webhook_health_path: str = Field(default="/payments/health", alias="LOCAL_WEBHOOK_HEALTH_PATH")
    ngrok_enabled: bool = Field(default=True, alias="NGROK_ENABLED")
    ngrok_exe: str = Field(default="ngrok", alias="NGROK_EXE")
    ngrok_path: str = Field(default="ngrok", alias="NGROK_PATH")
    ngrok_config_path: Path | None = Field(default=None, alias="NGROK_CONFIG_PATH")
    ngrok_authtoken: str = Field(default="", alias="NGROK_AUTHTOKEN")
    ngrok_api_base_url: str = Field(default="http://127.0.0.1:4040", alias="NGROK_API_BASE_URL")
    ngrok_start_timeout_seconds: int = Field(default=25, alias="NGROK_START_TIMEOUT_SECONDS")
    ngrok_tunnel_name: str = Field(default="rsi-crypto-pay", alias="NGROK_TUNNEL_NAME")
    private_followup_min_favorable_move_pct: float = Field(
        default=5.0,
        alias="PRIVATE_FOLLOWUP_MIN_FAVORABLE_MOVE_PCT",
    )
    private_followup_max_adverse_move_pct: float = Field(
        default=5.0,
        alias="PRIVATE_FOLLOWUP_MAX_ADVERSE_MOVE_PCT",
    )
    private_followup_max_adverse_per_day: int = Field(
        default=1,
        alias="PRIVATE_FOLLOWUP_MAX_ADVERSE_PER_DAY",
    )
    private_bot_recent_signals_limit: int = Field(default=3, alias="PRIVATE_BOT_RECENT_SIGNALS_LIMIT")
    private_bot_strong_signals_limit: int = Field(default=5, alias="PRIVATE_BOT_STRONG_SIGNALS_LIMIT")
    community_max_posts_per_day: int = Field(default=6, alias="COMMUNITY_MAX_POSTS_PER_DAY")
    community_min_interval_minutes: int = Field(default=180, alias="COMMUNITY_MIN_INTERVAL_MINUTES")
    twitter_followup_min_favorable_move_pct: float = Field(
        default=5.0,
        alias="TWITTER_FOLLOWUP_MIN_FAVORABLE_MOVE_PCT",
    )
    twitter_followup_max_adverse_move_pct: float = Field(
        default=5.0,
        alias="TWITTER_FOLLOWUP_MAX_ADVERSE_MOVE_PCT",
    )
    twitter_followup_max_adverse_per_day: int = Field(
        default=1,
        alias="TWITTER_FOLLOWUP_MAX_ADVERSE_PER_DAY",
    )

    @field_validator("telegram_bot_token")
    @classmethod
    def validate_telegram_bot_token(cls, value: str) -> str:
        token = value.strip()
        if not token or "<replace" in token or "<put" in token:
            raise ValueError("TELEGRAM_BOT_TOKEN must be set to a real bot token in .env")
        return token

    @field_validator(
        "sqlite_path",
        "instance_lock_path",
        "log_file",
        "temp_chart_dir",
        "runtime_dir",
        "webhook_url_file",
        "local_webhook_url_file",
        "tunnel_url_file",
        "ngrok_config_path",
        mode="before",
    )
    @classmethod
    def resolve_paths(cls, value: str | Path | None) -> Path | None:
        if value in {None, ""}:
            return None
        return Path(os.path.expandvars(str(value))).expanduser()

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def cooldown_seconds(self) -> int:
        return self.cooldown_minutes * 60

    @property
    def followup_delay_seconds(self) -> int:
        return self.followup_delay_hours * 3600

    @property
    def signal_candle_archive_seconds(self) -> int:
        return max(self.signal_candle_archive_hours, 1) * 3600

    @property
    def onboarding_trial_seconds(self) -> int:
        return max(self.onboarding_trial_hours, 1) * 3600

    @property
    def onboarding_invoice_retry_seconds(self) -> int:
        return max(self.onboarding_invoice_retry_minutes, 1) * 60

    @property
    def public_signal_delay_seconds(self) -> int:
        return max(self.public_signal_delay_minutes, 0) * 60

    @property
    def classic_bot_signal_delay_seconds(self) -> int:
        return max(self.classic_bot_signal_delay_minutes, 0) * 60

    @property
    def followup_stage_definitions(self) -> tuple[tuple[str, int], ...]:
        values: list[tuple[str, int]] = []
        for raw in self.followup_stage_hours.split(","):
            raw_value = raw.strip()
            if not raw_value:
                continue
            try:
                hours = max(int(float(raw_value)), 1)
            except ValueError:
                continue
            values.append((f"{hours}h", hours * 3600))
        if not values:
            return ((f"{self.followup_delay_hours}h", self.followup_delay_seconds),)
        values = sorted(dict.fromkeys(values), key=lambda item: item[1])
        return tuple(values)

    @property
    def telegram_destinations(self) -> dict[str, str]:
        return {
            "public": self.public_channel,
            "pro": self.pro_channel,
            "lab": self.lab_channel,
            "community": self.community_chat,
            "results": self.results_channel,
            "twitter_drafts": self.twitter_drafts_chat,
        }

    @property
    def effective_ollama_analysis_model(self) -> str:
        return (self.ollama_analysis_model or self.ollama_model).strip()

    @property
    def effective_ollama_writer_model(self) -> str:
        return (self.ollama_writer_model or self.ollama_model).strip()

    @property
    def interactive_timeframes(self) -> tuple[str, ...]:
        values = tuple(
            item.strip()
            for item in self.interactive_alert_timeframes.split(",")
            if item.strip()
        )
        return values or ("1m", "5m", "15m", "1h")

    @property
    def interactive_timeframes_twitter_drafts_value(self) -> tuple[str, ...]:
        values = tuple(
            item.strip()
            for item in self.interactive_alert_timeframes_twitter_drafts.split(",")
            if item.strip()
        )
        return values or ("1m", "5m", "15m")

    def interactive_timeframes_for(self, destination_kind: str) -> tuple[str, ...]:
        if destination_kind == "twitter_drafts":
            return self.interactive_timeframes_twitter_drafts_value
        return self.interactive_timeframes

    @property
    def resolved_private_bot_share_link(self) -> str:
        return self.private_bot_share_link.strip() or self.public_delay_premium_bot_link.strip()

    @property
    def private_bot_results_mirror_destination(self) -> str:
        return self.private_bot_results_mirror_channel.strip() or self.results_channel.strip()

    @property
    def admin_telegram_user_ids(self) -> tuple[int, ...]:
        values: list[int] = []
        for raw in self.admin_telegram_user_ids_raw.split(","):
            raw_value = raw.strip()
            if not raw_value:
                continue
            try:
                values.append(int(raw_value))
            except ValueError:
                continue
        return tuple(dict.fromkeys(values))

    @property
    def admin_telegram_usernames(self) -> tuple[str, ...]:
        values: list[str] = []
        for raw in self.admin_telegram_usernames_raw.split(","):
            raw_value = raw.strip().lstrip("@").casefold()
            if not raw_value:
                continue
            values.append(raw_value)
        return tuple(dict.fromkeys(values))

    def is_configured_admin(self, telegram_user_id: int | None = None, username: str | None = None) -> bool:
        if telegram_user_id is not None and int(telegram_user_id) in set(self.admin_telegram_user_ids):
            return True
        normalized_username = str(username or "").strip().lstrip("@").casefold()
        return bool(normalized_username) and normalized_username in set(self.admin_telegram_usernames)

    def interactive_enabled_for(self, destination_kind: str) -> bool:
        if not self.interactive_alerts_enabled:
            return False
        if destination_kind == "lab":
            return self.interactive_alerts_lab
        if destination_kind == "public":
            return self.interactive_alerts_public
        if destination_kind == "pro":
            return self.interactive_alerts_pro
        if destination_kind == "results":
            return self.interactive_alerts_results
        if destination_kind == "private":
            return self.interactive_alerts_private
        if destination_kind == "classic":
            return self.interactive_alerts_classic
        if destination_kind == "twitter_drafts":
            return self.interactive_alerts_twitter_drafts
        return False

    def premium_features_enabled_for(self, destination_kind: str) -> bool:
        if destination_kind == "lab":
            return self.interactive_premium_buttons_lab
        if destination_kind == "public":
            return self.interactive_premium_buttons_public
        if destination_kind == "pro":
            return self.interactive_premium_buttons_pro
        if destination_kind == "results":
            return self.interactive_premium_buttons_results
        if destination_kind == "private":
            return self.interactive_premium_buttons_private
        if destination_kind == "classic":
            return self.interactive_premium_buttons_classic
        if destination_kind == "twitter_drafts":
            return self.interactive_premium_buttons_twitter_drafts
        return False

    @property
    def classic_bot_is_configured(self) -> bool:
        return bool(self.telegram_classic_bot_token.strip()) and self.classic_bot_enabled

    @property
    def resolved_classic_bot_share_link(self) -> str:
        link = self.classic_bot_share_link.strip()
        if link:
            return link
        username = self.classic_bot_username.strip()
        if username:
            if username.startswith("@"):
                return f"https://t.me/{username.lstrip('@')}"
            return username
        return ""

    def ensure_runtime_directories(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.instance_lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_chart_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.webhook_url_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_webhook_url_file.parent.mkdir(parents=True, exist_ok=True)
        self.tunnel_url_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def crypto_pay_is_configured(self) -> bool:
        return self.crypto_pay_enabled and bool(self.crypto_pay_api_token.strip())

    @property
    def normalized_crypto_pay_webhook_path(self) -> str:
        path = self.crypto_pay_webhook_path.strip() or "/payments/crypto/webhook"
        return path if path.startswith("/") else f"/{path}"

    @property
    def local_webhook_base_url(self) -> str:
        return f"http://{self.local_webhook_host}:{self.local_webhook_port}"

    @property
    def local_crypto_pay_webhook_url(self) -> str:
        return f"{self.local_webhook_base_url}{self.normalized_crypto_pay_webhook_path}"

    @property
    def referral_reward_milestones(self) -> tuple[tuple[int, int], tuple[int, int]]:
        first_count = max(int(self.referral_milestone_first_count), 1)
        first_days = max(int(self.referral_milestone_first_reward_days), 1)
        second_count = max(int(self.referral_milestone_second_count), first_count + 1)
        second_days = max(int(self.referral_milestone_second_reward_days), 1)
        return ((first_count, first_days), (second_count, second_days))

    @property
    def resolved_ngrok_executable(self) -> str:
        explicit = self.ngrok_exe.strip()
        if explicit:
            return explicit
        legacy = self.ngrok_path.strip()
        return legacy or "ngrok"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
