from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from src.ai.generators import DraftGenerator
from src.bot.inline_keyboards import build_detail_card_keyboard_with_action
from src.bot.interactive_alerts import InteractiveAlertService
from src.bot.routing import MessageRouter
from src.bot.telegram_client import TelegramClient
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost
from src.core.utils import utc_now
from src.localization import normalize_language, ui_text
from src.market.binance_client import BinanceClient
from src.market.indicators import enrich_klines
from src.storage.models import PrivateBotUserRecord
from src.storage.repository import Repository
from src.userbot.formatters import (
    format_classic_access_message,
    format_classic_first_start_message,
    format_classic_help_message,
    format_classic_start_message,
    format_classic_status_message,
    format_empty_signals_message,
    format_premium_upsell_message,
)
from src.userbot.keyboards import (
    build_access_inline_keyboard,
    build_classic_main_menu_keyboard,
    build_collapsed_menu_keyboard,
    build_guided_start_keyboard,
    build_help_inline_keyboard,
    build_onboarding_inline_keyboard,
)
from src.userbot.premium_text import premium_text
from src.userbot.service import PrivateBotService

LOGGER = logging.getLogger(__name__)


class ClassicBotService(PrivateBotService):
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        telegram_client: TelegramClient,
        router: MessageRouter,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        interactive_alert_service: InteractiveAlertService,
        draft_generator: DraftGenerator,
        onboarding_service=None,
    ) -> None:
        super().__init__(
            settings,
            repository,
            telegram_client,
            router,
            binance_client,
            chart_renderer,
            interactive_alert_service,
            bot_kind="classic",
            destination_kind="classic",
            content_kind="classic_basic",
            onboarding_service=onboarding_service,
        )
        self.draft_generator = draft_generator
        self.scheduled_post_scheduler = None

    def _signal_list_limit(self, *, strong_only: bool) -> int:
        del strong_only
        return min(self.settings.classic_bot_recent_signals_limit, 3)

    async def render_delivery_chart(self, signal: AlertSignal) -> Path:
        frame = await self.binance_client.get_klines(
            signal.symbol,
            signal.timeframe,
            self.settings.klines_limit,
            end_time=signal.candle_close_time,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        return await self.chart_renderer.render_alert_chart(enriched, signal)

    async def handle_message(self, message: dict[str, object]) -> None:
        if not self.settings.classic_bot_is_configured:
            return
        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("type") != "private":
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
        if user_id in self._custom_setup_sessions and self._custom_setup_navigation_requested(normalized, command_token):
            self._clear_custom_setup_session(user_id)

        if command_token == "/start":
            if settings.onboarding_completed_at is None:
                if onboarding_state is not None and onboarding_state.completed_at is None:
                    await self._send_onboarding_step(
                        user_id,
                        step=onboarding_state.step,
                        draft=onboarding_state.draft,
                        preferred_language=preferred_language,
                    )
                    return
                await self._send_language_picker(
                    user_id,
                    preferred_language=preferred_language,
                    first_time=True,
                )
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
        if command_token == "/help" or normalized == "help" or self._matches_ui_label(normalized, "menu_help"):
            await self._send_help(user_id)
            return
        if self._matches_premium_label(normalized, "menu_signals") or self._matches_ui_label(normalized, "classic_menu_signals"):
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
        if command_token == "/setup" or any(
            self._matches_ui_label(normalized, key)
            for key in ("menu_signal_setup", "classic_menu_setup")
        ):
            await self._send_signal_setup(user_record)
            return
        if command_token == "/watchlist" or self._matches_ui_label(normalized, "menu_watchlist"):
            await self._send_watchlist(user_record)
            return
        if command_token in {"/xau", "/goldnow", "/goldcard"} or self._matches_ui_label(normalized, "menu_gold_snapshot"):
            await self._send_gold_snapshot(user_record)
            return
        if command_token == "/analyze":
            if await self._handle_analyze_request(user_record, text):
                return
            await self._send_analyze_symbol_help(user_record)
            return
        if self._matches_ui_label(normalized, "menu_analyze_symbol"):
            await self._send_analyze_symbol_help(user_record)
            return
        if command_token in {"/last", "/signals", "/strong"} or normalized in {
            ui_text("en", "menu_latest_signals").casefold(),
            ui_text("ru", "menu_latest_signals").casefold(),
            ui_text("en", "signals_title_strong").casefold(),
            ui_text("ru", "signals_title_strong").casefold(),
        }:
            await self._send_recent_signals(
                user_record,
                strong_only=command_token == "/strong" or normalized in {
                    ui_text("en", "signals_title_strong").casefold(),
                    ui_text("ru", "signals_title_strong").casefold(),
                },
            )
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
        if command_token == "/ai" or self._matches_ui_label(normalized, "menu_ai_analysis"):
            await self._send_ai_pick(user_record)
            return
        if command_token in {"/pro", "/pay"} or any(
            self._matches_ui_label(normalized, key)
            for key in ("menu_try_pro", "menu_pay_pro", "menu_renew_pro", "classic_menu_premium")
        ):
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
        if await self._try_handle_watchlist_input(user_record, text):
            return
        if await self._try_handle_symbol_lookup(user_record, text):
            return

        await self._send_chat_message(
            chat_id=str(user_id),
            text=ui_text(language, "menu_hint_classic"),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user_id),
        )

    async def deliver_classic_alert(self, signal: AlertSignal, alert_id: int) -> None:
        if not self.settings.classic_bot_is_configured or not self.settings.classic_bot_signal_delivery_enabled:
            LOGGER.info("Skipping CLASSIC live for %s: classic bot delivery disabled", signal.symbol)
            return

        decision = self.draft_generator._evaluate_public_best_setup(signal)
        if not decision.eligible:
            LOGGER.info("Skipping CLASSIC live for %s: %s", signal.symbol, decision.reason)
            return

        recipients = await self.repository.list_private_signal_recipients(bot_kind=self.bot_kind)
        if not recipients:
            LOGGER.info("Skipping CLASSIC live for %s: no opted-in recipients", signal.symbol)
            return

        sent_count = 0
        scheduled_count = 0
        queued_count = 0
        duplicate_skips = 0
        filter_skips = 0
        watchlist_cache: dict[int, set[str]] = {}
        now = utc_now()
        owned_chart_path: Path | None = None
        try:
            if self.settings.classic_bot_signal_delay_seconds <= 0:
                owned_chart_path = await self.render_delivery_chart(signal)
                signal.chart_path = owned_chart_path
            for user, settings in recipients:
                effective_settings = settings or await self._ensure_user_settings(user.telegram_user_id)
                watchlist_symbols = await self._watchlist_set(user.telegram_user_id, cache=watchlist_cache)
                favorite_symbols = set(await self._global_favorite_symbols(user.telegram_user_id))
                personalized_signal = self._apply_user_preferences_to_signal(signal, effective_settings)
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
                            "favorite_hit": self._watchlist_hit(personalized_signal.symbol, favorite_symbols),
                        },
                    )
                    queued_count += 1
                    continue
                if self.settings.classic_bot_signal_delay_seconds > 0:
                    due_at = utc_now() + timedelta(seconds=self.settings.classic_bot_signal_delay_seconds)
                    await self.repository.create_scheduled_generated_post(
                        post=GeneratedPost(
                            channel_kind="classic",
                            destination=str(user.telegram_user_id),
                            content_type="classic_delayed_alert",
                            generated_text="",
                            status="scheduled",
                            source_symbol=signal.symbol,
                            related_alert_id=alert_id,
                            metadata={
                                "bot_kind": self.bot_kind,
                                "content_kind": self.content_kind,
                                "scheduled_for_user_id": user.telegram_user_id,
                            },
                        ),
                        due_at=due_at,
                    )
                    scheduled_count += 1
                    continue
                delivery = await self.router.send_raw_alert_to_chat(
                    personalized_signal,
                    chat_id=str(user.telegram_user_id),
                    destination_kind=self.destination_kind,
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
                        "symbol": personalized_signal.symbol,
                        "score": personalized_signal.score,
                        "watchlist_hit": watchlist_hit,
                        "delivery_mode": effective_settings.delivery_mode,
                    },
                )
                if delivery.sent:
                    sent_count += 1
        finally:
            self.chart_renderer.cleanup(owned_chart_path)

        LOGGER.info(
            "CLASSIC live delivery for %s: eligible (%s), recipients=%s, sent=%s, scheduled=%s, queued=%s, skipped_by_user_filters=%s, skipped_duplicates=%s",
            signal.symbol,
            decision.reason,
            len(recipients),
            sent_count,
            scheduled_count,
            queued_count,
            filter_skips,
            duplicate_skips,
        )
        if scheduled_count and self.scheduled_post_scheduler is not None:
            self.scheduled_post_scheduler.notify()

    async def deliver_classic_followup(
        self,
        signal: AlertSignal,
        result: FollowUpResult,
        *,
        preferred_chart_path: Path | None = None,
    ) -> None:
        if not self.settings.classic_bot_is_configured or not self.settings.classic_bot_signal_delivery_enabled:
            LOGGER.info("Skipping CLASSIC follow-up for %s: classic bot delivery disabled", result.symbol)
            return

        decision = self.draft_generator._evaluate_results_followup(signal, result)
        if not decision.eligible:
            LOGGER.info("Skipping CLASSIC follow-up for %s: %s", result.symbol, decision.reason)
            return

        stage_decision = await self.draft_generator._evaluate_results_stage_policy(result)
        if not stage_decision.eligible:
            LOGGER.info(
                "Skipping CLASSIC follow-up for %s stage=%s: %s",
                result.symbol,
                result.stage,
                stage_decision.reason,
            )
            return

        recipients = await self.repository.list_private_signal_recipients(bot_kind=self.bot_kind)
        if not recipients:
            LOGGER.info("Skipping CLASSIC follow-up for %s: no opted-in recipients", result.symbol)
            return

        original_chart_path = result.chart_path
        if preferred_chart_path is not None:
            result.chart_path = preferred_chart_path

        sent_count = 0
        queued_count = 0
        duplicate_skips = 0
        followup_toggle_skips = 0
        origin_missing_skips = 0
        stage_message_kind = f"followup:{(result.stage or '2h').lower()}"
        now = utc_now()
        watchlist_cache: dict[int, set[str]] = {}
        for user, settings in recipients:
            if settings is not None and not settings.followup_delivery_enabled:
                followup_toggle_skips += 1
                continue
            if not await self.repository.delivered_signal_exists(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=result.alert_id,
                content_kind=self.content_kind,
                message_kind="alert",
            ):
                origin_missing_skips += 1
                continue
            if await self.repository.delivered_signal_exists(
                telegram_user_id=user.telegram_user_id,
                bot_kind=self.bot_kind,
                alert_id=result.alert_id,
                content_kind=self.content_kind,
                message_kind=stage_message_kind,
            ):
                duplicate_skips += 1
                continue
            effective_settings = settings or await self._ensure_user_settings(user.telegram_user_id)
            watchlist_symbols = await self._watchlist_set(user.telegram_user_id, cache=watchlist_cache)
            favorite_symbols = set(await self._global_favorite_symbols(user.telegram_user_id))
            queue_reason = await self._followup_delivery_queue_reason(
                result,
                effective_settings,
                watchlist_symbols=watchlist_symbols,
                favorite_symbols=favorite_symbols,
                telegram_user_id=user.telegram_user_id,
                now=now,
            )
            if queue_reason is not None:
                await self._record_private_candidate(
                    user=user,
                    alert_id=result.alert_id,
                    message_kind=f"queued:{stage_message_kind}",
                    symbol=result.symbol,
                    score=result.score,
                    queue_reason=queue_reason,
                    watchlist_hit=self._watchlist_hit(result.symbol, watchlist_symbols),
                    metadata={
                        "stage": result.stage,
                        "delivery_mode": effective_settings.delivery_mode,
                        "thesis_result_state": result.thesis_result_state,
                        "move_pct": result.move_pct,
                        "favorite_hit": self._watchlist_hit(result.symbol, favorite_symbols),
                    },
                )
                queued_count += 1
                continue
            localized_result = self._localize_followup_result(result, effective_settings)
            delivery = await self.router.send_followup_to_chat(
                localized_result,
                chat_id=str(user.telegram_user_id),
                destination_kind=self.destination_kind,
            )
            await self._register_private_delivery(
                user=user,
                delivery=delivery,
                signal=self._apply_user_preferences_to_signal(signal, effective_settings),
                alert_id=result.alert_id,
                message_kind="followup",
                record_message_kind=stage_message_kind,
                content_kind=self.content_kind,
                record_metadata={
                    "symbol": result.symbol,
                    "score": result.score,
                    "watchlist_hit": self._watchlist_hit(result.symbol, watchlist_symbols),
                    "delivery_mode": effective_settings.delivery_mode,
                    "stage": result.stage,
                    "thesis_result_state": result.thesis_result_state,
                    "favorable_move_pct": result.favorable_move_pct,
                    "adverse_move_pct": result.adverse_move_pct,
                    "move_pct": result.move_pct,
                },
            )
            if delivery.sent:
                sent_count += 1

        LOGGER.info(
            "CLASSIC follow-up delivery for %s: eligible (%s; %s), recipients=%s, sent=%s, queued=%s, skipped_missing_origin=%s, skipped_duplicates=%s",
            result.symbol,
            decision.reason,
            stage_decision.reason,
            len(recipients),
            sent_count,
            queued_count,
            origin_missing_skips,
            duplicate_skips,
        )
        if followup_toggle_skips:
            LOGGER.info(
                "CLASSIC follow-up delivery for %s skipped %s recipients because follow-ups were disabled",
                result.symbol,
                followup_toggle_skips,
            )
        result.chart_path = original_chart_path

    async def _send_start(self, user_id: int, payload: str | None, *, first_time: bool) -> None:
        del payload
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        text = (
            format_classic_first_start_message(
                premium_link=self.settings.resolved_private_bot_share_link or None,
                channels_folder_link=self.settings.channels_folder_link.strip() or None,
                trial_days=self.settings.private_bot_trial_days,
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                language_code=language,
            )
            if first_time
            else format_classic_start_message(
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                language_code=language,
            )
        )
        await self._send_chat_message(
            chat_id=str(user_id),
            text=text,
            parse_mode="HTML",
            reply_markup=build_guided_start_keyboard(
                language_code=language,
                bot_kind="classic",
            ),
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
        await self._send_or_edit_text(
            chat_id=chat_id or str(user_id),
            text=format_classic_help_message(
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                language_code=language,
            ),
            reply_markup=build_help_inline_keyboard(
                language_code=language,
                back_callback_data="ux:menu",
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

    async def _send_access(
        self,
        user: PrivateBotUserRecord,
        *,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
        access_state = await self._effective_access_state_for_user(user)
        await self._send_or_edit_text(
            chat_id=chat_id or str(user.telegram_user_id),
            text=format_classic_access_message(
                access_label=await self._access_label_for_user(user, language_code=language),
                access_state_line=self._access_state_line(access_state, language_code=language),
                signal_profile=setup_state.profile_label,
                min_score_label=self._score_label(setup_state),
                min_quote_volume_label=self._volume_label(setup_state.min_quote_volume),
                rsi_window_label=self._rsi_window_label(setup_state),
                direction_label=setup_state.direction_label,
                watchlist_summary=await self._watchlist_summary(
                    user.telegram_user_id,
                    watchlist_only=setup_state.watchlist_only,
                    language_code=language,
                ),
                direct_delivery_enabled=settings.direct_signal_delivery_enabled,
                followup_delivery_enabled=settings.followup_delivery_enabled,
                trial_days=self.settings.private_bot_trial_days,
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                language_code=language,
            ),
            reply_markup=build_access_inline_keyboard(
                can_renew=True,
                language_code=language,
                renew_label=ui_text(language, "open_pro"),
                back_callback_data="ux:settingshub",
            ),
            edit_message_id=edit_message_id,
        )
        await self._record_funnel_event(
            "my_access_opened",
            user.telegram_user_id,
            context="access",
            language_code=language,
            screen="my_access",
        )

    async def _send_status(self, user: PrivateBotUserRecord) -> None:
        now = utc_now()
        start = now - timedelta(hours=24)
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        setup_state = self._resolve_signal_setup_state(settings, language_code=language)
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
        LOGGER.info(
            "CLASSIC status requested user=%s alerts_delivered_24h=%s followups_delivered_24h=%s last_signal=%s source=delivered_signals/%s bot_kind=%s",
            user.telegram_user_id,
            alerts_last_24h,
            followups_last_24h,
            last_signal_label,
            self.content_kind,
            self.bot_kind,
        )
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=format_classic_status_message(
                timeframe=self.settings.scan_timeframe,
                access_state_line=self._access_state_line(access_state, language_code=language),
                signal_profile=setup_state.profile_label,
                watchlist_summary=await self._watchlist_summary(
                    user.telegram_user_id,
                    watchlist_only=setup_state.watchlist_only,
                    language_code=language,
                ),
                alerts_delivery_enabled=settings.direct_signal_delivery_enabled,
                followups_delivery_enabled=settings.followup_delivery_enabled,
                access_label=access_label,
                alerts_last_24h=alerts_last_24h,
                followups_last_24h=followups_last_24h,
                last_signal_label=last_signal_label,
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
                language_code=language,
            ),
            parse_mode="HTML",
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _send_ai_pick(self, user: PrivateBotUserRecord) -> None:
        LOGGER.info("CLASSIC premium-gated feature requested user=%s feature=AI Analysis", user.telegram_user_id)
        settings = await self._ensure_user_settings(user.telegram_user_id)
        await self._send_premium_upsell(user.telegram_user_id, feature_name=ui_text(self._language_code(settings), "button_ai_analysis"))

    async def _send_pro_link(self, user_id: int) -> None:
        settings = await self._ensure_user_settings(user_id)
        await self._send_premium_upsell(user_id, feature_name=ui_text(self._language_code(settings), "open_pro"))

    async def _send_recent_signals(
        self,
        user: PrivateBotUserRecord,
        *,
        strong_only: bool = False,
        chat_id: str | None = None,
        edit_message_id: int | None = None,
    ) -> None:
        await super()._send_recent_signals(
            user,
            strong_only=strong_only,
            chat_id=chat_id,
            edit_message_id=edit_message_id,
        )

    async def _toggle_direct_delivery(self, user: PrivateBotUserRecord, *, enable: bool) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        if not self.settings.classic_bot_signal_delivery_enabled:
            await self._send_chat_message(
                chat_id=str(user.telegram_user_id),
                text=ui_text(language, "classic_alerts_disabled_global"),
                parse_mode=None,
                reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
            )
            return
        await self.repository.upsert_user_settings(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=enable,
            followup_delivery_enabled=settings.followup_delivery_enabled,
            gold_alerts_enabled=settings.gold_alerts_enabled,
            signal_profile=settings.signal_profile,
            preferred_min_score=settings.preferred_min_score,
            min_quote_volume=settings.min_quote_volume,
            rsi_oversold=settings.rsi_oversold,
            rsi_overbought=settings.rsi_overbought,
            direction_filter=settings.direction_filter,
            watchlist_only=settings.watchlist_only,
            menu_collapsed=settings.menu_collapsed,
        )
        self._store_cached_settings(replace(settings, direct_signal_delivery_enabled=enable))
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(
                language,
                "classic_alerts_state_changed",
                state=ui_text(language, "status_enabled" if enable else "status_disabled"),
                delay_minutes=self.settings.classic_bot_signal_delay_minutes,
            ),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _toggle_followup_delivery(self, user: PrivateBotUserRecord, *, enable: bool) -> None:
        settings = await self._ensure_user_settings(user.telegram_user_id)
        language = self._language_code(settings)
        await self.repository.upsert_user_settings(
            telegram_user_id=user.telegram_user_id,
            bot_kind=self.bot_kind,
            direct_signal_delivery_enabled=settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=enable,
            gold_alerts_enabled=settings.gold_alerts_enabled,
            signal_profile=settings.signal_profile,
            preferred_min_score=settings.preferred_min_score,
            min_quote_volume=settings.min_quote_volume,
            rsi_oversold=settings.rsi_oversold,
            rsi_overbought=settings.rsi_overbought,
            direction_filter=settings.direction_filter,
            watchlist_only=settings.watchlist_only,
            menu_collapsed=settings.menu_collapsed,
        )
        self._store_cached_settings(replace(settings, followup_delivery_enabled=enable))
        await self._send_chat_message(
            chat_id=str(user.telegram_user_id),
            text=ui_text(
                language,
                "classic_followups_state_changed",
                state=ui_text(language, "status_enabled" if enable else "status_disabled"),
            ),
            parse_mode=None,
            reply_markup=await self._main_menu_keyboard_for_user(user.telegram_user_id),
        )

    async def _main_menu_keyboard_for_user(self, telegram_user_id: int) -> dict[str, object]:
        settings = await self._ensure_user_settings(telegram_user_id)
        language = self._language_code(settings)
        if settings.menu_collapsed:
            return build_collapsed_menu_keyboard(language_code=language)
        return build_classic_main_menu_keyboard(
            direct_delivery_enabled=settings.direct_signal_delivery_enabled,
            followup_delivery_enabled=settings.followup_delivery_enabled,
            include_community_button=bool(self._community_target()),
            include_gold_button=self.settings.gold_alerts_enabled,
            language_code=language,
        )

    def _build_classic_onboarding_keyboard(self, *, language_code: str = "en") -> dict[str, object]:
        return build_onboarding_inline_keyboard(
            public_channel=self.settings.public_channel,
            results_channel=self.settings.results_channel,
            language_code=language_code,
            community_target=self._community_target() or None,
            bot_target=self.settings.resolved_private_bot_share_link or None,
            bot_label=ui_text(
                language_code,
                "menu_try_pro" if self.settings.resolved_private_bot_share_link else "open_pro",
            ),
            channels_folder_target=self.settings.channels_folder_link.strip() or None,
        )

    async def _send_premium_upsell(self, user_id: int, *, feature_name: str) -> None:
        target = self.settings.resolved_private_bot_share_link
        settings = await self._ensure_user_settings(user_id)
        language = self._language_code(settings)
        await self._send_chat_message(
            chat_id=str(user_id),
            text=format_premium_upsell_message(
                feature_name=feature_name,
                trial_days=self.settings.private_bot_trial_days,
                language_code=language,
            ),
            parse_mode="HTML",
            reply_markup=build_detail_card_keyboard_with_action(
                include_delete=False,
                language_code=language,
                action_label=ui_text(language, "menu_try_pro") if target else None,
                action_url=target or None,
            ),
        )
        LOGGER.info("Classic premium upsell shown user=%s feature=%s", user_id, feature_name)

