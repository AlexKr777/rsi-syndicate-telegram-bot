from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress
from datetime import timedelta

import numpy as np
import pandas as pd

from src.ai.generators import DraftGenerator
from src.ai.ollama_client import OllamaClient
from src.ai.twitter_generators import TwitterDraftGenerator
from src.analysis.precompute import PreparedFeatureService
from src.bot.interactive_alerts import InteractiveAlertService, TelegramCallbackPoller
from src.bot.routing import MessageRouter
from src.bot.telegram_client import TelegramClient
from src.charts.renderer import ChartRenderer
from src.classicbot.service import ClassicBotService
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.models import AlertSignal, DeliveryResult
from src.core.runtime_lock import AlreadyRunningError, SingleInstanceLock
from src.core.utils import seconds_until_next_interval, utc_now
from src.jobs.followups import FollowUpService
from src.jobs.generated_posts import ScheduledGeneratedPostScheduler, ScheduledGeneratedPostService
from src.jobs.onboarding_payments import OnboardingPaymentScheduler
from src.jobs.scheduler import FollowUpScheduler
from src.jobs.twitter_drafts import TwitterDraftScheduler, TwitterDraftService
from src.jobs.user_delivery import UserDeliveryScheduler
from src.market.market_client import MarketClient
from src.payments.ngrok_tunnel import NgrokTunnelManager
from src.payments.onboarding import OnboardingPaymentService
from src.payments.service import CryptoPayService
from src.payments.webhook_server import PaymentWebhookServer
from src.market.indicators import enrich_klines
from src.market.breakout_scanner import BreakoutScanner
from src.market.daily_rsi_80_scanner import DailyRSI80Scanner
from src.market.bollinger_scanner import BollingerScanner
from src.market.ekek_scanner import EkekScanner
from src.market.false_breakout_scanner import FalseBreakoutScanner
from src.market.gold_breakout_scanner import GoldBreakoutScanner
from src.market.gold_liquidity_scanner import GoldLiquidityScanner
from src.market.gold_pullback_scanner import GoldPullbackScanner
from src.market.okak_scanner import OkakScanner
from src.market.rsi_bollinger_mr_scanner import RSIBollingerMeanReversionScanner
from src.market.rsi_bollinger_touch_scanner import RSIBollingerTouchScanner
from src.market.rsi_divergence_scanner import RSIDivergenceScanner
from src.market.scanner import MarketScanner
from src.market.trend_pullback_scanner import TrendPullbackScanner
from src.market.vwap_scanner import VWAPScanner
from src.signals import BackgroundTrackingService, SignalLifecycleService
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.service import PrivateBotService

LOGGER = logging.getLogger(__name__)


def summarize_alert_deliveries(
    *,
    lab_delivery: DeliveryResult | None,
    external_deliveries: list[DeliveryResult],
    curated_mode: bool,
) -> dict[str, object]:
    if curated_mode and lab_delivery is None:
        lab_status = "skipped_curated"
    elif lab_delivery is None:
        lab_status = "not_attempted"
    elif lab_delivery.sent:
        lab_status = "sent"
    elif lab_delivery.batched:
        lab_status = "batched"
    elif lab_delivery.rate_limited:
        lab_status = "rate_limited"
    else:
        lab_status = "failed"
    return {
        "lab_status": lab_status,
        "external_sent": sum(1 for delivery in external_deliveries if delivery.sent),
        "external_scheduled": sum(
            1
            for delivery in external_deliveries
            if not delivery.sent and bool(delivery.metadata.get("scheduled"))
        ),
        "external_skipped": sum(
            1
            for delivery in external_deliveries
            if not delivery.sent
            and not bool(delivery.metadata.get("scheduled"))
            and not delivery.rate_limited
            and not delivery.batched
        ),
        "external_rate_limited": sum(
            1 for delivery in external_deliveries if delivery.rate_limited
        ),
        "external_batched": sum(
            1 for delivery in external_deliveries if delivery.batched
        ),
    }


