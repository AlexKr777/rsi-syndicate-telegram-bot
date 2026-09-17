from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.ai.ollama_client import OllamaClient
from src.ai.twitter_prompts import (
    twitter_analysis_decision,
    twitter_best_setup_post,
    twitter_chart_post,
    twitter_daily_recap_post,
    twitter_daily_stats_post,
    twitter_followup_result_post,
    twitter_fomo_or_missed_move_post,
    twitter_market_insight_post,
    twitter_operator_opinion_post,
    twitter_rewrite_for_diversity,
)
from src.core.config import Settings
from src.core.models import TwitterDraft
from src.core.utils import should_include_soft_promo, stable_ratio, utc_now

LOGGER = logging.getLogger(__name__)

ALLOWED_ANGLES = (
    "observation",
    "result",
    "proof",
    "lesson",
    "market context",
    "operator opinion",
    "recap",
    "watchlist",
)
ALLOWED_VALUE_TYPES = (
    "curiosity value",
    "watchlist value",
    "learning value",
    "proof value",
    "decision value",
)


@dataclass(frozen=True, slots=True)
class _VariantRule:
    min_words: int
    max_words: int


@dataclass(frozen=True, slots=True)
class _AnalysisDecision:
    worth_posting: bool
    angle: str
    value_types: tuple[str, ...]
    hook: str
    takeaway: str
    why_it_matters: str
    skip_reason: str


@dataclass(frozen=True, slots=True)
class _PreparedContextFacts:
    fields: dict[str, str]
    sections: dict[str, tuple[str, ...]]

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key.lower(), default)

    def section(self, key: str) -> tuple[str, ...]:
        return self.sections.get(key.lower(), ())


