from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher

from src.ai.ollama_client import OllamaClient
from src.ai.prompts import (
    community_alert_post,
    community_startup_post,
    followup_summary_post,
    lab_internal_summary,
    lab_startup_post,
    pro_alert_post,
    pro_startup_post,
    public_alert_post,
    public_startup_post,
)
from src.core.config import Settings
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost
from src.core.utils import format_percent, format_price, format_rsi, local_day_bounds, utc_now
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContentProfile:
    min_words: int
    max_words: int
    banned_phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason: str


class DraftGenerator:
    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaClient | None,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.ollama_client = ollama_client
        self.repository = repository
        self._profiles = self._build_profiles()

    async def generate_startup_posts(self) -> list[GeneratedPost]:
        if self.settings.curated_lab_only_mode:
            return []
        now = utc_now()
        jobs: list[tuple[str, str, str, str, str, object | None]] = []
        if self.settings.public_startup_posts_enabled:
            jobs.append(
                (
                    "public",
                    self.settings.public_channel,
                    "startup_post",
                    public_startup_post(now),
                    self._fallback_public_startup(),
                    None,
                )
            )
        if self.settings.lab_startup_posts_enabled:
            jobs.append(
                (
                    "lab",
                    self.settings.lab_channel,
                    "startup_post",
                    lab_startup_post(now),
                    self._fallback_lab_startup(),
                    None,
                )
            )
        if self.settings.community_startup_posts_enabled:
            jobs.append(
                (
                    "community",
                    self.settings.community_chat,
                    "startup_post",
                    community_startup_post(now),
                    self._fallback_community_startup(),
                    None,
                )
            )
        if self.settings.pro_destination_enabled and self.settings.pro_startup_posts_enabled:
            jobs.insert(
                1 if jobs else 0,
                (
                    "pro",
                    self.settings.pro_channel,
                    "startup_post",
                    pro_startup_post(now),
                    self._fallback_pro_startup(),
                    None,
                ),
            )
        return await self._build_posts(
            jobs,
            source_symbol=None,
            related_alert_id=None,
            force_autopost=True,
            send_lab_copy=False,
            metadata_extra=None,
        )

    async def generate_for_alert(
        self,
        signal: AlertSignal,
        related_alert_id: int,
        *,
        chart_path=None,
    ) -> list[GeneratedPost]:
        if self.settings.curated_lab_only_mode:
            return []
        jobs: list[tuple[str, str, str, str, str, object | None]] = [
            (
                "lab",
                self.settings.lab_channel,
                "internal_summary",
                lab_internal_summary(signal),
                self._fallback_lab_alert(signal),
                None,
            )
        ]

        if self.settings.public_best_setups_enabled:
            public_decision = self._evaluate_public_best_setup(signal)
            if public_decision.eligible:
                if await self._can_emit_public_post():
                    LOGGER.info("PUBLIC best setup eligible for %s: %s", signal.symbol, public_decision.reason)
                    jobs.append(
                        (
                            "public",
                            self.settings.public_channel,
                            "public_best_setup",
                            public_alert_post(signal),
                            self._fallback_public_best_setup(signal),
                            chart_path,
                        )
                    )
                else:
                    LOGGER.info(
                        "Skipping PUBLIC best setup for %s: daily public cap reached after eligibility (%s)",
                        signal.symbol,
                        public_decision.reason,
                    )
            else:
                LOGGER.info("Skipping PUBLIC best setup for %s: %s", signal.symbol, public_decision.reason)

        if not self.settings.pro_destination_enabled:
            LOGGER.info("Skipping PRO live alert for %s: PRO destination disabled", signal.symbol)
        elif self.settings.pro_live_alerts_enabled:
            pro_decision = self._evaluate_pro_live_alert(signal)
            if pro_decision.eligible:
                if await self._can_emit_pro_post():
                    LOGGER.info("PRO live alert eligible for %s: %s", signal.symbol, pro_decision.reason)
                    jobs.append(
                        (
                            "pro",
                            self.settings.pro_channel,
                            "pro_live_alert",
                            pro_alert_post(signal),
                            self._fallback_pro_live_alert(signal),
                            chart_path,
                        )
                    )
                else:
                    LOGGER.info(
                        "Skipping PRO live alert for %s: daily PRO cap reached after eligibility (%s)",
                        signal.symbol,
                        pro_decision.reason,
                    )
            else:
                LOGGER.info("Skipping PRO live alert for %s: %s", signal.symbol, pro_decision.reason)

        community_decision = self._evaluate_community_prompt(signal)
        if community_decision.eligible:
            jobs.append(
                (
                    "community",
                    self.settings.community_chat,
                    "community_prompt",
                    community_alert_post(signal),
                    self._fallback_community_prompt(signal),
                    None,
                )
            )
        else:
            LOGGER.info("Skipping COMMUNITY prompt for %s: %s", signal.symbol, community_decision.reason)

        return await self._build_posts(
            jobs,
            source_symbol=signal.symbol,
            related_alert_id=related_alert_id,
            force_autopost=False,
            send_lab_copy=True,
            metadata_extra=None,
        )

    async def generate_for_followup(
        self,
        signal: AlertSignal,
        followup: FollowUpResult,
        *,
        result_chart_path=None,
        force_results_followup: bool = False,
    ) -> list[GeneratedPost]:
        curated_lab_only = self.settings.curated_lab_only_mode
        followup_metadata = {
            "followup_stage": followup.stage,
            "thesis_result_state": followup.thesis_result_state,
            "favorable_move_pct": float(followup.favorable_move_pct or 0.0),
            "adverse_move_pct": float(followup.adverse_move_pct or 0.0),
        }
        jobs: list[tuple[str, str, str, str, str, object | None]] = []
        if not curated_lab_only:
            jobs.append(
                (
                    "lab",
                    self.settings.lab_channel,
                    "followup_internal_summary",
                    followup_summary_post("lab", signal, followup),
                    self._fallback_lab_followup(signal, followup),
                    None,
                )
            )

        public_result_added = False
        if not curated_lab_only and self.settings.public_result_posts_enabled:
            public_result_decision = self._evaluate_public_result_post(signal, followup)
            if public_result_decision.eligible:
                if await self._can_emit_public_post():
                    LOGGER.info("PUBLIC result post eligible for %s: %s", signal.symbol, public_result_decision.reason)
                    jobs.append(
                        (
                            "public",
                            self.settings.public_channel,
                            "public_result_post",
                            followup_summary_post("public", signal, followup),
                            self._fallback_public_result_post(signal, followup),
                            result_chart_path,
                        )
                    )
                    public_result_added = True
                else:
                    LOGGER.info(
                        "Skipping PUBLIC result post for %s: daily public cap reached after eligibility (%s)",
                        signal.symbol,
                        public_result_decision.reason,
                    )
            else:
                LOGGER.info("Skipping PUBLIC result post for %s: %s", signal.symbol, public_result_decision.reason)

        if not curated_lab_only and self.settings.public_market_takeaways_enabled and not public_result_added:
            public_takeaway_decision = self._evaluate_public_market_takeaway(signal, followup)
            if public_takeaway_decision.eligible:
                if await self._can_emit_public_post():
                    LOGGER.info("PUBLIC market takeaway eligible for %s: %s", signal.symbol, public_takeaway_decision.reason)
                    jobs.append(
                        (
                            "public",
                            self.settings.public_channel,
                            "public_market_takeaway",
                            followup_summary_post("public", signal, followup),
                            self._fallback_public_market_takeaway(signal, followup),
                            result_chart_path,
                        )
                    )
                else:
                    LOGGER.info(
                        "Skipping PUBLIC market takeaway for %s: daily public cap reached after eligibility (%s)",
                        signal.symbol,
                        public_takeaway_decision.reason,
                    )
            else:
                LOGGER.info("Skipping PUBLIC market takeaway for %s: %s", signal.symbol, public_takeaway_decision.reason)

        if not self.settings.results_channel_enabled:
            LOGGER.info("Skipping RESULTS follow-up routing for %s: results channel disabled", signal.symbol)
        else:
            results_stage_decision = await self._evaluate_results_stage_policy(followup)
            if force_results_followup:
                if not results_stage_decision.eligible:
                    LOGGER.info(
                        "Skipping forced RESULTS mirror for %s: %s",
                        signal.symbol,
                        results_stage_decision.reason,
                    )
                else:
                    LOGGER.info(
                        "Mirroring RESULTS follow-up for %s because the case is Twitter-worthy: %s",
                        signal.symbol,
                        results_stage_decision.reason,
                    )
                    jobs.append(
                        (
                            "results",
                            self.settings.results_channel,
                            "results_followup_post",
                            followup_summary_post("results", signal, followup),
                            self._fallback_results_followup_post(signal, followup),
                            result_chart_path,
                        )
                    )
            else:
                results_decision = self._evaluate_results_followup(signal, followup)
                if not results_decision.eligible:
                    LOGGER.info("Skipping RESULTS follow-up for %s: %s", signal.symbol, results_decision.reason)
                elif not results_stage_decision.eligible:
                    LOGGER.info("Skipping RESULTS follow-up for %s: %s", signal.symbol, results_stage_decision.reason)
                elif self.settings.results_all_followups_enabled:
                    LOGGER.info(
                        "RESULTS follow-up eligible for %s and bypassing daily cap because RESULTS_ALL_FOLLOWUPS_ENABLED is on: %s",
                        signal.symbol,
                        results_stage_decision.reason,
                    )
                    jobs.append(
                        (
                            "results",
                            self.settings.results_channel,
                            "results_followup_post",
                            followup_summary_post("results", signal, followup),
                            self._fallback_results_followup_post(signal, followup),
                            result_chart_path,
                        )
                    )
                elif self.settings.results_proof_posts_enabled:
                    if await self._can_emit_results_post():
                        LOGGER.info("RESULTS proof post eligible for %s: %s", signal.symbol, results_stage_decision.reason)
                        jobs.append(
                            (
                                "results",
                                self.settings.results_channel,
                                "results_proof_post",
                                followup_summary_post("results", signal, followup),
                                self._fallback_results_proof_post(signal, followup),
                                result_chart_path,
                            )
                        )
                    else:
                        LOGGER.info(
                            "Skipping RESULTS proof post for %s: daily results cap reached after eligibility (%s)",
                            signal.symbol,
                            results_stage_decision.reason,
                        )

        if curated_lab_only:
            LOGGER.info(
                "Curated LAB-only mode keeps follow-up fanout narrowed to RESULTS only for %s",
                signal.symbol,
            )
        elif not self.settings.pro_destination_enabled:
            LOGGER.info("Skipping PRO follow-up for %s: PRO destination disabled", signal.symbol)
        elif self.settings.pro_followups_enabled:
            pro_followup_decision = self._evaluate_pro_followup(signal, followup)
            if pro_followup_decision.eligible:
                if await self._can_emit_pro_post():
                    LOGGER.info("PRO follow-up eligible for %s: %s", signal.symbol, pro_followup_decision.reason)
                    jobs.append(
                        (
                            "pro",
                            self.settings.pro_channel,
                            "pro_followup",
                            followup_summary_post("pro", signal, followup),
                            self._fallback_pro_followup(signal, followup),
                            result_chart_path,
                        )
                    )
                else:
                    LOGGER.info(
                        "Skipping PRO follow-up for %s: daily PRO cap reached after eligibility (%s)",
                        signal.symbol,
                        pro_followup_decision.reason,
                    )
            else:
                LOGGER.info("Skipping PRO follow-up for %s: %s", signal.symbol, pro_followup_decision.reason)

        if not curated_lab_only:
            community_decision = self._evaluate_community_followup(signal, followup)
            if community_decision.eligible:
                jobs.append(
                    (
                        "community",
                        self.settings.community_chat,
                        "community_followup_chat_post",
                        followup_summary_post("community", signal, followup),
                        self._fallback_community_followup(signal, followup),
                        None,
                    )
                )
            else:
                LOGGER.info("Skipping COMMUNITY follow-up for %s: %s", signal.symbol, community_decision.reason)

        return await self._build_posts(
            jobs,
            source_symbol=signal.symbol,
            related_alert_id=followup.alert_id,
            force_autopost=False,
            send_lab_copy=not curated_lab_only,
            metadata_extra=followup_metadata,
        )

    async def _build_posts(
        self,
        jobs: list[tuple[str, str, str, str, str, object | None]],
        *,
        source_symbol: str | None,
        related_alert_id: int | None,
        force_autopost: bool,
        send_lab_copy: bool,
        metadata_extra: dict[str, object] | None,
    ) -> list[GeneratedPost]:
        posts: list[GeneratedPost] = []
        for channel_kind, destination, content_type, prompt, fallback, chart_path in jobs:
            generated_text, model_name = await self._generate_text(
                prompt,
                fallback,
                channel_kind,
                content_type,
            )
            if channel_kind == "community" and self._community_mentions_explicit_price(generated_text):
                LOGGER.info(
                    "COMMUNITY %s for %s switched to fallback because AI copy mentioned an exact price directly",
                    content_type,
                    source_symbol,
                )
                generated_text = fallback
                model_name = model_name or "fallback"
            if channel_kind == "community" and content_type != "startup_post":
                community_delivery_decision = await self._evaluate_community_delivery()
                if not community_delivery_decision.eligible:
                    LOGGER.info(
                        "Skipping COMMUNITY %s for %s: %s",
                        content_type,
                        source_symbol,
                        community_delivery_decision.reason,
                    )
                    continue
                skip_reason = await self._community_skip_reason(
                    destination=destination,
                    content_type=content_type,
                    generated_text=generated_text,
                )
                if skip_reason is not None:
                    LOGGER.info(
                        "Skipping COMMUNITY %s for %s: %s",
                        content_type,
                        source_symbol,
                        skip_reason,
                    )
                    continue
            posts.append(
                GeneratedPost(
                    channel_kind=channel_kind,
                    destination=destination,
                    content_type=content_type,
                    generated_text=generated_text,
                    chart_path=chart_path,
                    status="generated",
                    ai_model=model_name,
                    source_symbol=source_symbol,
                    related_alert_id=related_alert_id,
                    force_autopost=force_autopost,
                    send_lab_copy=send_lab_copy and channel_kind != "lab",
                    metadata={
                        "generated_at": utc_now().isoformat(),
                        **(metadata_extra or {}),
                    },
                )
            )
        return posts

    async def _generate_text(
        self,
        prompt: str,
        fallback_text: str,
        channel_kind: str,
        content_type: str,
    ) -> tuple[str, str]:
        fallback_clean = self._clean_output(fallback_text)
        if not self.settings.ollama_enabled or self.ollama_client is None:
            return fallback_clean, "fallback-template"
        if self.ollama_client.is_cooling_down():
            return fallback_clean, "fallback-cooldown"

        try:
            response = await self.ollama_client.generate(
                prompt,
                timeout_seconds=min(float(self.settings.ollama_timeout_seconds), 22.0),
                retries=1,
                base_delay=0.8,
            )
            cleaned = self._clean_output(response)
            self._validate_output(cleaned, channel_kind, content_type)
            return cleaned, self.settings.ollama_model
        except Exception as exc:  # pragma: no cover - runtime dependent
            error_text = str(exc).strip() or f"{type(exc).__name__}: {exc!r}"
            lowered = error_text.lower()
            log_fn = LOGGER.warning
            if (
                "temporarily cooled down" in lowered
                or "assistant-like phrase detected" in lowered
                or "banned phrase detected" in lowered
            ):
                log_fn = LOGGER.info
            log_fn(
                "AI copy rejected for %s %s using model %s at %s. Falling back to template. Error: %s",
                channel_kind,
                content_type,
                self.settings.ollama_model,
                self.settings.ollama_base_url,
                error_text,
            )
            return fallback_clean, "fallback-template"

    def _clean_output(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = cleaned.replace("__", "").replace("`", "")
        cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(" \n\"'")

    def _validate_output(self, text: str, channel_kind: str, content_type: str) -> None:
        if not text:
            raise RuntimeError("model returned empty content")
        profile = self._profiles[(channel_kind, content_type)]
        lowered = text.lower()
        for phrase in profile.banned_phrases:
            if phrase in lowered:
                raise RuntimeError(f"assistant-like phrase detected: {phrase}")
        word_count = len(re.findall(r"\b[\w']+\b", text))
        if word_count < profile.min_words or word_count > profile.max_words:
            raise RuntimeError(
                f"word count {word_count} outside allowed range {profile.min_words}-{profile.max_words}"
            )
        if text.count("\n") > 8:
            raise RuntimeError("output too long for Telegram-first formatting")

    def _build_profiles(self) -> dict[tuple[str, str], ContentProfile]:
        common_banned = (
            "i'm excited",
            "i am excited",
            "i'm glad you're here",
            "i am glad you're here",
            "let me tell you",
            "best regards",
            "let's work together",
            "i'm your community manager",
            "i am your community manager",
            "countless hours",
            "if you have any questions",
            "join us",
            "revolutionizing",
            "trading experience",
            "best wishes",
        )
        return {
            ("public", "startup_post"): ContentProfile(50, 140, common_banned),
            ("pro", "startup_post"): ContentProfile(35, 110, common_banned),
            ("lab", "startup_post"): ContentProfile(20, 90, common_banned),
            ("community", "startup_post"): ContentProfile(20, 90, common_banned),
            ("lab", "internal_summary"): ContentProfile(8, 45, common_banned),
            ("lab", "followup_internal_summary"): ContentProfile(8, 45, common_banned),
            ("public", "public_best_setup"): ContentProfile(28, 90, common_banned),
            ("public", "public_result_post"): ContentProfile(28, 90, common_banned),
            ("public", "public_market_takeaway"): ContentProfile(28, 90, common_banned),
            ("pro", "pro_live_alert"): ContentProfile(20, 70, common_banned),
            ("pro", "pro_followup"): ContentProfile(20, 70, common_banned),
            ("results", "results_proof_post"): ContentProfile(24, 75, common_banned),
            ("results", "results_followup_post"): ContentProfile(22, 75, common_banned),
            ("community", "community_prompt"): ContentProfile(10, 45, common_banned),
            ("community", "community_followup_chat_post"): ContentProfile(10, 45, common_banned),
        }

    async def _can_emit_public_post(self) -> bool:
        start_utc, _ = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        sent_count = await self.repository.count_posts_history_since(
            destination=self.settings.public_channel,
            since=start_utc,
            channel_kind="public",
            content_types=["public_best_setup", "public_result_post", "public_market_takeaway"],
            preview_mode=False,
        )
        scheduled_count = await self.repository.count_scheduled_generated_posts_since(
            destination=self.settings.public_channel,
            since=start_utc,
            channel_kind="public",
            content_types=["public_best_setup"],
        )
        return (sent_count + scheduled_count) < self.settings.public_max_posts_per_day

    async def _can_emit_pro_post(self) -> bool:
        start_utc, _ = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        count = await self.repository.count_posts_history_since(
            destination=self.settings.pro_channel,
            since=start_utc,
            channel_kind="pro",
            content_types=["pro_live_alert", "pro_followup"],
            preview_mode=False,
        )
        return count < self.settings.pro_max_posts_per_day

    async def _can_emit_results_post(self) -> bool:
        start_utc, _ = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        count = await self.repository.count_posts_history_since(
            destination=self.settings.results_channel,
            since=start_utc,
            channel_kind="results",
            content_types=["results_proof_post"],
            preview_mode=False,
        )
        return count < self.settings.results_max_posts_per_day

    async def _evaluate_community_delivery(self) -> EligibilityDecision:
        start_utc, _ = local_day_bounds(utc_now().astimezone(self.settings.timezone).date(), self.settings.timezone)
        count = await self.repository.count_posts_history_since(
            destination=self.settings.community_chat,
            since=start_utc,
            channel_kind="community",
            content_types=["community_prompt", "community_followup_chat_post"],
            statuses=["sent"],
            preview_mode=False,
        )
        if count >= self.settings.community_max_posts_per_day:
            return EligibilityDecision(
                False,
                f"daily community cap reached ({count}/{self.settings.community_max_posts_per_day})",
            )
        if self.settings.community_min_interval_minutes > 0:
            recent_count = await self.repository.count_posts_history_since(
                destination=self.settings.community_chat,
                since=utc_now() - timedelta(minutes=self.settings.community_min_interval_minutes),
                channel_kind="community",
                content_types=["community_prompt", "community_followup_chat_post"],
                statuses=["sent"],
                preview_mode=False,
            )
            if recent_count > 0:
                return EligibilityDecision(
                    False,
                    f"community cooldown active: a bot message was already sent in the last {self.settings.community_min_interval_minutes}m",
                )
        return EligibilityDecision(True, f"community slot open ({count}/{self.settings.community_max_posts_per_day} today)")

    def _signal_quote_volume(self, signal: AlertSignal) -> float:
        return float(signal.quote_volume or signal.day_volume or 0.0)

    def _signal_volume_ratio(self, signal: AlertSignal) -> float:
        raw = signal.metadata.get("volume_ratio")
        try:
            return float(raw) if raw is not None else 1.0
        except (TypeError, ValueError):
            return 1.0

    def _signal_extremeness(self, signal: AlertSignal) -> float:
        threshold = 30.0 if signal.direction == "oversold" else 70.0
        return abs(signal.rsi - threshold)

    def _followup_rsi_recovery(self, signal: AlertSignal, followup: FollowUpResult) -> float:
        return abs(followup.current_rsi - signal.rsi)

    def _followup_confirmed(self, signal: AlertSignal, followup: FollowUpResult) -> bool:
        return followup.thesis_result_state == "favorable"

    def _evaluate_public_best_setup(self, signal: AlertSignal) -> EligibilityDecision:
        score_gate = max(self.settings.public_best_setup_min_score - 6, self.settings.public_min_score)
        quote_volume = self._signal_quote_volume(signal)
        extremeness = self._signal_extremeness(signal)
        volume_ratio = self._signal_volume_ratio(signal)
        quote_gate = 8_000_000.0
        extremeness_gate = 2.4
        volume_gate = 1.05
        bonus_gate = score_gate + 8
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < quote_gate:
            return EligibilityDecision(
                False,
                f"low quote_volume {self._format_millions(quote_volume)} < {self._format_millions(quote_gate)}",
            )
        if extremeness < extremeness_gate:
            return EligibilityDecision(False, f"low RSI extremeness {extremeness:.2f} < {extremeness_gate:.2f}")
        if volume_ratio < volume_gate and signal.score < bonus_gate:
            return EligibilityDecision(
                False,
                f"low volume_ratio {volume_ratio:.2f} < {volume_gate:.2f} and score {signal.score} < bonus gate {bonus_gate}",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, extremeness={extremeness:.2f}, volume_ratio={volume_ratio:.2f}",
        )

    def _evaluate_pro_live_alert(self, signal: AlertSignal) -> EligibilityDecision:
        score_gate = max(self.settings.pro_live_min_score - 8, self.settings.pro_min_score - 6, 70)
        quote_volume = self._signal_quote_volume(signal)
        extremeness = self._signal_extremeness(signal)
        volume_ratio = self._signal_volume_ratio(signal)
        quote_gate = 8_000_000.0
        extremeness_gate = 2.4
        volume_gate = 1.04
        bonus_gate = score_gate + 8
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < quote_gate:
            return EligibilityDecision(
                False,
                f"low quote_volume {self._format_millions(quote_volume)} < {self._format_millions(quote_gate)}",
            )
        if extremeness < extremeness_gate:
            return EligibilityDecision(False, f"low RSI extremeness {extremeness:.2f} < {extremeness_gate:.2f}")
        if volume_ratio < volume_gate and signal.score < bonus_gate:
            return EligibilityDecision(
                False,
                f"low volume_ratio {volume_ratio:.2f} < {volume_gate:.2f} and score {signal.score} < bonus gate {bonus_gate}",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, extremeness={extremeness:.2f}, volume_ratio={volume_ratio:.2f}",
        )

    def _evaluate_public_result_post(self, signal: AlertSignal, followup: FollowUpResult) -> EligibilityDecision:
        score_gate = max(self.settings.public_result_min_score, 68)
        quote_volume = self._signal_quote_volume(signal)
        rsi_recovery = self._followup_rsi_recovery(signal, followup)
        move_gate = self.settings.public_result_min_move_pct
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < 10_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 10.00M")
        if not self._followup_confirmed(signal, followup):
            return EligibilityDecision(False, f"follow-up was not favorable to thesis (state={followup.thesis_result_state}, move={followup.move_pct:+.2f}%)")
        if abs(followup.favorable_move_pct) < move_gate and rsi_recovery < 12.0:
            return EligibilityDecision(
                False,
                f"weak favorable follow-up move={followup.favorable_move_pct:+.2f}% < {move_gate:.2f}% and rsi_recovery={rsi_recovery:.2f} < 12.00",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, favorable_move={followup.favorable_move_pct:+.2f}%, rsi_recovery={rsi_recovery:.2f}, stage={followup.stage}",
        )

    def _evaluate_public_market_takeaway(self, signal: AlertSignal, followup: FollowUpResult) -> EligibilityDecision:
        score_gate = max(self.settings.public_result_min_score - 4, 60)
        quote_volume = self._signal_quote_volume(signal)
        rsi_recovery = self._followup_rsi_recovery(signal, followup)
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < 8_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 8.00M")
        if abs(followup.move_pct) < 1.0 and rsi_recovery < 10.0:
            return EligibilityDecision(
                False,
                f"weak takeaway move={followup.move_pct:+.2f}% < 1.00% and rsi_recovery={rsi_recovery:.2f} < 10.00",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, move={followup.move_pct:+.2f}%, rsi_recovery={rsi_recovery:.2f}, stage={followup.stage}",
        )

    def _evaluate_pro_followup(self, signal: AlertSignal, followup: FollowUpResult) -> EligibilityDecision:
        score_gate = max(self.settings.pro_followup_min_score, self.settings.pro_min_score - 4)
        quote_volume = self._signal_quote_volume(signal)
        rsi_recovery = self._followup_rsi_recovery(signal, followup)
        move_gate = self.settings.pro_followup_min_move_pct
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < 12_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 12.00M")
        if abs(followup.move_pct) < move_gate and rsi_recovery < 10.0:
            return EligibilityDecision(
                False,
                f"weak follow-up result move={followup.move_pct:+.2f}% < {move_gate:.2f}% and rsi_recovery={rsi_recovery:.2f} < 10.00",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, move={followup.move_pct:+.2f}%, rsi_recovery={rsi_recovery:.2f}, thesis_state={followup.thesis_result_state}, stage={followup.stage}",
        )

    def _evaluate_results_followup(self, signal: AlertSignal, followup: FollowUpResult) -> EligibilityDecision:
        quote_volume = self._signal_quote_volume(signal)
        score_gate = max(self.settings.results_min_score, self.settings.public_result_min_score)
        move_gate = self.settings.results_min_favorable_move_pct
        rsi_recovery = self._followup_rsi_recovery(signal, followup)
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < 8_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 8.00M")
        if not self._followup_confirmed(signal, followup):
            return EligibilityDecision(False, f"result was not favorable to thesis (state={followup.thesis_result_state})")
        if abs(followup.favorable_move_pct) < move_gate:
            return EligibilityDecision(
                False,
                f"favorable move {followup.favorable_move_pct:+.2f}% < {move_gate:.2f}% for outward results delivery",
            )
        return EligibilityDecision(
            True,
            f"score={signal.score}, favorable_move={followup.favorable_move_pct:+.2f}%, rsi_recovery={rsi_recovery:.2f}, stage={followup.stage}",
        )

    async def _evaluate_results_stage_policy(self, followup: FollowUpResult) -> EligibilityDecision:
        if followup.thesis_result_state != "favorable":
            return EligibilityDecision(False, f"result was not favorable to thesis (state={followup.thesis_result_state})")
        favorable_move = float(followup.favorable_move_pct or 0.0)
        if favorable_move < float(self.settings.results_min_favorable_move_pct):
            return EligibilityDecision(
                False,
                f"waiting for stronger favorable follow-up {favorable_move:.2f}% < {self.settings.results_min_favorable_move_pct:.2f}%",
            )
        prior_posts = await self.repository.list_generated_posts_history(
            destination=self.settings.results_channel,
            channel_kind="results",
            related_alert_id=followup.alert_id,
            content_types=["results_followup_post", "results_proof_post"],
            statuses=["sent"],
            limit=12,
        )
        previous_best = max(
            (
                float((post.get("metadata") or {}).get("favorable_move_pct") or 0.0)
                for post in prior_posts
                if str((post.get("metadata") or {}).get("thesis_result_state") or "") == "favorable"
            ),
            default=0.0,
        )
        if previous_best >= float(self.settings.results_min_favorable_move_pct) and favorable_move <= previous_best + 0.05:
            return EligibilityDecision(
                False,
                f"no improvement vs previous favorable RESULTS post {favorable_move:.2f}% <= {previous_best:.2f}%",
            )
        return EligibilityDecision(
            True,
            f"favorable follow-up {favorable_move:.2f}% >= {self.settings.results_min_favorable_move_pct:.2f}% and improved vs prior RESULTS stage",
        )

    def _format_millions(self, value: float) -> str:
        return f"{value / 1_000_000:.2f}M"

    def _should_generate_public_best_setup(self, signal: AlertSignal) -> bool:
        return self._evaluate_public_best_setup(signal).eligible

    def _should_generate_pro_live_alert(self, signal: AlertSignal) -> bool:
        return self._evaluate_pro_live_alert(signal).eligible

    def _evaluate_community_prompt(self, signal: AlertSignal) -> EligibilityDecision:
        score_gate = max(self.settings.community_min_score + 6, 64)
        quote_volume = self._signal_quote_volume(signal)
        extremeness = self._signal_extremeness(signal)
        volume_ratio = self._signal_volume_ratio(signal)
        if signal.score < score_gate:
            return EligibilityDecision(False, f"low score {signal.score} < {score_gate}")
        if quote_volume < 5_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 5.00M")
        if extremeness < 3.0 and volume_ratio < 1.10:
            return EligibilityDecision(False, f"low extremeness {extremeness:.2f} and volume_ratio {volume_ratio:.2f}")
        return EligibilityDecision(
            True,
            f"score={signal.score}, quote_volume={self._format_millions(quote_volume)}, extremeness={extremeness:.2f}, volume_ratio={volume_ratio:.2f}",
        )

    def _should_generate_public_result_post(self, signal: AlertSignal, followup: FollowUpResult) -> bool:
        return self._evaluate_public_result_post(signal, followup).eligible

    def _should_generate_public_market_takeaway(self, signal: AlertSignal, followup: FollowUpResult) -> bool:
        return self._evaluate_public_market_takeaway(signal, followup).eligible

    def _should_generate_pro_followup(self, signal: AlertSignal, followup: FollowUpResult) -> bool:
        return self._evaluate_pro_followup(signal, followup).eligible

    def _evaluate_community_followup(self, signal: AlertSignal, followup: FollowUpResult) -> EligibilityDecision:
        quote_volume = self._signal_quote_volume(signal)
        rsi_recovery = self._followup_rsi_recovery(signal, followup)
        if quote_volume < 5_000_000:
            return EligibilityDecision(False, f"low quote_volume {self._format_millions(quote_volume)} < 5.00M")
        if abs(followup.move_pct) < 0.9 and rsi_recovery < 8.0:
            return EligibilityDecision(
                False,
                f"weak follow-up move={followup.move_pct:+.2f}% and rsi_recovery={rsi_recovery:.2f}",
            )
        return EligibilityDecision(
            True,
            f"move={followup.move_pct:+.2f}%, rsi_recovery={rsi_recovery:.2f}, stage={followup.stage}",
        )

    def _fallback_public_startup(self) -> str:
        return (
            "This channel is here to surface what actually mattered on the board, not to dump every raw trigger.\n\n"
            "The edge is in filtering, context, and outcome quality. Stronger setups, cleaner follow-through, less time wasted flipping through noise."
        )

    def _fallback_pro_startup(self) -> str:
        return (
            "PRO is the faster and cleaner layer.\n\n"
            "Fewer weak prints, tighter filters, quicker access to the setups that deserve attention."
        )

    def _fallback_lab_startup(self) -> str:
        return (
            "LAB is live.\n\n"
            "Raw alerts, follow-ups, charts, summaries, and review flow are online. This is the engine room, not the storefront."
        )

    def _fallback_community_startup(self) -> str:
        return (
            "This room is for actual market reads, not signal spam.\n\n"
            "A few names are already starting to stretch on the short-term board. What looks clean to you right now?"
        )

    def _fallback_lab_alert(self, signal: AlertSignal) -> str:
        return (
            f"{signal.symbol} logged {signal.direction} on {signal.timeframe}. "
            f"Close {format_price(signal.price)}, RSI {format_rsi(signal.rsi)}, score {signal.score}/100. Follow-up scheduled."
        )

    def _fallback_public_best_setup(self, signal: AlertSignal) -> str:
        return (
            f"{signal.symbol} is one of the cleaner {signal.timeframe} setups on the board right now.\n\n"
            f"It stands out because score, liquidity, and reaction potential line up better than the average print. "
            "Worth attention for what happens next, not for the trigger alone."
        )

    def _fallback_pro_live_alert(self, signal: AlertSignal) -> str:
        return (
            f"{signal.symbol} is clearing the stronger filter on {signal.timeframe}.\n\n"
            f"Score {signal.score}/100, RSI {format_rsi(signal.rsi)}, cleaner than the average board print. "
            "The setup is worth tracking now, not later."
        )

    def _fallback_community_prompt(self, signal: AlertSignal) -> str:
        side = "oversold" if signal.direction == "oversold" else "overbought"
        variants = (
            f"{signal.symbol} just printed a cleaner {side} read on {signal.timeframe}.\nReaction quality matters more than the trigger from here.",
            f"{signal.symbol} is stretching on the {signal.timeframe} board.\nThis one looks more readable than most of the tape right now.",
            f"{signal.symbol} just moved into a cleaner {side} spot on {signal.timeframe}.\nWatching how price reacts next matters more than chasing the print.",
            f"{signal.symbol} is one of the more noticeable {side} names on {signal.timeframe} right now.\nDoes it actually follow through?",
        )
        return variants[hash(f"{signal.symbol}:{signal.timeframe}:{signal.score}") % len(variants)]

    def _fallback_lab_followup(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{signal.symbol} follow-up processed. Move {format_percent(followup.move_pct)}. "
            f"RSI {format_rsi(signal.rsi)} -> {format_rsi(followup.current_rsi)}. {followup.summary}"
        )

    def _fallback_public_result_post(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{signal.symbol} was flagged earlier and is now {format_percent(followup.move_pct)} from the alert level.\n\n"
            f"That matters less as a victory lap and more as proof that the setup had real follow-through. "
            "This is the kind of case that saves time when the board is noisy."
        )

    def _fallback_public_market_takeaway(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{signal.symbol} turned into a useful follow-up case after the alert.\n\n"
            "The lesson is simple: the trigger is not the product. The reaction after it is what tells you whether the setup was worth attention."
        )

    def _fallback_pro_followup(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{signal.symbol} {followup.stage} follow-up: thesis {followup.thesis_result_state}, raw move {format_percent(followup.move_pct)}, "
            f"favorable move {format_percent(followup.favorable_move_pct)}.\n\n"
            "The useful read is whether price moved with the original thesis, not just whether price moved."
        )

    def _fallback_results_proof_post(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        return (
            f"{signal.symbol} was flagged earlier, then printed a {format_percent(followup.favorable_move_pct)} move in the original thesis direction by the {followup.stage} check.\n\n"
            f"That makes it a useful proof case: the signal was not just extreme, the market actually respected the setup after it was logged."
        )

    def _fallback_results_followup_post(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        if followup.thesis_result_state == "favorable":
            return (
                f"{signal.symbol} {followup.stage} later is still tracking in the original thesis direction, with a favorable move of {format_percent(followup.favorable_move_pct)}.\n\n"
                "This is a result check first and a proof point second: the useful part is seeing how the market behaved after the alert, not pretending every case was a perfect win."
            )
        if followup.thesis_result_state == "adverse":
            return (
                f"{signal.symbol} {followup.stage} later moved {format_percent(followup.adverse_move_pct)} against the original thesis.\n\n"
                "That still belongs in the results layer because transparent follow-up matters more than hiding adverse reactions."
            )
        return (
            f"{signal.symbol} {followup.stage} later is still sitting near the original alert level, so the result remains neutral for now.\n\n"
            "Not every trigger turns into immediate follow-through, and this checkpoint is more about context than a victory lap."
        )

    def _fallback_community_followup(self, signal: AlertSignal, followup: FollowUpResult) -> str:
        variants = (
            f"{signal.symbol} is {format_percent(followup.move_pct)} from the alert after {followup.stage}.\nThat looks {followup.thesis_result_state} to the original thesis.",
            f"{signal.symbol} after {followup.stage}: RSI {format_rsi(signal.rsi)} -> {format_rsi(followup.current_rsi)}.\nThe reaction matters more than the trigger here.",
            f"{signal.symbol} {followup.stage} later is still behaving {followup.thesis_result_state} versus the original signal.\nNot every extreme earns follow-through.",
        )
        return variants[hash(f"{signal.symbol}:{followup.stage}:{followup.move_pct:.4f}") % len(variants)]

    async def _community_skip_reason(
        self,
        *,
        destination: str,
        content_type: str,
        generated_text: str,
    ) -> str | None:
        normalized = self._normalize_similarity_text(generated_text)
        if not normalized:
            return "empty content"
        recent_texts = await self.repository.list_recent_post_texts(
            destination=destination,
            channel_kind="community",
            content_types=["community_prompt", "community_followup_chat_post"],
            limit=8,
        )
        for previous in recent_texts:
            previous_normalized = self._normalize_similarity_text(previous)
            if not previous_normalized:
                continue
            similarity = SequenceMatcher(None, normalized, previous_normalized).ratio()
            if similarity >= 0.86:
                return f"too similar to recent community copy ({similarity:.2f})"
        return None

    def _normalize_similarity_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text.lower()).strip()
        normalized = re.sub(r"[^a-z0-9%+.\- ]+", "", normalized)
        return normalized

    def _community_mentions_explicit_price(self, text: str) -> bool:
        lowered = text.lower()
        if "$" in lowered:
            return True
        if "market price" in lowered or "current price" in lowered:
            return True
        if "price" in lowered and re.search(r"\d+\.\d+", lowered):
            return True
        if re.search(r"\btrading at\s+\d+\.\d+", lowered):
            return True
        return False
