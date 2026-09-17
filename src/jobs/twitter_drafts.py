from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.ai.twitter_context import build_daily_context, build_followup_context, build_signal_context
from src.ai.twitter_generators import TwitterDraftGenerator
from src.bot.interactive_alerts import InteractiveAlertService
from src.bot.routing import MessageRouter
from src.charts.renderer import ChartRenderer
from src.core.config import Settings
from src.core.models import AlertSignal, FollowUpResult, TwitterDraft
from src.core.utils import calc_pct_change, local_day_bounds, parse_hhmm, utc_now
from src.market.binance_client import BinanceClient
from src.market.indicators import enrich_klines
from src.storage.models import AlertRecord, FollowUpResultRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _FollowUpTwitterAssessment:
    eligible: bool
    package_candidate: bool
    chart_candidate: bool
    primary_type: str | None
    priority: float
    chart_priority: float
    proof_value: float
    learning_value: float
    favorable: bool
    favorable_move_pct: float
    adverse_move_pct: float
    rsi_recovery: float
    skip_reason: str


@dataclass(frozen=True, slots=True)
class _TwitterFollowUpSendDecision:
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class FollowUpMirrorDecision:
    eligible: bool
    reason: str
    favorable_move_pct: float
    proof_value: float
    chart_value: float
    stage: str
    thesis_result_state: str


