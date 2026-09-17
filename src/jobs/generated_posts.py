from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.bot.interactive_alerts import InteractiveAlertService
from src.bot.routing import MessageRouter
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.models import AlertSignal, GeneratedPost
from src.core.utils import utc_now
from src.market.binance_client import BinanceClient
from src.market.indicators import enrich_klines
from src.storage.models import AlertRecord, ScheduledGeneratedPostRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.classicbot.service import ClassicBotService


class ScheduledGeneratedPostService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        router: MessageRouter,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        interactive_alert_service: InteractiveAlertService | None = None,
        classic_router: MessageRouter | None = None,
        classic_interactive_alert_service: InteractiveAlertService | None = None,
        classic_bot_service: ClassicBotService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.router = router
        self.binance_client = binance_client
        self.chart_renderer = chart_renderer
        self.interactive_alert_service = interactive_alert_service
        self.classic_router = classic_router
        self.classic_interactive_alert_service = classic_interactive_alert_service
        self.classic_bot_service = classic_bot_service

    async def handle_task(self, task: ScheduledGeneratedPostRecord) -> None:
        attempt_number = task.attempts + 1
        await self.repository.mark_scheduled_generated_post_processing(task.id, attempt_number)
        owned_chart_path: Path | None = None
        try:
            post = self._post_from_record(task)
            if post.channel_kind == "classic" and post.content_type == "classic_delayed_alert":
                await self._deliver_scheduled_classic_alert(task, post)
                return
            if self._skip_for_curated_lab_only_mode(post):
                await self.repository.mark_scheduled_generated_post_skipped(
                    task.id,
                    "curated_lab_only_mode",
                    utc_now(),
                )
                LOGGER.info(
                    "Scheduled generated post skipped task_id=%s channel=%s type=%s reason=curated_lab_only_mode",
                    task.id,
                    post.channel_kind,
                    post.content_type,
                )
                return
            alert_record = None
            if post.related_alert_id is not None:
                alert_record = await self.repository.get_alert(post.related_alert_id)

            if post.channel_kind == "public" and post.content_type == "public_best_setup":
                if alert_record is None:
                    raise RuntimeError(f"Scheduled public post {task.id} is missing alert {post.related_alert_id}")
                post.chart_path = await self._render_public_alert_chart(alert_record)
                owned_chart_path = post.chart_path

            delivery = await self.router.deliver_scheduled_generated_post(post)
            if delivery.sent:
                sent_at = utc_now()
                await self.repository.mark_scheduled_generated_post_sent(task.id, sent_at)
                LOGGER.info(
                    "Scheduled generated post sent task_id=%s channel=%s type=%s destination=%s",
                    task.id,
                    post.channel_kind,
                    post.content_type,
                    post.destination,
                )
                await self._register_interactive_state(post, alert_record, delivery)
                return

            if delivery.rate_limited:
                retry_at = utc_now() + timedelta(minutes=min(15 * attempt_number, 60))
                await self.repository.reschedule_scheduled_generated_post(
                    task.id,
                    retry_at,
                    "rate_limited",
                    attempt_number,
                )
                LOGGER.info(
                    "Scheduled generated post rate limited task_id=%s type=%s retry_at=%s",
                    task.id,
                    post.content_type,
                    retry_at.isoformat(),
                )
                return

            await self.repository.mark_scheduled_generated_post_skipped(
                task.id,
                "delivery_not_sent",
                utc_now(),
            )
            LOGGER.info(
                "Scheduled generated post skipped task_id=%s channel=%s type=%s reason=delivery_not_sent",
                task.id,
                post.channel_kind,
                post.content_type,
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            LOGGER.exception("Scheduled generated post task %s failed", task.id)
            retry_at = utc_now() + timedelta(minutes=min(10 * attempt_number, 60))
            await self.repository.reschedule_scheduled_generated_post(
                task.id,
                retry_at,
                str(exc),
                attempt_number,
            )
        finally:
            self.chart_renderer.cleanup(owned_chart_path)

    async def _deliver_scheduled_classic_alert(
        self,
        task: ScheduledGeneratedPostRecord,
        post: GeneratedPost,
    ) -> None:
        owned_chart_path: Path | None = None
        if self.classic_router is None:
            await self.repository.mark_scheduled_generated_post_skipped(
                task.id,
                "classic_router_missing",
                utc_now(),
            )
            LOGGER.info("Scheduled CLASSIC alert skipped task_id=%s reason=classic_router_missing", task.id)
            return
        if post.related_alert_id is None:
            raise RuntimeError(f"Scheduled classic alert {task.id} is missing related_alert_id")
        alert_record = await self.repository.get_alert(post.related_alert_id)
        if alert_record is None:
            raise RuntimeError(f"Scheduled classic alert {task.id} is missing alert {post.related_alert_id}")

        user_id = int(str(post.destination))
        user = await self.repository.get_private_user(user_id)
        if user is None or not user.is_active:
            await self.repository.mark_scheduled_generated_post_skipped(
                task.id,
                "classic_user_missing_or_inactive",
                utc_now(),
            )
            LOGGER.info(
                "Scheduled CLASSIC alert skipped task_id=%s alert_id=%s user=%s reason=classic_user_missing_or_inactive",
                task.id,
                post.related_alert_id,
                user_id,
            )
            return
        settings = await self.repository.get_user_settings(user_id, bot_kind="classic")
        if settings is None and self.classic_bot_service is not None:
            settings = await self.classic_bot_service._ensure_user_settings(user_id)
        if settings is None or not settings.direct_signal_delivery_enabled:
            await self.repository.mark_scheduled_generated_post_skipped(
                task.id,
                "classic_alerts_disabled_before_due",
                utc_now(),
            )
            LOGGER.info(
                "Scheduled CLASSIC alert skipped task_id=%s alert_id=%s user=%s reason=classic_alerts_disabled_before_due",
                task.id,
                post.related_alert_id,
                user_id,
            )
            return
        if await self.repository.delivered_signal_exists(
            telegram_user_id=user_id,
            bot_kind="classic",
            alert_id=post.related_alert_id,
            content_kind=str(post.metadata.get("content_kind") or "classic_basic"),
            message_kind="alert",
        ):
            await self.repository.mark_scheduled_generated_post_skipped(
                task.id,
                "classic_alert_already_delivered",
                utc_now(),
            )
            LOGGER.info(
                "Scheduled CLASSIC alert skipped task_id=%s alert_id=%s user=%s reason=classic_alert_already_delivered",
                task.id,
                post.related_alert_id,
                user_id,
            )
            return
        try:
            signal = self._signal_from_alert_record(alert_record)
            if self.classic_bot_service is not None:
                effective_settings = settings or await self.classic_bot_service._ensure_user_settings(user_id)
                watchlist_symbols = await self.classic_bot_service._watchlist_set(user_id)
                signal = self.classic_bot_service._apply_user_preferences_to_signal(signal, effective_settings)
                matches_filters, reason = self.classic_bot_service._signal_matches_user_settings(
                    signal,
                    effective_settings,
                    watchlist_symbols=watchlist_symbols,
                    strong_only=False,
                )
                if not matches_filters:
                    await self.repository.mark_scheduled_generated_post_skipped(
                        task.id,
                        f"classic_filtered_{reason}",
                        utc_now(),
                    )
                    LOGGER.info(
                        "Scheduled CLASSIC alert skipped task_id=%s alert_id=%s user=%s reason=classic_filtered_%s",
                        task.id,
                        post.related_alert_id,
                        user_id,
                        reason,
                    )
                    return
                owned_chart_path = await self.classic_bot_service.render_delivery_chart(signal)
            else:
                owned_chart_path = await self._render_public_alert_chart(alert_record)
            signal.chart_path = owned_chart_path
            delivery = await self.classic_router.send_raw_alert_to_chat(
                signal,
                chat_id=str(user_id),
                destination_kind="classic",
                preview=False,
            )
        finally:
            self.chart_renderer.cleanup(owned_chart_path)
        await self.repository.record_delivered_signal(
            telegram_user_id=user_id,
            bot_kind="classic",
            alert_id=post.related_alert_id,
            content_kind=str(post.metadata.get("content_kind") or "classic_basic"),
            message_kind="alert",
            telegram_message_id=delivery.telegram_message_id,
            metadata={"sent": delivery.sent, "scheduled": True},
        )
        if delivery.sent and delivery.telegram_message_id is not None and self.classic_interactive_alert_service is not None:
            await self.classic_interactive_alert_service.register_alert_message(
                destination_kind="classic",
                chat_id=str(user_id),
                message_id=delivery.telegram_message_id,
                signal=signal,
                alert_id=post.related_alert_id,
                is_preview=False,
                message_kind="alert",
            )
        if delivery.sent:
            sent_at = utc_now()
            await self.repository.mark_scheduled_generated_post_sent(task.id, sent_at)
            LOGGER.info(
                "Scheduled CLASSIC alert sent task_id=%s alert_id=%s user=%s",
                task.id,
                post.related_alert_id,
                user_id,
            )
            return
        if delivery.rate_limited:
            retry_at = utc_now() + timedelta(minutes=min(15 * (task.attempts + 1), 60))
            await self.repository.reschedule_scheduled_generated_post(
                task.id,
                retry_at,
                "classic_rate_limited",
                task.attempts + 1,
            )
            LOGGER.info(
                "Scheduled CLASSIC alert rate limited task_id=%s alert_id=%s user=%s retry_at=%s",
                task.id,
                post.related_alert_id,
                user_id,
                retry_at.isoformat(),
            )
            return
        await self.repository.mark_scheduled_generated_post_skipped(
            task.id,
            "classic_delivery_not_sent",
            utc_now(),
        )
        LOGGER.info(
            "Scheduled CLASSIC alert skipped task_id=%s alert_id=%s user=%s reason=classic_delivery_not_sent",
            task.id,
            post.related_alert_id,
            user_id,
        )

    async def _render_public_alert_chart(self, alert: AlertRecord) -> Path:
        frame = await self.binance_client.get_klines(
            alert.symbol,
            alert.timeframe,
            self.settings.klines_limit,
            end_time=alert.candle_close_time,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        signal = self._signal_from_alert_record(alert)
        return await self.chart_renderer.render_alert_chart(enriched, signal)

    async def _register_interactive_state(
        self,
        post: GeneratedPost,
        alert_record: AlertRecord | None,
        delivery,
    ) -> None:
        if self.interactive_alert_service is None:
            return
        if not delivery.sent or delivery.telegram_message_id is None:
            return
        if post.channel_kind not in {"public", "results"}:
            return
        if alert_record is None:
            return
        signal = self._signal_from_alert_record(alert_record)
        message_kind = "followup" if post.content_type in {"public_result_post", "public_market_takeaway", "results_proof_post", "results_followup_post"} else "alert"
        await self.interactive_alert_service.register_alert_message(
            destination_kind=post.channel_kind,
            chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.telegram_destinations[post.channel_kind]),
            message_id=delivery.telegram_message_id,
            signal=signal,
            alert_id=alert_record.id,
            is_preview=False,
            message_kind=message_kind,
        )

    def _post_from_record(self, task: ScheduledGeneratedPostRecord) -> GeneratedPost:
        payload = task.payload
        chart_path_raw = payload.get("chart_path")
        chart_path = Path(chart_path_raw) if isinstance(chart_path_raw, str) and chart_path_raw else None
        return GeneratedPost(
            channel_kind=str(payload.get("channel_kind") or task.channel_kind),
            destination=str(payload.get("destination") or task.destination),
            content_type=str(payload.get("content_type") or task.content_type),
            generated_text=str(payload.get("generated_text") or ""),
            status=str(payload.get("status") or "generated"),
            chart_path=chart_path,
            delivery_text=payload.get("delivery_text"),
            ai_model=payload.get("ai_model"),
            source_symbol=payload.get("source_symbol"),
            related_alert_id=payload.get("related_alert_id"),
            force_autopost=bool(payload.get("force_autopost", False)),
            send_lab_copy=bool(payload.get("send_lab_copy", False)),
            bundle_in_lab_review=bool(payload.get("bundle_in_lab_review", False)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _skip_for_curated_lab_only_mode(self, post: GeneratedPost) -> bool:
        if not self.settings.curated_lab_only_mode:
            return False
        if post.channel_kind in {"public", "pro", "community"}:
            return True
        if post.channel_kind == "results":
            return False
        return post.channel_kind == "lab" and post.content_type in {
            "startup_post",
            "internal_summary",
            "followup_internal_summary",
        }

    def _signal_from_alert_record(self, alert: AlertRecord) -> AlertSignal:
        return AlertSignal(
            symbol=alert.symbol,
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
            metadata={**alert.metadata, "strategy_key": alert.strategy_key},
        )


class ScheduledGeneratedPostScheduler:
    def __init__(
        self,
        repository: Repository,
        handler: Callable[[ScheduledGeneratedPostRecord], Awaitable[None]],
    ) -> None:
        self.repository = repository
        self.handler = handler
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="scheduled-generated-post-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

    def notify(self) -> None:
        self._wake_event.set()

    async def _run(self) -> None:
        LOGGER.info("Scheduled generated post scheduler started")
        while not self._stop_event.is_set():
            next_task = await self.repository.get_next_due_scheduled_generated_post()
            if next_task is None:
                await self._wait_for_signal(timeout=900)
                continue

            wait_seconds = (next_task.due_at - utc_now()).total_seconds()
            if wait_seconds > 0:
                await self._wait_for_signal(timeout=wait_seconds)
                continue

            due_tasks = await self.repository.get_due_scheduled_generated_posts()
            for task in due_tasks:
                if self._stop_event.is_set():
                    break
                await self.handler(task)
        LOGGER.info("Scheduled generated post scheduler stopped")

    async def _wait_for_signal(self, timeout: float) -> None:
        if self._wake_event.is_set():
            self._wake_event.clear()
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake_event.clear()
