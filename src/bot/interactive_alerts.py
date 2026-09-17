from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from src.analysis.precompute import PreparedFeatureService
from src.bot.callbacks import AlertCallbackAction, parse_alert_callback_data
from src.bot.formatters import (
    _direction_label,
    format_alert_message,
    format_followup_message,
    format_interactive_analysis_message,
    format_interactive_compare_message,
    format_interactive_rationale_message,
    format_interactive_risk_message,
)
from src.bot.inline_keyboards import build_alert_inline_keyboard, build_detail_card_keyboard_with_action
from src.bot.telegram_client import TelegramClient
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.followup_logic import evaluate_thesis_result, summarize_followup
from src.core.models import AlertSignal, FollowUpResult
from src.core.utils import (
    calc_pct_change,
    format_percent,
    format_price,
    format_rsi,
    format_volume,
    normalize_symbol,
    utc_now,
)
from src.localization import is_russian, normalize_language, ui_text
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats
from src.storage.models import AlertRecord, FollowUpResultRecord, InteractiveAlertState
from src.storage.repository import Repository
from src.userbot.experience import BUILTIN_WATCHLIST_THEMES
from src.userbot.premium_text import premium_text

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.userbot.service import PrivateBotService


@dataclass(frozen=True, slots=True)
class InteractiveMarketSnapshot:
    signal: AlertSignal
    frame: pd.DataFrame


@dataclass(slots=True)
class LoadingIndicatorHandle:
    chat_id: str
    message_id: int | None
    animation_task: asyncio.Task[None] | None
    title: str
    stage_text: str
    started_at: float
    language_code: str = "en"
    current_progress: float = 0.04
    target_progress: float = 0.10
    completed: bool = False