class TwitterDraftGenerator:
    def __init__(self, settings: Settings, ollama_client: OllamaClient | None) -> None:
        self.settings = settings
        self.ollama_client = ollama_client
        self._banned_phrases = (
            "i'm excited",
            "best regards",
            "join us",
            "revolutionizing",
            "guaranteed profits",
            "guaranteed profit",
            "moon",
            "lambo",
            "100x",
            "financial advice",
            "here's a tweet-sized post",
            "here is a tweet-sized post",
            "tweet-sized post",
            "main draft:",
            "short version:",
            "reply/comment:",
            "twitter-style post",
            "twitter-sized post",
            "here's a possible",
            "here is a possible",
            "here are two",
            "optional reply",
            "longer variant",
            "first post:",
            "second post:",
            "draft tweet",
            "x/twitter post",
        )
        self._watched_phrases = (
            "reaction quality",
            "follow-through mattered",
            "worth a real look",
            "watchlist",
            "the alert mattered less than the reaction",
            "keep on the side",
            "late chasing",
        )
        self._emoji_options = {
            "twitter_best_setup_post": ("👀", "📍"),
            "twitter_followup_result_post": ("📈", "🧭"),
            "twitter_market_insight_post": ("🧭", "📍"),
            "twitter_operator_opinion_post": ("📝", "🧭"),
            "twitter_chart_post": ("📍", "👀"),
            "twitter_daily_recap_post": ("📝", "🧭"),
            "twitter_daily_stats_post": ("📊", "🧭"),
            "twitter_fomo_or_missed_move_post": ("👀", "📈"),
        }
        self._emoji_options = {
            "twitter_best_setup_post": ("\U0001F440", "\U0001F4CD"),
            "twitter_followup_result_post": ("\U0001F4C8", "\u26A0\uFE0F"),
            "twitter_market_insight_post": ("\U0001F440", "\U0001F4CD"),
            "twitter_operator_opinion_post": ("\U0001F4DD", "\U0001F440"),
            "twitter_chart_post": ("\U0001F4CD", "\U0001F440"),
            "twitter_daily_recap_post": ("\U0001F4DD", "\U0001F440"),
            "twitter_daily_stats_post": ("\U0001F4CA", "\U0001F440"),
            "twitter_fomo_or_missed_move_post": ("\U0001F440", "\U0001F4C8"),
        }

    @staticmethod
    def _error_text(exc: Exception) -> str:
        text = str(exc).strip()
        return text or f"{type(exc).__name__}: {exc!r}"

    def _should_abort_model_fallback(self, exc: Exception) -> bool:
        lowered = self._error_text(exc).lower()
        return "temporarily cooled down" in lowered or "timed out" in lowered

    async def generate_best_setup_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_best_setup_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="watchlist",
                value_types=("watchlist value", "decision value"),
                hook=f"{source_symbol or 'This setup'} looks cleaner than most of what the board is printing.",
                takeaway="The setup has enough structure, score, and liquidity to be worth attention.",
                why_it_matters="Useful filtering matters more than raw alert count.",
            ),
        )

    async def generate_followup_result_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_followup_result_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="result",
                value_types=("proof value", "learning value"),
                hook=f"{source_symbol or 'The setup'} already has a usable outcome.",
                takeaway="The value is in the follow-through and what it says about reaction quality.",
                why_it_matters="Outcome-based posts build more trust than raw signal claims.",
            ),
        )

    async def generate_market_insight_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_market_insight_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="market context",
                value_types=("learning value", "decision value"),
                hook="The session is starting to show a readable pattern instead of random noise.",
                takeaway="The useful part is the cluster and tone of the tape, not one isolated print.",
                why_it_matters="Context helps people filter the board faster.",
            ),
        )

    async def generate_operator_opinion_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_operator_opinion_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="operator opinion",
                value_types=("curiosity value", "learning value"),
                hook="The board is giving a better read on reaction quality than on raw trigger count.",
                takeaway="The cleaner edge usually comes from patience and filtering, not from chasing every print.",
                why_it_matters="A human read backed by data makes the account feel more credible.",
            ),
        )

    async def generate_chart_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_chart_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="observation",
                value_types=("watchlist value", "curiosity value"),
                hook=f"The chart in {source_symbol or 'this setup'} tells the story cleanly enough on its own.",
                takeaway="If the visual tells a clear story, the caption should stay tight.",
                why_it_matters="A chart-first post works best when the setup is obvious and readable.",
            ),
        )

    async def generate_daily_recap_draft(
        self,
        *,
        prepared_context: str,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_daily_recap_post",
            prepared_context=prepared_context,
            source_symbol=None,
            score=None,
            related_alert_id=None,
            chart_path=None,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="recap",
                value_types=("learning value", "proof value"),
                hook="The day had a readable shape, not just random signal flow.",
                takeaway="The better setups were the ones where price reaction confirmed the trigger.",
                why_it_matters="A short recap helps readers see the bigger pattern.",
            ),
        )

    async def generate_daily_stats_draft(
        self,
        *,
        prepared_context: str,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_daily_stats_post",
            prepared_context=prepared_context,
            source_symbol=None,
            score=None,
            related_alert_id=None,
            chart_path=None,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="proof",
                value_types=("proof value", "decision value"),
                hook="The numbers only matter if they point to a takeaway.",
                takeaway="Stats are useful when they explain the tape instead of dumping counts.",
                why_it_matters="Readers need interpretation, not a spreadsheet.",
            ),
        )

    async def generate_fomo_or_missed_move_draft(
        self,
        *,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool = False,
    ) -> TwitterDraft:
        return await self._generate_draft(
            content_type="twitter_fomo_or_missed_move_post",
            prepared_context=prepared_context,
            source_symbol=source_symbol,
            score=score,
            related_alert_id=related_alert_id,
            chart_path=chart_path,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=self._fallback_decision(
                angle="proof",
                value_types=("curiosity value", "proof value"),
                hook=f"{source_symbol or 'This setup'} already moved enough to make the earlier signal worth revisiting.",
                takeaway="After-the-fact proof works only when it stays grounded and specific.",
                why_it_matters="Honest missed-move posts can create curiosity without sounding manipulative.",
            ),
        )

    async def _generate_draft(
        self,
        *,
        content_type: str,
        prepared_context: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        chart_path,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool,
        fallback_decision: _AnalysisDecision,
    ) -> TwitterDraft:
        facts = self._parse_prepared_context(prepared_context)
        decision, analysis_model = await self._analyze_candidate(
            content_type=content_type,
            prepared_context=prepared_context,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            fallback_decision=fallback_decision,
        )

        if not decision.worth_posting and not preview_mode:
            return self._skipped_draft(
                content_type=content_type,
                source_symbol=source_symbol,
                score=score,
                related_alert_id=related_alert_id,
                analysis_model=analysis_model,
                preview_mode=preview_mode,
                skip_reason=decision.skip_reason or "weak_value",
                angle=decision.angle,
                value_types=decision.value_types,
            )

        if not decision.value_types and not preview_mode:
            return self._skipped_draft(
                content_type=content_type,
                source_symbol=source_symbol,
                score=score,
                related_alert_id=related_alert_id,
                analysis_model=analysis_model,
                preview_mode=preview_mode,
                skip_reason="missing_value_type",
                angle=decision.angle,
                value_types=decision.value_types,
            )

        if not preview_mode and self._angle_is_overused(decision.angle, recent_drafts):
            return self._skipped_draft(
                content_type=content_type,
                source_symbol=source_symbol,
                score=score,
                related_alert_id=related_alert_id,
                analysis_model=analysis_model,
                preview_mode=preview_mode,
                skip_reason="repeated_angle",
                angle=decision.angle,
                value_types=decision.value_types,
            )

        analysis_summary = self._analysis_summary(decision)
        include_soft_promo = should_include_soft_promo(
            f"{content_type}:{source_symbol}:{related_alert_id}:{utc_now().date().isoformat()}",
            self.settings.x_soft_promo_rate,
        )
        fallback_main_text = self._fallback_main_text(
            content_type,
            decision,
            source_symbol,
            include_soft_promo,
            prepared_context,
        )

        main_text, writer_model = await self._write_variant(
            prompt=self._main_prompt(
                content_type=content_type,
                prepared_context=prepared_context,
                analysis_summary=analysis_summary,
                include_soft_promo=include_soft_promo,
                preview_mode=preview_mode,
            ),
            fallback=fallback_main_text,
            variant="main",
            preview_mode=preview_mode,
        )
        main_text = self._polish_main_text(
            text=main_text,
            content_type=content_type,
            source_symbol=source_symbol,
            related_alert_id=related_alert_id,
        )
        if self._needs_value_rescue(main_text):
            main_text = self._polish_main_text(
                text=fallback_main_text,
                content_type=content_type,
                source_symbol=source_symbol,
                related_alert_id=related_alert_id,
            )
        if chart_path is None and source_symbol is None and self._text_mentions_symbol(main_text):
            main_text = self._polish_main_text(
                text=self._fallback_main_text(
                    content_type,
                    decision,
                    source_symbol,
                    include_soft_promo=False,
                    prepared_context=prepared_context,
                    allow_symbol_reference=False,
                ),
                content_type=content_type,
                source_symbol=source_symbol,
                related_alert_id=related_alert_id,
            )

        short_variant = None
        if preview_mode:
            short_variant = self._select_short_variant(
                main_text,
                self._fallback_short_text(content_type, decision, source_symbol, prepared_context),
            )
        reply_variant = None

        if not preview_mode and not self._final_text_is_worthy(
            main_text,
            decision,
            content_type,
            chart_path=chart_path,
        ):
            return self._skipped_draft(
                content_type=content_type,
                source_symbol=source_symbol,
                score=score,
                related_alert_id=related_alert_id,
                analysis_model=analysis_model,
                preview_mode=preview_mode,
                skip_reason="weak_value",
                angle=decision.angle,
                value_types=decision.value_types,
                writer_model=writer_model,
            )

        draft = TwitterDraft(
            destination=self.settings.twitter_drafts_chat,
            content_type=content_type,
            main_text=main_text,
            mode="PREVIEW" if preview_mode else "NORMAL",
            angle=decision.angle,
            value_types=decision.value_types,
            short_variant=short_variant,
            reply_variant=reply_variant,
            source_symbol=source_symbol,
            related_alert_id=related_alert_id,
            score=score,
            chart_path=chart_path,
            writer_model=writer_model,
            analysis_model=analysis_model,
            status="generated",
            preview_mode=preview_mode,
            metadata={
                "analysis_summary": analysis_summary,
                "generated_at": utc_now().isoformat(),
                "include_reply_in_telegram": False,
                "include_short_in_telegram": bool(short_variant and preview_mode),
                "facts_loaded": bool(facts.fields or facts.sections),
            },
        )

        return await self._finalize_draft(
            draft=draft,
            prepared_context=prepared_context,
            analysis_summary=analysis_summary,
            recent_drafts=recent_drafts,
            preview_mode=preview_mode,
            source_symbol=source_symbol,
        )

    async def _analyze_candidate(
        self,
        *,
        content_type: str,
        prepared_context: str,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool,
        fallback_decision: _AnalysisDecision,
    ) -> tuple[_AnalysisDecision, str]:
        if not self.settings.ollama_enabled or self.ollama_client is None:
            return fallback_decision, "fallback-analysis"
        if self.ollama_client.is_cooling_down():
            return fallback_decision, "fallback-cooldown"

        recent_angles = ", ".join(draft.angle for draft in recent_drafts[:8] if draft.angle) or "none"
        overused = ", ".join(self._overused_phrases(recent_drafts)) or "none"
        prompt = twitter_analysis_decision(
            candidate_type=content_type,
            prepared_context=prepared_context,
            recent_angles=recent_angles,
            overused_phrases=overused,
            preview_mode=preview_mode,
        )
        for model_name in self._analysis_model_candidates():
            try:
                raw = await self.ollama_client.generate(
                    prompt,
                    model_name=model_name,
                    temperature=0.15,
                    timeout_seconds=self._ollama_timeout_for_x(preview_mode=preview_mode, variant="analysis"),
                    retries=self._ollama_retries_for_x(preview_mode=preview_mode, variant="analysis"),
                    base_delay=0.8,
                )
                return self._parse_analysis_response(self._clean_output(raw)), model_name
            except Exception as exc:  # pragma: no cover - runtime dependent
                error_text = self._error_text(exc)
                if self._should_abort_model_fallback(exc):
                    LOGGER.info(
                        "X analysis for %s is temporarily using fallback. Model=%s Error=%s",
                        content_type,
                        model_name,
                        error_text,
                    )
                    break
                LOGGER.warning(
                    "X analysis model %s failed for %s. Falling back. Error: %s",
                    model_name,
                    content_type,
                    error_text,
                )
        return fallback_decision, "fallback-analysis"

    async def _write_variant(self, *, prompt: str, fallback: str, variant: str, preview_mode: bool) -> tuple[str, str]:
        fallback_clean = self._normalize_variant_output(self._clean_output(fallback), variant)
        if not self.settings.ollama_enabled or self.ollama_client is None:
            return fallback_clean, "fallback-template"
        if self.ollama_client.is_cooling_down():
            return fallback_clean, "fallback-cooldown"
        model_candidates = self._writer_model_candidates()
        if variant != "main":
            model_candidates = model_candidates[:1]
        for model_name in model_candidates:
            try:
                output = await self.ollama_client.generate(
                    prompt,
                    model_name=model_name,
                    temperature=0.48,
                    timeout_seconds=self._ollama_timeout_for_x(preview_mode=preview_mode, variant=variant),
                    retries=self._ollama_retries_for_x(preview_mode=preview_mode, variant=variant),
                    base_delay=0.8,
                )
                cleaned = self._normalize_variant_output(self._clean_output(output), variant)
                self._validate_writer_output(cleaned, variant)
                return cleaned, model_name
            except Exception as exc:  # pragma: no cover - runtime dependent
                error_text = self._error_text(exc)
                if variant == "main":
                    if self._should_abort_model_fallback(exc):
                        LOGGER.info(
                            "X writer for %s variant is temporarily using fallback. Model=%s Error=%s",
                            variant,
                            model_name,
                            error_text,
                        )
                        break
                    LOGGER.warning(
                        "X writer model %s failed for %s variant. Falling back. Error: %s",
                        model_name,
                        variant,
                        error_text,
                    )
                    continue
                LOGGER.debug(
                    "X %s variant from model %s was rejected, using fallback: %s",
                    variant,
                    model_name,
                    error_text,
                )
                return fallback_clean, "fallback-template"
        return fallback_clean, "fallback-template"

    def _ollama_timeout_for_x(self, *, preview_mode: bool, variant: str) -> float:
        configured = float(self.settings.ollama_timeout_seconds)
        if variant == "analysis":
            return min(configured, 18.0 if preview_mode else 24.0)
        if variant == "main":
            return min(configured, 20.0 if preview_mode else 28.0)
        return min(configured, 10.0)

    def _ollama_retries_for_x(self, *, preview_mode: bool, variant: str) -> int:
        if preview_mode:
            return 1
        if variant == "main":
            return max(1, min(self.settings.http_max_retries, 2))
        return 1

    async def _finalize_draft(
        self,
        *,
        draft: TwitterDraft,
        prepared_context: str,
        analysis_summary: str,
        recent_drafts: list[TwitterDraft],
        preview_mode: bool,
        source_symbol: str | None,
    ) -> TwitterDraft:
        overused_phrases = self._overused_phrases(recent_drafts)
        draft.similarity_score = self._max_similarity(draft.main_text, recent_drafts)
        if draft.similarity_score < 0.73 and not self._contains_overused_phrase(draft.main_text, overused_phrases):
            return draft

        draft.rewritten_for_similarity = True
        rewritten_text, rewrite_model = await self._rewrite_main_text(
            current_text=draft.main_text,
            prepared_context=prepared_context,
            analysis_summary=analysis_summary,
            recent_drafts=recent_drafts,
            fallback=self._fallback_rewrite_text(draft, source_symbol, prepared_context),
        )
        draft.main_text = self._polish_main_text(
            text=rewritten_text,
            content_type=draft.content_type,
            source_symbol=draft.source_symbol,
            related_alert_id=draft.related_alert_id,
        )
        draft.writer_model = rewrite_model
        draft.status = "rewritten"
        draft.similarity_score = self._max_similarity(draft.main_text, recent_drafts)
        if preview_mode:
            if draft.similarity_score >= 0.73 or self._contains_overused_phrase(draft.main_text, overused_phrases):
                draft.metadata["preview_similarity_warning"] = True
            return draft
        if draft.similarity_score >= 0.73 or self._contains_overused_phrase(draft.main_text, overused_phrases):
            return self._skipped_draft(
                content_type=draft.content_type,
                source_symbol=draft.source_symbol,
                score=draft.score,
                related_alert_id=draft.related_alert_id,
                analysis_model=draft.analysis_model,
                preview_mode=preview_mode,
                skip_reason="similarity",
                angle=draft.angle,
                value_types=draft.value_types,
                writer_model=draft.writer_model,
                similarity_score=draft.similarity_score,
                rewritten_for_similarity=True,
            )
        return draft

    async def _rewrite_main_text(
        self,
        *,
        current_text: str,
        prepared_context: str,
        analysis_summary: str,
        recent_drafts: list[TwitterDraft],
        fallback: str,
    ) -> tuple[str, str]:
        prompt = twitter_rewrite_for_diversity(
            existing_text=current_text,
            prepared_context=prepared_context,
            analysis_summary=analysis_summary,
            avoid_phrases=", ".join(self._overused_phrases(recent_drafts)) or "none",
            recent_openings=" | ".join(self._opening_line(draft.main_text) for draft in recent_drafts[:5]) or "none",
        )
        return await self._write_variant(prompt=prompt, fallback=fallback, variant="main", preview_mode=False)

    def _analysis_model_candidates(self) -> list[str]:
        models = [
            self.settings.effective_ollama_analysis_model,
            self.settings.effective_ollama_writer_model,
            self.settings.ollama_model,
        ]
        return [model for index, model in enumerate(models) if model and model not in models[:index]]

    def _writer_model_candidates(self) -> list[str]:
        models = [
            self.settings.effective_ollama_writer_model,
            self.settings.effective_ollama_analysis_model,
            self.settings.ollama_model,
        ]
        return [model for index, model in enumerate(models) if model and model not in models[:index]]

    def _main_prompt(
        self,
        *,
        content_type: str,
        prepared_context: str,
        analysis_summary: str,
        include_soft_promo: bool,
        preview_mode: bool,
    ) -> str:
        prompt_map = {
            "twitter_best_setup_post": twitter_best_setup_post,
            "twitter_followup_result_post": twitter_followup_result_post,
            "twitter_market_insight_post": twitter_market_insight_post,
            "twitter_operator_opinion_post": twitter_operator_opinion_post,
            "twitter_chart_post": twitter_chart_post,
            "twitter_daily_recap_post": twitter_daily_recap_post,
            "twitter_daily_stats_post": twitter_daily_stats_post,
            "twitter_fomo_or_missed_move_post": twitter_fomo_or_missed_move_post,
        }
        return prompt_map[content_type](
            prepared_context=prepared_context,
            analysis_summary=analysis_summary,
            include_soft_promo=include_soft_promo,
            preview_mode=preview_mode,
        )

    def _analysis_summary(self, decision: _AnalysisDecision) -> str:
        return (
            f"Angle: {decision.angle}\n"
            f"Value: {', '.join(decision.value_types)}\n"
            f"Hook: {decision.hook}\n"
            f"Takeaway: {decision.takeaway}\n"
            f"Why It Matters: {decision.why_it_matters}"
        )

    def _parse_analysis_response(self, text: str) -> _AnalysisDecision:
        parsed: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip().lower()] = value.strip()
        worth_posting = parsed.get("worth posting", "no").lower().startswith("y")
        angle = parsed.get("angle", "").strip().lower()
        if angle not in ALLOWED_ANGLES:
            angle = "observation"
        raw_values = [item.strip().lower() for item in parsed.get("value", "").split(",") if item.strip()]
        value_types = tuple(value for value in raw_values if value in ALLOWED_VALUE_TYPES)
        return _AnalysisDecision(
            worth_posting=worth_posting,
            angle=angle,
            value_types=value_types,
            hook=parsed.get("hook", ""),
            takeaway=parsed.get("takeaway", ""),
            why_it_matters=parsed.get("why it matters", ""),
            skip_reason=parsed.get("skip reason", "none"),
        )

    def _validate_writer_output(self, text: str, variant: str) -> None:
        if not text:
            raise RuntimeError("empty X draft output")
        lowered = text.lower()
        for phrase in self._banned_phrases:
            if phrase in lowered:
                raise RuntimeError(f"banned phrase detected: {phrase}")
        if self._contains_meta_output(text):
            raise RuntimeError("meta output detected")
        rule = self._variant_rules()[variant]
        word_count = len(re.findall(r"\b[\w']+\b", text))
        if word_count < rule.min_words or word_count > rule.max_words:
            raise RuntimeError(f"word count {word_count} outside {rule.min_words}-{rule.max_words}")
        if text.count("\n") > 5:
            raise RuntimeError("too many lines for X draft")
        if self._emoji_count(text) > 2:
            raise RuntimeError("too many emojis for X draft")

    def _variant_rules(self) -> dict[str, _VariantRule]:
        return {
            "main": _VariantRule(12, 130),
            "short": _VariantRule(4, 45),
            "reply": _VariantRule(3, 28),
        }

    def _normalize_variant_output(self, text: str, variant: str) -> str:
        normalized = self._extract_primary_candidate(text, variant)
        normalized = re.sub(r"[ \t]+", " ", normalized).strip()
        if variant == "main":
            return normalized

        normalized = re.sub(r"\n{2,}", "\n", normalized)
        rule = self._variant_rules()[variant]
        if len(re.findall(r"\b[\w']+\b", normalized)) <= rule.max_words and normalized.count("\n") <= 4:
            return normalized

        candidate = self._best_compact_candidate(normalized, rule.min_words, rule.max_words)
        if candidate:
            return self._trim_to_word_limit(candidate, rule.max_words)

        single_line = " ".join(part.strip() for part in normalized.splitlines() if part.strip())
        single_line = self._trim_to_word_limit(single_line, rule.max_words)
        return single_line

    def _best_compact_candidate(self, text: str, min_words: int, max_words: int) -> str | None:
        segments = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", text) if segment.strip()]
        if not segments:
            return None

        valid_segments = []
        for segment in segments:
            word_count = len(re.findall(r"\b[\w']+\b", segment))
            if min_words <= word_count <= max_words:
                valid_segments.append(segment)
        if valid_segments:
            return min(valid_segments, key=lambda segment: len(re.findall(r"\b[\w']+\b", segment)))

        combined = segments[0]
        for segment in segments[1:]:
            word_count = len(re.findall(r"\b[\w']+\b", combined))
            if word_count >= min_words:
                break
            combined = f"{combined} {segment}"
        return combined if combined else None

    def _trim_to_word_limit(self, text: str, max_words: int) -> str:
        words = re.findall(r"\S+", text)
        if len(words) <= max_words:
            return text
        trimmed = " ".join(words[:max_words]).rstrip(",;:-")
        if trimmed and trimmed[-1] not in ".!?":
            trimmed += "."
        return trimmed

    def _clean_output(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"^\s*#+\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = cleaned.replace("__", "").replace("`", "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(
            r"(?im)^\s*(here(?:['’?]s| is)\s+a\s+tweet-sized\s+post:?)\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?im)^\s*(main draft:|short version:|reply/comment:|reply:|alt version:)\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(r"(?im)^\s*here(?:['’?]s| is)\s+(?:a|the)\s+(?:rewritten\s+)?(?:draft|post|tweet):?\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*optional reply/comment line:?\s*", "", cleaned)
        cleaned = re.sub(r"(?i)\btweet-sized\s+post:?\s*", "", cleaned)
        cleaned = re.sub(r"(?i)\breply/comment:\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*(here(?:['’]s| is)\s+(?:a|an|the)\s+possible\s+.*?:)\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*(here(?:['’]s| is)\s+the\s+first\s+post:?)\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*(and\s+here(?:['’]s| is)\s+(?:a\s+)?shorter\s+variant:?)\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*(here(?:['’]s| is)\s+(?:the\s+)?twitter(?:-style|-sized)?\s+post:?)\s*", "", cleaned)
        return cleaned.strip(" \n\"'")

    def _polish_main_text(
        self,
        *,
        text: str,
        content_type: str,
        source_symbol: str | None,
        related_alert_id: int | None,
    ) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip().strip("\"'")
        cleaned = self._insert_readability_breaks(cleaned)
        if self._has_emoji(cleaned):
            return cleaned
        seed = f"{content_type}:{source_symbol}:{related_alert_id}:{utc_now().date().isoformat()}"
        if stable_ratio(seed) >= self.settings.x_emoji_rate:
            return cleaned
        emoji_choices = self._emoji_options.get(content_type)
        if not emoji_choices:
            return cleaned
        emoji = emoji_choices[int(stable_ratio(seed + ':emoji') * len(emoji_choices)) % len(emoji_choices)]
        return f"{emoji} {cleaned}"

    def _insert_readability_breaks(self, text: str) -> str:
        if "\n" in text or self._word_count(text) < 24:
            return text.strip()
        parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if len(parts) < 2:
            return text.strip()
        if len(parts) == 2:
            return f"{parts[0]}\n\n{parts[1]}".strip()
        first_block = parts[0]
        second_block = parts[1]
        remainder = " ".join(parts[2:]).strip()
        if not remainder:
            return f"{first_block}\n\n{second_block}".strip()
        return f"{first_block}\n\n{second_block}\n\n{remainder}".strip()

    def _has_emoji(self, text: str) -> bool:
        return bool(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))

    def _select_short_variant(self, main_text: str, candidate: str | None) -> str | None:
        if not candidate:
            return None
        if self._contains_meta_output(candidate):
            return None
        if self._variant_similarity(main_text, candidate) >= 0.84:
            return None
        main_words = self._word_count(main_text)
        candidate_words = self._word_count(candidate)
        if candidate_words >= max(18, int(main_words * 0.85)):
            return None
        if candidate.strip().lower() == main_text.strip().lower():
            return None
        return candidate.strip()

    def _select_reply_variant(self, main_text: str, candidate: str | None, preview_mode: bool) -> str | None:
        if not preview_mode or not candidate:
            return None
        if self._variant_similarity(main_text, candidate) >= 0.72:
            return None
        if self._word_count(candidate) > 22:
            return None
        return candidate.strip()

    def _variant_similarity(self, left: str, right: str) -> float:
        return SequenceMatcher(None, self._normalize_for_similarity(left), self._normalize_for_similarity(right)).ratio()

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"\b[\w']+\b", text))

    def _needs_value_rescue(self, text: str) -> bool:
        lowered = text.lower()
        generic_markers = (
            "rsi tells us",
            "oversold conditions",
            "overbought conditions",
            "can signal potential",
            "not as straightforward as it seems",
            "don't jump to conclusions",
            "always consider context",
            "15m chart?",
            "this setup highlights",
            "helps refine",
            "here's",
            "here is",
            "twitter-style",
            "tweet-sized",
            "this post",
            "optional reply",
            "longer variant",
        )
        return any(marker in lowered for marker in generic_markers) or self._contains_meta_output(text)

    def _final_text_is_worthy(
        self,
        text: str,
        decision: _AnalysisDecision,
        content_type: str,
        *,
        chart_path,
    ) -> bool:
        lowered = text.lower()
        if self._word_count(text) < 10:
            return False
        if not decision.value_types:
            return False
        if self._contains_meta_output(text):
            return False
        generic_patterns = (
            "crypto is noisy",
            "the market is noisy",
            "we filter the market",
            "we scan the market",
            "helps filter the market",
            "not financial advice",
        )
        if any(pattern in lowered for pattern in generic_patterns):
            return False
        if self._opening_is_generic(text):
            return False
        if chart_path is None and self._text_mentions_symbol(text):
            return False
        common_markers = (
            "watch",
            "reaction",
            "follow-through",
            "stretched",
            "liquidity",
            "moved",
            "outcome",
            "board",
            "setup",
            "price",
            "session",
            "today",
            "scan",
            "proof",
            "chasing",
        )
        if not any(phrase in lowered for phrase in common_markers):
            return False
        content_specific_markers = {
            "twitter_followup_result_post": ("after the alert", "flagged", "moved", "reaction", "follow-through", "outcome"),
            "twitter_fomo_or_missed_move_post": ("flagged", "moved", "earlier", "after the alert", "reaction"),
            "twitter_best_setup_post": ("cleaner", "setup", "liquidity", "structure", "watchlist", "board"),
            "twitter_chart_post": ("chart", "reaction", "structure", "price"),
            "twitter_market_insight_post": ("session", "board", "tape", "scan", "today"),
            "twitter_operator_opinion_post": ("my read", "tape", "board", "session", "today"),
            "twitter_daily_recap_post": ("today", "session", "follow-through", "reaction"),
            "twitter_daily_stats_post": ("today", "numbers", "follow-through", "session"),
        }
        return any(marker in lowered for marker in content_specific_markers.get(content_type, common_markers))

    def _max_similarity(self, text: str, recent_drafts: list[TwitterDraft]) -> float:
        if not recent_drafts:
            return 0.0
        target = self._normalize_for_similarity(text)
        target_opening = self._opening_line(text)
        scores: list[float] = []
        for draft in recent_drafts:
            compare = self._normalize_for_similarity(draft.main_text)
            if not compare:
                continue
            base_ratio = SequenceMatcher(None, target, compare).ratio()
            opening_ratio = SequenceMatcher(None, target_opening, self._opening_line(draft.main_text)).ratio()
            phrase_overlap = self._phrase_overlap(target, compare)
            scores.append(max(base_ratio, (opening_ratio * 0.7) + (phrase_overlap * 0.3)))
        return max(scores, default=0.0)

    def _phrase_overlap(self, left: str, right: str) -> float:
        left_words = left.split()
        right_words = right.split()
        left_phrases = {" ".join(left_words[index:index + 3]) for index in range(max(0, len(left_words) - 2))}
        right_phrases = {" ".join(right_words[index:index + 3]) for index in range(max(0, len(right_words) - 2))}
        if not left_phrases or not right_phrases:
            return 0.0
        return len(left_phrases & right_phrases) / max(len(left_phrases | right_phrases), 1)

    def _normalize_for_similarity(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()

    def _opening_line(self, text: str) -> str:
        return text.splitlines()[0].strip().lower() if text else ""

    def _overused_phrases(self, recent_drafts: list[TwitterDraft]) -> tuple[str, ...]:
        counter: Counter[str] = Counter()
        corpus = " || ".join(draft.main_text.lower() for draft in recent_drafts[:10])
        for phrase in self._watched_phrases:
            counter[phrase] = corpus.count(phrase)
        return tuple(phrase for phrase, count in counter.items() if count >= 2)

    def _contains_overused_phrase(self, text: str, phrases: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in phrases)

    def _angle_is_overused(self, angle: str, recent_drafts: list[TwitterDraft]) -> bool:
        recent_angles = [draft.angle for draft in recent_drafts[:3] if draft.angle]
        return len(recent_angles) >= 2 and all(existing == angle for existing in recent_angles[:2])

    def _fallback_decision(
        self,
        *,
        angle: str,
        value_types: tuple[str, ...],
        hook: str,
        takeaway: str,
        why_it_matters: str,
    ) -> _AnalysisDecision:
        return _AnalysisDecision(
            worth_posting=True,
            angle=angle,
            value_types=value_types,
            hook=hook,
            takeaway=takeaway,
            why_it_matters=why_it_matters,
            skip_reason="none",
        )

    def _fallback_main_text(
        self,
        content_type: str,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        include_soft_promo: bool,
        prepared_context: str,
        allow_symbol_reference: bool = True,
    ) -> str:
        facts = self._parse_prepared_context(prepared_context)
        builders = {
            "twitter_best_setup_post": self._build_best_setup_fallback,
            "twitter_followup_result_post": self._build_followup_result_fallback,
            "twitter_market_insight_post": self._build_market_insight_fallback,
            "twitter_operator_opinion_post": self._build_operator_opinion_fallback,
            "twitter_chart_post": self._build_chart_fallback,
            "twitter_daily_recap_post": self._build_daily_recap_fallback,
            "twitter_daily_stats_post": self._build_daily_stats_fallback,
            "twitter_fomo_or_missed_move_post": self._build_missed_move_fallback,
        }
        return builders[content_type](
            decision=decision,
            source_symbol=source_symbol,
            facts=facts,
            include_soft_promo=include_soft_promo,
            allow_symbol_reference=allow_symbol_reference,
        )

    def _fallback_short_text(
        self,
        content_type: str,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        prepared_context: str,
    ) -> str:
        facts = self._parse_prepared_context(prepared_context)
        symbol = source_symbol or facts.get("symbol") or "This setup"
        timeframe = facts.get("timeframe", "15m")
        move_text = facts.get("move since alert", "after the alert")
        short_map = {
            "twitter_best_setup_post": f"{symbol} is stretched enough on the {timeframe} that reaction matters more than chasing the print here.",
            "twitter_followup_result_post": f"{symbol} was flagged, then moved {move_text}. The follow-up mattered more than the trigger.",
            "twitter_market_insight_post": "Today's tape rewarded patience. The better read came from follow-through, not raw trigger count.",
            "twitter_operator_opinion_post": "My read today: reaction quality beat raw trigger count.",
            "twitter_chart_post": f"{symbol} is a good chart to save because the reaction after the signal is the real story.",
            "twitter_daily_recap_post": "Close note: the alerts only mattered when price actually respected them.",
            "twitter_daily_stats_post": "The useful stat today was selectivity, not alert count.",
            "twitter_fomo_or_missed_move_post": f"{symbol} was flagged, then {move_text} happened. Acceptance after the extreme mattered more than the extreme itself.",
        }
        return short_map.get(content_type, decision.takeaway)

    def _fallback_rewrite_text(self, draft: TwitterDraft, source_symbol: str | None, prepared_context: str) -> str:
        return self._fallback_main_text(
            draft.content_type,
            _AnalysisDecision(
                worth_posting=True,
                angle=draft.angle or "observation",
                value_types=draft.value_types,
                hook="",
                takeaway="",
                why_it_matters="",
                skip_reason="none",
            ),
            source_symbol,
            include_soft_promo=False,
            prepared_context=prepared_context,
        )

    def _parse_prepared_context(self, prepared_context: str) -> _PreparedContextFacts:
        fields: dict[str, str] = {}
        sections: dict[str, list[str]] = {}
        current_section: str | None = None
        for raw_line in prepared_context.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith(":") and ":" not in line[:-1]:
                current_section = line[:-1].strip().lower()
                sections.setdefault(current_section, [])
                continue
            if line.startswith("- "):
                if current_section is not None:
                    sections.setdefault(current_section, []).append(line[2:].strip())
                continue
            current_section = None
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        return _PreparedContextFacts(
            fields=fields,
            sections={key: tuple(value) for key, value in sections.items()},
        )

    def _build_best_setup_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        symbol = self._symbol_text(source_symbol, facts, allow_symbol_reference)
        timeframe = facts.get("timeframe", "15m")
        direction = facts.get("direction", "").lower()
        rsi_text = facts.get("rsi(14, closed)")
        score_text = facts.get("score")
        volume_context = facts.get("volume context")
        trend_context = facts.get("trend context")
        hook_options = (
            f"{symbol} is finally stretched enough on the {timeframe} to earn a real look.",
            f"Late chasing in {symbol} is getting less attractive on the {timeframe}.",
            f"{symbol} just moved from background noise to watchlist territory.",
        )
        if direction == "oversold":
            hook_options = (
                f"{symbol} is finally showing the kind of washout that can matter on the {timeframe}.",
                f"Selling in {symbol} is starting to look crowded on the {timeframe}.",
                f"{symbol} is stretched enough here that the next reaction matters more than the trigger itself.",
            )
        hook = self._pick(f"best:{symbol}:{timeframe}", hook_options)
        detail = self._join_sentences(
            [
                self._sentence_if(f"{symbol} printed RSI {rsi_text}, score {score_text}, and {volume_context}.", rsi_text and score_text and volume_context),
                self._sentence_if(f"The setup still needs price reaction, but the context is cleaner: {trend_context}.", trend_context),
                "That is enough context to keep it on the watchlist without pretending the reversal is already confirmed.",
            ]
        )
        takeaway = "Useful setups are not just extreme. They are extreme with enough structure and liquidity to matter."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_followup_result_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        symbol = self._symbol_text(source_symbol, facts, allow_symbol_reference)
        move_text = facts.get("move since alert", "after the alert")
        alert_rsi = facts.get("rsi then")
        current_rsi = facts.get("rsi now")
        reaction_quality = facts.get("reaction quality")
        summary = facts.get("summary")
        confirmed = self._followup_is_confirmed(facts)
        hook_options = (
            f"This is the part that made the alert useful: {symbol} moved {move_text} after the signal.",
            f"{symbol} gave the post-alert proof that matters more than the raw trigger.",
            f"{symbol} was flagged earlier. The follow-through is what made it worth revisiting.",
        ) if confirmed else (
            f"The raw alert was only step one. {symbol} showed the real story in the follow-up.",
            f"{symbol} did not respond cleanly to the signal, and that is useful information too.",
            f"{symbol} is a good reminder that the follow-up matters more than the screenshot.",
        )
        hook = self._pick(f"followup:{symbol}:{move_text}", hook_options)
        detail = self._join_sentences(
            [
                self._sentence_if(f"RSI went {alert_rsi} to {current_rsi} while price moved {move_text}.", alert_rsi and current_rsi),
                self._clean_sentence(summary or reaction_quality or decision.takeaway),
            ]
        )
        takeaway = (
            "The alert got attention. The reaction after it is what earned conviction."
            if confirmed
            else "Not every signal should be framed as a win. The useful part is learning what the market accepted after the alert."
        )
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_market_insight_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        session_tone = facts.get("session tone") or decision.hook or "The tape had a readable theme."
        proof_case = self._daily_proof_case(facts, allow_symbol_reference=allow_symbol_reference)
        total_alerts = facts.get("total alerts")
        total_followups = facts.get("total follow-ups")
        hook = self._pick(
            f"market:{session_tone}",
            (
                "Today's tape was easier to read through reactions than through raw alert count.",
                "The board finally showed a usable pattern instead of random noise.",
                "The useful part of today's session was not the triggers. It was which names actually followed through.",
            ),
        )
        detail = self._join_sentences(
            [
                self._clean_sentence(session_tone),
                self._sentence_if(f"{total_alerts} alerts and {total_followups} follow-ups only mattered once the market started separating proof from noise.", total_alerts and total_followups),
                self._clean_sentence(proof_case),
            ]
        )
        takeaway = "That is the read worth keeping: wait for reaction quality, then decide."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_operator_opinion_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        session_tone = facts.get("session tone")
        proof_case = self._daily_proof_case(facts, allow_symbol_reference=allow_symbol_reference)
        hook = self._pick(
            f"operator:{session_tone}",
            (
                "My read today: patience had a better edge than speed.",
                "My read on this session: the trigger was cheap, the confirmation was not.",
                "My takeaway from today's board: the useful setups made you wait a beat.",
            ),
        )
        detail = self._join_sentences(
            [
                self._clean_sentence(session_tone or decision.takeaway),
                self._clean_sentence(proof_case),
            ]
        )
        takeaway = "When the board starts printing extremes everywhere, I care more about acceptance after the trigger than the trigger itself."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_chart_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        symbol = self._symbol_text(source_symbol, facts, allow_symbol_reference)
        move_text = facts.get("move since alert")
        alert_rsi = facts.get("rsi then")
        current_rsi = facts.get("rsi now")
        reaction_quality = facts.get("reaction quality")
        volume_context = facts.get("volume context")
        hook = self._pick(
            f"chart:{symbol}:{move_text}",
            (
                f"{symbol} is a good chart to keep on the side today.",
                f"This {symbol} chart is useful because it shows the part people usually skip.",
                f"{symbol} is the kind of chart that explains why context matters more than speed.",
            ),
        )
        if move_text:
            detail = self._join_sentences(
                [
                    self._sentence_if(f"Price moved {move_text} after the alert while RSI shifted {alert_rsi} to {current_rsi}.", alert_rsi and current_rsi),
                    self._clean_sentence(reaction_quality or facts.get("summary") or decision.takeaway),
                ]
            )
            takeaway = "Before-and-after proof is more useful than a nice-looking indicator screenshot."
        else:
            detail = self._join_sentences(
                [
                    self._sentence_if(f"RSI is stretched and {volume_context}.", volume_context),
                    "The useful read is whether price starts rejecting the move here or keeps accepting it.",
                ]
            )
            takeaway = "The chart matters when it helps you judge whether price is rejecting the move or still accepting it."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_daily_recap_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        session_tone = facts.get("session tone")
        proof_case = self._daily_proof_case(facts, allow_symbol_reference=allow_symbol_reference)
        hook = self._pick(
            f"recap:{session_tone}",
            (
                "Close note: today was more about follow-through than triggers.",
                "Close note from the board: the useful setups were the ones that actually got respected after the alert.",
                "End-of-session read: the alerts only mattered once price confirmed them.",
            ),
        )
        detail = self._join_sentences(
            [
                self._clean_sentence(session_tone),
                self._clean_sentence(proof_case),
            ]
        )
        takeaway = "Going into the next session, the alert should get attention. The reaction should decide the trade."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_daily_stats_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        total_alerts = facts.get("total alerts")
        total_followups = facts.get("total follow-ups")
        confirmed = facts.get("confirmed follow-ups")
        failed = facts.get("failed follow-ups")
        proof_case = self._daily_proof_case(facts, allow_symbol_reference=allow_symbol_reference)
        hook = self._pick(
            f"stats:{total_alerts}:{total_followups}",
            (
                "The stat that mattered today was not the alert count. It was how selective you had to be.",
                "Today's numbers only got interesting once they pointed to a real takeaway.",
                "The board printed enough alerts today. The question was how many actually proved something.",
            ),
        )
        detail = self._join_sentences(
            [
                self._sentence_if(f"{total_alerts} alerts, {total_followups} follow-ups, {confirmed} confirmed reactions, {failed} misses.", total_alerts and total_followups and confirmed and failed),
                self._clean_sentence(proof_case),
            ]
        )
        takeaway = "Stats are only useful when they tell you what to ignore next time."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _build_missed_move_fallback(
        self,
        *,
        decision: _AnalysisDecision,
        source_symbol: str | None,
        facts: _PreparedContextFacts,
        include_soft_promo: bool,
        allow_symbol_reference: bool,
    ) -> str:
        symbol = self._symbol_text(source_symbol, facts, allow_symbol_reference)
        move_text = facts.get("move since alert", "after the alert")
        summary = facts.get("summary")
        direction = facts.get("direction", "").lower()
        confirmed = self._followup_is_confirmed(facts)
        hook_options = (
            f"{symbol} is why follow-ups matter more than screenshots of the trigger.",
            f"This is the kind of move that gets missed when people stop at the alert in {symbol}.",
            f"{symbol} was flagged, then the real information showed up after the trigger.",
        ) if confirmed else (
            f"{symbol} is a useful miss because the signal alone did not tell the whole story.",
            f"{symbol} kept the market honest after the alert, even if the first read was too simple.",
            f"{symbol} is a reminder that extremes do not trade themselves.",
        )
        hook = self._pick(f"missed:{symbol}:{move_text}", hook_options)
        if direction == "overbought" and not confirmed:
            hook = f"Overbought did not mean 'fade it' in {symbol}. The follow-up was the useful part."
        detail = self._join_sentences(
            [
                self._sentence_if(f"Price moved {move_text} after the alert.", move_text),
                self._clean_sentence(summary or decision.takeaway),
            ]
        )
        takeaway = "The lesson is simple: an extreme print matters less than whether price keeps accepting that direction after it."
        return self._compose_post(hook, detail, takeaway, include_soft_promo)

    def _compose_post(self, hook: str, detail: str, takeaway: str, include_soft_promo: bool) -> str:
        parts = [self._clean_sentence(hook), self._clean_sentence(detail), self._clean_sentence(takeaway)]
        if include_soft_promo:
            parts.append("That is why we keep logging the follow-up, not just the alert.")
        return "\n\n".join(part for part in parts if part)

    def _clean_sentence(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip().strip("\"'")
        if not cleaned:
            return ""
        return cleaned if cleaned[-1] in ".!?" else f"{cleaned}."

    def _join_sentences(self, parts: list[str]) -> str:
        return " ".join(part.strip() for part in parts if part).strip()

    def _sentence_if(self, text: str, condition: object) -> str:
        return self._clean_sentence(text) if condition else ""

    def _symbol_text(self, source_symbol: str | None, facts: _PreparedContextFacts, allow_symbol_reference: bool) -> str:
        if not allow_symbol_reference:
            return "This setup"
        return source_symbol or facts.get("symbol") or "This setup"

    def _pick(self, seed: str, options: tuple[str, ...]) -> str:
        if not options:
            return ""
        index = int(stable_ratio(seed) * len(options)) % len(options)
        return options[index]

    def _daily_proof_case(self, facts: _PreparedContextFacts, *, allow_symbol_reference: bool) -> str:
        proof_case = facts.get("top proof case")
        if not proof_case or proof_case == "none":
            notable = facts.section("notable follow-ups")
            proof_case = notable[0] if notable else ""
        if not allow_symbol_reference:
            proof_case = re.sub(r"\b[A-Z0-9]{2,}USDT\b", "the best follow-up", proof_case)
        if not proof_case:
            return ""
        return f"The clearest proof case was {proof_case}" if "proof case" not in proof_case.lower() else proof_case

    def _followup_is_confirmed(self, facts: _PreparedContextFacts) -> bool:
        direction = facts.get("direction", "").lower()
        move_value = self._parse_number(facts.get("move since alert"))
        if move_value is None:
            outcome = facts.get("outcome label", "").lower()
            return "follow-through" in outcome or "pullback" in outcome or "bounce" in outcome
        if direction == "oversold":
            return move_value > 0
        if direction == "overbought":
            return move_value < 0
        return abs(move_value) > 0

    def _parse_number(self, value: str | None) -> float | None:
        if not value:
            return None
        text = value.strip().lower().replace(",", "")
        if text in {"n/a", "none", "unknown"}:
            return None
        multiplier = 1.0
        if text.endswith("k"):
            multiplier = 1_000.0
        elif text.endswith("m"):
            multiplier = 1_000_000.0
        elif text.endswith("b"):
            multiplier = 1_000_000_000.0
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if match is None:
            return None
        return float(match.group(0)) * multiplier

    def _extract_primary_candidate(self, text: str, variant: str) -> str:
        quoted_candidates = [
            match.strip()
            for match in re.findall(r"[\"“](.{20,500}?)[\"”]", text, flags=re.DOTALL)
            if match.strip()
        ]
        if quoted_candidates:
            best = max(quoted_candidates, key=self._word_count)
            if self._word_count(best) >= self._variant_rules()[variant].min_words:
                return best

        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        usable_blocks = [block for block in blocks if not self._contains_meta_output(block)]
        if usable_blocks:
            return usable_blocks[0]
        return text

    def _contains_meta_output(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            r"\bhere(?:['’]s| is)\b",
            r"\b(?:tweet|post|draft|variant|reply)\b.{0,20}\b(?:for|:)",
            r"\btwitter-style\b",
            r"\boptional reply\b",
            r"\blonger variant\b",
            r"\bfirst post\b",
            r"\bsecond post\b",
            r"\bthis post aims\b",
        )
        return any(re.search(pattern, lowered) for pattern in patterns)

    def _emoji_count(self, text: str) -> int:
        return len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))

    def _opening_is_generic(self, text: str) -> bool:
        opening = self._opening_line(text)
        generic_openings = (
            "today's lesson",
            "crypto markets",
            "in today's session",
            "overbought signals dominated",
            "oversold signals dominated",
            "today's numbers",
            "short close note",
            "here's",
        )
        return any(opening.startswith(candidate) for candidate in generic_openings)

    def _text_mentions_symbol(self, text: str) -> bool:
        return bool(re.search(r"\b[A-Z0-9]{2,}USDT\b", text))

    def _skipped_draft(
        self,
        *,
        content_type: str,
        source_symbol: str | None,
        score: int | None,
        related_alert_id: int | None,
        analysis_model: str | None,
        preview_mode: bool,
        skip_reason: str,
        angle: str,
        value_types: tuple[str, ...],
        writer_model: str | None = None,
        similarity_score: float | None = None,
        rewritten_for_similarity: bool = False,
    ) -> TwitterDraft:
        return TwitterDraft(
            destination=self.settings.twitter_drafts_chat,
            content_type=content_type,
            main_text="",
            mode="PREVIEW" if preview_mode else "NORMAL",
            angle=angle,
            value_types=value_types,
            source_symbol=source_symbol,
            related_alert_id=related_alert_id,
            score=score,
            writer_model=writer_model,
            analysis_model=analysis_model,
            status="skipped",
            similarity_score=similarity_score,
            rewritten_for_similarity=rewritten_for_similarity,
            preview_mode=preview_mode,
            skipped_reason=skip_reason,
            metadata={"generated_at": utc_now().isoformat()},
        )