class RSISyndicateApp:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.ensure_runtime_directories()
        configure_logging(self.settings)

        self.repository = Repository(str(self.settings.sqlite_path))
        self.binance_client = MarketClient(self.settings)
        self.telegram_client = TelegramClient(self.settings)
        self.classic_telegram_client = (
            TelegramClient(
                self.settings,
                bot_token=self.settings.telegram_classic_bot_token,
                bot_label="classic",
            )
            if self.settings.classic_bot_is_configured
            else None
        )
        self.chart_renderer = ChartRenderer(self.settings)
        self.ollama_client = OllamaClient(self.settings) if self.settings.ollama_enabled else None
        self.draft_generator = DraftGenerator(self.settings, self.ollama_client, self.repository)
        self.twitter_draft_generator = TwitterDraftGenerator(self.settings, self.ollama_client)
        self.prepared_feature_service = PreparedFeatureService(
            self.settings,
            self.repository,
            self.binance_client,
            self.ollama_client,
        )
        self.signal_lifecycle_service = SignalLifecycleService(self.repository)
        self.router = MessageRouter(self.settings, self.telegram_client, self.repository)
        self.classic_router = (
            MessageRouter(self.settings, self.classic_telegram_client, self.repository)
            if self.classic_telegram_client is not None
            else None
        )
        self.scanner = MarketScanner(self.settings, self.binance_client, self.repository)
        self.bollinger_scanner = BollingerScanner(self.settings, self.binance_client, self.repository)
        self.breakout_scanner = BreakoutScanner(self.settings, self.binance_client, self.repository)
        self.trend_pullback_scanner = TrendPullbackScanner(self.settings, self.binance_client, self.repository)
        self.rsi_bollinger_mr_scanner = RSIBollingerMeanReversionScanner(
            self.settings,
            self.binance_client,
            self.repository,
        )
        self.rsi_bollinger_touch_scanner = RSIBollingerTouchScanner(
            self.settings,
            self.binance_client,
            self.repository,
        )
        self.daily_rsi_80_scanner = DailyRSI80Scanner(
            self.settings,
            self.binance_client,
            self.repository,
        )
        self.rsi_divergence_scanner = RSIDivergenceScanner(
            self.settings,
            self.binance_client,
            self.repository,
        )
        self.okak_scanner = OkakScanner(self.settings, self.binance_client, self.repository)
        self.ekek_scanner = EkekScanner(self.settings, self.binance_client, self.repository)
        self.vwap_scanner = VWAPScanner(self.settings, self.binance_client, self.repository)
        self.false_breakout_scanner = FalseBreakoutScanner(self.settings, self.binance_client, self.repository)
        self.gold_breakout_scanner = GoldBreakoutScanner(self.settings, self.binance_client, self.repository)
        self.gold_pullback_scanner = GoldPullbackScanner(self.settings, self.binance_client, self.repository)
        self.gold_liquidity_scanner = GoldLiquidityScanner(self.settings, self.binance_client, self.repository)
        self.interactive_alert_service = InteractiveAlertService(
            self.settings,
            self.repository,
            self.telegram_client,
            self.binance_client,
            self.chart_renderer,
            self.prepared_feature_service,
        )
        self.classic_interactive_alert_service = (
            InteractiveAlertService(
                self.settings,
                self.repository,
                self.classic_telegram_client,
                self.binance_client,
                self.chart_renderer,
                self.prepared_feature_service,
                state_scope="classic",
            )
            if self.classic_telegram_client is not None
            else None
        )
        self.private_bot_service = PrivateBotService(
            self.settings,
            self.repository,
            self.telegram_client,
            self.router,
            self.binance_client,
            self.chart_renderer,
            self.interactive_alert_service,
        )
        self.private_bot_service.signal_lifecycle_service = self.signal_lifecycle_service
        self.classic_bot_service = (
            ClassicBotService(
                self.settings,
                self.repository,
                self.classic_telegram_client,
                self.classic_router,
                self.binance_client,
                self.chart_renderer,
                self.classic_interactive_alert_service,
                self.draft_generator,
            )
            if self.classic_telegram_client is not None and self.classic_router is not None and self.classic_interactive_alert_service is not None
            else None
        )
        self.callback_poller = TelegramCallbackPoller(
            self.settings,
            self.telegram_client,
            self.interactive_alert_service,
            self.private_bot_service,
        )
        self.classic_callback_poller = (
            TelegramCallbackPoller(
                self.settings,
                self.classic_telegram_client,
                self.classic_interactive_alert_service,
                self.classic_bot_service,
            )
            if self.classic_telegram_client is not None
            and self.classic_interactive_alert_service is not None
            and self.classic_bot_service is not None
            else None
        )
        self.twitter_draft_service = TwitterDraftService(
            self.settings,
            self.repository,
            self.binance_client,
            self.chart_renderer,
            self.router,
            self.twitter_draft_generator,
            self.interactive_alert_service,
        )
        self.instance_lock = SingleInstanceLock(self.settings.instance_lock_path)
        self.followup_service = FollowUpService(
            self.settings,
            self.repository,
            self.binance_client,
            self.chart_renderer,
            self.router,
            self.draft_generator,
            self.interactive_alert_service,
            self.twitter_draft_service,
            self.private_bot_service,
            self.classic_bot_service,
            self.prepared_feature_service,
            lifecycle_service=self.signal_lifecycle_service,
        )
        self.followup_scheduler = FollowUpScheduler(self.repository, self.followup_service.handle_task)
        self.background_tracking_service = BackgroundTrackingService(
            self.repository,
            self.binance_client,
            self.signal_lifecycle_service,
            settings=self.settings,
        )
        self.scheduled_post_service = ScheduledGeneratedPostService(
            self.settings,
            self.repository,
            self.router,
            self.binance_client,
            self.chart_renderer,
            self.interactive_alert_service,
            classic_router=self.classic_router,
            classic_interactive_alert_service=self.classic_interactive_alert_service,
            classic_bot_service=self.classic_bot_service,
        )
        self.scheduled_post_scheduler = ScheduledGeneratedPostScheduler(
            self.repository,
            self.scheduled_post_service.handle_task,
        )
        self.followup_service.scheduled_post_scheduler = self.scheduled_post_scheduler
        if self.classic_bot_service is not None:
            self.classic_bot_service.scheduled_post_scheduler = self.scheduled_post_scheduler
        self.twitter_draft_scheduler = TwitterDraftScheduler(self.twitter_draft_service)
        self.crypto_pay_service = (
            CryptoPayService(
                self.settings,
                self.repository,
                telegram_client=self.telegram_client,
                classic_telegram_client=self.classic_telegram_client,
            )
            if self.settings.crypto_pay_enabled
            else None
        )
        self.onboarding_payment_service = OnboardingPaymentService(
            self.settings,
            self.repository,
            crypto_pay_service=self.crypto_pay_service,
            premium_telegram_client=self.telegram_client,
            classic_telegram_client=self.classic_telegram_client,
        )
        self.private_bot_service.onboarding_service = self.onboarding_payment_service
        if self.classic_bot_service is not None:
            self.classic_bot_service.onboarding_service = self.onboarding_payment_service
        self.onboarding_payment_scheduler = OnboardingPaymentScheduler(
            self.repository,
            self.onboarding_payment_service.handle_due_campaign,
            idle_check_seconds=self.settings.onboarding_payment_check_interval_seconds,
        )
        self.onboarding_payment_service.schedule_wakeup = self.onboarding_payment_scheduler.notify
        delivery_handlers = [
            self.private_bot_service.run_delivery_maintenance,
            self.followup_service.run_results_channel_maintenance,
            self.background_tracking_service.run_maintenance,
        ]
        if self.classic_bot_service is not None:
            delivery_handlers.append(self.classic_bot_service.run_delivery_maintenance)
        self.user_delivery_scheduler = UserDeliveryScheduler(
            handlers=delivery_handlers,
            interval_seconds=60,
        )
        self.payment_webhook_server = (
            PaymentWebhookServer(self.settings, self.crypto_pay_service)
            if self.crypto_pay_service is not None
            else None
        )
        self.ngrok_tunnel = NgrokTunnelManager(self.settings) if self.settings.crypto_pay_enabled else None
        self._payment_runtime_status: dict[str, str | None] = {
            "webhook": "disabled",
            "ngrok": "disabled",
            "local_webhook_url": None,
            "public_base_url": None,
            "public_webhook_url": None,
            "error": None,
        }
        self._webhook_url_file_opened = False
        self._stop_event = asyncio.Event()
        self._scan_task: asyncio.Task | None = None
        self._startup_x_preview_task: asyncio.Task | None = None

    def _signal_strategy_key(self, signal: AlertSignal) -> str:
        return str(signal.metadata.get("strategy_key") or "rsi").strip().lower() or "rsi"

    def _is_public_stream_strategy(self, signal: AlertSignal) -> bool:
        return self._signal_strategy_key(signal) == "rsi"

    async def run(self) -> None:
        self.instance_lock.acquire()
        await initialize_database(str(self.settings.sqlite_path))
        await self.repository.connect()
        await self._ensure_configured_admin_access()
        self._install_signal_handlers()
        await self._start_payment_runtime()

        bot_identity = await self.telegram_client.get_me()
        LOGGER.info("Connected to Telegram as @%s", bot_identity.get("username"))
        classic_username: str | None = None
        if self.classic_telegram_client is not None:
            classic_identity = await self.classic_telegram_client.get_me()
            classic_username = classic_identity.get("username")
            LOGGER.info("Connected to Classic Telegram as @%s", classic_identity.get("username"))
        LOGGER.info(
            "Autopost config: public=%s pro=%s community=%s results=%s",
            self.settings.autopost_public,
            self.settings.autopost_pro,
            self.settings.autopost_community,
            self.settings.results_channel_enabled,
        )
        self._print_local_dev_runtime_summary(
            premium_username=bot_identity.get("username"),
            classic_username=classic_username,
        )

        await self._send_startup_ai_posts()
        await self._send_preview_alert()

        await self.callback_poller.start()
        if self.classic_callback_poller is not None:
            await self.classic_callback_poller.start()
        await self.followup_scheduler.start()
        await self.onboarding_payment_scheduler.start()
        await self.scheduled_post_scheduler.start()
        await self.twitter_draft_scheduler.start()
        await self.user_delivery_scheduler.start()
        self._scan_task = asyncio.create_task(self._scan_loop(), name="scan-loop")
        if self.settings.x_drafts_enabled and self.settings.x_preview_all_types:
            self._startup_x_preview_task = asyncio.create_task(
                self._run_startup_x_preview(),
                name="startup-x-preview",
            )

        await self._stop_event.wait()

    async def shutdown(self) -> None:
        LOGGER.info("Shutdown requested")
        self._stop_event.set()

        if self._scan_task is not None:
            self._scan_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scan_task
        if self._startup_x_preview_task is not None:
            self._startup_x_preview_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._startup_x_preview_task

        await self.callback_poller.stop()
        if self.classic_callback_poller is not None:
            await self.classic_callback_poller.stop()
        await self.followup_scheduler.stop()
        await self.onboarding_payment_scheduler.stop()
        await self.scheduled_post_scheduler.stop()
        await self.twitter_draft_scheduler.stop()
        await self.user_delivery_scheduler.stop()
        await self.router.close()
        if self.classic_router is not None:
            await self.classic_router.close()
        await self.prepared_feature_service.shutdown()
        await self.telegram_client.close()
        if self.classic_telegram_client is not None:
            await self.classic_telegram_client.close()
        await self.binance_client.close()
        if self.ollama_client is not None:
            await self.ollama_client.close()
        if self.ngrok_tunnel is not None:
            await self.ngrok_tunnel.stop()
        if self.payment_webhook_server is not None:
            await self.payment_webhook_server.stop()
        if self.crypto_pay_service is not None:
            await self.crypto_pay_service.close()
        await self.repository.close()
        self.instance_lock.release()
        LOGGER.info("Shutdown complete")

    async def _ensure_configured_admin_access(self) -> None:
        if not self.settings.admin_telegram_user_ids:
            return
        for telegram_user_id in self.settings.admin_telegram_user_ids:
            await self.repository.upsert_private_user(
                telegram_user_id=telegram_user_id,
                username=None,
                first_name=None,
                last_name=None,
                is_active=True,
                is_admin=True,
            )
            await self.onboarding_payment_service.ensure_admin_access(telegram_user_id)

    async def _scan_loop(self) -> None:
        await self._run_scan_cycle(reason="startup")
        while not self._stop_event.is_set():
            wait_seconds = seconds_until_next_interval(
                self.settings.scan_timeframe,
                self.settings.scan_offset_seconds,
            )
            LOGGER.info("Waiting %.1f seconds for next %s scan", wait_seconds, self.settings.scan_timeframe)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                await self._run_scan_cycle(reason="scheduled")

    async def _run_startup_x_preview(self) -> None:
        try:
            await self.twitter_draft_service.send_preview_package_if_enabled()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - long-running service
            LOGGER.exception("Startup X preview package failed")

    async def _run_scan_cycle(self, *, reason: str) -> None:
        LOGGER.info("Starting %s scan cycle", reason)
        try:
            rsi_alerts = await self.scanner.scan_once()
            bollinger_alerts = await self.bollinger_scanner.scan_once()
            breakout_alerts = await self.breakout_scanner.scan_once()
            trend_pullback_alerts = await self.trend_pullback_scanner.scan_once()
            rsi_bollinger_mr_alerts = await self.rsi_bollinger_mr_scanner.scan_once()
            rsi_bollinger_touch_alerts = await self.rsi_bollinger_touch_scanner.scan_once()
            daily_rsi_80_alerts = await self.daily_rsi_80_scanner.scan_once()
            rsi_divergence_alerts = await self.rsi_divergence_scanner.scan_once()
            okak_alerts = await self.okak_scanner.scan_once()
            ekek_alerts = await self.ekek_scanner.scan_once()
            vwap_alerts = await self.vwap_scanner.scan_once()
            false_breakout_alerts = await self.false_breakout_scanner.scan_once()
            gold_breakout_alerts = await self.gold_breakout_scanner.scan_once()
            gold_pullback_alerts = await self.gold_pullback_scanner.scan_once()
            gold_liquidity_alerts = await self.gold_liquidity_scanner.scan_once()
            alerts = [
                *rsi_alerts,
                *bollinger_alerts,
                *breakout_alerts,
                *trend_pullback_alerts,
                *rsi_bollinger_mr_alerts,
                *rsi_bollinger_touch_alerts,
                *daily_rsi_80_alerts,
                *rsi_divergence_alerts,
                *okak_alerts,
                *ekek_alerts,
                *vwap_alerts,
                *false_breakout_alerts,
                *gold_breakout_alerts,
                *gold_pullback_alerts,
                *gold_liquidity_alerts,
            ]
            for signal in alerts:
                await self._process_alert(signal)
        except Exception:  # pragma: no cover - long-running service
            LOGGER.exception("Scan cycle failed")

    async def _process_alert(self, signal: AlertSignal) -> None:
        if str(signal.metadata.get("asset_class") or "").lower() == "gold":
            await self._process_gold_alert(signal)
            return
        chart_path = None
        try:
            prepared_lifecycle = self.signal_lifecycle_service.prepare_signal_metadata(
                signal,
                created_at=utc_now(),
                source_type="strategy_stream",
            )
            self.signal_lifecycle_service.apply_prepared_metadata(signal, prepared_lifecycle)
            frame = await self.binance_client.get_klines(
                signal.symbol,
                self.settings.scan_timeframe,
                self.settings.klines_limit,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal)
            signal.chart_path = chart_path

            lab_delivery = None
            if self.settings.curated_lab_only_mode:
                LOGGER.info(
                    "Skipping LAB raw alert for %s because curated LAB-only mode keeps LAB for curated X/thought ideas",
                    signal.symbol,
                )
            else:
                lab_delivery = await self.router.send_raw_alert(signal)
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="lab",
                    chat_id=str(lab_delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                    message_id=lab_delivery.telegram_message_id,
                    signal=signal,
                    alert_id=None,
                    is_preview=False,
                    message_kind="alert",
                )
            sent_at = utc_now()
            first_followup_stage = self.settings.followup_stage_definitions[0][1]
            followup_due_at = sent_at + timedelta(seconds=first_followup_stage)
            alert_id = await self.repository.create_alert(
                signal,
                sent_at=sent_at,
                followup_due_at=followup_due_at,
                lab_message_id=lab_delivery.telegram_message_id if lab_delivery is not None else None,
            )
            await self.signal_lifecycle_service.create_signal(
                signal=signal,
                alert_id=alert_id,
                created_at=sent_at,
                parent_alert_message_id=lab_delivery.telegram_message_id if lab_delivery is not None else None,
                source_type="strategy_stream",
            )
            LOGGER.info(
                "Follow-up checkpoints scheduled for %s alert_id=%s stages=%s",
                signal.symbol,
                alert_id,
                ",".join(stage for stage, _ in self.settings.followup_stage_definitions),
            )
            if lab_delivery is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="lab",
                    chat_id=str(lab_delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                    message_id=lab_delivery.telegram_message_id,
                    signal=signal,
                    alert_id=alert_id,
                    is_preview=False,
                    message_kind="alert",
                )
            if str(signal.metadata.get("strategy_key") or "").strip().lower() in {"rsi", "gold"}:
                await self.scanner.confirm_signal_sent(signal, sent_at)
            self.followup_scheduler.notify()
            await self.private_bot_service.deliver_pro_alert(signal, alert_id)
            if self.classic_bot_service is not None and self._is_public_stream_strategy(signal):
                await self.classic_bot_service.deliver_classic_alert(signal, alert_id)
            if self._is_public_stream_strategy(signal) and self._qualifies_for_prepared_features(signal):
                self.prepared_feature_service.schedule_prepare_for_signal(signal, alert_id)

            external_posts = []
            external_deliveries: list[DeliveryResult] = []
            if self._is_public_stream_strategy(signal) and not self.settings.curated_lab_only_mode:
                posts = await self.draft_generator.generate_for_alert(signal, alert_id, chart_path=signal.chart_path)
                lab_posts = [post for post in posts if post.channel_kind == "lab"]
                external_posts = [post for post in posts if post.channel_kind != "lab"]
                for post in lab_posts:
                    await self.router.route_generated_post(post)
                for post in external_posts:
                    post.bundle_in_lab_review = True
                    delivery = await self.router.route_generated_post(post)
                    external_deliveries.append(delivery)
                    if delivery.metadata.get("scheduled"):
                        self.scheduled_post_scheduler.notify()
                    if (
                        post.channel_kind in {"public", "pro", "results"}
                        and delivery.sent
                        and delivery.telegram_message_id is not None
                    ):
                        await self.interactive_alert_service.register_alert_message(
                            destination_kind=post.channel_kind,
                            chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.telegram_destinations[post.channel_kind]),
                            message_id=delivery.telegram_message_id,
                            signal=signal,
                            alert_id=alert_id,
                            is_preview=False,
                            message_kind="alert",
                        )
            twitter_draft = (
                await self.twitter_draft_service.handle_alert(signal, alert_id)
                if self._is_public_stream_strategy(signal)
                else None
            )
            if not self.settings.curated_lab_only_mode:
                await self.router.send_lab_review_bundle(
                    symbol=signal.symbol,
                    scope="alert",
                    posts=external_posts,
                    twitter_draft=twitter_draft,
                )
            delivery_summary = summarize_alert_deliveries(
                lab_delivery=lab_delivery,
                external_deliveries=external_deliveries,
                curated_mode=self.settings.curated_lab_only_mode,
            )
            LOGGER.info(
                "Alert processed symbol=%s direction=%s rsi=%.2f lab=%s "
                "external_sent=%s external_scheduled=%s external_skipped=%s "
                "external_rate_limited=%s external_batched=%s",
                signal.symbol,
                signal.direction,
                signal.rsi,
                delivery_summary["lab_status"],
                delivery_summary["external_sent"],
                delivery_summary["external_scheduled"],
                delivery_summary["external_skipped"],
                delivery_summary["external_rate_limited"],
                delivery_summary["external_batched"],
            )
        except Exception:  # pragma: no cover - long-running service
            LOGGER.exception("Failed to process alert for %s", signal.symbol)
        finally:
            self.chart_renderer.cleanup(chart_path)

    async def _process_gold_alert(self, signal: AlertSignal) -> None:
        chart_path = None
        try:
            prepared_lifecycle = self.signal_lifecycle_service.prepare_signal_metadata(
                signal,
                created_at=utc_now(),
                source_type="gold_stream",
            )
            self.signal_lifecycle_service.apply_prepared_metadata(signal, prepared_lifecycle)
            frame = await self.binance_client.get_klines(
                signal.symbol,
                self.settings.scan_timeframe,
                self.settings.klines_limit,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal)
            signal.chart_path = chart_path

            lab_delivery = None
            if self.settings.curated_lab_only_mode:
                LOGGER.info(
                    "Skipping LAB gold alert for %s because curated LAB-only mode keeps LAB for curated X/thought ideas",
                    signal.symbol,
                )
            else:
                lab_delivery = await self.router.send_raw_alert(signal)
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="lab",
                    chat_id=str(lab_delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                    message_id=lab_delivery.telegram_message_id,
                    signal=signal,
                    alert_id=None,
                    is_preview=False,
                    message_kind="alert",
                )
            sent_at = utc_now()
            first_followup_stage = self.settings.followup_stage_definitions[0][1]
            followup_due_at = sent_at + timedelta(seconds=first_followup_stage)
            alert_id = await self.repository.create_alert(
                signal,
                sent_at=sent_at,
                followup_due_at=followup_due_at,
                lab_message_id=lab_delivery.telegram_message_id if lab_delivery is not None else None,
            )
            await self.signal_lifecycle_service.create_signal(
                signal=signal,
                alert_id=alert_id,
                created_at=sent_at,
                parent_alert_message_id=lab_delivery.telegram_message_id if lab_delivery is not None else None,
                source_type="gold_stream",
            )
            LOGGER.info(
                "Gold follow-up checkpoints scheduled for %s alert_id=%s stages=%s",
                signal.symbol,
                alert_id,
                ",".join(stage for stage, _ in self.settings.followup_stage_definitions),
            )
            if lab_delivery is not None:
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="lab",
                    chat_id=str(lab_delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                    message_id=lab_delivery.telegram_message_id,
                    signal=signal,
                    alert_id=alert_id,
                    is_preview=False,
                    message_kind="alert",
                )
            if str(signal.metadata.get("strategy_key") or "").strip().lower() in {"rsi", "gold"}:
                await self.scanner.confirm_signal_sent(signal, sent_at)
            self.followup_scheduler.notify()
            await self.private_bot_service.deliver_pro_alert(signal, alert_id)
            LOGGER.info("Gold alert sent for %s %s at RSI %.2f", signal.symbol, signal.direction, signal.rsi)
        except Exception:
            LOGGER.exception("Failed to process gold alert for %s", signal.symbol)
        finally:
            self.chart_renderer.cleanup(chart_path)

    async def _send_preview_alert(self) -> None:
        if self.settings.curated_lab_only_mode:
            LOGGER.info("Skipping startup LAB preview alert because curated LAB-only mode is enabled")
            return
        chart_path = None
        try:
            signal = await self.scanner.build_preview_signal("BTCUSDT")
            frame = await self.binance_client.get_klines(
                signal.symbol,
                self.settings.scan_timeframe,
                self.settings.klines_limit,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        except Exception as exc:  # pragma: no cover - runtime dependent
            LOGGER.warning("Live preview generation failed, using real-market fallback: %s", exc)
            try:
                signal, enriched = await self.scanner.build_preview_fallback_signal("BTCUSDT")
            except Exception as fallback_exc:  # pragma: no cover - runtime dependent
                LOGGER.warning("Real-market preview fallback failed, using local synthetic preview: %s", fallback_exc)
                signal, enriched = self._build_synthetic_preview()

        try:
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal, preview=True)
            signal.chart_path = chart_path
            delivery = await self.router.send_raw_alert(signal, preview=True)
            await self.interactive_alert_service.register_alert_message(
                destination_kind="lab",
                chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                message_id=delivery.telegram_message_id,
                signal=signal,
                alert_id=None,
                is_preview=True,
                message_kind="alert",
            )
            LOGGER.info("Sample preview alert sent to LAB")
        finally:
            self.chart_renderer.cleanup(chart_path)

    async def _send_startup_ai_posts(self) -> None:
        if self.settings.curated_lab_only_mode:
            LOGGER.info("Skipping startup AI posts because curated LAB-only mode is enabled")
            return
        posts = await self.draft_generator.generate_startup_posts()
        sent_count = 0
        failed_count = 0
        for post in posts:
            delivery = await self.router.route_generated_post(post)
            if delivery.metadata.get("scheduled"):
                self.scheduled_post_scheduler.notify()
            if delivery.sent:
                sent_count += 1
            elif delivery.metadata.get("error"):
                failed_count += 1
                LOGGER.warning(
                    "Startup AI post failed channel=%s destination=%s error=%s",
                    post.channel_kind,
                    post.destination,
                    delivery.metadata.get("error"),
                )
        LOGGER.info(
            "Startup AI posts processed for enabled destinations: sent=%s failed=%s",
            sent_count,
            failed_count,
        )

    def _build_synthetic_preview(self) -> tuple[AlertSignal, pd.DataFrame]:
        periods = max(self.settings.klines_limit + 70, 220)
        end = pd.Timestamp(utc_now()).floor("15min")
        index = pd.date_range(end=end, periods=periods, freq="15min", tz="UTC")
        rng = np.random.default_rng(7)
        close = np.empty(periods, dtype=float)
        close[0] = 62000.0
        for idx in range(1, periods):
            if idx < int(periods * 0.55):
                drift = 2.0
            elif idx < int(periods * 0.80):
                drift = -5.0
            else:
                drift = 1.0
            close[idx] = close[idx - 1] + drift + rng.normal(0, 10)
        open_ = np.roll(close, 1)
        open_[0] = close[0] + 30
        high = np.maximum(open_, close) + 55
        low = np.minimum(open_, close) - 55
        volume = np.linspace(1200, 2600, periods) + np.sin(np.linspace(0, 5, periods)) * 120

        frame = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "close_time_ms": [(ts + pd.Timedelta(minutes=15)).value // 1_000_000 - 1 for ts in index],
                "close_time": index + pd.Timedelta(minutes=15) - pd.Timedelta(milliseconds=1),
            },
            index=index,
        )
        enriched_full = enrich_klines(frame, self.settings.rsi_length).dropna()
        target_rows = enriched_full[(enriched_full["rsi"] >= 23.0) & (enriched_full["rsi"] <= 29.0)]
        enriched = (
            enriched_full.loc[: target_rows.index[-1]].tail(self.settings.klines_limit).copy()
            if not target_rows.empty
            else enriched_full.tail(self.settings.klines_limit).copy()
        )
        row = enriched.iloc[-1]
        preview_rsi = float(row["rsi"])
        signal = AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe=self.settings.scan_timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=row["close_time"].to_pydatetime(),
            price=float(row["close"]),
            rsi=preview_rsi,
            day_change_pct=-1.74,
            day_volume=523_000_000,
            quote_volume=523_000_000,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]),
            atr=float(row["atr"]),
            atr_pct=float(row["atr_pct"]),
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=72,
            explanation="Preview alert generated locally at startup so you can verify formatting, chart style, and Telegram delivery before live alerts arrive.",
            metadata={
                "preview": True,
                "sample_preview": True,
                "rsi_mode": "closed_trigger",
                "rsi_source": "synthetic_preview+wilder_rma",
                "closed_rsi": preview_rsi,
                "live_rsi": preview_rsi,
                "live_price": float(row["close"]),
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": row["close_time"].to_pydatetime().isoformat(),
            },
        )
        return signal, enriched

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._stop_event.set)

    def _qualifies_for_prepared_features(self, signal: AlertSignal) -> bool:
        if str(signal.metadata.get("asset_class") or "").lower() == "gold":
            return False
        return (
            signal.score >= self.settings.pro_live_min_score
            and (signal.quote_volume or 0.0) >= max(self.settings.x_min_quote_volume, 5_000_000)
        )

    async def _start_payment_runtime(self) -> None:
        if self.crypto_pay_service is None or self.payment_webhook_server is None:
            return
        if not self.settings.crypto_pay_is_configured:
            LOGGER.warning(
                "Crypto Pay runtime skipped: CRYPTO_PAY_ENABLED=%s but CRYPTO_PAY_API_TOKEN is not configured",
                self.settings.crypto_pay_enabled,
            )
            await self._write_runtime_url_files(
                local_webhook_url=self.settings.local_crypto_pay_webhook_url,
                public_base_url=None,
                public_webhook_url=None,
            )
            self._payment_runtime_status.update(
                {
                    "webhook": "disabled",
                    "ngrok": "disabled",
                    "local_webhook_url": self.settings.local_crypto_pay_webhook_url,
                    "public_base_url": None,
                    "public_webhook_url": None,
                    "error": "CRYPTO_PAY_API_TOKEN is not configured in .env",
                }
            )
            return
        try:
            await self.crypto_pay_service.startup_validate()
            server_status = await self.payment_webhook_server.start()
        except Exception as exc:
            LOGGER.exception("Payment runtime startup failed before webhook became ready")
            await self._write_runtime_url_files(
                local_webhook_url=self.settings.local_crypto_pay_webhook_url,
                public_base_url=None,
                public_webhook_url=None,
            )
            self._payment_runtime_status.update(
                {
                    "webhook": "failed",
                    "ngrok": "not_started",
                    "local_webhook_url": self.settings.local_crypto_pay_webhook_url,
                    "public_base_url": None,
                    "public_webhook_url": None,
                    "error": str(exc),
                }
            )
            return
        await self._write_runtime_url_files(
            local_webhook_url=server_status.local_webhook_url,
            public_base_url=None,
            public_webhook_url=None,
        )
        LOGGER.info("Local payment webhook health endpoint: %s", server_status.health_url)
        self._payment_runtime_status.update(
            {
                "webhook": f"running on port {self.settings.local_webhook_port}",
                "ngrok": "disabled" if self.ngrok_tunnel is None else "starting",
                "local_webhook_url": server_status.local_webhook_url,
                "public_base_url": None,
                "public_webhook_url": None,
                "error": None,
            }
        )

        if self.ngrok_tunnel is None:
            return
        tunnel_status = await self.ngrok_tunnel.start()
        if tunnel_status.webhook_url:
            await self._write_runtime_url_files(
                local_webhook_url=server_status.local_webhook_url,
                public_base_url=tunnel_status.public_base_url,
                public_webhook_url=tunnel_status.webhook_url,
            )
            LOGGER.info("Crypto Pay public webhook URL: %s", tunnel_status.webhook_url)
            self._payment_runtime_status.update(
                {
                    "ngrok": "running",
                    "public_base_url": tunnel_status.public_base_url,
                    "public_webhook_url": tunnel_status.webhook_url,
                    "error": None,
                }
            )
            await self._auto_open_webhook_url_file_if_enabled()
            self._print_webhook_ready_banner(
                public_base_url=tunnel_status.public_base_url,
                public_webhook_url=tunnel_status.webhook_url,
            )
            return

        LOGGER.warning(
            "Public payment tunnel is unavailable: %s",
            tunnel_status.error or "unknown ngrok error",
        )
        self._payment_runtime_status.update(
            {
                "ngrok": "failed",
                "public_base_url": None,
                "public_webhook_url": None,
                "error": tunnel_status.error or "ngrok did not become ready",
            }
        )
        self._print_webhook_failure_banner(tunnel_status.error or "ngrok did not become ready")

    async def _write_runtime_url_files(
        self,
        *,
        local_webhook_url: str,
        public_base_url: str | None,
        public_webhook_url: str | None,
    ) -> None:
        await asyncio.to_thread(self.settings.local_webhook_url_file.write_text, f"{local_webhook_url}\n", "utf-8")
        if public_base_url:
            await asyncio.to_thread(self.settings.tunnel_url_file.write_text, f"{public_base_url}\n", "utf-8")
        else:
            await asyncio.to_thread(
                self.settings.tunnel_url_file.write_text,
                "UNAVAILABLE\n",
                "utf-8",
            )
        if public_webhook_url:
            await asyncio.to_thread(self.settings.webhook_url_file.write_text, f"{public_webhook_url}\n", "utf-8")
        else:
            await asyncio.to_thread(
                self.settings.webhook_url_file.write_text,
                (
                    "UNAVAILABLE\n"
                    f"local_webhook={local_webhook_url}\n"
                ),
                "utf-8",
            )

    def _print_local_dev_runtime_summary(
        self,
        *,
        premium_username: str | None,
        classic_username: str | None,
    ) -> None:
        print("")
        print("=== Local Dev Runtime ===")
        print(f"Bot: running (@{premium_username})" if premium_username else "Bot: running")
        if self.classic_telegram_client is not None:
            if classic_username:
                print(f"Classic bot: running (@{classic_username})")
            else:
                print("Classic bot: running")
        webhook_status = self._payment_runtime_status.get("webhook") or "disabled"
        ngrok_status = self._payment_runtime_status.get("ngrok") or "disabled"
        print(f"Webhook server: {webhook_status}")
        print(f"ngrok: {ngrok_status}")
        print(f"Public base URL: {self._payment_runtime_status.get('public_base_url') or 'UNAVAILABLE'}")
        print(f"Crypto Pay webhook URL: {self._payment_runtime_status.get('public_webhook_url') or 'UNAVAILABLE'}")
        print(f"Saved to: {self.settings.webhook_url_file}")
        if self._payment_runtime_status.get("local_webhook_url"):
            print(f"Local webhook URL: {self._payment_runtime_status['local_webhook_url']}")
        if self._payment_runtime_status.get("error"):
            print(f"Payment runtime note: {self._payment_runtime_status['error']}")
        print("")

    def _print_webhook_ready_banner(
        self,
        *,
        public_base_url: str | None,
        public_webhook_url: str,
    ) -> None:
        print("")
        print("=== Crypto Pay Webhook Ready ===", flush=True)
        print(f"ngrok: running", flush=True)
        print(f"Public base URL: {public_base_url or 'UNAVAILABLE'}", flush=True)
        print(f"Crypto Pay webhook URL: {public_webhook_url}", flush=True)
        print(f"Saved to: {self.settings.webhook_url_file}", flush=True)
        print("")

    def _print_webhook_failure_banner(self, error: str) -> None:
        print("")
        print("=== Crypto Pay Webhook Tunnel Unavailable ===", flush=True)
        print("ngrok: failed", flush=True)
        print(f"Reason: {error}", flush=True)
        print(f"Expected file: {self.settings.webhook_url_file}", flush=True)
        print("")

    async def _auto_open_webhook_url_file_if_enabled(self) -> None:
        if not self.settings.webhook_url_auto_open or self._webhook_url_file_opened:
            return
        path = self.settings.webhook_url_file
        if not path.exists():
            return
        try:
            await asyncio.to_thread(os.startfile, str(path))
            self._webhook_url_file_opened = True
            LOGGER.info("Opened webhook URL file for quick copy: %s", path)
        except Exception as exc:
            LOGGER.warning("Failed to auto-open webhook URL file %s: %s", path, exc)


async def main() -> None:
    app = RSISyndicateApp()
    try:
        await app.run()
    except AlreadyRunningError as exc:
        LOGGER.error(str(exc))
        raise SystemExit(1)
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