class TwitterDraftService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        binance_client: BinanceClient,
        chart_renderer: ChartRenderer,
        router: MessageRouter,
        generator: TwitterDraftGenerator,
        interactive_alert_service: InteractiveAlertService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.binance_client = binance_client
        self.chart_renderer = chart_renderer
        self.router = router
        self.generator = generator
        self.interactive_alert_service = interactive_alert_service

    async def send_preview_package_if_enabled(self) -> None:
        if not self.settings.x_drafts_enabled or not self.settings.x_preview_all_types:
            return

        LOGGER.info("X preview mode enabled. Building full preview package.")
        recent_drafts = await self.repository.list_recent_twitter_drafts(limit=40)
        sent_recent_drafts = await self.repository.list_recent_twitter_drafts(limit=220, statuses=("sent",))
        best_alerts = await self._load_recent_alerts(days=7, limit=12, min_score=0, min_quote_volume=0)
        followups = await self.repository.list_followup_results_between(
            start=utc_now() - timedelta(days=7),
            end=utc_now() + timedelta(minutes=1),
            limit=24,
        )

        best_alert = best_alerts[0] if best_alerts else None
        preview_signal = await self._resolve_preview_signal(best_alert)
        preview_followup = await self._resolve_preview_followup(best_alert, preview_signal, followups)
        session_date = utc_now().astimezone(self.settings.timezone).date()
        preview_alert_records = best_alerts or [self._signal_to_alert_record(best_alert, preview_signal)]
        preview_followup_records = followups or (
            [self._followup_result_to_record(preview_followup[1])] if preview_followup is not None else []
        )
        daily_context = build_daily_context(
            session_date,
            preview_alert_records,
            preview_followup_records,
        )

        preview_drafts: list[TwitterDraft] = []
        interactive_preview_map: dict[int, tuple[AlertSignal, str]] = {}
        
        def _remember(
            draft: TwitterDraft,
            *,
            interactive_signal: AlertSignal | None = None,
            message_kind: str = "alert",
        ) -> None:
            preview_drafts.append(draft)
            recent_drafts.append(draft)
            if interactive_signal is not None:
                interactive_preview_map[id(draft)] = (interactive_signal, message_kind)

        best_setup_chart = await self._render_signal_chart(preview_signal)
        best_setup_draft = await self.generator.generate_best_setup_draft(
            prepared_context=self._signal_prepared_context(
                preview_signal,
                reason="Best available setup for preview mode.",
                chart_available=True,
            ),
            source_symbol=preview_signal.symbol,
            score=preview_signal.score,
            related_alert_id=best_alert.id if best_alert else None,
            chart_path=best_setup_chart,
            recent_drafts=recent_drafts,
            preview_mode=True,
        )
        best_setup_draft.metadata["owned_chart"] = True
        best_setup_draft.metadata["interactive_timeframe"] = preview_signal.timeframe
        _remember(best_setup_draft, interactive_signal=preview_signal, message_kind="alert")

        if preview_followup is not None:
            preview_signal_for_followup, preview_followup_result = preview_followup
            followup_chart = await self._render_followup_chart(preview_followup_result)
            followup_draft = await self.generator.generate_followup_result_draft(
                prepared_context=self._followup_prepared_context(preview_signal_for_followup, preview_followup_result),
                source_symbol=preview_followup_result.symbol,
                score=preview_followup_result.score,
                related_alert_id=preview_followup_result.alert_id,
                chart_path=followup_chart,
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
            followup_draft.metadata["owned_chart"] = True
            followup_draft.metadata["interactive_timeframe"] = preview_followup_result.timeframe
            _remember(
                followup_draft,
                interactive_signal=preview_signal_for_followup,
                message_kind="followup" if preview_followup_result.alert_id else "alert",
            )
            followup_chart_2 = await self._render_followup_chart(preview_followup_result)
            fomo_draft = await self.generator.generate_fomo_or_missed_move_draft(
                prepared_context=self._followup_prepared_context(preview_signal_for_followup, preview_followup_result),
                source_symbol=preview_followup_result.symbol,
                score=preview_followup_result.score,
                related_alert_id=preview_followup_result.alert_id,
                chart_path=followup_chart_2,
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
            fomo_draft.metadata["owned_chart"] = True
            fomo_draft.metadata["interactive_timeframe"] = preview_followup_result.timeframe
            _remember(
                fomo_draft,
                interactive_signal=preview_signal_for_followup,
                message_kind="followup" if preview_followup_result.alert_id else "alert",
            )

        _remember(
            await self.generator.generate_market_insight_draft(
                prepared_context=self._daily_prepared_context(daily_context, extra_reason="Previewing the market insight style."),
                source_symbol=None,
                score=None,
                related_alert_id=None,
                chart_path=None,
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
        )
        _remember(
            await self.generator.generate_operator_opinion_draft(
                prepared_context=self._daily_prepared_context(daily_context, extra_reason="Previewing the operator opinion style."),
                source_symbol=None,
                score=None,
                related_alert_id=None,
                chart_path=None,
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
        )
        chart_preview_draft = await self.generator.generate_chart_draft(
            prepared_context=self._signal_prepared_context(
                preview_signal,
                reason="Previewing the chart-first style.",
                chart_available=True,
            ),
            source_symbol=preview_signal.symbol,
            score=preview_signal.score,
            related_alert_id=best_alert.id if best_alert else None,
            chart_path=await self._render_signal_chart(preview_signal),
            recent_drafts=recent_drafts,
            preview_mode=True,
        )
        chart_preview_draft.metadata["owned_chart"] = True
        chart_preview_draft.metadata["interactive_timeframe"] = preview_signal.timeframe
        _remember(chart_preview_draft, interactive_signal=preview_signal, message_kind="alert")
        _remember(
            await self.generator.generate_daily_recap_draft(
                prepared_context=self._daily_prepared_context(daily_context, extra_reason="Previewing the daily recap style."),
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
        )
        _remember(
            await self.generator.generate_daily_stats_draft(
                prepared_context=self._daily_prepared_context(daily_context, extra_reason="Previewing the daily stats style."),
                recent_drafts=recent_drafts,
                preview_mode=True,
            )
        )

        for draft in preview_drafts:
            interactive = interactive_preview_map.get(id(draft))
            if interactive is not None:
                interactive_signal, message_kind = interactive
                await self._finalize_draft(
                    draft,
                    interactive_signal=interactive_signal,
                    message_kind=message_kind,
                )
            else:
                await self._finalize_draft(draft)

    async def handle_alert(self, signal: AlertSignal, related_alert_id: int) -> TwitterDraft | None:
        if not self.settings.x_drafts_enabled or not self.settings.x_signal_drafts:
            return None

        if not self._alert_is_best_setup_candidate(signal):
            await self._store_skip(
                content_type="twitter_best_setup_post",
                source_symbol=signal.symbol,
                score=signal.score,
                related_alert_id=related_alert_id,
                skip_reason="weak_setup",
            )
            return None

        if await self._remaining_daily_slots() <= 0:
            LOGGER.info("Skipping X best-setup draft for %s because daily cap was reached", signal.symbol)
            return None

        recent_drafts = await self.repository.list_recent_twitter_drafts(limit=40)
        owned_chart = False
        chart_path = signal.chart_path
        if chart_path is None:
            try:
                chart_path = await self._render_signal_chart(signal)
                owned_chart = True
            except Exception:  # pragma: no cover - runtime dependent
                LOGGER.exception("Failed to backfill X chart for live setup draft on %s", signal.symbol)
        draft = await self.generator.generate_best_setup_draft(
            prepared_context=self._signal_prepared_context(signal, reason="Potential best setup candidate from live flow."),
            source_symbol=signal.symbol,
            score=signal.score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
        )
        if owned_chart:
            draft.metadata["owned_chart"] = True
        draft.metadata["interactive_timeframe"] = signal.timeframe
        return await self._finalize_draft(
            draft,
            interactive_signal=signal,
            message_kind="alert",
        )

    async def handle_followup(
        self,
        signal: AlertSignal,
        followup: FollowUpResult,
        *,
        preferred_chart_path=None,
    ) -> TwitterDraft | None:
        if not self.settings.x_drafts_enabled or not self.settings.x_followup_drafts or not self.settings.twitter_proof_posts_enabled:
            return None

        bypass_followup_filters = self.settings.twitter_all_followups_enabled

        if not bypass_followup_filters and await self._remaining_daily_slots() <= 0:
            await self._store_skip(
                content_type="twitter_followup_result_post",
                source_symbol=followup.symbol,
                score=followup.score,
                related_alert_id=followup.alert_id,
                skip_reason="daily_cap_reached",
                metadata={
                    "followup_stage": followup.stage,
                    "thesis_result_state": followup.thesis_result_state,
                },
            )
            return None
        if bypass_followup_filters and await self._remaining_daily_slots() <= 0:
            LOGGER.info(
                "X follow-up for %s stage=%s is bypassing daily cap because TWITTER_ALL_FOLLOWUPS_ENABLED is on",
                followup.symbol,
                followup.stage,
            )

        recent_drafts = await self.repository.list_recent_twitter_drafts(limit=160)
        sent_recent_drafts = await self.repository.list_recent_twitter_drafts(limit=220, statuses=("sent",))
        if self._followup_case_key(followup.alert_id, followup.stage) in self._recent_followup_case_keys(recent_drafts):
            await self._store_skip(
                content_type="twitter_followup_result_post",
                source_symbol=followup.symbol,
                score=followup.score,
                related_alert_id=followup.alert_id,
                skip_reason="duplicate_recent_case",
                metadata={
                    "followup_stage": followup.stage,
                    "thesis_result_state": followup.thesis_result_state,
                },
            )
            return None

        send_decision = self._evaluate_followup_send_policy(followup, sent_recent_drafts)
        if not send_decision.eligible:
            await self._store_skip(
                content_type="twitter_followup_result_post",
                source_symbol=followup.symbol,
                score=followup.score,
                related_alert_id=followup.alert_id,
                skip_reason=send_decision.reason,
                metadata={
                    "followup_stage": followup.stage,
                    "thesis_result_state": followup.thesis_result_state,
                    "favorable_move_pct": followup.favorable_move_pct,
                    "adverse_move_pct": followup.adverse_move_pct,
                },
            )
            LOGGER.info(
                "X follow-up skipped symbol=%s stage=%s reason=%s",
                followup.symbol,
                followup.stage,
                send_decision.reason,
            )
            return None

        assessment = self._assess_followup_candidate(signal, followup)
        if not assessment.eligible and not bypass_followup_filters:
            await self._store_skip(
                content_type="twitter_followup_result_post",
                source_symbol=followup.symbol,
                score=followup.score,
                related_alert_id=followup.alert_id,
                skip_reason=assessment.skip_reason,
                metadata={
                    "followup_stage": followup.stage,
                    "thesis_result_state": followup.thesis_result_state or ("favorable" if assessment.favorable else "adverse"),
                    "favorable_move_pct": assessment.favorable_move_pct,
                    "adverse_move_pct": assessment.adverse_move_pct,
                    "proof_value": round(assessment.proof_value, 2),
                    "learning_value": round(assessment.learning_value, 2),
                    "chart_value": round(assessment.chart_priority, 2),
                },
            )
            LOGGER.info(
                "X follow-up skipped symbol=%s stage=%s reason=%s favorable=%s favorable_move=%.2f proof=%.1f chart=%.1f",
                followup.symbol,
                followup.stage,
                assessment.skip_reason,
                assessment.favorable,
                assessment.favorable_move_pct,
                assessment.proof_value,
                assessment.chart_priority,
            )
            return None
        if not assessment.eligible and bypass_followup_filters:
            LOGGER.info(
                "X follow-up for %s stage=%s is being mirrored despite strict skip reason=%s",
                followup.symbol,
                followup.stage,
                assessment.skip_reason,
            )

        draft_type = assessment.primary_type or "twitter_followup_result_post"
        LOGGER.info(
            "X follow-up eligible symbol=%s stage=%s type=%s favorable_move=%.2f proof=%.1f chart=%.1f",
            followup.symbol,
            followup.stage,
            draft_type,
            assessment.favorable_move_pct,
            assessment.proof_value,
            assessment.chart_priority,
        )

        prepared_context = self._followup_prepared_context(signal, followup)
        owned_chart = False
        chart_path = preferred_chart_path or followup.chart_path
        if chart_path is None:
            try:
                chart_path = await self._render_result_chart(signal, followup)
                owned_chart = True
            except Exception:  # pragma: no cover - runtime dependent
                LOGGER.exception("Failed to backfill X chart for follow-up draft on %s", followup.symbol)
        if not assessment.eligible and bypass_followup_filters:
            draft = self._build_mirrored_followup_draft(
                signal=signal,
                followup=followup,
                chart_path=chart_path,
                assessment=assessment,
            )
        else:
            if draft_type == "twitter_fomo_or_missed_move_post":
                draft = await self.generator.generate_fomo_or_missed_move_draft(
                    prepared_context=prepared_context,
                    source_symbol=followup.symbol,
                    score=followup.score,
                    related_alert_id=followup.alert_id,
                    chart_path=chart_path,
                    recent_drafts=recent_drafts,
                )
            else:
                draft = await self.generator.generate_followup_result_draft(
                    prepared_context=prepared_context,
                    source_symbol=followup.symbol,
                    score=followup.score,
                    related_alert_id=followup.alert_id,
                    chart_path=chart_path,
                    recent_drafts=recent_drafts,
                )
            if draft.status == "skipped" and bypass_followup_filters:
                LOGGER.info(
                    "X follow-up for %s stage=%s fell back to mirrored final draft after generator skip reason=%s",
                    followup.symbol,
                    followup.stage,
                    draft.skipped_reason,
                )
                draft = self._build_mirrored_followup_draft(
                    signal=signal,
                    followup=followup,
                    chart_path=chart_path,
                    assessment=assessment,
                )
        if owned_chart:
            draft.metadata["owned_chart"] = True
        draft.metadata["interactive_timeframe"] = followup.timeframe
        draft.metadata["followup_stage"] = followup.stage
        draft.metadata["thesis_result_state"] = followup.thesis_result_state or ("favorable" if assessment.favorable else "adverse")
        draft.metadata["favorable_move_pct"] = followup.favorable_move_pct
        draft.metadata["adverse_move_pct"] = followup.adverse_move_pct
        draft.metadata["proof_value"] = round(assessment.proof_value, 2)
        draft.metadata["chart_value"] = round(assessment.chart_priority, 2)
        return await self._finalize_draft(
            draft,
            interactive_signal=signal,
            message_kind="followup" if followup.alert_id else "alert",
        )

    async def assess_followup_mirror(
        self,
        signal: AlertSignal,
        followup: FollowUpResult,
    ) -> FollowUpMirrorDecision:
        recent_drafts = await self.repository.list_recent_twitter_drafts(limit=160)
        sent_recent_drafts = await self.repository.list_recent_twitter_drafts(limit=220, statuses=("sent",))
        if self._followup_case_key(followup.alert_id, followup.stage) in self._recent_followup_case_keys(recent_drafts):
            return FollowUpMirrorDecision(
                eligible=False,
                reason="duplicate_recent_case",
                favorable_move_pct=float(followup.favorable_move_pct or 0.0),
                proof_value=0.0,
                chart_value=0.0,
                stage=followup.stage,
                thesis_result_state=followup.thesis_result_state or "neutral",
            )

        send_decision = self._evaluate_followup_send_policy(followup, sent_recent_drafts)
        assessment = self._assess_followup_candidate(signal, followup)
        eligible = send_decision.eligible and (assessment.eligible or self.settings.twitter_all_followups_enabled)
        reason = send_decision.reason if not send_decision.eligible else (
            "twitter_followup_mirror_enabled"
            if (assessment.eligible or self.settings.twitter_all_followups_enabled)
            else assessment.skip_reason
        )
        return FollowUpMirrorDecision(
            eligible=eligible,
            reason=reason,
            favorable_move_pct=float(assessment.favorable_move_pct),
            proof_value=float(assessment.proof_value),
            chart_value=float(assessment.chart_priority),
            stage=followup.stage,
            thesis_result_state=followup.thesis_result_state or ("favorable" if assessment.favorable else "neutral"),
        )

    def _build_mirrored_followup_draft(
        self,
        *,
        signal: AlertSignal,
        followup: FollowUpResult,
        chart_path,
        assessment: _FollowUpTwitterAssessment,
    ) -> TwitterDraft:
        state = followup.thesis_result_state or ("favorable" if assessment.favorable else "adverse")
        if state == "favorable":
            main_text = (
                f"{followup.symbol} was flagged on the {signal.timeframe} board, then printed a {followup.favorable_move_pct:+.2f}% move in the original thesis direction by the {followup.stage} check.\n\n"
                f"That is the useful part: the market respected the setup after the signal instead of leaving it as a raw RSI print.\n\n"
                f"RSI shifted from {followup.alert_rsi:.2f} to {followup.current_rsi:.2f}, which made the follow-through easier to trust."
            )
            angle = "result"
            value_types = ("proof value", "learning value")
        elif state == "adverse":
            main_text = (
                f"{followup.symbol} was flagged on the {signal.timeframe} board, but by the {followup.stage} check it had moved {followup.adverse_move_pct:+.2f}% against the original thesis.\n\n"
                "That still matters because transparent follow-up is more useful than pretending every extreme was a win.\n\n"
                "The lesson here is simple: the trigger printed, but the market never confirmed the idea cleanly enough."
            )
            angle = "lesson"
            value_types = ("learning value", "decision value")
        else:
            main_text = (
                f"{followup.symbol} was flagged on the {signal.timeframe} board, and by the {followup.stage} follow-up it was still sitting close to the original alert level.\n\n"
                "That makes it more of a context case than a proof case for now.\n\n"
                "Useful reminder: not every trigger earns real follow-through, and neutral outcomes still help frame what was worth attention."
            )
            angle = "observation"
            value_types = ("watchlist value", "learning value")

        return TwitterDraft(
            destination=self.settings.twitter_drafts_chat,
            content_type="twitter_followup_result_post",
            main_text=main_text.strip(),
            mode="NORMAL",
            angle=angle,
            value_types=value_types,
            source_symbol=followup.symbol,
            related_alert_id=followup.alert_id,
            score=followup.score,
            chart_path=chart_path,
            writer_model="followup-mirror-template",
            analysis_model="followup-mirror-template",
            status="generated",
            preview_mode=False,
            metadata={
                "generated_at": utc_now().isoformat(),
                "followup_stage": followup.stage,
                "thesis_result_state": state,
                "favorable_move_pct": followup.favorable_move_pct,
                "adverse_move_pct": followup.adverse_move_pct,
                "mirror_all_followups": True,
                "proof_value": round(assessment.proof_value, 2),
                "chart_value": round(assessment.chart_priority, 2),
            },
        )

    async def run_scheduled_jobs(self) -> None:
        if not self.settings.x_drafts_enabled:
            return

        remaining_slots = await self._remaining_daily_slots()
        if remaining_slots <= 0:
            return

        now_local = utc_now().astimezone(self.settings.timezone)
        session_date = now_local.date()
        alerts = await self._load_recent_alerts(days=1, limit=50, min_score=self.settings.x_min_score, min_quote_volume=self.settings.x_min_quote_volume)
        followups = await self.repository.list_followup_results_between(
            start=local_day_bounds(session_date, self.settings.timezone)[0],
            end=local_day_bounds(session_date, self.settings.timezone)[1],
            limit=50,
        )
        if not alerts and not followups:
            return

        recent_drafts = await self.repository.list_recent_twitter_drafts(limit=12)
        daily_context = build_daily_context(session_date, alerts, followups)
        scan_time = parse_hhmm(self.settings.x_daily_scan_time)
        package_time = parse_hhmm(self.settings.x_end_of_day_package_time)

        if (
            self.settings.x_daily_scan_draft
            and now_local.time() >= scan_time
            and await self._should_send_today("twitter_market_insight_post", session_date)
            and self._daily_context_is_meaningful(daily_context)
            and remaining_slots > 0
        ):
            draft = await self.generator.generate_market_insight_draft(
                prepared_context=self._daily_prepared_context(daily_context, extra_reason="Market insight candidate from today's session."),
                source_symbol=None,
                score=None,
                related_alert_id=None,
                chart_path=None,
                recent_drafts=recent_drafts,
            )
            await self._finalize_draft(draft)
            remaining_slots = await self._remaining_daily_slots()

        if now_local.time() < package_time or remaining_slots <= 0:
            return

        package_drafts: list[TwitterDraft] = []
        ranked_followups = await self._rank_followup_records_for_twitter(followups, recent_drafts, sent_recent_drafts)
        chart_slots = min(2, remaining_slots)
        selected_followup_alerts: set[int] = set()
        for ranked in ranked_followups:
            if len([draft for draft in package_drafts if draft.content_type == "twitter_chart_post"]) >= chart_slots:
                break
            if len(package_drafts) >= remaining_slots:
                break
            if ranked["record"].alert_id in selected_followup_alerts:
                LOGGER.info(
                    "X follow-up package skipped symbol=%s stage=%s reason=repetitive_with_another_stronger_case",
                    ranked["record"].symbol,
                    ranked["record"].stage,
                )
                continue
            chart_draft = await self._build_chart_draft_from_followup(
                ranked["record"],
                recent_drafts + package_drafts,
                signal=ranked["signal"],
                followup_result=ranked["followup"],
                assessment=ranked["assessment"],
            )
            if chart_draft is not None:
                package_drafts.append(chart_draft)
                selected_followup_alerts.add(ranked["record"].alert_id)
                LOGGER.info(
                    "X follow-up package selected symbol=%s stage=%s proof=%.1f chart=%.1f",
                    ranked["record"].symbol,
                    ranked["record"].stage,
                    ranked["assessment"].proof_value,
                    ranked["assessment"].chart_priority,
                )
        if (
            self.settings.x_daily_recap_draft
            and len(package_drafts) < remaining_slots
            and await self._should_send_today("twitter_daily_recap_post", session_date)
        ):
            package_drafts.append(
                await self.generator.generate_daily_recap_draft(
                    prepared_context=self._daily_prepared_context(daily_context, extra_reason="End-of-day recap candidate."),
                    recent_drafts=recent_drafts + package_drafts,
                )
            )
        if (
            self.settings.x_operator_posts
            and self.settings.twitter_operator_posts_enabled
            and len(package_drafts) < remaining_slots
            and await self._should_send_today("twitter_operator_opinion_post", session_date)
        ):
            package_drafts.append(
                await self.generator.generate_operator_opinion_draft(
                    prepared_context=self._daily_prepared_context(daily_context, extra_reason="Operator thought candidate from today's data."),
                    source_symbol=None,
                    score=None,
                    related_alert_id=None,
                    chart_path=None,
                    recent_drafts=recent_drafts + package_drafts,
                )
            )
        if (
            self.settings.x_daily_stats_draft
            and len(package_drafts) < remaining_slots
            and await self._should_send_today("twitter_daily_stats_post", session_date)
        ):
            package_drafts.append(
                await self.generator.generate_daily_stats_draft(
                    prepared_context=self._daily_prepared_context(daily_context, extra_reason="End-of-day stats candidate."),
                    recent_drafts=recent_drafts + package_drafts,
                )
            )
        if not any(draft.chart_path for draft in package_drafts):
            for alert in alerts[:1]:
                if len(package_drafts) >= remaining_slots:
                    break
                chart_draft = await self._build_chart_draft_from_alert(alert, recent_drafts + package_drafts)
                if chart_draft is not None:
                    package_drafts.append(chart_draft)

        for draft in package_drafts[:remaining_slots]:
            await self._finalize_draft(draft)

    async def _finalize_draft(
        self,
        draft: TwitterDraft,
        *,
        interactive_signal: AlertSignal | None = None,
        message_kind: str = "alert",
    ) -> TwitterDraft:
        try:
            if draft.status == "skipped":
                await self.repository.save_twitter_draft(draft=draft)
                LOGGER.info(
                    "X draft skipped type=%s source=%s stage=%s angle=%s reason=%s similarity=%s preview=%s",
                    draft.content_type,
                    draft.source_symbol,
                    draft.metadata.get("followup_stage"),
                    draft.angle,
                    draft.skipped_reason,
                    draft.similarity_score,
                    draft.preview_mode,
                )
                return draft

            if self._draft_requires_chart(draft) and draft.chart_path is None:
                missing_chart = TwitterDraft(
                    destination=draft.destination,
                    content_type=draft.content_type,
                    main_text="",
                    mode=draft.mode,
                    angle=draft.angle,
                    value_types=draft.value_types,
                    source_symbol=draft.source_symbol,
                    related_alert_id=draft.related_alert_id,
                    score=draft.score,
                    writer_model=draft.writer_model,
                    analysis_model=draft.analysis_model,
                    status="skipped",
                    preview_mode=draft.preview_mode,
                    skipped_reason="missing_chart",
                    metadata={**draft.metadata, "generated_at": utc_now().isoformat()},
                )
                await self.repository.save_twitter_draft(draft=missing_chart)
                LOGGER.info(
                    "X draft skipped type=%s source=%s stage=%s angle=%s reason=%s similarity=%s preview=%s",
                    missing_chart.content_type,
                    missing_chart.source_symbol,
                    missing_chart.metadata.get("followup_stage"),
                    missing_chart.angle,
                    missing_chart.skipped_reason,
                    missing_chart.similarity_score,
                    missing_chart.preview_mode,
                )
                return missing_chart

            delivery = await self.router.send_twitter_draft(draft)
            if draft.status in {"generated", "rewritten"}:
                if delivery.sent:
                    draft.status = "sent"
                elif delivery.rate_limited:
                    draft.status = "rate_limited"
                else:
                    draft.status = "failed"
            draft.metadata["delivery_sent"] = delivery.sent
            draft.metadata["delivery_rate_limited"] = delivery.rate_limited
            await self.repository.save_twitter_draft(
                draft=draft,
                sent_at=utc_now() if delivery.sent else None,
            )
            if (
                self.interactive_alert_service is not None
                and delivery.sent
                and delivery.telegram_message_id is not None
                and interactive_signal is not None
                and draft.source_symbol
                and draft.chart_path is not None
            ):
                await self.interactive_alert_service.register_alert_message(
                    destination_kind="twitter_drafts",
                    chat_id=str(delivery.metadata.get("telegram_chat_id") or self.settings.twitter_drafts_chat),
                    message_id=delivery.telegram_message_id,
                    signal=interactive_signal,
                    alert_id=draft.related_alert_id,
                    is_preview=draft.preview_mode,
                    message_kind=message_kind,
                )
            if self._should_mirror_draft_to_lab(draft):
                try:
                    await self.router.send_lab_review_bundle(
                        symbol=self._lab_symbol_for_draft(draft),
                        scope=self._lab_scope_for_draft(draft),
                        posts=[],
                        twitter_draft=draft,
                    )
                except Exception:  # pragma: no cover - runtime dependent
                    LOGGER.exception(
                        "Failed to mirror X draft into LAB type=%s source=%s",
                        draft.content_type,
                        draft.source_symbol,
                    )
            LOGGER.info(
                "X draft generated type=%s mode=%s stage=%s angle=%s value=%s source=%s score=%s status=%s similarity=%s rewritten=%s chart=%s",
                draft.content_type,
                draft.mode,
                draft.metadata.get("followup_stage"),
                draft.angle,
                ",".join(draft.value_types),
                draft.source_symbol,
                draft.score,
                draft.status,
                draft.similarity_score,
                draft.rewritten_for_similarity,
                bool(draft.chart_path),
            )
            return draft
        finally:
            if draft.metadata.get("owned_chart"):
                self.chart_renderer.cleanup(draft.chart_path)

    def _should_mirror_draft_to_lab(self, draft: TwitterDraft) -> bool:
        return self.settings.curated_lab_only_mode and not draft.preview_mode and draft.status != "skipped"

    def _lab_symbol_for_draft(self, draft: TwitterDraft) -> str:
        symbol = str(draft.source_symbol or "").strip().upper()
        return symbol or "MARKET"

    def _lab_scope_for_draft(self, draft: TwitterDraft) -> str:
        return "followup" if str(draft.metadata.get("followup_stage") or "").strip() else "alert"

    async def _store_skip(
        self,
        *,
        content_type: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        skip_reason: str,
        metadata: dict | None = None,
    ) -> None:
        draft = TwitterDraft(
            destination=self.settings.twitter_drafts_chat,
            content_type=content_type,
            main_text="",
            angle="",
            value_types=(),
            source_symbol=source_symbol,
            related_alert_id=related_alert_id,
            score=score,
            status="skipped",
            skipped_reason=skip_reason,
            metadata={"generated_at": utc_now().isoformat(), **(metadata or {})},
        )
        await self.repository.save_twitter_draft(draft=draft)
        LOGGER.info(
            "X draft skipped type=%s source=%s reason=%s metadata=%s",
            content_type,
            source_symbol,
            skip_reason,
            metadata or {},
        )

    async def _remaining_daily_slots(self) -> int:
        start_utc, _ = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        drafted_today = await self.repository.count_posts_history_since(
            destination="twitter_drafts",
            since=start_utc,
            channel_kind="twitter_drafts",
            statuses=("sent", "generated", "rewritten"),
            preview_mode=False,
        )
        return max(0, self.settings.x_max_drafts_per_day - drafted_today)

    async def _should_send_today(self, content_type: str, day) -> bool:
        start_utc, _ = local_day_bounds(day, self.settings.timezone)
        existing = await self.repository.count_posts_history_since(
            destination="twitter_drafts",
            since=start_utc,
            channel_kind="twitter_drafts",
            content_types=[content_type],
            statuses=("sent", "generated", "rewritten"),
            preview_mode=False,
        )
        return existing == 0

    async def _build_chart_draft_from_alert(
        self,
        alert: AlertRecord,
        recent_drafts: list[TwitterDraft],
    ) -> TwitterDraft | None:
        chart_path = None
        try:
            signal = self._alert_record_to_signal(alert)
            frame = await self.binance_client.get_klines(signal.symbol, signal.timeframe, self.settings.klines_limit)
            enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
            chart_path = await self.chart_renderer.render_alert_chart(enriched, signal)
            draft = await self.generator.generate_chart_draft(
                prepared_context=self._signal_prepared_context(
                    signal,
                    reason="Chart candidate selected from the day's stronger setups.",
                    chart_available=True,
                ),
                source_symbol=signal.symbol,
                score=signal.score,
                related_alert_id=alert.id,
                chart_path=chart_path,
                recent_drafts=recent_drafts,
            )
            draft.metadata["owned_chart"] = True
            draft.metadata["interactive_timeframe"] = signal.timeframe
            return draft
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception("Failed to prepare X chart draft for %s", alert.symbol)
            self.chart_renderer.cleanup(chart_path)
            return None

    async def _build_chart_draft_from_followup(
        self,
        followup: FollowUpResultRecord,
        recent_drafts: list[TwitterDraft],
        *,
        signal: AlertSignal | None = None,
        followup_result: FollowUpResult | None = None,
        assessment: _FollowUpTwitterAssessment | None = None,
    ) -> TwitterDraft | None:
        chart_path = None
        try:
            resolved_signal = signal or await self._resolve_signal_for_followup_record(followup)
            resolved_followup = followup_result or self._followup_record_to_result(followup)
            chart_path = await self._render_result_chart(resolved_signal, resolved_followup)
            draft = await self.generator.generate_chart_draft(
                prepared_context=(
                    f"{self._followup_prepared_context(resolved_signal, resolved_followup)}\n"
                    "Why This Case Matters: This chart already has before/after proof, not just a raw trigger."
                ),
                source_symbol=followup.symbol,
                score=followup.score,
                related_alert_id=followup.alert_id,
                chart_path=chart_path,
                recent_drafts=recent_drafts,
            )
            draft.metadata["owned_chart"] = True
            draft.metadata["interactive_timeframe"] = followup.timeframe
            draft.metadata["followup_stage"] = resolved_followup.stage
            if assessment is not None:
                draft.metadata["thesis_result_state"] = resolved_followup.thesis_result_state or ("favorable" if assessment.favorable else "adverse")
                draft.metadata["proof_value"] = round(assessment.proof_value, 2)
                draft.metadata["chart_value"] = round(assessment.chart_priority, 2)
            return draft
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception("Failed to prepare X chart draft from follow-up for %s", followup.symbol)
            self.chart_renderer.cleanup(chart_path)
            return None

    async def _render_signal_chart(self, signal: AlertSignal):
        frame = await self.binance_client.get_klines(signal.symbol, signal.timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        return await self.chart_renderer.render_alert_chart(enriched, signal, preview=True)

    async def _render_followup_chart(self, followup: FollowUpResult):
        frame = await self.binance_client.get_klines(followup.symbol, followup.timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        return await self.chart_renderer.render_followup_chart(enriched, followup)

    async def _render_result_chart(self, signal: AlertSignal, followup: FollowUpResult):
        frame = await self.binance_client.get_klines(followup.symbol, followup.timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        return await self.chart_renderer.render_result_chart(enriched, signal, followup, label="Proof")

    async def _resolve_preview_signal(self, best_alert: AlertRecord | None) -> AlertSignal:
        if best_alert is not None:
            return self._alert_record_to_signal(best_alert)

        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=True)
        frame = await self.binance_client.get_klines("BTCUSDT", self.settings.scan_timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        row = enriched.iloc[-1]
        ticker = ticker_map.get("BTCUSDT")
        rsi = float(row["rsi"])
        direction = "oversold" if rsi < 50 else "overbought"
        score = max(60, min(85, int(abs(rsi - 50) * 1.9)))
        return AlertSignal(
            symbol="BTCUSDT",
            direction=direction,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=row["close_time"].to_pydatetime(),
            price=float(row["close"]),
            rsi=rsi,
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]),
            atr=float(row["atr"]),
            atr_pct=float(row["atr_pct"]),
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=score,
            explanation="Fallback preview signal built from current BTCUSDT context because stored alert history was not available yet.",
            metadata={"preview_mode_seed": True, "volume_ratio": float(row["volume_ratio"]) if row["volume_ratio"] == row["volume_ratio"] else None},
        )

    async def _resolve_preview_followup(
        self,
        best_alert: AlertRecord | None,
        preview_signal: AlertSignal,
        followups: list[FollowUpResultRecord],
    ) -> tuple[AlertSignal, FollowUpResult] | None:
        if followups:
            record = followups[0]
            signal = preview_signal if best_alert is None or best_alert.id != record.alert_id else self._alert_record_to_signal(best_alert)
            return signal, self._followup_record_to_result(record)

        signal = preview_signal
        frame = await self.binance_client.get_klines(signal.symbol, self.settings.scan_timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        row = enriched.iloc[-1]
        current_price = float(row["close"])
        current_rsi = float(row["rsi"])
        move_pct = calc_pct_change(signal.price, current_price)
        return signal, FollowUpResult(
            alert_id=best_alert.id if best_alert is not None else 0,
            symbol=signal.symbol,
            direction=signal.direction,
            timeframe=signal.timeframe,
            alert_price=signal.price,
            current_price=current_price,
            alert_rsi=signal.rsi,
            current_rsi=current_rsi,
            move_pct=move_pct,
            summary="Preview-mode follow-up built from the latest available market state because no stored follow-up existed yet.",
            score=signal.score,
            observed_at=utc_now(),
            metadata={"preview_mode_seed": True},
        )

    async def _resolve_signal_for_followup_record(self, followup: FollowUpResultRecord) -> AlertSignal:
        alert_record = await self.repository.get_alert(followup.alert_id)
        if alert_record is not None:
            return self._alert_record_to_signal(alert_record)

        return AlertSignal(
            symbol=followup.symbol,
            direction=followup.direction,
            timeframe=followup.timeframe,
            candle_open_time=followup.observed_at,
            candle_close_time=followup.observed_at,
            price=followup.alert_price,
            rsi=followup.alert_rsi,
            day_change_pct=None,
            day_volume=None,
            quote_volume=None,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=followup.score,
            explanation=followup.summary,
            metadata={},
        )

    async def _load_recent_alerts(
        self,
        *,
        days: int,
        limit: int,
        min_score: int,
        min_quote_volume: float,
    ) -> list[AlertRecord]:
        start = utc_now() - timedelta(days=days)
        end = utc_now() + timedelta(minutes=1)
        return await self.repository.list_alerts_between(
            start=start,
            end=end,
            min_score=min_score,
            min_quote_volume=min_quote_volume,
            limit=limit,
        )

    def _alert_is_best_setup_candidate(self, signal: AlertSignal) -> bool:
        quote_volume = signal.quote_volume or signal.day_volume or 0.0
        volume_ratio = float(signal.metadata.get("volume_ratio") or 1.0)
        threshold_distance = (
            self.settings.rsi_oversold - signal.rsi
            if signal.direction == "oversold"
            else signal.rsi - self.settings.rsi_overbought
        )
        return (
            signal.score >= max(self.settings.x_min_score + 18, 84)
            and quote_volume >= self.settings.x_min_quote_volume
            and volume_ratio >= 1.35
            and threshold_distance >= 3.0
        )

    def _daily_context_is_meaningful(self, daily_context) -> bool:
        return daily_context.total_followups >= 1 or daily_context.total_alerts >= 5

    def _signal_prepared_context(self, signal: AlertSignal, *, reason: str, chart_available: bool | None = None) -> str:
        chart_flag = bool(signal.chart_path) if chart_available is None else chart_available
        return f"{build_signal_context(signal).to_prompt_context()}\nChart Available: {'yes' if chart_flag else 'no'}\nWhy This Case Matters: {reason}"

    def _followup_prepared_context(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{build_followup_context(signal, followup).to_prompt_context()}\n"
            f"Chart Available: {'yes' if followup.chart_path else 'no'}\n"
            f"Why This Case Matters: This is outcome-based proof, not just a raw trigger."
        )

    def _daily_prepared_context(self, daily_context, *, extra_reason: str) -> str:
        return f"{daily_context.to_prompt_context()}\nWhy This Case Matters: {extra_reason}"

    def _alert_record_to_signal(self, alert: AlertRecord) -> AlertSignal:
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
            metadata=alert.metadata,
        )

    def _followup_record_to_result(self, record: FollowUpResultRecord) -> FollowUpResult:
        favorable_move = record.metadata.get("favorable_move_pct")
        adverse_move = record.metadata.get("adverse_move_pct")
        return FollowUpResult(
            alert_id=record.alert_id,
            symbol=record.symbol,
            direction=record.direction,
            timeframe=record.timeframe,
            alert_price=record.alert_price,
            current_price=record.current_price,
            alert_rsi=record.alert_rsi,
            current_rsi=record.current_rsi,
            move_pct=record.move_pct,
            summary=record.summary,
            score=record.score,
            observed_at=record.observed_at,
            stage=record.stage,
            thesis_direction=str(record.metadata.get("thesis_direction") or self._thesis_direction(record.direction)),
            favorable_move_pct=float(favorable_move) if isinstance(favorable_move, (int, float)) else self._favorable_move(record.direction, record.move_pct),
            adverse_move_pct=float(adverse_move) if isinstance(adverse_move, (int, float)) else self._adverse_move(record.direction, record.move_pct),
            thesis_result_state=str(record.metadata.get("thesis_result_state") or self._thesis_result_state(record.direction, record.move_pct)),
            metadata=record.metadata,
        )

    def _signal_to_alert_record(self, alert: AlertRecord | None, signal: AlertSignal) -> AlertRecord:
        timestamp = utc_now()
        return AlertRecord(
            id=alert.id if alert is not None else 0,
            symbol=signal.symbol,
            direction=signal.direction,
            timeframe=signal.timeframe,
            candle_open_time=signal.candle_open_time,
            candle_close_time=signal.candle_close_time,
            alert_price=signal.price,
            alert_rsi=signal.rsi,
            day_change_pct=signal.day_change_pct,
            day_volume=signal.day_volume,
            score=signal.score,
            alert_sent_at=timestamp,
            followup_due_at=timestamp,
            followup_sent_at=None,
            lab_message_id=None,
            metadata=signal.metadata,
        )

    def _followup_result_to_record(self, result: FollowUpResult) -> FollowUpResultRecord:
        return FollowUpResultRecord(
            alert_id=result.alert_id,
            stage=result.stage,
            symbol=result.symbol,
            direction=result.direction,
            timeframe=result.timeframe,
            alert_price=result.alert_price,
            alert_rsi=result.alert_rsi,
            score=result.score,
            current_price=result.current_price,
            current_rsi=result.current_rsi,
            move_pct=result.move_pct,
            summary=result.summary,
            observed_at=result.observed_at,
            metadata=result.metadata,
        )

    async def _rank_followup_records_for_twitter(
        self,
        followups: list[FollowUpResultRecord],
        recent_drafts: list[TwitterDraft],
        sent_recent_drafts: list[TwitterDraft],
    ) -> list[dict[str, object]]:
        recent_case_keys = self._recent_followup_case_keys(recent_drafts)
        ranked: list[dict[str, object]] = []
        for record in followups:
            signal = await self._resolve_signal_for_followup_record(record)
            followup = self._followup_record_to_result(record)
            send_decision = self._evaluate_followup_send_policy(followup, sent_recent_drafts)
            assessment = self._assess_followup_candidate(signal, followup)
            case_key = self._followup_case_key(record.alert_id, record.stage)
            if case_key in recent_case_keys:
                LOGGER.info(
                    "X follow-up package skipped symbol=%s stage=%s reason=duplicate_recent_case",
                    record.symbol,
                    record.stage,
                )
                continue
            if not send_decision.eligible:
                LOGGER.info(
                    "X follow-up package skipped symbol=%s stage=%s reason=%s",
                    record.symbol,
                    record.stage,
                    send_decision.reason,
                )
                continue
            if not assessment.package_candidate:
                LOGGER.info(
                    "X follow-up package skipped symbol=%s stage=%s reason=%s favorable=%s favorable_move=%.2f proof=%.1f chart=%.1f",
                    record.symbol,
                    record.stage,
                    assessment.skip_reason,
                    assessment.favorable,
                    assessment.favorable_move_pct,
                    assessment.proof_value,
                    assessment.chart_priority,
                )
                continue
            if not assessment.chart_candidate:
                LOGGER.info(
                    "X follow-up package skipped symbol=%s stage=%s reason=poor_chart_value favorable_move=%.2f chart=%.1f",
                    record.symbol,
                    record.stage,
                    assessment.favorable_move_pct,
                    assessment.chart_priority,
                )
                continue
            ranked.append(
                {
                    "record": record,
                    "signal": signal,
                    "followup": followup,
                    "assessment": assessment,
                }
            )
        ranked.sort(
            key=lambda item: (
                float(item["assessment"].chart_priority),
                float(item["assessment"].priority),
                float(item["followup"].favorable_move_pct),
                int(item["followup"].score),
            ),
            reverse=True,
        )
        return ranked

    def _assess_followup_candidate(self, signal: AlertSignal, followup: FollowUpResult) -> _FollowUpTwitterAssessment:
        quote_volume = signal.quote_volume or signal.day_volume or 0.0
        volume_ratio = float(signal.metadata.get("volume_ratio") or 1.0)
        favorable = (followup.thesis_result_state or self._thesis_result_state(signal.direction, followup.move_pct)) == "favorable"
        favorable_move = followup.favorable_move_pct if followup.favorable_move_pct else self._favorable_move(signal.direction, followup.move_pct)
        adverse_move = followup.adverse_move_pct if followup.adverse_move_pct else self._adverse_move(signal.direction, followup.move_pct)
        rsi_recovery = self._rsi_recovery(signal.direction, followup)
        stage_bonus = self._followup_stage_bonus(followup.stage)
        quote_bonus = 6.0 if quote_volume >= max(self.settings.x_min_quote_volume * 2, 10_000_000) else 3.0 if quote_volume >= self.settings.x_min_quote_volume else 0.0
        volume_bonus = 4.0 if volume_ratio >= 1.25 else 1.5 if volume_ratio >= 1.05 else 0.0
        proof_value = (
            favorable_move * 20.0
            + min(rsi_recovery, 18.0) * 1.3
            + max(signal.score - self.settings.x_min_score, 0) * 0.55
            + stage_bonus
            + quote_bonus
            + volume_bonus
        )
        chart_value = (
            favorable_move * 18.0
            + min(rsi_recovery, 16.0) * 1.1
            + stage_bonus
            + (4.0 if abs(followup.move_pct) >= 1.25 else 0.0)
            + (2.0 if volume_ratio >= 1.1 else 0.0)
        )
        learning_value = (
            proof_value
            if favorable
            else abs(followup.move_pct) * 9.0
            + min(abs(followup.current_rsi - followup.alert_rsi), 20.0) * 0.8
            + stage_bonus
        )
        priority = proof_value + chart_value * 0.25 + learning_value * 0.15

        if quote_volume < self.settings.x_min_quote_volume:
            return _FollowUpTwitterAssessment(
                eligible=False,
                package_candidate=False,
                chart_candidate=False,
                primary_type=None,
                priority=priority,
                chart_priority=chart_value,
                proof_value=proof_value,
                learning_value=learning_value,
                favorable=favorable,
                favorable_move_pct=favorable_move,
                adverse_move_pct=adverse_move,
                rsi_recovery=rsi_recovery,
                skip_reason="low_quote_volume",
            )
        if not favorable:
            return _FollowUpTwitterAssessment(
                eligible=False,
                package_candidate=False,
                chart_candidate=False,
                primary_type=None,
                priority=priority,
                chart_priority=chart_value,
                proof_value=proof_value,
                learning_value=learning_value,
                favorable=favorable,
                favorable_move_pct=favorable_move,
                adverse_move_pct=adverse_move,
                rsi_recovery=rsi_recovery,
                skip_reason="adverse_followup",
            )

        package_candidate = proof_value >= 54.0 or chart_value >= 58.0 or (favorable_move >= 0.8 and rsi_recovery >= 9.0)
        chart_candidate = package_candidate and (chart_value >= 60.0 or favorable_move >= 1.1 or (favorable_move >= 0.85 and rsi_recovery >= 10.0))
        eligible = proof_value >= 64.0 or favorable_move >= 1.25 or (favorable_move >= 0.95 and rsi_recovery >= 12.0)
        primary_type = None
        if eligible:
            if proof_value >= 84.0 or favorable_move >= 2.25 or (favorable_move >= 1.75 and rsi_recovery >= 14.0):
                primary_type = "twitter_fomo_or_missed_move_post"
            else:
                primary_type = "twitter_followup_result_post"

        if eligible:
            skip_reason = "none"
        elif package_candidate:
            skip_reason = "reserve_for_daily_package"
        elif chart_value < 54.0:
            skip_reason = "poor_chart_value"
        elif learning_value < 48.0:
            skip_reason = "low_learning_value"
        else:
            skip_reason = "low_proof_value"

        return _FollowUpTwitterAssessment(
            eligible=eligible,
            package_candidate=package_candidate,
            chart_candidate=chart_candidate,
            primary_type=primary_type,
            priority=priority,
            chart_priority=chart_value,
            proof_value=proof_value,
            learning_value=learning_value,
            favorable=favorable,
            favorable_move_pct=favorable_move,
            adverse_move_pct=adverse_move,
            rsi_recovery=rsi_recovery,
            skip_reason=skip_reason,
        )

    def _evaluate_followup_send_policy(
        self,
        followup: FollowUpResult,
        sent_recent_drafts: list[TwitterDraft],
    ) -> _TwitterFollowUpSendDecision:
        state = followup.thesis_result_state or "neutral"
        favorable_move = float(followup.favorable_move_pct or 0.0)
        adverse_move = float(followup.adverse_move_pct or 0.0)
        favorable_gate = float(self.settings.twitter_followup_min_favorable_move_pct)
        adverse_cap = float(self.settings.twitter_followup_max_adverse_move_pct)
        adverse_daily_cap = int(self.settings.twitter_followup_max_adverse_per_day)

        if state == "favorable":
            if favorable_move < favorable_gate:
                return _TwitterFollowUpSendDecision(
                    False,
                    f"waiting_for_{favorable_gate:.0f}pct_favorable_followthrough",
                )
            previous_best = self._best_sent_favorable_followup_move(
                sent_recent_drafts,
                alert_id=followup.alert_id,
            )
            if previous_best is not None and favorable_move <= previous_best + 0.05:
                return _TwitterFollowUpSendDecision(
                    False,
                    f"no_improvement_vs_previous_sent_followup_{previous_best:.2f}pct",
                )
            return _TwitterFollowUpSendDecision(
                True,
                f"favorable_followup_{favorable_move:.2f}pct",
            )

        if state == "adverse":
            if adverse_move <= 0.0:
                return _TwitterFollowUpSendDecision(False, "no_meaningful_adverse_move")
            if adverse_move > adverse_cap:
                return _TwitterFollowUpSendDecision(
                    False,
                    f"adverse_move_too_large_{adverse_move:.2f}pct",
                )
            adverse_sent_today = self._count_adverse_followups_today(sent_recent_drafts)
            if adverse_sent_today >= adverse_daily_cap:
                return _TwitterFollowUpSendDecision(False, "daily_adverse_followup_cap_reached")
            return _TwitterFollowUpSendDecision(
                True,
                f"single_daily_adverse_followup_{adverse_move:.2f}pct",
            )

        return _TwitterFollowUpSendDecision(False, "waiting_for_clear_followthrough")

    def _best_sent_favorable_followup_move(
        self,
        drafts: list[TwitterDraft],
        *,
        alert_id: int,
    ) -> float | None:
        values = [
            float(draft.metadata.get("favorable_move_pct") or 0.0)
            for draft in drafts
            if draft.related_alert_id == alert_id
            and str(draft.metadata.get("thesis_result_state") or "") == "favorable"
            and draft.metadata.get("followup_stage")
        ]
        return max(values) if values else None

    def _count_adverse_followups_today(self, drafts: list[TwitterDraft]) -> int:
        day_start, day_end = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        total = 0
        for draft in drafts:
            if str(draft.metadata.get("thesis_result_state") or "") != "adverse":
                continue
            timestamp_raw = draft.metadata.get("sent_at") or draft.metadata.get("created_at") or draft.metadata.get("generated_at")
            if not isinstance(timestamp_raw, str):
                continue
            try:
                timestamp = datetime.fromisoformat(timestamp_raw)
            except ValueError:
                continue
            if day_start <= timestamp <= day_end:
                total += 1
        return total

    def _followup_case_key(self, alert_id: int, stage: str) -> tuple[int, str]:
        return alert_id, (stage or "").lower()

    def _recent_followup_case_keys(self, drafts: list[TwitterDraft]) -> set[tuple[int, str]]:
        keys: set[tuple[int, str]] = set()
        for draft in drafts:
            if draft.related_alert_id is None:
                continue
            if draft.content_type not in {
                "twitter_followup_result_post",
                "twitter_fomo_or_missed_move_post",
                "twitter_chart_post",
            }:
                continue
            stage = str(draft.metadata.get("followup_stage") or "").lower()
            if stage:
                keys.add(self._followup_case_key(draft.related_alert_id, stage))
        return keys

    def _thesis_result_state(self, direction: str, move_pct: float) -> str:
        if direction in {"oversold", "long"}:
            if move_pct > 0.15:
                return "favorable"
            if move_pct < -0.15:
                return "adverse"
            return "neutral"
        if move_pct < -0.15:
            return "favorable"
        if move_pct > 0.15:
            return "adverse"
        return "neutral"

    def _thesis_direction(self, direction: str) -> str:
        if direction == "oversold":
            return "upside bounce"
        if direction == "overbought":
            return "downside cooling"
        if direction == "long":
            return "bullish continuation"
        return "bearish continuation"

    def _favorable_move(self, direction: str, move_pct: float) -> float:
        if direction in {"oversold", "long"}:
            return max(move_pct, 0.0)
        return max(-move_pct, 0.0)

    def _adverse_move(self, direction: str, move_pct: float) -> float:
        if direction in {"oversold", "long"}:
            return max(-move_pct, 0.0)
        return max(move_pct, 0.0)

    def _rsi_recovery(self, direction: str, followup: FollowUpResult) -> float:
        if direction in {"oversold", "long"}:
            return max(0.0, followup.current_rsi - followup.alert_rsi)
        return max(0.0, followup.alert_rsi - followup.current_rsi)

    def _followup_stage_bonus(self, stage: str) -> float:
        return {
            "2h": 2.0,
            "4h": 4.0,
            "6h": 5.0,
            "8h": 6.0,
        }.get((stage or "").lower(), 3.0)

    def _draft_requires_chart(self, draft: TwitterDraft) -> bool:
        return draft.source_symbol is not None and draft.content_type in {
            "twitter_best_setup_post",
            "twitter_fomo_or_missed_move_post",
            "twitter_chart_post",
        }


class TwitterDraftScheduler:
    def __init__(self, service: TwitterDraftService) -> None:
        self.service = service
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="twitter-draft-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        LOGGER.info("Twitter draft scheduler started")
        while not self._stop_event.is_set():
            try:
                await self.service.run_scheduled_jobs()
            except Exception:  # pragma: no cover - runtime dependent
                LOGGER.exception("Twitter draft scheduled run failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                continue
        LOGGER.info("Twitter draft scheduler stopped")
