from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.ai.generators import DraftGenerator
from src.analysis.precompute import PreparedFeatureService
from src.bot.interactive_alerts import InteractiveAlertService
from src.bot.routing import MessageRouter
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.followup_logic import evaluate_thesis_result, summarize_followup
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost
from src.core.utils import calc_pct_change, format_percent, local_day_bounds, normalize_symbol, utc_now
from src.jobs.twitter_drafts import TwitterDraftService
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.signals.service import SignalLifecycleService
from src.storage.models import AlertRecord, FollowUpResultRecord, FollowUpTaskRecord
from src.storage.repository import Repository
from src.userbot.service import PrivateBotService

LOGGER = logging.getLogger(__name__)


class FollowUpService:
    RESULTS_BEST_FOLLOWUP_SLOT_HOURS = (18, 21)
    RESULTS_BEST_FOLLOWUPS_PER_SLOT = 2
    RESULTS_BEST_FOLLOWUP_CONTENT_TYPE = "results_best_followups_digest"

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        router: MessageRouter,
        draft_generator: DraftGenerator,
        interactive_alert_service: InteractiveAlertService | None = None,
        twitter_draft_service: TwitterDraftService | None = None,
        private_bot_service: PrivateBotService | None = None,
        classic_bot_service: PrivateBotService | None = None,
        prepared_feature_service: PreparedFeatureService | None = None,
        scheduled_post_scheduler=None,
        lifecycle_service: SignalLifecycleService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.binance_client = binance_client
        self.chart_renderer = chart_renderer
        self.router = router
        self.draft_generator = draft_generator
        self.interactive_alert_service = interactive_alert_service
        self.twitter_draft_service = twitter_draft_service
        self.private_bot_service = private_bot_service
        self.classic_bot_service = classic_bot_service
        self.prepared_feature_service = prepared_feature_service
        self.scheduled_post_scheduler = scheduled_post_scheduler
        self.lifecycle_service = lifecycle_service or SignalLifecycleService(repository)

    def _signal_strategy_key(self, signal: AlertSignal) -> str:
        return str(signal.metadata.get("strategy_key") or "rsi").strip().lower() or "rsi"

    def _is_public_stream_strategy(self, signal: AlertSignal) -> bool:
        return self._signal_strategy_key(signal) == "rsi"

    def _alert_strategy_key(self, alert: AlertRecord) -> str:
        return str(alert.strategy_key or "rsi").strip().lower() or "rsi"

    def _followup_favorable_move(self, followup: FollowUpResultRecord) -> float:
        return float(followup.metadata.get("favorable_move_pct") or 0.0)

    def _results_followup_rank(
        self,
        alert: AlertRecord,
        followup: FollowUpResultRecord,
    ) -> tuple[float, int, float]:
        return (
            self._followup_favorable_move(followup),
            int(alert.score),
            followup.observed_at.timestamp(),
        )

    def _results_channel_followup_is_eligible(
        self,
        alert: AlertRecord,
        followup: FollowUpResultRecord,
    ) -> bool:
        if self._alert_strategy_key(alert) != "rsi":
            return False
        if str(followup.metadata.get("thesis_result_state") or "") != "favorable":
            return False
        if self._followup_favorable_move(followup) < float(self.settings.results_min_favorable_move_pct):
            return False
        if int(alert.score) < max(int(self.settings.results_min_score), int(self.settings.public_result_min_score)):
            return False
        quote_volume = float(alert.metadata.get("quote_volume") or 0.0)
        return quote_volume >= 8_000_000.0

    def _format_results_best_followups_digest(
        self,
        candidates: list[tuple[AlertRecord, FollowUpResultRecord]],
        *,
        slot_hour: int,
        local_now: datetime,
    ) -> str:
        slot_label = f"{slot_hour:02d}:00 {local_now.tzname() or ''}".strip()
        lines = [
            f"Top follow-up winners by {slot_label}",
            "",
            "Best results that kept moving in the original thesis direction today:",
            "",
        ]
        for index, (alert, followup) in enumerate(candidates, start=1):
            lines.append(
                f"{index}. {normalize_symbol(followup.symbol)} | {followup.stage} | "
                f"favorable {format_percent(self._followup_favorable_move(followup))} | score {alert.score}"
            )
        lines.extend(
            [
                "",
                "This digest is based on completed follow-up checks, not raw alerts.",
            ]
        )
        return "\n".join(lines)

    async def _select_results_channel_best_followups(
        self,
        *,
        start: datetime,
        end: datetime,
        exclude_alert_ids: set[int],
    ) -> list[tuple[AlertRecord, FollowUpResultRecord]]:
        ranked_by_symbol: dict[str, tuple[AlertRecord, FollowUpResultRecord]] = {}
        followups = await self.repository.list_followup_results_between(start=start, end=end, limit=160)
        for followup in followups:
            if followup.alert_id in exclude_alert_ids:
                continue
            alert = await self.repository.get_alert(followup.alert_id)
            if alert is None or not self._results_channel_followup_is_eligible(alert, followup):
                continue
            symbol = normalize_symbol(followup.symbol)
            current = ranked_by_symbol.get(symbol)
            if current is None or self._results_followup_rank(alert, followup) > self._results_followup_rank(*current):
                ranked_by_symbol[symbol] = (alert, followup)
        return sorted(
            ranked_by_symbol.values(),
            key=lambda item: self._results_followup_rank(item[0], item[1]),
            reverse=True,
        )

    async def _send_results_channel_best_followups_if_due(
        self,
        *,
        now: datetime | None = None,
    ) -> None:
        if not self.settings.results_channel_enabled:
            return

        effective_now = now or utc_now()
        local_now = effective_now.astimezone(self.settings.timezone)
        day_start, _ = local_day_bounds(local_now.date(), self.settings.timezone)
        sent_today = await self.repository.list_generated_posts_history(
            destination=self.settings.results_channel,
            channel_kind="results",
            content_types=[self.RESULTS_BEST_FOLLOWUP_CONTENT_TYPE],
            statuses=["sent"],
            since=day_start,
            limit=8,
        )
        sent_slot_hours: set[int] = set()
        sent_alert_ids: set[int] = set()
        for post in sent_today:
            slot_hour = post.get("metadata", {}).get("slot_hour")
            if isinstance(slot_hour, (int, float)):
                sent_slot_hours.add(int(slot_hour))
            for alert_id in post.get("metadata", {}).get("alert_ids", []):
                if isinstance(alert_id, int):
                    sent_alert_ids.add(alert_id)

        for slot_hour in self.RESULTS_BEST_FOLLOWUP_SLOT_HOURS:
            if local_now.hour < slot_hour or slot_hour in sent_slot_hours:
                continue
            candidates = await self._select_results_channel_best_followups(
                start=day_start,
                end=effective_now + timedelta(minutes=1),
                exclude_alert_ids=sent_alert_ids,
            )
            if not candidates:
                continue
            winners = candidates[: self.RESULTS_BEST_FOLLOWUPS_PER_SLOT]
            post = GeneratedPost(
                channel_kind="results",
                destination=self.settings.results_channel,
                content_type=self.RESULTS_BEST_FOLLOWUP_CONTENT_TYPE,
                generated_text=self._format_results_best_followups_digest(
                    winners,
                    slot_hour=slot_hour,
                    local_now=local_now,
                ),
                status="generated",
                force_autopost=True,
                send_lab_copy=False,
                metadata={
                    "slot_hour": slot_hour,
                    "summary_date": local_now.date().isoformat(),
                    "alert_ids": [alert.id for alert, _followup in winners],
                    "symbols": [normalize_symbol(followup.symbol) for _alert, followup in winners],
                    "winner_count": len(winners),
                },
            )
            delivery = await self.router.route_generated_post(post)
            if not delivery.sent:
                continue
            sent_slot_hours.add(slot_hour)
            sent_alert_ids.update(alert.id for alert, _followup in winners)
            LOGGER.info(
                "RESULTS best follow-up digest sent slot=%s winners=%s destination=%s",
                slot_hour,
                len(winners),
                self.settings.results_channel,
            )

    async def run_results_channel_maintenance(self) -> None:
        await self._send_results_channel_best_followups_if_due()

    async def handle_task(self, task: FollowUpTaskRecord) -> None:
        attempt_number = task.attempts + 1
        await self.repository.mark_followup_processing(task.id, attempt_number)
        result_chart_path = None

        try:
            alert_record = await self.repository.get_alert(task.alert_id)
            if alert_record is None:
                raise RuntimeError(f"Alert {task.alert_id} not found")

            expected_due_at = task.due_at
            now = utc_now()
            if now < expected_due_at:
                LOGGER.warning(
                    "Follow-up task %s for %s stage=%s became due too early. "
                    "Rescheduling from %s to %s"
                    % (
                        task.id,
                        alert_record.symbol,
                        task.stage,
                        task.due_at.isoformat(),
                        expected_due_at.isoformat(),
                    )
                )
                await self.repository.reschedule_followup(
                    task.id,
                    expected_due_at,
                    "followup_guard_early",
                    attempt_number,
                )
                return

            max_lateness = timedelta(minutes=self.settings.followup_max_lateness_minutes)
            lateness = now - expected_due_at
            if lateness > max_lateness:
                LOGGER.warning(
                    "Skipping stale follow-up task %s for %s stage=%s because it is %s late "
                    "(expected %s, now %s)"
                    % (
                        task.id,
                        alert_record.symbol,
                        task.stage,
                        lateness,
                        expected_due_at.isoformat(),
                        now.isoformat(),
                    )
                )
                await self.repository.mark_followup_skipped(
                    task.id,
                    f"followup_stale:{int(lateness.total_seconds())}s",
                    now,
                )
                return

            ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=False)
            frame = await self.binance_client.get_klines(
                alert_record.symbol,
                self.settings.scan_timeframe,
                self.settings.klines_limit,
            )
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            if enriched.empty:
                raise RuntimeError(f"No candles available for follow-up on {alert_record.symbol}")

            row = enriched.iloc[-1]
            latest_15m_close_price = float(row["close"])
            current_rsi = float(row["rsi"])
            ticker = ticker_map.get(alert_record.symbol)
            current_market_price = (
                float(ticker.last_price)
                if ticker is not None and ticker.last_price
                else latest_15m_close_price
            )
            live_rsi = calculate_live_rsi(enriched["close"], current_market_price, self.settings.rsi_length)
            move_pct = calc_pct_change(alert_record.alert_price, current_market_price)
            candle_move_pct = calc_pct_change(alert_record.alert_price, latest_15m_close_price)
            LOGGER.debug(
                "Follow-up RSI snapshot symbol=%s timeframe=%s closed_rsi=%.2f live_rsi=%s candle_close=%s live_price=%.8f source=binance_futures_klines+wilder_rma",
                alert_record.symbol,
                self.settings.scan_timeframe,
                current_rsi,
                f"{live_rsi:.2f}" if live_rsi is not None else "n/a",
                row["close_time"].to_pydatetime().isoformat(),
                current_market_price,
            )
            observed_at = utc_now()
            elapsed_seconds = max((observed_at - alert_record.alert_sent_at).total_seconds(), 0.0)
            thesis = evaluate_thesis_result(alert_record.direction, move_pct)
            summary = summarize_followup(
                alert_record.direction,
                stage=task.stage,
                market_move_pct=move_pct,
                candle_move_pct=candle_move_pct,
                current_rsi=current_rsi,
                alert_rsi=alert_record.alert_rsi,
            )
            signal = AlertSignal(
                symbol=alert_record.symbol,
                direction=alert_record.direction,
                timeframe=alert_record.timeframe,
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
                score=alert_record.score,
                explanation=alert_record.metadata.get("explanation", ""),
                metadata={
                    **alert_record.metadata,
                    "strategy_key": alert_record.strategy_key,
                    "origin_timeframe": alert_record.timeframe,
                    "followup_stage": task.stage,
                    "latest_followup_stage": task.stage,
                },
            )

            result = FollowUpResult(
                alert_id=alert_record.id,
                symbol=alert_record.symbol,
                direction=alert_record.direction,
                timeframe=alert_record.timeframe,
                alert_price=alert_record.alert_price,
                current_price=current_market_price,
                alert_rsi=alert_record.alert_rsi,
                current_rsi=current_rsi,
                move_pct=move_pct,
                summary=summary,
                score=alert_record.score,
                observed_at=observed_at,
                stage=task.stage,
                thesis_direction=thesis.thesis_direction,
                favorable_move_pct=thesis.favorable_move_pct,
                adverse_move_pct=thesis.adverse_move_pct,
                thesis_result_state=thesis.thesis_result_state,
                metadata={
                    "followup_stage": task.stage,
                    "thesis_direction": thesis.thesis_direction,
                    "favorable_move_pct": thesis.favorable_move_pct,
                    "adverse_move_pct": thesis.adverse_move_pct,
                    "thesis_result_state": thesis.thesis_result_state,
                    "alert_timeframe": alert_record.timeframe,
                    "marker_price": alert_record.alert_price,
                    "marker_candle_open_time": alert_record.candle_open_time.isoformat(),
                    "marker_candle_close_time": alert_record.candle_close_time.isoformat(),
                    "asset_class": alert_record.metadata.get("asset_class"),
                    "strategy_key": alert_record.strategy_key,
                    "external_link_label": alert_record.metadata.get("external_link_label"),
                    "external_link_url": alert_record.metadata.get("external_link_url"),
                    "interactive_ai_enabled": alert_record.metadata.get("interactive_ai_enabled"),
                    "interactive_risk_enabled": alert_record.metadata.get("interactive_risk_enabled"),
                    "interactive_reason_enabled": alert_record.metadata.get("interactive_reason_enabled"),
                    "24h_change_pct": ticker.price_change_percent if ticker else None,
                    "current_candle_close_price": latest_15m_close_price,
                    "candle_move_pct": candle_move_pct,
                    "current_market_price_source": "ticker_last_price" if ticker is not None else "last_closed_15m_close",
                    "live_rsi": live_rsi,
                    "rsi_mode": "closed_with_live_secondary",
                    "rsi_source": "binance_futures_klines+wilder_rma",
                    "signal_candle_close_time": row["close_time"].to_pydatetime().isoformat(),
                    "elapsed_seconds": elapsed_seconds,
                },
            )
            LOGGER.info(
                "Follow-up result computed alert_id=%s symbol=%s stage=%s state=%s favorable=%+.2f%% adverse=%+.2f%% raw=%+.2f%%",
                alert_record.id,
                alert_record.symbol,
                task.stage,
                thesis.thesis_result_state,
                thesis.favorable_move_pct,
                thesis.adverse_move_pct,
                move_pct,
            )

            # Persist the observation before any Telegram or chart work. A retry after
            # an outbound failure therefore updates this same (alert_id, stage) record
            # instead of inventing a second follow-up event.
            lifecycle_record = await self.repository.get_tracked_signal_by_alert_id(alert_record.id)
            if lifecycle_record is None:
                lifecycle_record = await self.lifecycle_service.create_signal(
                    signal=signal,
                    alert_id=alert_record.id,
                    created_at=alert_record.alert_sent_at,
                    source_type="followup_backfill",
                )
            lifecycle_record = await self.lifecycle_service.evaluate_signal_state(
                lifecycle_record,
                high_price=current_market_price,
                low_price=current_market_price,
                close_price=current_market_price,
                observed_at=observed_at,
            )
            result.metadata.update(
                {
                    "signal_id": lifecycle_record.signal_id,
                    "signal_status": lifecycle_record.status,
                    "lifecycle_status": lifecycle_record.status,
                    "result_type": lifecycle_record.result_type,
                    "mfe_percent": lifecycle_record.mfe_percent,
                    "mae_percent": lifecycle_record.mae_percent,
                }
            )
            await self.repository.save_followup_result(result)

            result.chart_path = await self.chart_renderer.render_followup_chart(enriched, result)
            if self.settings.result_chart_generation_enabled:
                result_chart_path = await self.chart_renderer.render_result_chart(
                    enriched,
                    signal,
                    result,
                    label=f"{task.stage} Result",
                )
            delivery = None
            if self.settings.curated_lab_only_mode:
                LOGGER.info(
                    "Skipping LAB follow-up card for %s stage=%s because curated LAB-only mode keeps LAB for curated X/thought ideas",
                    result.symbol,
                    result.stage,
                )
            else:
                delivery = await self.router.send_followup(result)
                if self.interactive_alert_service is not None:
                    await self.interactive_alert_service.register_alert_message(
                        destination_kind="lab",
                        chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.lab_channel),
                        message_id=delivery.telegram_message_id,
                        signal=signal,
                        alert_id=alert_record.id,
                        is_preview=False,
                        message_kind="followup",
                    )
            await self.repository.mark_followup_complete(task.id, task.alert_id, result.observed_at)
            LOGGER.info(
                "Follow-up executed alert_id=%s symbol=%s stage=%s destination=lab sent=%s",
                task.alert_id,
                alert_record.symbol,
                task.stage,
                delivery.sent if delivery is not None else False,
            )
            is_gold_followup = str(alert_record.metadata.get("asset_class") or "").lower() == "gold"
            if (
                self.prepared_feature_service is not None
                and not is_gold_followup
                and self._is_public_stream_strategy(signal)
                and signal.score >= self.settings.pro_followup_min_score
            ):
                self.prepared_feature_service.schedule_prepare_for_signal(signal, alert_record.id)
            twitter_followup_mirror = None
            if self.twitter_draft_service is not None and not is_gold_followup and self._is_public_stream_strategy(signal):
                try:
                    twitter_followup_mirror = await self.twitter_draft_service.assess_followup_mirror(signal, result)
                    LOGGER.info(
                        "Follow-up mirror assessment symbol=%s stage=%s eligible=%s reason=%s favorable=%+.2f%% proof=%.1f chart=%.1f",
                        signal.symbol,
                        result.stage,
                        twitter_followup_mirror.eligible,
                        twitter_followup_mirror.reason,
                        twitter_followup_mirror.favorable_move_pct,
                        twitter_followup_mirror.proof_value,
                        twitter_followup_mirror.chart_value,
                    )
                except Exception:
                    LOGGER.exception(
                        "Failed to assess Twitter-worthy mirror policy for follow-up symbol=%s stage=%s",
                        signal.symbol,
                        result.stage,
                    )
            if self.private_bot_service is not None:
                await self.private_bot_service.deliver_pro_followup(
                    signal,
                    result,
                    preferred_chart_path=result_chart_path,
                    mirror_if_twitter_eligible=bool(twitter_followup_mirror and twitter_followup_mirror.eligible),
                )
            if self.classic_bot_service is not None and not is_gold_followup and self._is_public_stream_strategy(signal):
                await self.classic_bot_service.deliver_classic_followup(
                    signal,
                    result,
                    preferred_chart_path=result_chart_path,
                )

            if is_gold_followup:
                LOGGER.info(
                    "Skipping external gold follow-up fanout for %s stage=%s; premium-only gold stream",
                    signal.symbol,
                    result.stage,
                )
                return
            if not self._is_public_stream_strategy(signal):
                LOGGER.info(
                    "Skipping classic/public follow-up fanout for %s stage=%s strategy=%s; premium-only strategy stream",
                    signal.symbol,
                    result.stage,
                    self._signal_strategy_key(signal),
                )
                return

            try:
                external_posts = []
                posts = await self.draft_generator.generate_for_followup(
                    signal,
                    result,
                    result_chart_path=result_chart_path,
                    force_results_followup=bool(twitter_followup_mirror and twitter_followup_mirror.eligible),
                )
                lab_posts = [post for post in posts if post.channel_kind == "lab"]
                external_posts = [post for post in posts if post.channel_kind != "lab"]
                for post in lab_posts:
                    await self.router.route_generated_post(post)
                for post in external_posts:
                    post.bundle_in_lab_review = not self.settings.curated_lab_only_mode
                    delivery = await self.router.route_generated_post(post)
                    scheduler = getattr(self, "scheduled_post_scheduler", None)
                    if scheduler is not None and delivery.metadata.get("scheduled"):
                        scheduler.notify()
                    if (
                        self.interactive_alert_service is not None
                        and post.channel_kind in {"public", "pro", "results"}
                        and delivery.sent
                        and delivery.telegram_message_id is not None
                    ):
                        await self.interactive_alert_service.register_alert_message(
                            destination_kind=post.channel_kind,
                            chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.telegram_destinations[post.channel_kind]),
                            message_id=delivery.telegram_message_id,
                            signal=signal,
                            alert_id=alert_record.id,
                            is_preview=False,
                            message_kind="followup",
                        )
                twitter_draft = None
                if self.twitter_draft_service is not None:
                    twitter_draft = await self.twitter_draft_service.handle_followup(
                        signal,
                        result,
                        preferred_chart_path=result_chart_path,
                    )
                if not self.settings.curated_lab_only_mode:
                    await self.router.send_lab_review_bundle(
                        symbol=signal.symbol,
                        scope="followup",
                        posts=external_posts,
                        twitter_draft=twitter_draft,
                    )
            except Exception:  # pragma: no cover - runtime dependent
                LOGGER.exception(
                    "Follow-up post fanout failed for task %s after the core follow-up was already completed",
                    task.id,
                )
        except Exception as exc:  # pragma: no cover - runtime dependent
            LOGGER.exception("Follow-up task %s failed", task.id)
            retry_at = utc_now() + timedelta(minutes=min(15 * attempt_number, 60))
            await self.repository.reschedule_followup(task.id, retry_at, str(exc), attempt_number)
        finally:
            self.chart_renderer.cleanup(
                locals().get("result").chart_path if "result" in locals() else None
            )
            self.chart_renderer.cleanup(result_chart_path)
