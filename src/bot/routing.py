from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from src.bot.formatters import (
    format_alert_message,
    format_followup_message,
    format_generated_post_review,
    format_lab_batch_message,
    format_lab_review_bundle,
    format_twitter_draft_message,
)
from src.bot.inline_keyboards import build_alert_inline_keyboard
from src.bot.telegram_client import TelegramClient
from src.core.config import Settings
from src.core.models import AlertSignal, DeliveryResult, FollowUpResult, GeneratedPost, TwitterDraft
from src.core.utils import normalize_symbol, utc_now
from src.localization import normalize_language, ui_text
from src.market.symbols import (
    build_futures_app_link,
    build_futures_link,
    build_tradingview_futures_link,
    is_supported_futures_symbol,
)
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


class MessageRouter:
    def __init__(
        self,
        settings: Settings,
        telegram_client: TelegramClient,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.telegram_client = telegram_client
        self.repository = repository
        self._lab_batch_buffers: dict[str, list[str]] = {
            "internal_summary": [],
            "review_copy": [],
        }
        self._lab_batch_lock = asyncio.Lock()
        self._lab_batch_task: asyncio.Task | None = None

    def _classic_delay_footer(self, language_code: str) -> str:
        delay_minutes = self.settings.classic_bot_signal_delay_minutes
        if normalize_language(language_code) == "ru":
            return f"Classic приходит примерно на {delay_minutes} минут позже PRO+."
        return f"Classic arrives about {delay_minutes} minutes later than PRO+."

    async def close(self) -> None:
        task = self._lab_batch_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for batch_kind in ("internal_summary", "review_copy"):
            await self._flush_lab_batch(batch_kind, force=True)

    async def send_raw_alert(
        self,
        signal: AlertSignal,
        *,
        destination_kind: str = "lab",
        preview: bool = False,
    ) -> DeliveryResult:
        destination = self.settings.telegram_destinations[destination_kind]
        return await self.send_raw_alert_to_chat(
            signal,
            chat_id=destination,
            destination_kind=destination_kind,
            preview=preview,
        )

    async def send_raw_alert_to_chat(
        self,
        signal: AlertSignal,
        *,
        chat_id: str,
        destination_kind: str,
        preview: bool = False,
    ) -> DeliveryResult:
        if destination_kind == "private":
            message_type = "private_preview_alert" if preview else "private_raw_alert"
        elif destination_kind == "classic":
            message_type = "classic_preview_alert" if preview else "classic_raw_alert"
        else:
            message_type = "preview_alert" if preview else "raw_alert"
        language_code = normalize_language(str(signal.metadata.get("language_code") or "en"))
        caption = format_alert_message(
            signal,
            self.settings.timezone,
            self.settings.binance_futures_web_base_url,
            preview=preview,
            language_code=language_code,
            footer_note=(
                self._classic_delay_footer(language_code)
                if destination_kind == "classic"
                else None
            ),
        )
        if self.settings.interactive_enabled_for(destination_kind):
            reply_markup = self._build_interactive_reply_markup(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                destination_kind=destination_kind,
                language_code=language_code,
                external_link_label=str(signal.metadata.get("external_link_label") or "") or None,
                external_link_url=str(signal.metadata.get("external_link_url") or ""),
                include_ai_analysis=(
                    bool(signal.metadata["interactive_ai_enabled"])
                    if "interactive_ai_enabled" in signal.metadata
                    else None
                ),
                include_risk_management=(
                    bool(signal.metadata["interactive_risk_enabled"])
                    if "interactive_risk_enabled" in signal.metadata
                    else None
                ),
                include_signal_reason=(
                    bool(signal.metadata["interactive_reason_enabled"])
                    if "interactive_reason_enabled" in signal.metadata
                    else None
                ),
            )
        else:
            reply_markup = self._build_symbol_reply_markup(
                signal.symbol,
                include_binance_link=True,
                include_tradingview_link=destination_kind in {"private", "pro"},
                language_code=language_code,
                external_link_label=str(signal.metadata.get("external_link_label") or "") or None,
                external_link_url=str(signal.metadata.get("external_link_url") or ""),
            )
        if signal.chart_path is not None:
            return await self._send_photo_with_policy(
                destination=chat_id,
                message_type=message_type,
                photo_path=signal.chart_path,
                caption=caption,
                reply_markup=reply_markup,
            )
        return await self._send_message_with_policy(
            destination=chat_id,
            message_type=message_type,
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    async def send_followup(
        self,
        result: FollowUpResult,
        *,
        destination_kind: str = "lab",
    ) -> DeliveryResult:
        destination = self.settings.telegram_destinations[destination_kind]
        return await self.send_followup_to_chat(
            result,
            chat_id=destination,
            destination_kind=destination_kind,
        )

    async def send_followup_to_chat(
        self,
        result: FollowUpResult,
        *,
        chat_id: str,
        destination_kind: str,
    ) -> DeliveryResult:
        if destination_kind == "private":
            message_type = "private_followup"
        elif destination_kind == "classic":
            message_type = "classic_followup"
        else:
            message_type = "followup"
        language_code = normalize_language(str(result.metadata.get("language_code") or "en"))
        caption = format_followup_message(
            result,
            self.settings.timezone,
            language_code=language_code,
            footer_note=(
                self._classic_delay_footer(language_code)
                if destination_kind == "classic"
                else None
            ),
        )
        if self.settings.interactive_enabled_for(destination_kind):
            reply_markup = self._build_interactive_reply_markup(
                symbol=result.symbol,
                timeframe=result.timeframe,
                destination_kind=destination_kind,
                language_code=language_code,
                external_link_label=str(result.metadata.get("external_link_label") or "") or None,
                external_link_url=str(result.metadata.get("external_link_url") or ""),
                include_ai_analysis=(
                    bool(result.metadata["interactive_ai_enabled"])
                    if "interactive_ai_enabled" in result.metadata
                    else None
                ),
                include_risk_management=(
                    bool(result.metadata["interactive_risk_enabled"])
                    if "interactive_risk_enabled" in result.metadata
                    else None
                ),
                include_signal_reason=(
                    bool(result.metadata["interactive_reason_enabled"])
                    if "interactive_reason_enabled" in result.metadata
                    else None
                ),
            )
        else:
            reply_markup = self._build_symbol_reply_markup(
                result.symbol,
                include_binance_link=True,
                include_tradingview_link=destination_kind in {"private", "pro"},
                language_code=language_code,
                external_link_label=str(result.metadata.get("external_link_label") or "") or None,
                external_link_url=str(result.metadata.get("external_link_url") or ""),
            )
        if result.chart_path is not None:
            return await self._send_photo_with_policy(
                destination=chat_id,
                message_type=message_type,
                photo_path=result.chart_path,
                caption=caption,
                reply_markup=reply_markup,
            )
        return await self._send_message_with_policy(
            destination=chat_id,
            message_type=message_type,
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    async def send_twitter_draft(self, draft: TwitterDraft) -> DeliveryResult:
        message = format_twitter_draft_message(draft)
        reply_markup = self._build_twitter_draft_reply_markup(draft)
        if draft.chart_path is not None:
            return await self._send_photo_with_policy(
                destination=draft.destination,
                message_type=f"twitter_draft:{draft.content_type}",
                photo_path=draft.chart_path,
                caption=message,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        return await self._send_message_with_policy(
            destination=draft.destination,
            message_type=f"twitter_draft:{draft.content_type}",
            text=message,
            parse_mode=None,
            reply_markup=reply_markup,
        )

    async def send_lab_review_bundle(
        self,
        *,
        symbol: str,
        scope: str,
        posts: list[GeneratedPost],
        twitter_draft: TwitterDraft | None = None,
    ) -> DeliveryResult | None:
        if not posts and (twitter_draft is None or twitter_draft.status == "skipped"):
            return None
        return await self._send_message_with_policy(
            destination=self.settings.lab_channel,
            message_type=f"lab_review_package:{scope}",
            text=format_lab_review_bundle(
                symbol=symbol,
                scope=scope,
                posts=posts,
                twitter_draft=twitter_draft,
            ),
            parse_mode=None,
        )

    async def route_generated_post(self, post: GeneratedPost) -> DeliveryResult:
        autopost_enabled = post.force_autopost or self._is_autopost_enabled(post.channel_kind)
        try:
            if self._should_schedule_generated_post(post, autopost_enabled):
                due_at = utc_now() + timedelta(seconds=self.settings.public_signal_delay_seconds)
                scheduled_id = await self.repository.create_scheduled_generated_post(post=post, due_at=due_at)
                post.status = "scheduled"
                post.delivery_text = self._delivery_text_for_post(post)
                post.metadata = {
                    **post.metadata,
                    "autopost_enabled": autopost_enabled,
                    "scheduled_generated_post_id": scheduled_id,
                    "scheduled_due_at": due_at.isoformat(),
                }
                await self.repository.record_message_event(
                    destination=post.destination,
                    message_type=f"ai:{post.channel_kind}:{post.content_type}",
                    status="scheduled",
                    created_at=utc_now(),
                    metadata={
                        "scheduled_due_at": due_at.isoformat(),
                        "source_symbol": post.source_symbol,
                        "related_alert_id": post.related_alert_id,
                    },
                )
                LOGGER.info(
                    "Scheduled delayed PUBLIC delivery id=%s symbol=%s type=%s due_at=%s",
                    scheduled_id,
                    post.source_symbol,
                    post.content_type,
                    due_at.isoformat(),
                )
                return DeliveryResult(
                    destination=post.destination,
                    message_type=f"ai:{post.channel_kind}:{post.content_type}",
                    sent=False,
                    rate_limited=False,
                    metadata={
                        "scheduled": True,
                        "scheduled_post_id": scheduled_id,
                        "due_at": due_at.isoformat(),
                    },
                )

            return await self._deliver_generated_post_now(post, autopost_enabled=autopost_enabled)
        except Exception as exc:
            LOGGER.exception(
                "Generated post delivery failed channel=%s type=%s destination=%s symbol=%s",
                post.channel_kind,
                post.content_type,
                post.destination,
                post.source_symbol,
            )
            post.status = "failed"
            post.delivery_text = self._delivery_text_for_post(post)
            post.metadata = {
                **post.metadata,
                "autopost_enabled": autopost_enabled,
                "error": str(exc),
            }
            await self.repository.save_generated_post(post=post, sent_at=None)
            return DeliveryResult(
                destination=post.destination,
                message_type=f"ai:{post.channel_kind}:{post.content_type}",
                sent=False,
                rate_limited=False,
                metadata={"error": str(exc)},
            )

    async def deliver_scheduled_generated_post(self, post: GeneratedPost) -> DeliveryResult:
        LOGGER.info(
            "Delivering scheduled generated post symbol=%s channel=%s type=%s",
            post.source_symbol,
            post.channel_kind,
            post.content_type,
        )
        return await self._deliver_generated_post_now(post, autopost_enabled=True)

    async def _deliver_generated_post_now(
        self,
        post: GeneratedPost,
        *,
        autopost_enabled: bool,
    ) -> DeliveryResult:
        primary_delivery: DeliveryResult | None = None
        review_delivery: DeliveryResult | None = None
        bundle_only = post.bundle_in_lab_review
        interactive_markup = self._build_generated_post_reply_markup(post)
        delivery_text = self._delivery_text_for_post(post)
        if post.channel_kind != "lab" and not autopost_enabled:
            LOGGER.info(
                "Autopost disabled for %s %s; routing as draft/review instead of live send",
                post.channel_kind,
                post.content_type,
            )

        if post.channel_kind == "lab":
            if post.chart_path is not None:
                primary_delivery = await self._send_photo_with_policy(
                    destination=post.destination,
                    message_type=f"ai:lab:{post.content_type}",
                    photo_path=post.chart_path,
                    caption=delivery_text,
                    parse_mode=None,
                )
            else:
                primary_delivery = await self._send_message_with_policy(
                    destination=post.destination,
                    message_type=f"ai:lab:{post.content_type}",
                    text=delivery_text,
                    parse_mode=None,
                )
        else:
            if autopost_enabled:
                if post.chart_path is not None:
                    primary_delivery = await self._send_photo_with_policy(
                        destination=post.destination,
                        message_type=f"ai:{post.channel_kind}:{post.content_type}",
                        photo_path=post.chart_path,
                        caption=delivery_text,
                        parse_mode=None,
                        reply_markup=interactive_markup,
                    )
                else:
                    primary_delivery = await self._send_message_with_policy(
                        destination=post.destination,
                        message_type=f"ai:{post.channel_kind}:{post.content_type}",
                        text=delivery_text,
                        parse_mode=None,
                        reply_markup=interactive_markup,
                    )

            if not bundle_only and (post.send_lab_copy or not autopost_enabled):
                review_status = self._review_status_label(
                    autopost_enabled=autopost_enabled,
                    primary_delivery=primary_delivery,
                )
                review_delivery = await self._send_message_with_policy(
                    destination=self.settings.lab_channel,
                    message_type=f"lab_review:{post.channel_kind}:{post.content_type}",
                    text=format_generated_post_review(
                        post.channel_kind,
                        post.content_type,
                        post.generated_text,
                        status=review_status,
                        destination=post.destination,
                    ),
                    parse_mode=None,
                )

        post.status = self._resolve_generated_post_status(
            post=post,
            autopost_enabled=autopost_enabled,
            primary_delivery=primary_delivery,
            review_delivery=review_delivery,
        )
        post.delivery_text = delivery_text
        post.metadata = {
            **post.metadata,
            "autopost_enabled": autopost_enabled,
            "bundle_in_lab_review": bundle_only,
            "primary_delivery": self._delivery_snapshot(primary_delivery),
            "review_delivery": self._delivery_snapshot(review_delivery),
        }

        sent_at = utc_now() if self._was_delivered(primary_delivery, review_delivery) else None
        await self.repository.save_generated_post(post=post, sent_at=sent_at)
        LOGGER.info(
            "Generated post routed channel=%s type=%s status=%s destination=%s",
            post.channel_kind,
            post.content_type,
            post.status,
            post.destination,
        )

        return primary_delivery or review_delivery or DeliveryResult(
            destination=post.destination,
            message_type=f"ai:{post.channel_kind}:{post.content_type}",
            sent=False,
            rate_limited=False,
        )

    async def _send_message_with_policy(
        self,
        *,
        destination: str,
        message_type: str,
        text: str,
        parse_mode: str | None,
        reply_markup: dict[str, object] | None = None,
    ) -> DeliveryResult:
        delivery_mode = await self._resolve_delivery_mode(destination, message_type)
        if delivery_mode == "send":
            telegram_result = await self.telegram_client.send_message(
                chat_id=destination,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
            now = utc_now()
            await self.repository.record_message_event(
                destination=destination,
                message_type=message_type,
                status="sent",
                created_at=now,
                telegram_message_id=telegram_result.get("message_id"),
            )
            return DeliveryResult(
                destination=destination,
                message_type=message_type,
                sent=True,
                rate_limited=False,
                telegram_message_id=telegram_result.get("message_id"),
                metadata={
                    "telegram_chat_id": (
                        telegram_result.get("chat", {}) or {}
                    ).get("id"),
                },
            )

        if delivery_mode == "rate_limited":
            return await self._record_rate_limited(destination, message_type)

        return await self._buffer_lab_message(
            destination=destination,
            message_type=message_type,
            text=text,
            batch_kind=delivery_mode.removeprefix("batch:"),
        )

    async def _send_photo_with_policy(
        self,
        *,
        destination: str,
        message_type: str,
        photo_path: Path,
        caption: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, object] | None = None,
    ) -> DeliveryResult:
        delivery_mode = await self._resolve_delivery_mode(destination, message_type)
        if delivery_mode == "send":
            telegram_result = await self.telegram_client.send_photo(
                chat_id=destination,
                photo_path=photo_path,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            now = utc_now()
            await self.repository.record_message_event(
                destination=destination,
                message_type=message_type,
                status="sent",
                created_at=now,
                telegram_message_id=telegram_result.get("message_id"),
            )
            return DeliveryResult(
                destination=destination,
                message_type=message_type,
                sent=True,
                rate_limited=False,
                telegram_message_id=telegram_result.get("message_id"),
                metadata={
                    "telegram_chat_id": (
                        telegram_result.get("chat", {}) or {}
                    ).get("id"),
                },
            )

        if delivery_mode == "rate_limited":
            return await self._record_rate_limited(destination, message_type)

        return await self._buffer_lab_message(
            destination=destination,
            message_type=message_type,
            text=caption,
            batch_kind=delivery_mode.removeprefix("batch:"),
        )

    async def _resolve_delivery_mode(self, destination: str, message_type: str) -> str:
        if destination == self.settings.twitter_drafts_chat:
            return "send"
        if destination == self.settings.results_channel and message_type.startswith("ai:results:"):
            return "send"
        if message_type.startswith("private_") or message_type.startswith("classic_"):
            return "send"
        if message_type.endswith(":startup_post"):
            return "send"

        if destination != self.settings.lab_channel:
            sent_last_hour = await self.repository.count_sent_messages_since(
                destination,
                utc_now() - timedelta(hours=1),
            )
            if sent_last_hour >= self.settings.telegram_destination_hourly_limit:
                LOGGER.info(
                    "Rate limit reached for destination %s: %s messages sent in the last hour",
                    destination,
                    sent_last_hour,
                )
                return "rate_limited"
            return "send"

        if message_type in {"raw_alert", "preview_alert", "followup", "diagnostic", "ai:lab:startup_post"}:
            return "send"

        since = utc_now() - timedelta(hours=1)

        if message_type in {"ai:lab:internal_summary", "ai:lab:followup_summary", "lab_batch:internal_summary"}:
            sent_internal = await self.repository.count_sent_messages_since(
                destination,
                since,
                message_types=[
                    "ai:lab:internal_summary",
                    "ai:lab:followup_summary",
                    "lab_batch:internal_summary",
                ],
            )
            if sent_internal >= self.settings.lab_internal_summary_hourly_limit:
                LOGGER.info(
                    "LAB internal summary quota reached: %s sent in the last hour, batching %s",
                    sent_internal,
                    message_type,
                )
                return "batch:internal_summary"
            return "send"

        if (
            message_type == "lab_batch:review_copy"
            or message_type.startswith("lab_review:")
            or message_type.startswith("lab_review_package:")
        ):
            sent_reviews = await self.repository.count_sent_messages_since(
                destination,
                since,
                message_types=["lab_batch:review_copy"],
                message_type_prefixes=["lab_review:", "lab_review_package:"],
            )
            if sent_reviews >= self.settings.lab_review_copy_hourly_limit:
                LOGGER.info(
                    "LAB review-copy quota reached: %s sent in the last hour, batching %s",
                    sent_reviews,
                    message_type,
                )
                return "batch:review_copy"
            return "send"

        return "send"

    async def _buffer_lab_message(
        self,
        *,
        destination: str,
        message_type: str,
        text: str,
        batch_kind: str,
    ) -> DeliveryResult:
        should_flush_now = False
        async with self._lab_batch_lock:
            self._lab_batch_buffers[batch_kind].append(text)
            remaining_count = len(self._lab_batch_buffers[batch_kind])
            should_flush_now = remaining_count >= self.settings.lab_batch_max_items
            if not should_flush_now:
                self._ensure_lab_batch_task_locked()

        now = utc_now()
        await self.repository.record_message_event(
            destination=destination,
            message_type=message_type,
            status="batched",
            created_at=now,
            metadata={"batch_kind": batch_kind},
        )
        LOGGER.info(
            "Buffered LAB %s message for batching. Queue size is now %s",
            batch_kind,
            remaining_count,
        )

        if should_flush_now:
            await self._flush_lab_batch(batch_kind)

        return DeliveryResult(
            destination=destination,
            message_type=message_type,
            sent=False,
            rate_limited=False,
            batched=True,
            metadata={"batch_kind": batch_kind},
        )

    async def _flush_lab_batch(self, batch_kind: str, *, force: bool = False) -> None:
        async with self._lab_batch_lock:
            buffer = self._lab_batch_buffers[batch_kind]
            if not buffer:
                return
            items = buffer[: self.settings.lab_batch_max_items]

        if not force:
            delivery_mode = await self._resolve_delivery_mode(
                self.settings.lab_channel,
                f"lab_batch:{batch_kind}",
            )
            if delivery_mode != "send":
                LOGGER.info(
                    "LAB batch flush deferred for %s because quota is still full. Queued items: %s",
                    batch_kind,
                    len(items),
                )
                return

        message = format_lab_batch_message(
            batch_kind,
            items,
            remaining_count=max(
                0,
                await self._batch_remaining_after_current_flush(batch_kind, len(items)),
            ),
        )

        try:
            telegram_result = await self.telegram_client.send_message(
                chat_id=self.settings.lab_channel,
                text=message,
                parse_mode=None,
                disable_web_page_preview=True,
            )
        except Exception:
            LOGGER.exception("Failed to flush LAB %s batch; keeping queued items", batch_kind)
            return

        now = utc_now()
        async with self._lab_batch_lock:
            del self._lab_batch_buffers[batch_kind][: len(items)]
            remaining_count = len(self._lab_batch_buffers[batch_kind])
            if remaining_count == 0 and not any(self._lab_batch_buffers.values()):
                self._lab_batch_task = None

        await self.repository.record_message_event(
            destination=self.settings.lab_channel,
            message_type=f"lab_batch:{batch_kind}",
            status="sent",
            created_at=now,
            telegram_message_id=telegram_result.get("message_id"),
            metadata={"items_flushed": len(items), "remaining_count": remaining_count},
        )
        LOGGER.info(
            "Flushed LAB %s batch with %s items. Remaining queued: %s",
            batch_kind,
            len(items),
            remaining_count,
        )

    async def _batch_remaining_after_current_flush(self, batch_kind: str, flush_count: int) -> int:
        async with self._lab_batch_lock:
            return len(self._lab_batch_buffers[batch_kind]) - flush_count

    async def _record_rate_limited(self, destination: str, message_type: str) -> DeliveryResult:
        now = utc_now()
        await self.repository.record_message_event(
            destination=destination,
            message_type=message_type,
            status="rate_limited",
            created_at=now,
        )
        return DeliveryResult(
            destination=destination,
            message_type=message_type,
            sent=False,
            rate_limited=True,
        )

    def _is_autopost_enabled(self, channel_kind: str) -> bool:
        if channel_kind == "public":
            return self.settings.autopost_public
        if channel_kind == "pro":
            return self.settings.autopost_pro
        if channel_kind == "results":
            return self.settings.results_channel_enabled
        if channel_kind == "community":
            return self.settings.autopost_community
        return True

    def _should_schedule_generated_post(self, post: GeneratedPost, autopost_enabled: bool) -> bool:
        return (
            post.channel_kind == "public"
            and autopost_enabled
            and not post.force_autopost
            and post.content_type == "public_best_setup"
            and self.settings.public_signal_delay_seconds > 0
        )

    def _delivery_text_for_post(self, post: GeneratedPost) -> str:
        text = post.generated_text.strip()
        if (
            post.channel_kind == "public"
            and post.content_type == "public_best_setup"
            and self.settings.public_delay_premium_note_enabled
        ):
            if self.settings.public_delay_premium_bot_link.strip():
                note = (
                    f"This feed runs about {self.settings.public_signal_delay_minutes}m later than the private bot. "
                    f"If you want the same setups on time, use {self.settings.public_delay_premium_bot_link.strip()}. "
                    f"New users get a {self.settings.public_delay_trial_days}-day trial."
                )
            else:
                note = (
                    f"This feed runs about {self.settings.public_signal_delay_minutes}m later than the private bot. "
                    "The same setup was shared earlier in the private flow."
                )
            if note.lower() not in text.lower():
                text = f"{text}\n\n{note}"
        return text

    def _review_status_label(
        self,
        *,
        autopost_enabled: bool,
        primary_delivery: DeliveryResult | None,
    ) -> str:
        if not autopost_enabled:
            return "draft"
        if primary_delivery is None:
            return "draft"
        if primary_delivery.sent:
            return "live"
        if primary_delivery.batched:
            return "batched"
        if primary_delivery.rate_limited:
            return "rate_limited"
        return "draft"

    def _resolve_generated_post_status(
        self,
        *,
        post: GeneratedPost,
        autopost_enabled: bool,
        primary_delivery: DeliveryResult | None,
        review_delivery: DeliveryResult | None,
    ) -> str:
        if post.channel_kind == "lab":
            return self._delivery_status(primary_delivery)

        if post.bundle_in_lab_review and not autopost_enabled:
            return "bundle_pending"

        if not autopost_enabled:
            return self._draft_status(review_delivery)

        if primary_delivery is not None and primary_delivery.sent:
            return "sent"
        if primary_delivery is not None and primary_delivery.batched:
            return "batched"
        if primary_delivery is not None and primary_delivery.rate_limited:
            return "rate_limited"
        if review_delivery is not None:
            return self._draft_status(review_delivery)
        return "generated"

    def _draft_status(self, delivery: DeliveryResult | None) -> str:
        if delivery is None:
            return "generated"
        if delivery.sent:
            return "draft_sent"
        if delivery.batched:
            return "draft_batched"
        if delivery.rate_limited:
            return "rate_limited"
        return "generated"

    def _delivery_status(self, delivery: DeliveryResult | None) -> str:
        if delivery is None:
            return "generated"
        if delivery.sent:
            return "sent"
        if delivery.batched:
            return "batched"
        if delivery.rate_limited:
            return "rate_limited"
        return "generated"

    def _delivery_snapshot(self, delivery: DeliveryResult | None) -> dict[str, object] | None:
        if delivery is None:
            return None
        return {
            "destination": delivery.destination,
            "message_type": delivery.message_type,
            "sent": delivery.sent,
            "rate_limited": delivery.rate_limited,
            "batched": delivery.batched,
            "telegram_message_id": delivery.telegram_message_id,
            "metadata": delivery.metadata,
        }

    def _was_delivered(
        self,
        primary_delivery: DeliveryResult | None,
        review_delivery: DeliveryResult | None,
    ) -> bool:
        for delivery in (primary_delivery, review_delivery):
            if delivery is not None and (delivery.sent or delivery.batched):
                return True
        return False

    def _ensure_lab_batch_task_locked(self) -> None:
        if self._lab_batch_task is None or self._lab_batch_task.done():
            self._lab_batch_task = asyncio.create_task(
                self._lab_batch_loop(),
                name="lab-batch-loop",
            )

    def _build_symbol_reply_markup(
        self,
        symbol: str,
        *,
        include_binance_link: bool,
        include_tradingview_link: bool = False,
        language_code: str = "en",
        external_link_label: str | None = None,
        external_link_url: str | None = None,
    ) -> dict[str, object]:
        display_symbol = normalize_symbol(symbol)
        symbol_link_actions_enabled = bool(external_link_url) or is_supported_futures_symbol(display_symbol)
        copy_row: list[dict[str, object]] = [
            {
                "text": f"Copy {display_symbol}",
                "copy_text": {"text": display_symbol},
            }
        ]
        rows: list[list[dict[str, object]]] = []
        if include_binance_link and symbol_link_actions_enabled:
            link_url = external_link_url or build_futures_link(self.settings.binance_futures_web_base_url, display_symbol)
            link_label = external_link_label or ui_text(language_code, "open_binance")
            app_link_url = (
                build_futures_app_link(self.settings.binance_futures_app_base_url, display_symbol)
                if not external_link_url
                else None
            )
            tradingview_link_url = (
                build_tradingview_futures_link(display_symbol)
                if include_tradingview_link and not external_link_url
                else None
            )
            if app_link_url:
                rows.append(copy_row)
                link_row: list[dict[str, object]] = []
                if tradingview_link_url:
                    link_row.append({"text": ui_text(language_code, "open_tradingview"), "url": tradingview_link_url})
                link_row.append(
                    {
                        "text": ui_text(language_code, "open_binance_app"),
                        "url": app_link_url,
                    }
                )
                rows.append(link_row)
                rows.append([{"text": link_label, "url": link_url}])
                return {"inline_keyboard": rows}
            if tradingview_link_url:
                copy_row.append(
                    {
                        "text": ui_text(language_code, "open_tradingview"),
                        "url": tradingview_link_url,
                    }
                )
            copy_row.append(
                {
                    "text": link_label,
                    "url": link_url,
                }
            )
        if symbol_link_actions_enabled:
            rows.append(copy_row)
        return {"inline_keyboard": rows}

    def _build_generated_post_reply_markup(self, post: GeneratedPost) -> dict[str, object] | None:
        if post.channel_kind not in {"public", "pro", "results"}:
            return None
        if not self.settings.interactive_enabled_for(post.channel_kind):
            return None
        if not post.source_symbol:
            return None
        timeframe = str(post.metadata.get("timeframe") or self.settings.scan_timeframe)
        return self._build_interactive_reply_markup(
            symbol=post.source_symbol,
            timeframe=timeframe,
            destination_kind=post.channel_kind,
        )

    def _build_twitter_draft_reply_markup(self, draft: TwitterDraft) -> dict[str, object] | None:
        if not self.settings.interactive_enabled_for("twitter_drafts"):
            return None
        if draft.chart_path is None or not draft.source_symbol:
            return None
        selected_timeframe = str(
            draft.metadata.get("interactive_timeframe")
            or draft.metadata.get("timeframe")
            or self.settings.scan_timeframe
        )
        return self._build_interactive_reply_markup(
            symbol=draft.source_symbol,
            timeframe=selected_timeframe,
            destination_kind="twitter_drafts",
        )

    def _build_interactive_reply_markup(
        self,
        *,
        symbol: str,
        timeframe: str,
        destination_kind: str,
        language_code: str = "en",
        external_link_label: str | None = None,
        external_link_url: str | None = None,
        include_ai_analysis: bool | None = None,
        include_risk_management: bool | None = None,
        include_signal_reason: bool | None = None,
    ) -> dict[str, object]:
        premium_enabled = self.settings.premium_features_enabled_for(destination_kind)
        return build_alert_inline_keyboard(
            symbol=symbol,
            selected_timeframe=timeframe,
            supported_timeframes=self.settings.interactive_timeframes_for(destination_kind),
            futures_base_url=self.settings.binance_futures_web_base_url,
            futures_app_base_url=self.settings.binance_futures_app_base_url,
            language_code=language_code,
            external_link_label=external_link_label,
            external_link_url=external_link_url,
            include_ai_analysis=(destination_kind != "twitter_drafts") if include_ai_analysis is None else include_ai_analysis,
            include_risk_management=(premium_enabled or destination_kind == "classic") if include_risk_management is None else include_risk_management,
            include_signal_reason=(premium_enabled or destination_kind == "classic") if include_signal_reason is None else include_signal_reason,
            include_compare=destination_kind != "twitter_drafts",
            include_copy_symbol=True,
            include_binance_app_link=True,
            include_tradingview_link=destination_kind in {"private", "pro"},
            include_home_button=destination_kind in {"private", "pro"},
        )

    async def _lab_batch_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.lab_batch_flush_seconds)
                await self._flush_lab_batch("internal_summary")
                await self._flush_lab_batch("review_copy")
                async with self._lab_batch_lock:
                    if not any(self._lab_batch_buffers.values()):
                        self._lab_batch_task = None
                        return
        except asyncio.CancelledError:
            async with self._lab_batch_lock:
                self._lab_batch_task = None
            raise