class InteractiveAlertService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        telegram_client: TelegramClient,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        prepared_feature_service: PreparedFeatureService,
        *,
        state_scope: str = "",
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.telegram_client = telegram_client
        self.binance_client = binance_client
        self.chart_renderer = chart_renderer
        self.prepared_feature_service = prepared_feature_service
        self.state_scope = state_scope.strip()
        self._timeframe_switch_locks: dict[tuple[str, int], str] = {}

    async def register_alert_message(
        self,
        *,
        destination_kind: str,
        chat_id: str,
        message_id: int | None,
        signal: AlertSignal,
        alert_id: int | None,
        is_preview: bool,
        message_kind: str = "alert",
    ) -> None:
        if message_id is None or not self.settings.interactive_enabled_for(destination_kind):
            return
        scoped_chat_id = self._scoped_chat_id(chat_id)
        await self.repository.upsert_interactive_alert_state(
            chat_id=scoped_chat_id,
            message_id=message_id,
            alert_id=alert_id,
            destination_kind=destination_kind,
            symbol=normalize_symbol(signal.symbol),
            original_timeframe=signal.timeframe,
            displayed_timeframe=signal.timeframe,
            direction=signal.direction,
            is_preview=is_preview,
            metadata={
                "message_kind": message_kind,
                "telegram_chat_id": str(chat_id),
                "last_price": signal.price,
                "last_rsi": signal.rsi,
                "score": signal.score,
                "alert_rsi": signal.metadata.get("alert_rsi", signal.rsi),
                "alert_score": signal.metadata.get("alert_score", signal.score),
                "live_price": signal.metadata.get("live_price"),
                "live_rsi": signal.metadata.get("live_rsi"),
                "setup_direction": signal.metadata.get("setup_direction", signal.direction),
                "followup_stage": signal.metadata.get("followup_stage") or signal.metadata.get("latest_followup_stage"),
                "marker_price": signal.metadata.get("marker_price", signal.price),
                "marker_candle_open_time": self._iso_or_none(
                    signal.metadata.get("marker_candle_open_time") or signal.candle_open_time
                ),
                "marker_candle_close_time": self._iso_or_none(
                    signal.metadata.get("marker_candle_close_time") or signal.candle_close_time
                ),
                "origin_timeframe": signal.metadata.get("origin_timeframe", signal.timeframe),
                "language_code": normalize_language(str(signal.metadata.get("language_code") or "en")),
                "strategy_key": signal.metadata.get("strategy_key"),
                **self._interactive_state_fields(signal.metadata),
            },
        )

    def _interactive_state_fields(self, metadata: dict[str, object] | None) -> dict[str, object]:
        if not metadata:
            return {}
        persisted: dict[str, object] = {}
        for key in (
            "asset_class",
            "external_link_label",
            "external_link_url",
            "interactive_ai_enabled",
            "interactive_risk_enabled",
            "interactive_reason_enabled",
            "display_mode",
            "text_layout",
            "rsi_source",
            "rsi_oversold_threshold",
            "rsi_overbought_threshold",
            "context_text",
            "origin_timeframe",
            "setup_direction",
            "strategy_key",
            "alert_rsi",
            "alert_score",
            "signal_status",
            "result_type",
            "why_received_text",
            "invalidation_price",
            "tp_price_primary",
            "tp_price_secondary",
            "entry_zone_low",
            "entry_zone_high",
            "benchmark_win_percent",
            "expiry_at",
            "market_regime_tag",
            "asset_cluster_tag",
            "liquidity_tag",
            "confidence_score",
            "setup_quality",
            "explanation_short",
            "ekek_impulse_summary",
            "historical_resistance_variant",
            "historical_resistance_available",
            "historical_resistance_zone_low",
            "historical_resistance_zone_high",
            "historical_resistance_zone_price",
            "historical_resistance_distance_pct",
            "historical_resistance_touch_count",
            "historical_resistance_strong_rejections",
            "historical_resistance_avg_rejection_pct",
            "historical_resistance_avg_impulse_pct",
            "historical_resistance_quality",
            "historical_resistance_confidence",
            "historical_resistance_timeframes",
            "historical_resistance_highest_peak_price",
            "historical_resistance_highest_peak_timeframe",
            "historical_resistance_highest_peak_distance_pct",
        ):
            if key in metadata:
                persisted[key] = metadata[key]
        return persisted

    async def build_alert_snapshot(self, symbol: str, timeframe: str) -> InteractiveMarketSnapshot:
        return await self._build_snapshot(symbol, timeframe)

    async def generate_analysis_text(
        self,
        *,
        symbol: str,
        timeframe: str,
        alert_id: int | None,
        destination_kind: str,
        language: str = "en",
        progress_callback=None,
    ) -> str:
        feature = await self.prepared_feature_service.get_or_prepare_feature(
            symbol=normalize_symbol(symbol),
            timeframe=timeframe,
            alert_id=alert_id,
            content_type="analysis",
            language=language,
            progress_callback=progress_callback,
        )
        return feature.text_payload

    async def generate_risk_text(
        self,
        *,
        symbol: str,
        timeframe: str,
        alert_id: int | None,
        language: str = "en",
        progress_callback=None,
    ) -> str:
        feature = await self.prepared_feature_service.get_or_prepare_feature(
            symbol=normalize_symbol(symbol),
            timeframe=timeframe,
            alert_id=alert_id,
            content_type="risk",
            language=language,
            progress_callback=progress_callback,
        )
        return feature.text_payload

    async def generate_rationale_text(
        self,
        *,
        symbol: str,
        timeframe: str,
        alert_id: int | None,
        language: str = "en",
        progress_callback=None,
    ) -> str:
        feature = await self.prepared_feature_service.get_or_prepare_feature(
            symbol=normalize_symbol(symbol),
            timeframe=timeframe,
            alert_id=alert_id,
            content_type="rationale",
            language=language,
            progress_callback=progress_callback,
        )
        return feature.text_payload

    async def handle_callback_query(self, callback_query: dict[str, object]) -> None:
        query_id = str(callback_query.get("id") or "")
        from_user = callback_query.get("from")
        request_language = normalize_language(
            str(from_user.get("language_code") or "") if isinstance(from_user, dict) else None
        )
        message = callback_query.get("message")
        if not isinstance(message, dict):
            await self._safe_answer(query_id, text=ui_text(request_language, "interactive_stale"))
            return

        chat = message.get("chat")
        if not isinstance(chat, dict):
            await self._safe_answer(query_id, text=ui_text(request_language, "interactive_stale"))
            return

        chat_id = str(chat.get("id") or "")
        message_id = message.get("message_id")
        if not chat_id or not isinstance(message_id, int):
            await self._safe_answer(query_id, text=ui_text(request_language, "interactive_stale"))
            return
        scoped_chat_id = self._scoped_chat_id(chat_id)

        action = parse_alert_callback_data(callback_data=str(callback_query.get("data") or ""))
        if action is None:
            await self._safe_answer(query_id, text=ui_text(request_language, "unknown_action"))
            return
        if action.kind == "delete_detail":
            await self._handle_delete_detail(
                query_id,
                chat_id=chat_id,
                message_id=message_id,
                language_code=request_language,
            )
            return

        state = await self.repository.get_interactive_alert_state(chat_id=scoped_chat_id, message_id=message_id)
        if state is None:
            state = await self.repository.get_interactive_alert_state_by_message_id(
                message_id=message_id,
                symbol=action.symbol,
                chat_id_prefix=self.state_scope,
            )
            if state is not None and state.chat_id != scoped_chat_id:
                await self.repository.rebind_interactive_alert_message(
                    state_id=state.id,
                    chat_id=scoped_chat_id,
                    message_id=message_id,
                    displayed_timeframe=state.displayed_timeframe,
                    direction=state.direction,
                    metadata=state.metadata,
                )
                state = await self.repository.get_interactive_alert_state(chat_id=scoped_chat_id, message_id=message_id)
        if state is None:
            await self._safe_answer(query_id, text=ui_text(request_language, "interactive_not_interactive"), show_alert=True)
            return
        language = self._state_language(state, fallback=request_language)
        if action.symbol and normalize_symbol(action.symbol) != normalize_symbol(state.symbol):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_state_stale"), show_alert=True)
            return
        if not self.settings.interactive_enabled_for(state.destination_kind):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_disabled"))
            return

        if action.kind == "timeframe":
            await self._handle_timeframe_switch(query_id, state, action)
            return
        if action.kind == "ai":
            await self._handle_ai_analysis(query_id, state)
            return
        if action.kind == "compare":
            await self._handle_signal_compare(query_id, state)
            return
        if action.kind == "risk":
            await self._handle_risk_management(query_id, state)
            return
        if action.kind == "reason":
            await self._handle_signal_reason(query_id, state)
            return

        await self._safe_answer(query_id, text=ui_text(language, "unknown_action"))

    async def _handle_timeframe_switch(
        self,
        query_id: str,
        state: InteractiveAlertState,
        action: AlertCallbackAction,
    ) -> None:
        language = self._state_language(state)
        if state.destination_kind == "private" and not await self._premium_feature_allowed_for_state(state):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_private_inactive"))
            await self._send_premium_upgrade_notice(state, feature_name="Private signal review")
            return
        requested_timeframe = action.timeframe or state.displayed_timeframe
        allowed_timeframes = {
            *self.settings.interactive_timeframes_for(state.destination_kind),
            str(state.original_timeframe or "").strip(),
            str(state.displayed_timeframe or "").strip(),
            str(state.metadata.get("origin_timeframe") or "").strip(),
        }
        allowed_timeframes.discard("")
        if requested_timeframe not in allowed_timeframes:
            await self._safe_answer(query_id, text=ui_text(language, "interactive_unsupported_tf"), show_alert=True)
            return
        lock_key = (self._delivery_chat_id(state), int(state.message_id))
        if lock_key in self._timeframe_switch_locks:
            await self._safe_answer(
                query_id,
                text=ui_text(language, "interactive_updating", timeframe=requested_timeframe),
            )
            return
        self._timeframe_switch_locks[lock_key] = requested_timeframe
        is_refresh = requested_timeframe == state.displayed_timeframe
        await self._safe_answer(
            query_id,
            text=ui_text(
                language,
                "interactive_refreshing" if is_refresh else "interactive_updating",
                timeframe=requested_timeframe,
            ),
        )
        chart_path = None
        try:
            reply_markup = self._build_alert_keyboard(
                symbol=state.symbol,
                selected_timeframe=requested_timeframe,
                destination_kind=state.destination_kind,
                metadata=state.metadata,
                language_code=language,
            )
            message_kind = str(state.metadata.get("message_kind", "alert"))
            if message_kind == "followup" and state.alert_id is not None:
                alert_record = await self._resolve_alert_record_for_state(state)
                followup_result, chart_frame, reference_signal = await self._build_followup_snapshot(
                    alert_record=alert_record,
                    timeframe=requested_timeframe,
                    stage=str(state.metadata.get("followup_stage") or "2h"),
                    language_code=language,
                )
                followup_result.metadata = {
                    **followup_result.metadata,
                    "text_layout": str(state.metadata.get("text_layout") or followup_result.metadata.get("text_layout") or ""),
                    "language_code": language,
                }
                caption = format_followup_message(followup_result, self.settings.timezone, language_code=language)
                chart_path = await self.chart_renderer.render_result_chart(
                    chart_frame,
                    reference_signal,
                    followup_result,
                    label="Follow-up",
                )
                direction = followup_result.direction
                metadata = {
                    **state.metadata,
                    "message_kind": "followup",
                    "followup_stage": followup_result.stage,
                    "last_price": followup_result.current_price,
                    "last_rsi": followup_result.current_rsi,
                    "score": followup_result.score,
                    "live_price": followup_result.current_price,
                    "live_rsi": followup_result.metadata.get("live_rsi"),
                    "language_code": language,
                }
            else:
                alert_record = (
                    await self._resolve_alert_record_for_state(state)
                    if state.alert_id is not None
                    else None
                )
                snapshot = await self._build_snapshot(
                    state.symbol,
                    requested_timeframe,
                    alert_record=alert_record,
                    origin_metadata=state.metadata,
                )
                caption = format_alert_message(
                    snapshot.signal,
                    self.settings.timezone,
                    self.settings.binance_futures_web_base_url,
                    preview=state.is_preview,
                    language_code=language,
                )
                chart_path = await self.chart_renderer.render_alert_chart(
                    snapshot.frame,
                    snapshot.signal,
                    preview=state.is_preview,
                )
                direction = str(snapshot.signal.metadata.get("setup_direction") or snapshot.signal.direction)
                metadata = {
                    **state.metadata,
                    **self._interactive_state_fields(snapshot.signal.metadata),
                    "message_kind": "alert",
                    "last_price": snapshot.signal.price,
                    "last_rsi": snapshot.signal.rsi,
                    "score": snapshot.signal.score,
                    "live_price": snapshot.signal.metadata.get("live_price"),
                    "live_rsi": snapshot.signal.metadata.get("live_rsi"),
                    "language_code": language,
                }

            try:
                await self.telegram_client.edit_message_media(
                    chat_id=self._delivery_chat_id(state),
                    message_id=state.message_id,
                    photo_path=chart_path,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                await self.repository.update_interactive_alert_display(
                    state_id=state.id,
                    displayed_timeframe=requested_timeframe,
                    direction=direction,
                    metadata=metadata,
                )
                LOGGER.info(
                    "Interactive alert %s for %s %s via %s",
                    "refreshed" if is_refresh else "updated",
                    state.symbol,
                    requested_timeframe,
                    "editMessageMedia",
                )
            except Exception as exc:  # pragma: no cover - runtime dependent
                LOGGER.warning(
                    "Interactive media edit failed for message %s (%s %s -> %s, refresh=%s). Replacing message instead. Error: %s",
                    state.message_id,
                    state.symbol,
                    state.displayed_timeframe,
                    requested_timeframe,
                    is_refresh,
                    exc,
                )
                await self._replace_alert_message(
                    state=state,
                    photo_path=chart_path,
                    caption=caption,
                    reply_markup=reply_markup,
                    displayed_timeframe=requested_timeframe,
                    direction=direction,
                    metadata=metadata,
                )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception(
                "Failed to %s interactive alert message %s for %s on %s",
                "refresh" if is_refresh else "update",
                state.message_id,
                state.symbol,
                requested_timeframe,
            )
        finally:
            if self._timeframe_switch_locks.get(lock_key) == requested_timeframe:
                self._timeframe_switch_locks.pop(lock_key, None)
            self.chart_renderer.cleanup(chart_path)

    async def _handle_ai_analysis(self, query_id: str, state: InteractiveAlertState) -> None:
        language = self._state_language(state)
        if not await self._premium_feature_allowed_for_state(state):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_ai_locked"))
            await self._send_premium_upgrade_notice(state, feature_name=ui_text(language, "button_ai_analysis"))
            return
        await self._safe_answer(query_id, text=ui_text(language, "interactive_ai_preparing"))
        loading_handle = await self._start_loading_indicator(
            state=state,
            title=ui_text(language, "interactive_ai_loading_title"),
            subtitle=ui_text(language, "interactive_ai_loading_subtitle"),
            language_code=language,
        )
        LOGGER.info(
            "Interactive button callback handled type=analysis symbol=%s timeframe=%s alert_id=%s",
            state.symbol,
            state.displayed_timeframe,
            state.alert_id,
        )
        try:
            progress_callback = self._build_loading_progress_callback(loading_handle)
            analysis_text = await self.generate_analysis_text(
                symbol=state.symbol,
                timeframe=state.displayed_timeframe,
                alert_id=state.alert_id,
                destination_kind=state.destination_kind,
                language=language,
                progress_callback=progress_callback,
            )
            await self._send_detail_card(
                state=state,
                text=format_interactive_analysis_message(
                    symbol=state.symbol,
                    timeframe=state.displayed_timeframe,
                    analysis_text=analysis_text,
                    language_code=language,
                ),
            )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception(
                "Failed to build interactive AI analysis for %s (%s)",
                state.symbol,
                state.displayed_timeframe,
            )
            await self._send_detail_error(state, ui_text(language, "interactive_ai_failed"))
        finally:
            await self._stop_loading_indicator(loading_handle, final_stage="Анализ готов" if language == "ru" else "Analysis ready")

    async def _handle_signal_compare(self, query_id: str, state: InteractiveAlertState) -> None:
        language = self._state_language(state)
        await self._safe_answer(query_id, text="Готовлю сравнение..." if language == "ru" else "Preparing compare...")
        try:
            current_alert = await self._resolve_alert_record_for_state(state) if state.alert_id is not None else None
            followup_compare = str(state.metadata.get("message_kind", "alert")) == "followup" and current_alert is not None
            compare_current_alert: AlertRecord | None = None
            compare_snapshot: InteractiveMarketSnapshot | None = None
            if followup_compare:
                followup_result, _chart_frame, _reference_signal = await self._build_followup_snapshot(
                    alert_record=current_alert,
                    timeframe=state.displayed_timeframe,
                    stage=str(state.metadata.get("followup_stage") or "2h"),
                    language_code=language,
                )
                compare_snapshot = InteractiveMarketSnapshot(
                    signal=self._build_compare_signal_from_followup(
                        alert_record=current_alert,
                        followup_result=followup_result,
                    ),
                    frame=pd.DataFrame(),
                )
            else:
                compare_snapshot = await self._build_snapshot(
                    state.symbol,
                    state.displayed_timeframe,
                    alert_record=current_alert,
                    origin_metadata=state.metadata,
                )
            reference_alert, reference_label = await self._resolve_compare_reference(
                state=state,
                current_alert=current_alert,
            )
            if reference_alert is None:
                await self._send_detail_card(
                    state=state,
                    text=format_interactive_compare_message(
                        symbol=state.symbol,
                        timeframe=state.displayed_timeframe,
                        reference_label=premium_text(language, "compare_empty"),
                        strength_text=premium_text(language, "compare_empty"),
                        changed_lines=[],
                        passed_lines=[],
                        language_code=language,
                    ),
                )
                return
            strength_text, changed_lines = self._build_compare_changed_lines(
                current_alert=compare_current_alert,
                snapshot=compare_snapshot,
                reference_alert=reference_alert,
                language_code=language,
            )
            passed_lines = await self._build_compare_passed_lines(
                state=state,
                current_alert=compare_current_alert,
                snapshot=compare_snapshot,
                language_code=language,
            )
            await self._send_detail_card(
                state=state,
                text=format_interactive_compare_message(
                    symbol=state.symbol,
                    timeframe=state.displayed_timeframe,
                    reference_label=reference_label,
                    strength_text=strength_text,
                    changed_lines=changed_lines,
                    passed_lines=passed_lines,
                    language_code=language,
                ),
            )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception("Failed to build compare card for %s (%s)", state.symbol, state.displayed_timeframe)
            await self._send_detail_error(state, premium_text(language, "compare_empty"))

    async def _handle_risk_management(self, query_id: str, state: InteractiveAlertState) -> None:
        language = self._state_language(state)
        if not await self._premium_feature_allowed_for_state(state):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_risk_locked"))
            await self._send_premium_upgrade_notice(state, feature_name=ui_text(language, "button_risk_management"))
            return
        await self._safe_answer(query_id, text=ui_text(language, "interactive_risk_preparing"))
        loading_handle = await self._start_loading_indicator(
            state=state,
            title=ui_text(language, "interactive_risk_loading_title"),
            subtitle=ui_text(language, "interactive_risk_loading_subtitle"),
            language_code=language,
        )
        LOGGER.info(
            "Interactive button callback handled type=risk symbol=%s timeframe=%s alert_id=%s",
            state.symbol,
            state.displayed_timeframe,
            state.alert_id,
        )
        try:
            progress_callback = self._build_loading_progress_callback(loading_handle)
            risk_text = await self.generate_risk_text(
                symbol=state.symbol,
                timeframe=state.displayed_timeframe,
                alert_id=state.alert_id,
                language=language,
                progress_callback=progress_callback,
            )
            await self._send_detail_card(
                state=state,
                text=format_interactive_risk_message(
                    symbol=state.symbol,
                    timeframe=state.displayed_timeframe,
                    risk_text=risk_text,
                    language_code=language,
                ),
            )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception(
                "Failed to build risk management card for %s (%s)",
                state.symbol,
                state.displayed_timeframe,
            )
            await self._send_detail_error(state, ui_text(language, "interactive_risk_failed"))
        finally:
            await self._stop_loading_indicator(loading_handle, final_stage="Риск готов" if language == "ru" else "Risk card ready")

    async def _handle_signal_reason(self, query_id: str, state: InteractiveAlertState) -> None:
        language = self._state_language(state)
        if not await self._premium_feature_allowed_for_state(state):
            await self._safe_answer(query_id, text=ui_text(language, "interactive_reason_locked"))
            await self._send_premium_upgrade_notice(state, feature_name=ui_text(language, "button_signal_reason"))
            return
        await self._safe_answer(query_id, text=ui_text(language, "interactive_reason_preparing"))
        loading_handle = await self._start_loading_indicator(
            state=state,
            title=ui_text(language, "interactive_reason_loading_title"),
            subtitle=ui_text(language, "interactive_reason_loading_subtitle"),
            language_code=language,
        )
        LOGGER.info(
            "Interactive button callback handled type=reason symbol=%s timeframe=%s alert_id=%s",
            state.symbol,
            state.displayed_timeframe,
            state.alert_id,
        )
        try:
            progress_callback = self._build_loading_progress_callback(loading_handle)
            rationale_text = await self.generate_rationale_text(
                symbol=state.symbol,
                timeframe=state.displayed_timeframe,
                alert_id=state.alert_id,
                language=language,
                progress_callback=progress_callback,
            )
            await self._send_detail_card(
                state=state,
                text=format_interactive_rationale_message(
                    symbol=state.symbol,
                    timeframe=state.displayed_timeframe,
                    rationale_text=rationale_text,
                    language_code=language,
                ),
            )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception(
                "Failed to build signal rationale card for %s (%s)",
                state.symbol,
                state.displayed_timeframe,
            )
            await self._send_detail_error(state, ui_text(language, "interactive_reason_failed"))
        finally:
            await self._stop_loading_indicator(loading_handle, final_stage="Логика готова" if language == "ru" else "Signal reason ready")

    def _compare_subject_values(
        self,
        *,
        current_alert: AlertRecord | None,
        snapshot: InteractiveMarketSnapshot | None,
    ) -> tuple[int, float, float | None, str, str]:
        if current_alert is not None:
            volume_value = current_alert.metadata.get("quote_volume")
            if not isinstance(volume_value, (int, float)):
                volume_value = current_alert.day_volume
            return (
                int(current_alert.score),
                float(current_alert.alert_rsi),
                float(volume_value) if isinstance(volume_value, (int, float)) else None,
                str(current_alert.timeframe),
                str(current_alert.direction),
            )
        if snapshot is not None:
            signal = snapshot.signal
            volume_value = signal.quote_volume if signal.quote_volume is not None else signal.day_volume
            return (
                int(signal.score),
                float(signal.rsi),
                float(volume_value) if isinstance(volume_value, (int, float)) else None,
                str(signal.timeframe),
                str(signal.direction),
            )
        return (0, 0.0, None, "", "neutral")

    def _compare_bot_kind(self, state: InteractiveAlertState) -> str | None:
        if state.destination_kind == "classic":
            return "classic"
        if state.destination_kind == "private":
            return "premium"
        return None

    def _compare_content_kind(self, state: InteractiveAlertState) -> str | None:
        if state.destination_kind == "classic":
            return "classic_basic"
        if state.destination_kind == "private":
            return "private_pro"
        return None

    async def _resolve_compare_reference(
        self,
        *,
        state: InteractiveAlertState,
        current_alert: AlertRecord | None,
    ) -> tuple[AlertRecord | None, str]:
        language = self._state_language(state)
        if current_alert is not None:
            return current_alert, premium_text(language, "compare_vs_original")
        synthetic_reference = self._reference_alert_from_state_metadata(state)
        if synthetic_reference is not None:
            return synthetic_reference, premium_text(language, "compare_vs_original")
        current_alert_id = current_alert.id if current_alert is not None else None
        candidates = await self.repository.list_recent_alerts_for_symbol(normalize_symbol(state.symbol), limit=8)
        for candidate in candidates:
            if current_alert_id is not None and candidate.id == current_alert_id:
                continue
            return candidate, premium_text(language, "compare_vs_symbol", symbol=normalize_symbol(candidate.symbol))
        chat_id = self._delivery_chat_id(state).strip()
        bot_kind = self._compare_bot_kind(state)
        content_kind = self._compare_content_kind(state)
        if bot_kind is None or content_kind is None or not chat_id.lstrip("-").isdigit():
            return None, premium_text(language, "compare_empty")
        recent_deliveries = await self.repository.list_delivered_signals(
            telegram_user_id=int(chat_id),
            bot_kind=bot_kind,
            content_kind=content_kind,
            message_kind_prefix="alert",
            limit=12,
        )
        for delivery in recent_deliveries:
            if delivery.alert_id is None or delivery.alert_id == current_alert_id:
                continue
            reference_alert = await self.repository.get_alert(delivery.alert_id)
            if reference_alert is not None:
                return reference_alert, premium_text(language, "compare_vs_recent")
        return None, premium_text(language, "compare_empty")

    def _reference_alert_from_state_metadata(self, state: InteractiveAlertState) -> AlertRecord | None:
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        score = metadata.get("score")
        last_rsi = metadata.get("last_rsi")
        marker_price = metadata.get("marker_price", metadata.get("last_price"))
        strategy_key = str(metadata.get("strategy_key") or "rsi").strip().lower() or "rsi"
        if not isinstance(score, (int, float)) or not isinstance(last_rsi, (int, float)) or not isinstance(marker_price, (int, float)):
            return None
        marker_open = self._datetime_from_metadata(metadata.get("marker_candle_open_time")) or state.created_at
        marker_close = self._datetime_from_metadata(metadata.get("marker_candle_close_time")) or state.updated_at or state.created_at
        volume_value = metadata.get("quote_volume")
        day_volume = float(volume_value) if isinstance(volume_value, (int, float)) else None
        return AlertRecord(
            id=0,
            symbol=normalize_symbol(state.symbol),
            direction=str(metadata.get("setup_direction") or state.direction or "neutral"),
            timeframe=str(metadata.get("origin_timeframe") or state.original_timeframe or state.displayed_timeframe),
            candle_open_time=marker_open,
            candle_close_time=marker_close,
            alert_price=float(marker_price),
            alert_rsi=float(last_rsi),
            day_change_pct=None,
            day_volume=day_volume,
            score=int(score),
            alert_sent_at=state.created_at,
            followup_due_at=state.created_at,
            followup_sent_at=None,
            lab_message_id=None,
            metadata={
                "quote_volume": float(volume_value) if isinstance(volume_value, (int, float)) else None,
            },
            strategy_key=strategy_key,
        )

    def _datetime_from_metadata(self, value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            with suppress(ValueError):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return None

    def _build_compare_changed_lines(
        self,
        *,
        current_alert: AlertRecord | None,
        snapshot: InteractiveMarketSnapshot | None,
        reference_alert: AlertRecord,
        language_code: str,
    ) -> tuple[str, list[str]]:
        current_score, current_rsi, current_volume, current_timeframe, current_direction = self._compare_subject_values(
            current_alert=current_alert,
            snapshot=snapshot,
        )
        previous_score = int(reference_alert.score)
        score_delta = current_score - previous_score
        stronger_lines: list[str] = []
        weaker_lines: list[str] = []
        neutral_lines: list[str] = []
        if score_delta >= 5:
            strength_text = "Сетап выглядит сильнее" if language_code == "ru" else "The setup looks stronger now"
            stronger_lines.append(
                premium_text(language_code, "compare_change_score_up", value=str(abs(score_delta)))
            )
        elif score_delta <= -5:
            strength_text = "Сетап стал слабее" if language_code == "ru" else "The setup looks weaker now"
            weaker_lines.append(
                premium_text(language_code, "compare_change_score_down", value=str(abs(score_delta)))
            )
        else:
            strength_text = "Сильных изменений пока нет" if language_code == "ru" else "No major change yet"
            neutral_lines.append(premium_text(language_code, "compare_change_score_flat"))
        neutral_lines.append(
            premium_text(
                language_code,
                "compare_change_rsi",
                previous=format_rsi(reference_alert.alert_rsi),
                current=format_rsi(current_rsi),
            )
        )
        previous_volume = reference_alert.metadata.get("quote_volume")
        if not isinstance(previous_volume, (int, float)):
            previous_volume = reference_alert.day_volume
        if isinstance(current_volume, (int, float)) and isinstance(previous_volume, (int, float)) and previous_volume > 0:
            relative_change = (current_volume - float(previous_volume)) / float(previous_volume)
            if relative_change >= 0.15:
                stronger_lines.append(premium_text(language_code, "compare_change_volume_up"))
            elif relative_change <= -0.15:
                weaker_lines.append(premium_text(language_code, "compare_change_volume_down"))
            else:
                neutral_lines.append(premium_text(language_code, "compare_change_volume_flat"))
        if current_timeframe and current_timeframe != reference_alert.timeframe:
            neutral_lines.append(
                premium_text(
                    language_code,
                    "compare_change_timeframe",
                    previous=reference_alert.timeframe,
                    current=current_timeframe,
                )
            )
        if current_direction and current_direction != reference_alert.direction:
            weaker_lines.append(
                premium_text(
                    language_code,
                    "compare_change_direction",
                    previous=_direction_label(reference_alert.direction, language_code=language_code),
                    current=_direction_label(current_direction, language_code=language_code),
                )
            )
        changed_lines = (
            [("Усилилось: " if language_code == "ru" else "Stronger: ") + line for line in stronger_lines]
            + [("Ослабло: " if language_code == "ru" else "Weaker: ") + line for line in weaker_lines]
            + [("По факту: " if language_code == "ru" else "Context: ") + line for line in neutral_lines]
        )
        return strength_text, changed_lines

    async def _build_compare_passed_lines(
        self,
        *,
        state: InteractiveAlertState,
        current_alert: AlertRecord | None,
        snapshot: InteractiveMarketSnapshot | None,
        language_code: str,
    ) -> list[str]:
        bot_kind = self._compare_bot_kind(state)
        chat_id = self._delivery_chat_id(state).strip()
        if bot_kind is None or not chat_id.lstrip("-").isdigit():
            return []
        user_id = int(chat_id)
        settings = await self.repository.get_user_settings(user_id, bot_kind=bot_kind)
        if settings is None:
            return []
        current_score, _current_rsi, current_volume, _current_timeframe, current_direction = self._compare_subject_values(
            current_alert=current_alert,
            snapshot=snapshot,
        )
        passed_lines: list[str] = []
        min_score = int(settings.preferred_min_score or 0)
        if current_score >= min_score:
            passed_lines.append(
                premium_text(language_code, "compare_filter_score", value=f"{current_score}/{min_score}")
            )
        min_volume = float(settings.min_quote_volume or 0.0)
        if isinstance(current_volume, (int, float)) and current_volume >= min_volume and min_volume > 0:
            passed_lines.append(
                premium_text(
                    language_code,
                    "compare_filter_volume",
                    value=f"{format_volume(float(current_volume))} / {format_volume(min_volume)}",
                )
            )
        if settings.direction_filter == "both" or settings.direction_filter == current_direction.replace("overbought", "short").replace("oversold", "long"):
            direction_label = {
                "both": "Both",
                "long": "Long",
                "short": "Short",
            }.get(settings.direction_filter, settings.direction_filter)
            if language_code == "ru":
                direction_label = {
                    "Both": "Обе стороны",
                    "Long": "Лонг",
                    "Short": "Шорт",
                }.get(direction_label, direction_label)
            passed_lines.append(
                premium_text(language_code, "compare_filter_direction", value=direction_label)
            )
        watchlist_entries = await self.repository.list_user_watchlist(user_id, bot_kind=bot_kind)
        watchlist_symbols = {normalize_symbol(entry.symbol) for entry in watchlist_entries}
        if settings.active_watchlist_theme in BUILTIN_WATCHLIST_THEMES:
            watchlist_symbols.update(BUILTIN_WATCHLIST_THEMES[settings.active_watchlist_theme])
        if normalize_symbol(state.symbol) in watchlist_symbols:
            passed_lines.append(premium_text(language_code, "compare_filter_watchlist"))
        if normalize_symbol(state.symbol) == "XAUUSD" and settings.gold_alerts_enabled:
            passed_lines.append(premium_text(language_code, "compare_filter_gold"))
        return passed_lines

    async def _resolve_alert_record_for_state(self, state: InteractiveAlertState) -> AlertRecord:
        expected_symbol = normalize_symbol(state.symbol)
        alert_record = await self.repository.get_alert(state.alert_id) if state.alert_id is not None else None
        if alert_record is not None and normalize_symbol(alert_record.symbol) == expected_symbol:
            return alert_record

        if state.alert_id is not None:
            LOGGER.warning(
                "Interactive alert binding mismatch state_id=%s expected_symbol=%s alert_id=%s actual_symbol=%s",
                state.id,
                expected_symbol,
                state.alert_id,
                alert_record.symbol if alert_record is not None else "missing",
            )

        origin_timeframe = str(state.metadata.get("origin_timeframe") or state.original_timeframe)
        marker_close_time = self._parse_dt(state.metadata.get("marker_candle_close_time"))
        candidates = await self.repository.list_recent_alerts_for_symbol(expected_symbol, limit=20)
        filtered = [
            candidate
            for candidate in candidates
            if candidate.direction == state.direction and candidate.timeframe == origin_timeframe
        ]
        if not filtered:
            filtered = [candidate for candidate in candidates if candidate.timeframe == origin_timeframe]
        if not filtered:
            filtered = [candidate for candidate in candidates if candidate.direction == state.direction]
        if not filtered:
            raise RuntimeError(
                f"Interactive alert state for {expected_symbol} could not be repaired from stored alerts"
            )

        if marker_close_time is not None:
            repaired = min(
                filtered,
                key=lambda candidate: abs((candidate.candle_close_time - marker_close_time).total_seconds()),
            )
            delta_seconds = abs((repaired.candle_close_time - marker_close_time).total_seconds())
            if delta_seconds > 12 * 3600:
                raise RuntimeError(
                    f"Interactive alert state for {expected_symbol} drifted too far from the original signal marker"
                )
        else:
            repaired = filtered[0]

        if state.alert_id != repaired.id:
            repaired_metadata = {**state.metadata, "origin_timeframe": repaired.timeframe}
            await self.repository.update_interactive_alert_binding(
                state_id=state.id,
                alert_id=repaired.id,
                symbol=expected_symbol,
                metadata=repaired_metadata,
            )
            LOGGER.info(
                "Interactive alert binding repaired state_id=%s expected_symbol=%s old_alert_id=%s new_alert_id=%s",
                state.id,
                expected_symbol,
                state.alert_id,
                repaired.id,
            )
        return repaired

    async def _build_snapshot(
        self,
        symbol: str,
        timeframe: str,
        *,
        alert_record: AlertRecord | None = None,
        origin_metadata: dict[str, object] | None = None,
    ) -> InteractiveMarketSnapshot:
        symbol = normalize_symbol(symbol)
        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=False)
        marker_time = (
            alert_record.candle_close_time
            if alert_record is not None
            else self._parse_dt(origin_metadata.get("marker_candle_close_time") if origin_metadata else None)
            or self._parse_dt(origin_metadata.get("marker_candle_open_time") if origin_metadata else None)
        )
        frame = await self.binance_client.get_klines(
            symbol,
            timeframe,
            self._interactive_klines_limit(timeframe, marker_time),
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            raise RuntimeError(f"No candle data available for {symbol} on {timeframe}")
        ticker = ticker_map.get(symbol)
        signal = self._build_signal(
            symbol=symbol,
            timeframe=timeframe,
            frame=enriched,
            ticker=ticker,
            alert_record=alert_record,
            origin_metadata=origin_metadata,
        )
        return InteractiveMarketSnapshot(signal=signal, frame=enriched)

    def _build_signal(
        self,
        *,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        alert_record: AlertRecord | None = None,
        origin_metadata: dict[str, object] | None = None,
    ) -> AlertSignal:
        row = frame.iloc[-1]
        rsi = float(row["rsi"])
        language = normalize_language(
            str(
                (origin_metadata or {}).get("language_code")
                or (alert_record.metadata.get("language_code") if alert_record is not None else "")
                or "en"
            )
        )
        metadata_source = {
            **(alert_record.metadata if alert_record is not None else {}),
            **(origin_metadata or {}),
        }
        threshold_source = metadata_source
        oversold_threshold, overbought_threshold = self._resolve_rsi_thresholds(threshold_source)
        is_gold = normalize_symbol(symbol) == normalize_symbol(self.settings.gold_symbol)
        direction = self._classify_zone(
            rsi,
            oversold_threshold=oversold_threshold,
            overbought_threshold=overbought_threshold,
        )
        setup_direction = (
            str(alert_record.direction).strip().lower()
            if alert_record is not None and str(alert_record.direction).strip()
            else str((origin_metadata or {}).get("setup_direction") or direction).strip().lower()
        )
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        candle_close_time = row["close_time"].to_pydatetime()
        marker_open_time = (
            alert_record.candle_open_time
            if alert_record is not None
            else self._parse_dt(origin_metadata.get("marker_candle_open_time") if origin_metadata else None)
            or row.name.to_pydatetime()
        )
        marker_close_time = (
            alert_record.candle_close_time
            if alert_record is not None
            else self._parse_dt(origin_metadata.get("marker_candle_close_time") if origin_metadata else None)
            or candle_close_time
        )
        marker_price = (
            alert_record.alert_price
            if alert_record is not None
            else float(origin_metadata.get("marker_price", row["close"])) if origin_metadata else float(row["close"])
        )
        alert_rsi_value = (
            float(alert_record.alert_rsi)
            if alert_record is not None
            else float(origin_metadata.get("alert_rsi"))
            if origin_metadata and isinstance(origin_metadata.get("alert_rsi"), (int, float))
            else float(rsi)
        )
        alert_score_value = (
            int(alert_record.score)
            if alert_record is not None
            else int(origin_metadata.get("alert_score"))
            if origin_metadata and isinstance(origin_metadata.get("alert_score"), (int, float))
            else int(origin_metadata.get("score"))
            if origin_metadata and isinstance(origin_metadata.get("score"), (int, float))
            else int(self._score_signal(
                row,
                direction,
                oversold_threshold=oversold_threshold,
                overbought_threshold=overbought_threshold,
            ))
        )
        current_score = self._score_signal(
            row,
            direction,
            oversold_threshold=oversold_threshold,
            overbought_threshold=overbought_threshold,
        )
        LOGGER.debug(
            "Interactive RSI snapshot symbol=%s timeframe=%s mode=closed_display closed_rsi=%.2f live_rsi=%s candle_close=%s live_price=%.8f source=binance_futures_klines+wilder_rma",
            symbol,
            timeframe,
            rsi,
            f"{live_rsi:.2f}" if live_rsi is not None else "n/a",
            candle_close_time.isoformat(),
            live_price,
        )
        return AlertSignal(
            symbol=normalize_symbol(symbol),
            direction=direction,
            timeframe=timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(row["close"]),
            rsi=rsi,
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]) if pd.notna(row["avg_volume_20"]) else 0.0,
            atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=current_score,
            explanation=self._build_explanation(
                direction,
                timeframe,
                language_code=language,
                oversold_threshold=oversold_threshold,
                overbought_threshold=overbought_threshold,
            ),
            metadata={
                "interactive_context": True,
                "asset_class": "gold" if is_gold else "crypto",
                "strategy_key": str(metadata_source.get("strategy_key") or "").strip() or None,
                "setup_direction": setup_direction,
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "rsi_mode": "closed_display",
                "rsi_source": "yahoo_gold_klines+wilder_rma" if is_gold else "binance_futures_klines+wilder_rma",
                "closed_rsi": rsi,
                "live_rsi": live_rsi,
                "alert_rsi": alert_rsi_value,
                "alert_score": alert_score_value,
                "live_price": live_price,
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "external_link_label": (
                    str(metadata_source.get("external_link_label") or "").strip()
                    or (ui_text(language, "open_gold_chart") if is_gold else "")
                ),
                "external_link_url": (
                    str(metadata_source.get("external_link_url") or "").strip()
                    or (self.settings.gold_web_base_url if is_gold else "")
                ),
                "interactive_ai_enabled": bool(metadata_source.get("interactive_ai_enabled")) if "interactive_ai_enabled" in metadata_source else not is_gold,
                "interactive_risk_enabled": bool(metadata_source.get("interactive_risk_enabled")) if "interactive_risk_enabled" in metadata_source else not is_gold,
                "interactive_reason_enabled": bool(metadata_source.get("interactive_reason_enabled")) if "interactive_reason_enabled" in metadata_source else not is_gold,
                "marker_price": marker_price,
                "marker_candle_open_time": marker_open_time,
                "marker_candle_close_time": marker_close_time,
                "origin_timeframe": alert_record.timeframe if alert_record is not None else origin_metadata.get("origin_timeframe", timeframe) if origin_metadata else timeframe,
                "rsi_oversold_threshold": oversold_threshold,
                "rsi_overbought_threshold": overbought_threshold,
                "language_code": language,
                "context_text": (
                    str((origin_metadata or {}).get("context_text") or "").strip()
                    or self._build_explanation(
                        direction,
                        timeframe,
                        language_code=language,
                        oversold_threshold=oversold_threshold,
                        overbought_threshold=overbought_threshold,
                    )
                ),
                "signal_status": metadata_source.get("signal_status", "fresh"),
                "result_type": metadata_source.get("result_type", "open"),
                "invalidation_price": metadata_source.get("invalidation_price"),
                "tp_price_primary": metadata_source.get("tp_price_primary"),
                "tp_price_secondary": metadata_source.get("tp_price_secondary"),
                "entry_zone_low": metadata_source.get("entry_zone_low"),
                "entry_zone_high": metadata_source.get("entry_zone_high"),
                "benchmark_win_percent": metadata_source.get("benchmark_win_percent"),
                "expiry_at": metadata_source.get("expiry_at"),
                "market_regime_tag": metadata_source.get("market_regime_tag"),
                "asset_cluster_tag": metadata_source.get("asset_cluster_tag"),
                "liquidity_tag": metadata_source.get("liquidity_tag"),
                "confidence_score": metadata_source.get("confidence_score"),
                "setup_quality": metadata_source.get("setup_quality"),
                "explanation_short": metadata_source.get("explanation_short"),
                "ekek_impulse_summary": metadata_source.get("ekek_impulse_summary"),
                "text_layout": metadata_source.get("text_layout"),
                "historical_resistance_variant": metadata_source.get("historical_resistance_variant"),
                "historical_resistance_available": metadata_source.get("historical_resistance_available"),
                "historical_resistance_zone_low": metadata_source.get("historical_resistance_zone_low"),
                "historical_resistance_zone_high": metadata_source.get("historical_resistance_zone_high"),
                "historical_resistance_zone_price": metadata_source.get("historical_resistance_zone_price"),
                "historical_resistance_distance_pct": metadata_source.get("historical_resistance_distance_pct"),
                "historical_resistance_touch_count": metadata_source.get("historical_resistance_touch_count"),
                "historical_resistance_strong_rejections": metadata_source.get("historical_resistance_strong_rejections"),
                "historical_resistance_avg_rejection_pct": metadata_source.get("historical_resistance_avg_rejection_pct"),
                "historical_resistance_avg_impulse_pct": metadata_source.get("historical_resistance_avg_impulse_pct"),
                "historical_resistance_quality": metadata_source.get("historical_resistance_quality"),
                "historical_resistance_confidence": metadata_source.get("historical_resistance_confidence"),
                "historical_resistance_timeframes": metadata_source.get("historical_resistance_timeframes"),
                "historical_resistance_highest_peak_price": metadata_source.get("historical_resistance_highest_peak_price"),
                "historical_resistance_highest_peak_timeframe": metadata_source.get("historical_resistance_highest_peak_timeframe"),
                "historical_resistance_highest_peak_distance_pct": metadata_source.get("historical_resistance_highest_peak_distance_pct"),
            },
        )

    async def _build_followup_snapshot(
        self,
        *,
        alert_record: AlertRecord,
        timeframe: str,
        stage: str,
        language_code: str = "en",
    ) -> tuple[FollowUpResult, pd.DataFrame, AlertSignal]:
        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=False)
        frame = await self.binance_client.get_klines(
            alert_record.symbol,
            timeframe,
            self._interactive_klines_limit(timeframe, alert_record.candle_close_time),
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            raise RuntimeError(f"No candle data available for {alert_record.symbol} on {timeframe}")

        row = enriched.iloc[-1]
        latest_close_price = float(row["close"])
        ticker = ticker_map.get(alert_record.symbol)
        current_market_price = (
            float(ticker.last_price)
            if ticker is not None and ticker.last_price
            else latest_close_price
        )
        closed_rsi = float(row["rsi"])
        live_rsi = calculate_live_rsi(enriched["close"], current_market_price, self.settings.rsi_length)
        move_pct = calc_pct_change(alert_record.alert_price, current_market_price)
        candle_move_pct = calc_pct_change(alert_record.alert_price, latest_close_price)
        candle_close_time = row["close_time"].to_pydatetime()
        observed_at = utc_now()
        elapsed_seconds = max((observed_at - alert_record.alert_sent_at).total_seconds(), 0.0)
        thesis = evaluate_thesis_result(alert_record.direction, move_pct)
        LOGGER.debug(
            "Interactive follow-up snapshot symbol=%s timeframe=%s closed_rsi=%.2f live_rsi=%s candle_close=%s live_price=%.8f alert_id=%s",
            alert_record.symbol,
            timeframe,
            closed_rsi,
            f"{live_rsi:.2f}" if live_rsi is not None else "n/a",
            candle_close_time.isoformat(),
            current_market_price,
            alert_record.id,
        )
        result = FollowUpResult(
            alert_id=alert_record.id,
            symbol=normalize_symbol(alert_record.symbol),
            direction=alert_record.direction,
            timeframe=timeframe,
            alert_price=alert_record.alert_price,
            current_price=current_market_price,
            alert_rsi=alert_record.alert_rsi,
            current_rsi=closed_rsi,
            move_pct=move_pct,
            summary=summarize_followup(
                alert_record.direction,
                stage=stage,
                market_move_pct=move_pct,
                candle_move_pct=candle_move_pct,
                current_rsi=closed_rsi,
                alert_rsi=alert_record.alert_rsi,
                language=language_code,
            ),
            score=alert_record.score,
            observed_at=observed_at,
            stage=stage,
            thesis_direction=thesis.thesis_direction,
            favorable_move_pct=thesis.favorable_move_pct,
            adverse_move_pct=thesis.adverse_move_pct,
            thesis_result_state=thesis.thesis_result_state,
            metadata={
                "followup_stage": stage,
                "thesis_direction": thesis.thesis_direction,
                "favorable_move_pct": thesis.favorable_move_pct,
                "adverse_move_pct": thesis.adverse_move_pct,
                "thesis_result_state": thesis.thesis_result_state,
                "alert_timeframe": alert_record.timeframe,
                "current_candle_close_price": latest_close_price,
                "candle_move_pct": candle_move_pct,
                "current_market_price_source": "ticker_last_price" if ticker is not None else f"last_closed_{timeframe}_close",
                "live_rsi": live_rsi,
                "rsi_mode": "closed_with_live_secondary",
                "rsi_source": "binance_futures_klines+wilder_rma",
                "signal_candle_close_time": candle_close_time.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "language_code": normalize_language(language_code),
            },
        )
        reference_signal = self._build_followup_reference_signal(
            alert_record=alert_record,
            timeframe=timeframe,
            score=alert_record.score,
        )
        return result, enriched, reference_signal

    def _build_followup_reference_signal(
        self,
        *,
        alert_record: AlertRecord,
        timeframe: str,
        score: int,
    ) -> AlertSignal:
        return AlertSignal(
            symbol=normalize_symbol(alert_record.symbol),
            direction=alert_record.direction,
            timeframe=timeframe,
            candle_open_time=alert_record.candle_open_time,
            candle_close_time=alert_record.candle_close_time,
            price=alert_record.alert_price,
            rsi=alert_record.alert_rsi,
            day_change_pct=alert_record.day_change_pct,
            day_volume=alert_record.day_volume,
            quote_volume=alert_record.metadata.get("quote_volume"),
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=alert_record.metadata.get("atr_pct", 0.0),
            ema20=0.0,
            ema50=0.0,
            score=score,
            explanation=alert_record.metadata.get("explanation", ""),
            metadata={
                **alert_record.metadata,
                "alert_rsi": alert_record.alert_rsi,
                "alert_score": alert_record.score,
                "origin_timeframe": alert_record.timeframe,
                "marker_price": alert_record.alert_price,
                "marker_candle_open_time": alert_record.candle_open_time,
                "marker_candle_close_time": alert_record.candle_close_time,
            },
        )

    def _build_compare_signal_from_followup(
        self,
        *,
        alert_record: AlertRecord,
        followup_result: FollowUpResult,
    ) -> AlertSignal:
        signal = self._build_followup_reference_signal(
            alert_record=alert_record,
            timeframe=followup_result.timeframe,
            score=followup_result.score,
        )
        signal.price = followup_result.current_price
        signal.rsi = followup_result.current_rsi
        signal.candle_close_time = followup_result.observed_at
        signal.metadata = {
            **signal.metadata,
            "live_rsi": followup_result.metadata.get("live_rsi"),
            "followup_stage": followup_result.stage,
        }
        return signal

    async def _replace_alert_message(
        self,
        *,
        state: InteractiveAlertState,
        photo_path,
        caption: str,
        reply_markup: dict[str, object],
        displayed_timeframe: str,
        direction: str,
        metadata: dict[str, object],
    ) -> None:
        send_result = await self.telegram_client.send_photo(
            chat_id=self._delivery_chat_id(state),
            photo_path=photo_path,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        new_message_id = int(send_result["message_id"])
        await self.repository.rebind_interactive_alert_message(
            state_id=state.id,
            chat_id=state.chat_id,
            message_id=new_message_id,
            displayed_timeframe=displayed_timeframe,
            direction=direction,
            metadata=metadata,
        )
        with suppress(Exception):
            await self.telegram_client.delete_message(
                chat_id=self._delivery_chat_id(state),
                message_id=state.message_id,
            )

    async def _send_detail_card(
        self,
        *,
        state: InteractiveAlertState,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        language = self._state_language(state)
        await self.telegram_client.send_message(
            chat_id=self._delivery_chat_id(state),
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=state.message_id,
            reply_markup=reply_markup or build_detail_card_keyboard_with_action(include_delete=True, language_code=language),
        )

    async def _send_detail_error(self, state: InteractiveAlertState, message: str) -> None:
        with suppress(Exception):
            await self.telegram_client.send_message(
                chat_id=self._delivery_chat_id(state),
                text=message,
                parse_mode=None,
                disable_web_page_preview=True,
                reply_to_message_id=state.message_id,
            )

    async def start_chat_loading_indicator(
        self,
        *,
        chat_id: str,
        title: str,
        subtitle: str,
        language_code: str = "en",
        reply_to_message_id: int | None = None,
    ) -> LoadingIndicatorHandle:
        return await self._start_loading_indicator_for_chat(
            chat_id=chat_id,
            title=title,
            subtitle=subtitle,
            language_code=language_code,
            reply_to_message_id=reply_to_message_id,
        )

    async def stop_loading_indicator(self, handle: LoadingIndicatorHandle, *, final_stage: str) -> None:
        await self._stop_loading_indicator(handle, final_stage=final_stage)

    def build_loading_progress_callback(self, handle: LoadingIndicatorHandle):
        return self._build_loading_progress_callback(handle)

    async def _start_loading_indicator(
        self,
        *,
        state: InteractiveAlertState,
        title: str,
        subtitle: str,
        language_code: str = "en",
    ) -> LoadingIndicatorHandle:
        return await self._start_loading_indicator_for_chat(
            chat_id=self._delivery_chat_id(state),
            title=title,
            subtitle=subtitle,
            language_code=language_code,
            reply_to_message_id=state.message_id,
            log_symbol=state.symbol,
            log_timeframe=state.displayed_timeframe,
            log_destination=state.destination_kind,
        )

    async def _start_loading_indicator_for_chat(
        self,
        *,
        chat_id: str,
        title: str,
        subtitle: str,
        language_code: str = "en",
        reply_to_message_id: int | None = None,
        log_symbol: str | None = None,
        log_timeframe: str | None = None,
        log_destination: str | None = None,
    ) -> LoadingIndicatorHandle:
        try:
            started_at = asyncio.get_running_loop().time()
            send_result = await self.telegram_client.send_message(
                chat_id=chat_id,
                text=self._render_loading_frame(
                    title=title,
                    subtitle=subtitle,
                    language_code=language_code,
                    frame_index=0,
                    progress=0.04,
                    elapsed_seconds=0.0,
                    completed=False,
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=reply_to_message_id,
            )
            message_id = int(send_result["message_id"])
            handle = LoadingIndicatorHandle(
                chat_id=chat_id,
                message_id=message_id,
                animation_task=None,
                title=title,
                stage_text=subtitle,
                started_at=started_at,
                language_code=language_code,
            )
            animation_task = asyncio.create_task(
                self._animate_loading_indicator(handle),
                name=f"loading-indicator-{(log_symbol or 'chat')}-{message_id}",
            )
            handle.animation_task = animation_task
            return handle
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.debug(
                "Failed to start loading indicator for %s (%s) in %s",
                log_symbol or "unknown",
                log_timeframe or "n/a",
                log_destination or "chat",
                exc_info=True,
            )
            return LoadingIndicatorHandle(
                chat_id=chat_id,
                message_id=None,
                animation_task=None,
                title=title,
                stage_text=subtitle,
                started_at=asyncio.get_running_loop().time(),
                language_code=language_code,
            )

    async def _stop_loading_indicator(self, handle: LoadingIndicatorHandle, *, final_stage: str) -> None:
        handle.completed = True
        handle.stage_text = final_stage
        handle.target_progress = 1.0
        if handle.animation_task is not None:
            try:
                await asyncio.wait_for(handle.animation_task, timeout=2.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                handle.animation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await handle.animation_task
        if handle.message_id is not None:
            with suppress(Exception):
                await self.telegram_client.delete_message(chat_id=handle.chat_id, message_id=handle.message_id)

    async def _animate_loading_indicator(self, handle: LoadingIndicatorHandle) -> None:
        frame_index = 1
        while True:
            await asyncio.sleep(0.55 if not handle.completed else 0.18)
            progress = self._advance_loading_progress(handle)
            elapsed_seconds = max(asyncio.get_running_loop().time() - handle.started_at, 0.0)
            try:
                await self.telegram_client.edit_message_text(
                    chat_id=handle.chat_id,
                    message_id=handle.message_id,
                    text=self._render_loading_frame(
                        title=handle.title,
                        subtitle=handle.stage_text,
                        language_code=handle.language_code,
                        frame_index=frame_index,
                        progress=progress,
                        elapsed_seconds=elapsed_seconds,
                        completed=handle.completed,
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:  # pragma: no cover - runtime dependent
                LOGGER.debug(
                    "Loading indicator animation stopped for chat_id=%s message_id=%s",
                    handle.chat_id,
                    handle.message_id,
                    exc_info=True,
                )
                return
            if handle.completed and progress >= 0.999:
                return
            frame_index = (frame_index + 1) % 6

    def _legacy_render_loading_frame(self, *, title: str, subtitle: str, frame_index: int) -> str:
        bars = ("▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰", "▰▰▰▰▱")
        faces = ("\U0001F642", "\U0001F60C", "\U0001F914", "\U0001F916", "\U0001F680", "\U0001F60E")
        frame = frame_index % len(bars)
        return (
            f"\U0001F9E0 <b>{title}</b>\n"
            f"<code>{bars[frame]}</code> {faces[frame]}\n"
            f"{subtitle}"
        )

    def _render_loading_frame(
        self,
        *,
        title: str,
        subtitle: str,
        language_code: str = "en",
        frame_index: int,
        progress: float,
        elapsed_seconds: float,
        completed: bool,
    ) -> str:
        faces = ("\U0001F9E0", "\U0001F50D", "\U0001F4CA", "\U0001F9ED", "\u26A1", "\U0001F680")
        pulse = ("\u2022", "\u2022\u2022", "\u2022\u2022\u2022", "\u2022\u2022", "\u2022", "\u2022\u2022")
        frame = frame_index % len(faces)
        bounded_progress = max(0.0, min(progress, 1.0))
        percent = max(1, min(int(round(bounded_progress * 100)), 100))
        total_segments = 18
        if completed or bounded_progress >= 0.999:
            bar = "▰" * total_segments
        else:
            visual_progress = min(bounded_progress, 0.965)
            filled = min(total_segments - 1, max(1, int(visual_progress * (total_segments - 1))))
            head = "▸" if frame_index % 2 == 0 else "▹"
            empty = max(total_segments - filled - 1, 0)
            bar = "▰" * filled + head + "▱" * empty
        stage_label = "Этап" if is_russian(language_code) else "Stage"
        elapsed_label = "Прошло" if is_russian(language_code) else "Elapsed"
        return (
            f"{faces[frame]} <b>{title}</b>\n"
            f"<code>{bar} {percent:02d}%</code> {pulse[frame]}\n"
            f"<b>{stage_label}:</b> {subtitle}\n"
            f"<b>{elapsed_label}:</b> {int(elapsed_seconds)}s"
        )

    def _build_loading_progress_callback(self, handle: LoadingIndicatorHandle):
        async def _progress(stage_text: str, progress: float | None) -> None:
            handle.stage_text = stage_text
            if progress is not None:
                bounded = max(handle.current_progress, min(float(progress), 0.97))
                handle.target_progress = max(handle.target_progress, bounded)

        return _progress

    def _advance_loading_progress(self, handle: LoadingIndicatorHandle) -> float:
        if handle.completed:
            remaining = 1.0 - handle.current_progress
            if remaining <= 0.001:
                handle.current_progress = 1.0
                return handle.current_progress
            handle.current_progress = min(1.0, handle.current_progress + max(0.06, remaining * 0.7))
            return handle.current_progress

        target = min(max(handle.target_progress, 0.10), 0.94)
        gap = target - handle.current_progress
        if gap > 0.002:
            handle.current_progress = min(target, handle.current_progress + max(0.012, gap * 0.35))
        else:
            elapsed = max(asyncio.get_running_loop().time() - handle.started_at, 0.0)
            soft_ceiling = min(0.96, 0.82 + min(elapsed / 90.0, 0.10))
            if handle.current_progress < soft_ceiling:
                handle.current_progress = min(soft_ceiling, handle.current_progress + 0.004)
        return handle.current_progress

    async def _handle_delete_detail(
        self,
        query_id: str,
        *,
        chat_id: str,
        message_id: int,
        language_code: str = "en",
    ) -> None:
        await self._safe_answer(query_id, text=ui_text(language_code, "interactive_deleting"))
        try:
            await self.telegram_client.delete_message(chat_id=chat_id, message_id=message_id)
            LOGGER.info("Delete button action chat_id=%s message_id=%s", chat_id, message_id)
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception("Failed to delete detail card chat_id=%s message_id=%s", chat_id, message_id)

    def _build_alert_keyboard(
        self,
        *,
        symbol: str,
        selected_timeframe: str,
        destination_kind: str,
        language_code: str = "en",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        premium_enabled = self.settings.premium_features_enabled_for(destination_kind)
        effective_metadata = metadata or {}
        return build_alert_inline_keyboard(
            symbol=normalize_symbol(symbol),
            selected_timeframe=selected_timeframe,
            supported_timeframes=self.settings.interactive_timeframes_for(destination_kind),
            futures_base_url=self.settings.binance_futures_web_base_url,
            futures_app_base_url=self.settings.binance_futures_app_base_url,
            language_code=language_code,
            external_link_label=str(effective_metadata.get("external_link_label") or "") or None,
            external_link_url=str(effective_metadata.get("external_link_url") or ""),
            include_ai_analysis=(
                bool(effective_metadata["interactive_ai_enabled"])
                if "interactive_ai_enabled" in effective_metadata
                else self._ai_button_enabled(destination_kind)
            ),
            include_risk_management=(
                bool(effective_metadata["interactive_risk_enabled"])
                if "interactive_risk_enabled" in effective_metadata
                else (premium_enabled or destination_kind == "classic")
            ),
            include_signal_reason=(
                bool(effective_metadata["interactive_reason_enabled"])
                if "interactive_reason_enabled" in effective_metadata
                else (premium_enabled or destination_kind == "classic")
            ),
            include_compare=destination_kind in {"private", "classic", "public", "pro", "community", "results"},
            include_copy_symbol=True,
            include_binance_app_link=True,
            include_tradingview_link=destination_kind in {"private", "pro"},
            include_home_button=destination_kind in {"private", "pro"},
        )

    def _premium_feature_allowed(self, destination_kind: str) -> bool:
        return self.settings.premium_features_enabled_for(destination_kind)

    async def _premium_feature_allowed_for_state(self, state: InteractiveAlertState) -> bool:
        if not self._premium_feature_allowed(state.destination_kind):
            return False
        if state.destination_kind != "private":
            return True
        chat_id = self._delivery_chat_id(state).strip()
        if not chat_id.lstrip("-").isdigit():
            return True
        telegram_user_id = int(chat_id)
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            return False
        if user.is_admin:
            return True
        latest_access = await self.repository.get_latest_user_access(telegram_user_id)
        if latest_access is None:
            return False
        status = (latest_access.status or "").strip().lower()
        if status == "admin_active":
            return True
        if status == "trial_active":
            return latest_access.ends_at is None or latest_access.ends_at > utc_now()
        if status == "paid_active":
            return latest_access.ends_at is None or latest_access.ends_at > utc_now()
        return False

    def _ai_button_enabled(self, destination_kind: str) -> bool:
        if destination_kind == "twitter_drafts":
            return False
        return destination_kind in {"private", "classic", "lab", "pro", "public", "community", "results"}

    async def _send_premium_upgrade_notice(self, state: InteractiveAlertState, *, feature_name: str) -> None:
        language = self._state_language(state)
        trial_days = max(int(self.settings.private_bot_trial_days), 0)
        link = self.settings.resolved_private_bot_share_link
        lines = [
            ui_text(language, "interactive_upgrade_title", feature_name=feature_name),
            "",
            ui_text(language, "interactive_upgrade_body"),
        ]
        if trial_days > 0:
            lines.append(ui_text(language, "interactive_upgrade_trial", days=trial_days))
        if link:
            lines.extend(
                [
                    "",
                    ui_text(language, "interactive_upgrade_cta"),
                ]
            )
        await self._send_detail_card(
            state=state,
            text="\n".join(lines),
            reply_markup=build_detail_card_keyboard_with_action(
                include_delete=True,
                language_code=language,
                action_label=ui_text(language, "interactive_upgrade_button") if link else None,
                action_url=link or None,
            ),
        )

    def _iso_or_none(self, value: object) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
        return None

    def _scoped_chat_id(self, chat_id: str) -> str:
        if not self.state_scope:
            return str(chat_id)
        return f"{self.state_scope}:{chat_id}"

    def _delivery_chat_id(self, state: InteractiveAlertState) -> str:
        raw_chat_id = state.metadata.get("telegram_chat_id")
        if raw_chat_id:
            return str(raw_chat_id)
        if self.state_scope and state.chat_id.startswith(f"{self.state_scope}:"):
            return state.chat_id.split(":", maxsplit=1)[1]
        return state.chat_id

    def _state_language(self, state: InteractiveAlertState, *, fallback: str = "en") -> str:
        return normalize_language(str(state.metadata.get("language_code") or fallback))

    def _parse_dt(self, value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            with suppress(ValueError):
                return datetime.fromisoformat(value)
        return None

    def _interactive_klines_limit(self, timeframe: str, marker_time: datetime | None) -> int:
        base_limit = self.settings.klines_limit
        if marker_time is None:
            return base_limit
        interval_seconds = self._interval_to_seconds(timeframe)
        if interval_seconds <= 0:
            return base_limit
        age_seconds = max((utc_now() - marker_time).total_seconds(), 0.0)
        required_bars = int(age_seconds // interval_seconds) + 30
        return max(base_limit, min(required_bars, 500))

    def _interval_to_seconds(self, timeframe: str) -> int:
        if timeframe.endswith("m"):
            return int(timeframe[:-1]) * 60
        if timeframe.endswith("h"):
            return int(timeframe[:-1]) * 3600
        if timeframe.endswith("d"):
            return int(timeframe[:-1]) * 86400
        return 0

    def _classify_zone(
        self,
        rsi: float,
        *,
        oversold_threshold: float | None = None,
        overbought_threshold: float | None = None,
    ) -> str:
        oversold_value = self.settings.rsi_oversold if oversold_threshold is None else float(oversold_threshold)
        overbought_value = self.settings.rsi_overbought if overbought_threshold is None else float(overbought_threshold)
        if rsi <= oversold_value:
            return "oversold"
        if rsi >= overbought_value:
            return "overbought"
        return "neutral"

    def _nearest_extreme_direction(
        self,
        rsi: float,
        *,
        oversold_threshold: float | None = None,
        overbought_threshold: float | None = None,
    ) -> str:
        oversold_value = self.settings.rsi_oversold if oversold_threshold is None else float(oversold_threshold)
        overbought_value = self.settings.rsi_overbought if overbought_threshold is None else float(overbought_threshold)
        oversold_distance = abs(rsi - oversold_value)
        overbought_distance = abs(rsi - overbought_value)
        return "oversold" if oversold_distance <= overbought_distance else "overbought"

    def _score_signal(
        self,
        row: pd.Series,
        direction: str,
        *,
        oversold_threshold: float | None = None,
        overbought_threshold: float | None = None,
    ) -> int:
        oversold_value = self.settings.rsi_oversold if oversold_threshold is None else float(oversold_threshold)
        overbought_value = self.settings.rsi_overbought if overbought_threshold is None else float(overbought_threshold)
        effective_direction = direction if direction != "neutral" else self._nearest_extreme_direction(
            float(row["rsi"]),
            oversold_threshold=oversold_value,
            overbought_threshold=overbought_value,
        )
        if effective_direction == "oversold":
            threshold_distance = max(oversold_value - float(row["rsi"]), 0.0)
            trend_score = 12 if row["close"] < row["ema20"] < row["ema50"] else 5
            stretch = max((row["ema20"] - row["close"]) / row["close"], 0.0)
        else:
            threshold_distance = max(float(row["rsi"]) - overbought_value, 0.0)
            trend_score = 12 if row["close"] > row["ema20"] > row["ema50"] else 5
            stretch = max((row["close"] - row["ema20"]) / row["close"], 0.0)

        extremeness_score = min(threshold_distance * 4.2, 42)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16, 18)
        volatility_score = min(float(row["atr_pct"]) * 600, 16)
        stretch_score = min(stretch * 4000, 14)
        total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score

        if direction == "neutral":
            nearest_distance = min(
                abs(float(row["rsi"]) - oversold_value),
                abs(float(row["rsi"]) - overbought_value),
            )
            proximity_score = max(0.0, 20.0 - nearest_distance)
            total = proximity_score + min(volume_score, 12) + min(volatility_score, 10) + max(trend_score - 2, 3)
            total = min(total, 62)

        return int(max(0, min(round(total), 100)))

    def _build_explanation(
        self,
        direction: str,
        timeframe: str,
        *,
        language_code: str = "en",
        oversold_threshold: float | None = None,
        overbought_threshold: float | None = None,
    ) -> str:
        oversold_value = self.settings.rsi_oversold if oversold_threshold is None else float(oversold_threshold)
        overbought_value = self.settings.rsi_overbought if overbought_threshold is None else float(overbought_threshold)
        language = normalize_language(language_code)
        if direction == "oversold":
            if is_russian(language):
                return (
                    f"RSI ниже {oversold_value:.0f} на графике {timeframe}, что может указывать на краткосрочное истощение снижения. "
                    "Но реакция цены все еще должна это подтвердить."
                )
            return (
                f"RSI is below {oversold_value:.0f} on the {timeframe} chart, which may point to short-term downside exhaustion. "
                "That still needs confirmation from price response and follow-through."
            )
        if direction == "overbought":
            if is_russian(language):
                return (
                    f"RSI выше {overbought_value:.0f} на графике {timeframe}, что может указывать на краткосрочное истощение роста. "
                    "Но это все еще требует подтверждения по структуре цены."
                )
            return (
                f"RSI is above {overbought_value:.0f} on the {timeframe} chart, which may point to short-term upside exhaustion. "
                "That still needs confirmation from price structure, not just the oscillator alone."
            )
        if is_russian(language):
            return (
                f"RSI вернулся в среднюю зону на графике {timeframe}. "
                "Это скорее контекст для watchlist, чем чистый экстремум."
            )
        return (
            f"RSI is back inside the middle range on the {timeframe} chart. "
            "This looks more like watchlist context than a clean extreme on its own."
        )

    def _resolve_rsi_thresholds(self, metadata: dict[str, object] | None) -> tuple[float, float]:
        if not metadata:
            return self.settings.rsi_oversold, self.settings.rsi_overbought
        oversold_raw = metadata.get("rsi_oversold_threshold")
        overbought_raw = metadata.get("rsi_overbought_threshold")
        oversold_value = (
            float(oversold_raw)
            if isinstance(oversold_raw, (int, float))
            else self.settings.rsi_oversold
        )
        overbought_value = (
            float(overbought_raw)
            if isinstance(overbought_raw, (int, float))
            else self.settings.rsi_overbought
        )
        return oversold_value, overbought_value

    def _build_analysis_context(
        self,
        signal: AlertSignal,
        alert_record: AlertRecord | None,
        followup_record: FollowUpResultRecord | None,
    ) -> str:
        strategy_key = str(signal.metadata.get("strategy_key") or "").strip().lower() or "rsi"
        setup_direction = str(signal.metadata.get("setup_direction") or signal.direction).strip().lower()
        parts = [
            "Current market context:",
            f"Symbol: {signal.symbol}",
            f"Displayed timeframe: {signal.timeframe}",
            f"Strategy key: {strategy_key}",
            f"Trade direction: {setup_direction}",
            f"Signal close: {format_price(signal.price)}",
            f"RSI(14, closed {signal.timeframe}): {format_rsi(signal.rsi)}",
            f"Score: {signal.score}/100",
            f"24h Change: {format_percent(signal.day_change_pct)}",
            f"24h Quote Volume: {format_volume(signal.quote_volume or signal.day_volume)}",
            f"ATR%: {signal.atr_pct:.4%}" if signal.atr_pct else "ATR%: n/a",
            f"Trend context: close {format_price(signal.price)}, EMA20 {format_price(signal.ema20)}, EMA50 {format_price(signal.ema50)}",
        ]
        if setup_direction != signal.direction:
            parts.append(f"Current RSI status: {signal.direction}")
        if isinstance(signal.metadata.get("live_price"), (int, float)):
            parts.append(f"Current market price: {format_price(float(signal.metadata['live_price']))}")
        if isinstance(signal.metadata.get("live_rsi"), (int, float)):
            parts.append(f"RSI(14, live {signal.timeframe}): {format_rsi(float(signal.metadata['live_rsi']))}")

        volume_ratio = signal.metadata.get("volume_ratio")
        if volume_ratio is not None:
            parts.append(f"Volume ratio vs 20-bar average: {float(volume_ratio):.2f}x")
        if isinstance(signal.metadata.get("signal_model"), str) and str(signal.metadata.get("signal_model")).strip():
            parts.append(f"Signal model: {signal.metadata['signal_model']}")
        if isinstance(signal.metadata.get("trigger_level"), (int, float)):
            parts.append(f"Trigger level: {format_price(float(signal.metadata['trigger_level']))}")
        if isinstance(signal.metadata.get("vwap_value"), (int, float)):
            parts.append(f"VWAP value: {format_price(float(signal.metadata['vwap_value']))}")
        if isinstance(signal.metadata.get("breakout_type"), str) and str(signal.metadata.get("breakout_type")).strip():
            parts.append(f"Breakout subtype: {signal.metadata['breakout_type']}")
        if isinstance(signal.metadata.get("touched_ema"), (int, float)):
            parts.append(f"Touched EMA: EMA{int(float(signal.metadata['touched_ema']))}")
        if isinstance(signal.metadata.get("sweep_side"), str) and str(signal.metadata.get("sweep_side")).strip():
            parts.append(f"Sweep side: {signal.metadata['sweep_side']}")
        context_text = str(signal.metadata.get("context_text") or signal.explanation or "").strip()
        if context_text:
            parts.append(f"Setup note: {context_text}")

        if alert_record is not None:
            parts.extend(
                [
                    "",
                    "Original alert context:",
                    f"Original timeframe: {alert_record.timeframe}",
                    f"Alert type: {alert_record.direction}",
                    f"Alert price: {format_price(alert_record.alert_price)}",
                    f"Alert RSI: {format_rsi(alert_record.alert_rsi)}",
                    f"Original score: {alert_record.score}/100",
                ]
            )
        if followup_record is not None:
            parts.extend(
                [
                    "",
                    "Stored follow-up context:",
                    f"Move after alert: {format_percent(followup_record.move_pct)}",
                    f"RSI then -> now: {format_rsi(followup_record.alert_rsi)} -> {format_rsi(followup_record.current_rsi)}",
                    f"Follow-up summary: {followup_record.summary}",
                ]
            )
        parts.extend(
            [
                "",
                "Explain clearly whether this looks worth watching now, whether it looks actionable yet, what looks weak or stronger than average, and what matters next.",
            ]
        )
        return "\n".join(parts)

    def _fallback_analysis_text(
        self,
        signal: AlertSignal,
        alert_record: AlertRecord | None,
        followup_record: FollowUpResultRecord | None,
    ) -> str:
        strategy_key = str(signal.metadata.get("strategy_key") or "").strip().lower() or "rsi"
        analysis_direction = str(signal.metadata.get("setup_direction") or signal.direction).strip().lower()
        trigger_level = signal.metadata.get("trigger_level")
        trigger_line = (
            f" Trigger level to watch is {format_price(float(trigger_level))}."
            if isinstance(trigger_level, (int, float))
            else ""
        )
        if analysis_direction == "long":
            opening = (
                f"This {signal.timeframe} chart is currently showing a long-side setup from the {strategy_key} strategy."
            )
            if strategy_key == "breakout":
                middle = f"The main question now is whether price can keep holding above the broken level and build follow-through.{trigger_line}"
            elif strategy_key == "trend_pullback":
                touched_ema = signal.metadata.get("touched_ema")
                ema_label = f" EMA{int(float(touched_ema))}" if isinstance(touched_ema, (int, float)) else ""
                middle = (
                    f"This is a trend pullback continuation case, so the quality depends on whether the market keeps respecting{ema_label} support and prints continuation after the reaction candle."
                )
            elif strategy_key in {"bollinger", "rsi_bollinger_mr"}:
                middle = "This is a mean-reversion style long, so the next thing that matters is whether price keeps reclaiming space away from the lower band instead of slipping back into weakness."
            elif strategy_key == "rsi_bollinger_touch":
                middle = "This long setup came from an RSI extreme plus a lower Bollinger touch, so the key now is whether price can keep bouncing away from that stretched area instead of falling back into flat chop."
            elif strategy_key == "rsi_divergence":
                middle = "This is a bullish RSI divergence, so the next confirmation is whether buyers can defend the new low and turn that momentum mismatch into an actual rebound."
            elif strategy_key == "ekek":
                middle = "This is an overheated impulse-short shortlist, so the key now is whether the sharp burst starts stalling instead of extending into another squeeze."
            elif strategy_key == "vwap":
                middle = f"The intraday long bias stays healthier only while price keeps holding above daily VWAP after the reclaim.{trigger_line}"
            elif strategy_key == "false_breakout":
                middle = f"This is a reclaim after a liquidity sweep, so the idea weakens quickly if price loses the swept level again.{trigger_line}"
            else:
                middle = f"The setup needs continuation to prove the long thesis and avoid turning into a failed trigger.{trigger_line}"
        elif analysis_direction == "short":
            opening = (
                f"This {signal.timeframe} chart is currently showing a short-side setup from the {strategy_key} strategy."
            )
            if strategy_key == "breakout":
                middle = f"The main question now is whether price can stay below the broken level and continue pressing lower.{trigger_line}"
            elif strategy_key == "trend_pullback":
                touched_ema = signal.metadata.get("touched_ema")
                ema_label = f" EMA{int(float(touched_ema))}" if isinstance(touched_ema, (int, float)) else ""
                middle = (
                    f"This is a trend pullback continuation case, so the quality depends on whether the market keeps respecting{ema_label} as resistance and follows through lower."
                )
            elif strategy_key in {"bollinger", "rsi_bollinger_mr"}:
                middle = "This is a mean-reversion style short, so the next thing that matters is whether price keeps accepting back below the upper band instead of squeezing higher again."
            elif strategy_key == "rsi_bollinger_touch":
                middle = "This short setup came from an RSI extreme plus an upper Bollinger touch, so the key now is whether price can keep rejecting from that overheated area instead of drifting into sideways noise."
            elif strategy_key == "rsi_divergence":
                middle = "This is a bearish RSI divergence, so the next confirmation is whether sellers can defend the new high rejection and turn that momentum mismatch into real downside."
            elif strategy_key == "ekek":
                middle = "This is an overheated impulse-short shortlist, so the key now is whether sellers can keep fading the burst instead of letting it turn into another squeeze higher."
            elif strategy_key == "vwap":
                middle = f"The intraday short bias stays healthier only while price keeps trading below daily VWAP after the rejection.{trigger_line}"
            elif strategy_key == "false_breakout":
                middle = f"This is a failed breakout after a sweep, so the idea weakens quickly if price gets back above the swept level.{trigger_line}"
            else:
                middle = f"The setup needs downside continuation to prove the short thesis and avoid turning into a failed trigger.{trigger_line}"
        elif analysis_direction == "oversold":
            opening = (
                f"This {signal.timeframe} setup is currently oversold, so the market is showing short-term downside stretch."
            )
            middle = "That alone does not make it a clean bounce. The next thing that matters is whether price can stabilize while RSI lifts out of the extreme zone."
        elif analysis_direction == "overbought":
            opening = (
                f"This {signal.timeframe} setup is currently overbought, which means short-term momentum looks stretched."
            )
            middle = "That does not confirm a reversal by itself. What matters next is whether price starts cooling off while RSI fades back from the extreme."
        else:
            opening = (
                f"On the {signal.timeframe}, RSI is back in the middle range, so this is more watchlist context than a clean extreme."
            )
            middle = "That usually means patience matters more than speed. The setup becomes more interesting only if momentum stretches again or structure improves."

        if signal.score >= 75:
            quality = "This looks stronger than average because score, liquidity, and structure are lining up better than most routine prints."
        elif signal.score >= 55:
            quality = "Worth keeping on the watchlist, but this still looks more normal than exceptional right now."
        else:
            quality = "At the moment this looks fairly average, so it is more of a reference point than a high-conviction case."

        followup_line = ""
        if followup_record is not None:
            followup_line = (
                f"\n\nThere is already follow-up context on this symbol: the stored move after the alert was {format_percent(followup_record.move_pct)}. "
                "That helps, but the current chart still matters more than the old print."
            )
        elif alert_record is not None and alert_record.timeframe != signal.timeframe:
            followup_line = (
                f"\n\nThe original alert was on {alert_record.timeframe}, so treat this {signal.timeframe} view as added context rather than the same setup."
            )

        return f"{opening}\n\n{quality}\n\n{middle}{followup_line}"

    async def _safe_answer(self, query_id: str, *, text: str | None = None, show_alert: bool = False) -> None:
        if not query_id:
            return
        with suppress(Exception):
            await self.telegram_client.answer_callback_query(
                callback_query_id=query_id,
                text=text,
                show_alert=show_alert,
            )


class TelegramCallbackPoller:
    def __init__(
        self,
        settings: Settings,
        telegram_client: TelegramClient,
        interactive_service: InteractiveAlertService,
        private_bot_service: "PrivateBotService | None" = None,
    ) -> None:
        self.settings = settings
        self.telegram_client = telegram_client
        self.interactive_service = interactive_service
        self.private_bot_service = private_bot_service
        self._offset: int | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._child_tasks: set[asyncio.Task] = set()
        self._conflict_logged = False

    def _attach_child_task(self, task: asyncio.Task) -> None:
        self._child_tasks.add(task)
        task.add_done_callback(self._child_tasks.discard)
        task.add_done_callback(self._log_child_task_exception)

    def _log_child_task_exception(self, task: asyncio.Task) -> None:
        with suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                LOGGER.error(
                    "Telegram callback child task failed task=%s",
                    task.get_name(),
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

    async def start(self) -> None:
        if not self.settings.interactive_alerts_enabled or self._task is not None:
            return
        await self._prime_offset()
        self._task = asyncio.create_task(self._run(), name="telegram-callback-poller")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for task in list(self._child_tasks):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _prime_offset(self) -> None:
        try:
            updates = await self.telegram_client.get_updates(timeout=0, allowed_updates=["callback_query", "message"])
        except Exception as exc:  # pragma: no cover - runtime dependent
            if self._is_getupdates_conflict(exc):
                self._log_getupdates_conflict()
                return
            LOGGER.exception("Failed to prime Telegram callback offset")
            return
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = update_id + 1
        self._conflict_logged = False

    async def _run(self) -> None:
        LOGGER.info("Telegram callback poller started")
        while not self._stop_event.is_set():
            try:
                updates = await self.telegram_client.get_updates(
                    offset=self._offset,
                    timeout=self.settings.interactive_callback_poll_timeout_seconds,
                    allowed_updates=["callback_query", "message"],
                )
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1
                    callback_query = update.get("callback_query")
                    if isinstance(callback_query, dict):
                        callback_data = str(callback_query.get("data") or "")
                        callback_handler = (
                            self.interactive_service.handle_callback_query
                            if callback_data.startswith("alert:") or callback_data.startswith("detail:")
                            else getattr(self.private_bot_service, "handle_callback_query", None)
                        )
                        if callback_handler is None:
                            continue
                        task = asyncio.create_task(
                            callback_handler(callback_query),
                            name="telegram-callback-handler",
                        )
                        self._attach_child_task(task)
                    message = update.get("message")
                    if isinstance(message, dict) and self.private_bot_service is not None:
                        task = asyncio.create_task(
                            self.private_bot_service.handle_message(message),
                            name="telegram-private-message-handler",
                        )
                        self._attach_child_task(task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - runtime dependent
                if self._is_getupdates_conflict(exc):
                    self._log_getupdates_conflict()
                    await asyncio.sleep(5)
                    continue
                if isinstance(exc, TimeoutError):
                    self._conflict_logged = False
                    continue
                self._conflict_logged = False
                LOGGER.exception("Telegram callback poller failed")
                await asyncio.sleep(3)
        LOGGER.info("Telegram callback poller stopped")

    def _is_getupdates_conflict(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "getupdates failed: status=409" in message or "terminated by other getupdates request" in message

    def _log_getupdates_conflict(self) -> None:
        if self._conflict_logged:
            return
        LOGGER.error(
            "Telegram callback polling is blocked by another getUpdates consumer. "
            "Stop the duplicate RSI bot process or any other bot session using the same token, then restart this instance."
        )
        self._conflict_logged = True
