from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
from contextlib import suppress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd

from src.ai.ollama_client import OllamaClient
from src.ai.prompts import premium_risk_commentary, premium_signal_analysis, premium_signal_rationale
from src.analysis.rationale import SignalRationale, compute_signal_rationale
from src.analysis.risk import RiskPlan, compute_risk_plan
from src.core.config import Settings
from src.core.models import AlertSignal, FollowUpResult
from src.core.utils import format_percent, format_price, format_rsi, format_volume, utc_now
from src.market.binance_client import BinanceClient
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats
from src.localization import is_russian, normalize_language
from src.storage.models import AlertRecord, FollowUpResultRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, float | None], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class PreparedFeature:
    content_type: str
    text_payload: str
    json_payload: dict[str, Any]
    model_name: str | None
    source_data_hash: str
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class PreparedFeatureContext:
    signal: AlertSignal
    frame: pd.DataFrame
    alert_record: AlertRecord | None
    followup_record: FollowUpResultRecord | None
    risk_plan: RiskPlan
    rationale: SignalRationale
    source_data_hash: str
    fact_payload: dict[str, Any]


class PreparedFeatureService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        binance_client: BinanceClient,
        ollama_client: OllamaClient | None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.binance_client = binance_client
        self.ollama_client = ollama_client
        self._tasks: set[asyncio.Task] = set()
        self._banned_phrases = (
            "guaranteed",
            "definitely buy",
            "definitely short",
            "100x",
            "moon",
            "lambo",
            "best regards",
            "join us",
            "this could be huge",
            "game changer",
            "revolutionary",
        )
        self._generic_note_fragments = (
            "watch price action",
            "manage risk accordingly",
            "do your own research",
            "keep an eye on it",
            "this could go either way",
            "wait for confirmation",
        )

    @staticmethod
    def _error_text(exc: Exception) -> str:
        text = str(exc).strip()
        return text or f"{type(exc).__name__}: {exc!r}"

    def _localized_content_type(self, content_type: str, language: str) -> str:
        normalized = normalize_language(language)
        return content_type if normalized == "en" else f"{content_type}:{normalized}"

    def _asset_class_for_symbol(self, symbol: str) -> str:
        normalized_symbol = str(symbol or "").strip().upper()
        gold_symbol = str(self.settings.gold_symbol or "").strip().upper()
        return "gold" if gold_symbol and normalized_symbol == gold_symbol else "crypto"

    def _market_label(self, symbol: str, *, language: str = "en") -> str:
        if self._asset_class_for_symbol(symbol) == "gold":
            return "Золото / XAUUSD" if is_russian(language) else "Gold / XAUUSD"
        return "Крипто-фьючерсы" if is_russian(language) else "Crypto futures"

    def _required_terms(self, content_type: str, language: str) -> tuple[str, ...]:
        if is_russian(language):
            return {
                "analysis": ("подтверд", "слаб", "след", "контекст", "структур", "отмен"),
                "risk": ("стоп", "цель", "риск", "размер", "част", "отмен"),
                "rationale": ("rsi", "объем", "тренд", "контекст", "триггер", "реакц"),
            }.get(content_type, ())
        return {
            "analysis": ("confirm", "weak", "watch", "invalidate", "context", "structure"),
            "risk": ("stop", "target", "risk", "size", "partial", "invalid"),
            "rationale": ("rsi", "volume", "trend", "context", "trigger", "reaction"),
        }.get(content_type, ())

    def _progress_text(self, key: str, language: str, **kwargs: object) -> str:
        normalized = normalize_language(language)
        ru = {
            "check_cache": "Проверяю кэш подготовленной карточки",
            "compare_context": "Сверяю контекст с сохраненными данными",
            "build_card": "Собираю новую {content_type} карточку",
            "save_snapshot": "Сохраняю входной snapshot",
            "analysis_stage": "Собираю AI-разбор сетапа",
            "risk_stage": "Считаю стопы, цели и риск-план",
            "rationale_stage": "Проверяю, почему сработал сигнал",
            "finalize": "Финализирую premium-карточку",
            "ready": "Карточка готова",
            "load_snapshot": "Загружаю живой рыночный snapshot",
            "compute_context": "Считаю сигнал, risk и rationale-контекст",
            "loaded_cache": "Загрузил карточку из кэша",
        }
        en = {
            "check_cache": "Checking prepared cache",
            "compare_context": "Comparing against stored premium context",
            "build_card": "Building fresh {content_type} card",
            "save_snapshot": "Saving prepared input snapshot",
            "analysis_stage": "Writing decision-ready AI analysis",
            "risk_stage": "Packaging risk variants and desk note",
            "rationale_stage": "Packaging signal rationale",
            "finalize": "Finalizing premium card",
            "ready": "Premium card ready",
            "load_snapshot": "Loading live market snapshot",
            "compute_context": "Computing signal, risk, and rationale context",
            "loaded_cache": "Loaded prepared card from cache",
        }
        template = (ru if normalized == "ru" else en)[key]
        return template.format(**kwargs)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def schedule_prepare_for_signal(self, signal: AlertSignal, alert_id: int) -> None:
        if not self.settings.prepared_feature_precompute_enabled:
            return
        task = asyncio.create_task(
            self._prepare_default_bundle(signal.symbol, signal.timeframe, alert_id),
            name=f"prepared-features-{signal.symbol}-{alert_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def get_or_prepare_feature(
        self,
        *,
        symbol: str,
        timeframe: str,
        alert_id: int | None,
        content_type: str,
        language: str = "en",
        progress_callback: ProgressCallback | None = None,
    ) -> PreparedFeature:
        normalized_language = normalize_language(language)
        localized_content_type = self._localized_content_type(content_type, normalized_language)
        await self._report_progress(
            progress_callback,
            self._progress_text("check_cache", normalized_language),
            0.08,
        )
        context = await self._build_context(
            symbol=symbol,
            timeframe=timeframe,
            alert_id=alert_id,
            language=normalized_language,
            progress_callback=progress_callback,
        )
        await self._report_progress(
            progress_callback,
            self._progress_text("compare_context", normalized_language),
            0.34,
        )
        cached = await self.repository.get_prepared_feature_card(
            symbol=symbol,
            timeframe=timeframe,
            content_type=localized_content_type,
            source_data_hash=context.source_data_hash,
            alert_id=alert_id,
        )
        if cached is not None:
            LOGGER.info(
                "Prepared feature cache hit type=%s symbol=%s timeframe=%s alert_id=%s",
                content_type,
                symbol,
                timeframe,
                alert_id,
            )
            await self._report_progress(progress_callback, self._progress_text("loaded_cache", normalized_language), 1.0)
            return PreparedFeature(
                content_type=content_type,
                text_payload=cached.text_payload,
                json_payload=cached.json_payload,
                model_name=cached.model_name,
                source_data_hash=cached.source_data_hash,
                cache_hit=True,
            )

        LOGGER.info(
            "Prepared feature cache miss type=%s symbol=%s timeframe=%s alert_id=%s",
            content_type,
            symbol,
            timeframe,
            alert_id,
        )
        await self._report_progress(
            progress_callback,
            self._progress_text("build_card", normalized_language, content_type=content_type),
            0.46,
        )
        return await self._generate_and_store(
            context=context,
            content_type=content_type,
            language=normalized_language,
            alert_id=alert_id,
            progress_callback=progress_callback,
        )

    async def _prepare_default_bundle(self, symbol: str, timeframe: str, alert_id: int) -> None:
        LOGGER.info(
            "Prepared analysis started symbol=%s timeframe=%s alert_id=%s",
            symbol,
            timeframe,
            alert_id,
        )
        try:
            for content_type in ("analysis", "risk", "rationale"):
                await self.get_or_prepare_feature(
                    symbol=symbol,
                    timeframe=timeframe,
                    alert_id=alert_id,
                    content_type=content_type,
                )
            LOGGER.info(
                "Prepared analysis ready symbol=%s timeframe=%s alert_id=%s",
                symbol,
                timeframe,
                alert_id,
            )
        except Exception:  # pragma: no cover - runtime dependent
            LOGGER.exception(
                "Prepared analysis failed symbol=%s timeframe=%s alert_id=%s",
                symbol,
                timeframe,
                alert_id,
            )

    async def _generate_and_store(
        self,
        *,
        context: PreparedFeatureContext,
        content_type: str,
        language: str,
        alert_id: int | None,
        progress_callback: ProgressCallback | None = None,
    ) -> PreparedFeature:
        localized_content_type = self._localized_content_type(content_type, language)
        await self._report_progress(progress_callback, self._progress_text("save_snapshot", language), 0.52)
        await self.repository.save_prepared_feature_card(
            symbol=context.signal.symbol,
            timeframe=context.signal.timeframe,
            content_type=localized_content_type,
            source_data_hash=context.source_data_hash,
            alert_id=alert_id,
            text_payload="",
            json_payload=context.fact_payload,
            model_name=None,
            is_ready=False,
            metadata={"status": "preparing", "language_code": language},
        )
        if content_type == "analysis":
            await self._report_progress(progress_callback, self._progress_text("analysis_stage", language), 0.72)
            text_payload, model_name = await self._build_analysis_text(
                context,
                language=language,
                progress_callback=progress_callback,
            )
            LOGGER.info("Prepared analysis card generated symbol=%s timeframe=%s alert_id=%s", context.signal.symbol, context.signal.timeframe, alert_id)
        elif content_type == "risk":
            await self._report_progress(progress_callback, self._progress_text("risk_stage", language), 0.72)
            text_payload, model_name = await self._build_risk_text(
                context,
                language=language,
                progress_callback=progress_callback,
            )
            LOGGER.info("Prepared risk card generated symbol=%s timeframe=%s alert_id=%s", context.signal.symbol, context.signal.timeframe, alert_id)
        elif content_type == "rationale":
            await self._report_progress(progress_callback, self._progress_text("rationale_stage", language), 0.72)
            text_payload, model_name = await self._build_rationale_text(
                context,
                language=language,
                progress_callback=progress_callback,
            )
            LOGGER.info("Prepared rationale card generated symbol=%s timeframe=%s alert_id=%s", context.signal.symbol, context.signal.timeframe, alert_id)
        else:
            raise RuntimeError(f"Unsupported prepared feature type: {content_type}")

        await self._report_progress(progress_callback, self._progress_text("finalize", language), 0.92)
        await self.repository.save_prepared_feature_card(
            symbol=context.signal.symbol,
            timeframe=context.signal.timeframe,
            content_type=localized_content_type,
            source_data_hash=context.source_data_hash,
            alert_id=alert_id,
            text_payload=text_payload,
            json_payload=context.fact_payload,
            model_name=model_name,
            is_ready=True,
            metadata={"content_type": content_type, "language_code": language},
        )
        await self._report_progress(progress_callback, self._progress_text("ready", language), 1.0)
        return PreparedFeature(
            content_type=content_type,
            text_payload=text_payload,
            json_payload=context.fact_payload,
            model_name=model_name,
            source_data_hash=context.source_data_hash,
            cache_hit=False,
        )

    async def _build_context(
        self,
        *,
        symbol: str,
        timeframe: str,
        alert_id: int | None,
        language: str = "en",
        progress_callback: ProgressCallback | None = None,
    ) -> PreparedFeatureContext:
        await self._report_progress(progress_callback, self._progress_text("load_snapshot", language), 0.16)
        ticker_map = await self.binance_client.get_all_ticker_stats(force_refresh=False)
        frame = await self.binance_client.get_klines(symbol, timeframe, self.settings.klines_limit)
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            raise RuntimeError(f"No candle data available for prepared feature {symbol} on {timeframe}")

        await self._report_progress(progress_callback, self._progress_text("compute_context", language), 0.28)
        ticker = ticker_map.get(symbol)
        alert_record = await self.repository.get_alert(alert_id) if alert_id is not None else None
        followup_record = await self.repository.get_followup_result(alert_id) if alert_id is not None else None
        signal = self._build_signal(
            symbol=symbol,
            timeframe=timeframe,
            frame=enriched,
            ticker=ticker,
            alert_record=alert_record,
        )
        rationale = compute_signal_rationale(
            frame=enriched,
            direction=signal.direction if signal.direction != "neutral" else (alert_record.direction if alert_record else "neutral"),
            timeframe=timeframe,
            score=signal.score,
            closed_rsi=signal.rsi,
            live_rsi=signal.metadata.get("live_rsi"),
            volume_ratio=signal.metadata.get("volume_ratio"),
            language=language,
        )
        risk_plan = compute_risk_plan(
            frame=enriched,
            entry_price=float(alert_record.alert_price if alert_record else signal.metadata.get("live_price") or signal.price),
            direction=alert_record.direction if alert_record is not None else signal.direction,
            score=signal.score,
            timeframe=timeframe,
            trend_note=self._trend_note(signal, language=language),
            volume_note=self._volume_note(signal.metadata.get("volume_ratio"), language=language),
            language=language,
        )
        fact_payload = self._build_fact_payload(signal, alert_record, followup_record, risk_plan, rationale, enriched)
        source_hash = self._hash_payload(fact_payload)
        return PreparedFeatureContext(
            signal=signal,
            frame=enriched,
            alert_record=alert_record,
            followup_record=followup_record,
            risk_plan=risk_plan,
            rationale=rationale,
            source_data_hash=source_hash,
            fact_payload=fact_payload,
        )

    def _build_signal(
        self,
        *,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        alert_record: AlertRecord | None,
    ) -> AlertSignal:
        row = frame.iloc[-1]
        closed_rsi = float(row["rsi"])
        direction = self._classify_zone(closed_rsi)
        live_price = float(ticker.last_price) if ticker and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        price = float(row["close"])
        score = alert_record.score if alert_record is not None else self._score_signal(row, direction)
        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=row["close_time"].to_pydatetime(),
            price=price,
            rsi=closed_rsi,
            day_change_pct=ticker.price_change_percent if ticker else alert_record.day_change_pct if alert_record else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else alert_record.day_volume if alert_record else None,
            quote_volume=ticker.quote_volume if ticker else alert_record.metadata.get("quote_volume") if alert_record else None,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]) if pd.notna(row["avg_volume_20"]) else 0.0,
            atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
            ema20=float(row["ema20"]) if pd.notna(row["ema20"]) else price,
            ema50=float(row["ema50"]) if pd.notna(row["ema50"]) else price,
            score=score,
            explanation=alert_record.metadata.get("explanation", "") if alert_record else "",
            metadata={
                "live_price": live_price,
                "live_rsi": live_rsi,
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "closed_rsi": closed_rsi,
                "origin_timeframe": alert_record.timeframe if alert_record else timeframe,
            },
        )

    async def _build_analysis_text(
        self,
        context: PreparedFeatureContext,
        *,
        language: str,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str, str]:
        fallback = self._analysis_fallback(context, language=language)
        analysis_terms = self._required_terms("analysis", language)
        await self._report_progress(progress_callback, self._progress_text("analysis_stage", language), 0.84)
        ai_note, model_name = await self._generate_ai_note(
            prompt=premium_signal_analysis(
                prepared_context=self._analysis_prompt_context(context, language=language),
                language=language,
                asset_class=self._asset_class_for_symbol(context.signal.symbol),
            ),
            fallback_text=self._analysis_interpretation_fallback(context, language=language),
            min_words=38,
            max_words=95,
            required_terms=analysis_terms,
        )
        ai_note = self._finalize_ai_note(
            ai_note,
            fallback=self._analysis_interpretation_fallback(context, language=language),
            required_terms=analysis_terms,
        )
        signal = context.signal
        risk = context.risk_plan
        followup_line = self._followup_context_line(context, language=language)
        direction_label = self._direction_label(signal.direction, language=language)
        status_line = (
            f"- Статус: {direction_label} на активном таймфрейме {signal.timeframe}"
            if is_russian(language)
            else f"- Status: {direction_label} on the active {signal.timeframe} view"
        )
        price_line = (
            f"- Закрытие сигнала: {format_price(signal.price)} | Рынок: {format_price(float(signal.metadata.get('live_price') or signal.price))}"
            if is_russian(language)
            else f"- Signal close: {format_price(signal.price)} | Market: {format_price(float(signal.metadata.get('live_price') or signal.price))}"
        )
        rsi_line = (
            f"- RSI(14): закрытый {format_rsi(signal.rsi)} | live {format_rsi(float(signal.metadata.get('live_rsi') or signal.rsi))}"
            if is_russian(language)
            else f"- RSI(14): closed {format_rsi(signal.rsi)} | live {format_rsi(float(signal.metadata.get('live_rsi') or signal.rsi))}"
        )
        score_line = (
            f"- Оценка / объем: {signal.score}/100 | {format_volume(signal.quote_volume or signal.day_volume)} объем в котируемой валюте"
            if is_russian(language)
            else f"- Score / volume: {signal.score}/100 | {format_volume(signal.quote_volume or signal.day_volume)} quote volume"
        )
        lines = [
            "🧩 Снимок сетапа" if is_russian(language) else "🧩 Setup Snapshot",
            status_line,
            price_line,
            rsi_line,
            score_line,
            self._bullet_if(
                f"{'Последний результат' if is_russian(language) else 'Latest follow-up'}: {followup_line}",
                bool(followup_line),
            ),
            "",
            "✅ Что поддерживает идею" if is_russian(language) else "✅ What Supports It",
            f"- {context.rationale.factors[1].detail}",
            f"- {context.rationale.factors[2].detail}",
            f"- {context.rationale.factors[5].detail}",
            "",
            "⚠️ Что ослабляет идею" if is_russian(language) else "⚠️ What Weakens It",
            f"- {self._weakening_line(context, language=language)}",
            f"- {context.rationale.factors[3].detail}",
            "",
            "🧭 Короткий вывод" if is_russian(language) else "🧭 Desk Read",
            ai_note,
            "",
            "👀 Что смотреть дальше" if is_russian(language) else "👀 What To Watch Next",
            f"- {context.rationale.watch_next[0]}",
            f"- {self._confirmation_line(context, language=language)}",
            "",
            "🛑 Инвалидация / осторожность" if is_russian(language) else "🛑 Invalidation / Caution",
            (
                f"- Пробой зоны структурной инвалидации около {format_price(risk.invalidation_level)} заметно ослабит исходный сценарий."
                if is_russian(language)
                else f"- A break through the structural invalidation area around {format_price(risk.invalidation_level)} would weaken the original thesis materially."
            ),
            f"- {self._caution_line(context, language=language)}",
            "",
            "💡 Кому подходит" if is_russian(language) else "💡 Trader Fit",
            f"- {'Трейдерский профиль' if is_russian(language) else 'Trader fit'}: {self._trader_fit_line(context, language=language)}",
            f"- {risk.capital_management_notes[0]}",
        ]
        text = self._join_card_lines(lines)
        return text if text else fallback, model_name

    async def _build_risk_text(
        self,
        context: PreparedFeatureContext,
        *,
        language: str,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str, str]:
        risk = context.risk_plan
        fallback = self._risk_fallback(context, language=language)
        risk_terms = self._required_terms("risk", language)
        await self._report_progress(progress_callback, self._progress_text("risk_stage", language), 0.84)
        ai_note, model_name = await self._generate_ai_note(
            prompt=premium_risk_commentary(
                prepared_context=self._risk_prompt_context(context, language=language),
                language=language,
                asset_class=self._asset_class_for_symbol(context.signal.symbol),
            ),
            fallback_text=self._risk_commentary_fallback(context, language=language),
            min_words=28,
            max_words=80,
            required_terms=risk_terms,
        )
        ai_note = self._finalize_ai_note(
            ai_note,
            fallback=self._risk_commentary_fallback(context, language=language),
            required_terms=risk_terms,
        )
        lines = (
            [
                "📌 Рамка сделки",
                f"- Направление: {self._bias_label(risk.bias, language=language)}",
                f"- Уверенность: {risk.confidence_label} ({risk.confidence_score}/100)",
                f"- Базовый вход: {format_price(risk.entry_price)}",
                f"- Структурная инвалидация: {format_price(risk.invalidation_level)}",
                f"- ATR ориентир: {format_price(risk.atr_value)}",
                "",
                "🧠 Драйверы уверенности",
                *(f"- {factor}" for factor in risk.factor_notes),
                "",
            ]
            if is_russian(language)
            else [
                "📌 Trade Frame",
                f"- Bias: {self._bias_label(risk.bias, language=language)}",
                f"- Confidence: {risk.confidence_label} ({risk.confidence_score}/100)",
                f"- Reference entry: {format_price(risk.entry_price)}",
                f"- Structural invalidation: {format_price(risk.invalidation_level)}",
                f"- ATR reference: {format_price(risk.atr_value)}",
                "",
                "🧠 Confidence Drivers",
                *(f"- {factor}" for factor in risk.factor_notes),
                "",
            ]
        )
        for option in risk.options:
            lines.extend(self._render_risk_option(context, option, language=language))
        lines.extend(
            (
                [
                    "Управление позицией",
                    *(f"- {note}" for note in risk.capital_management_notes),
                    "",
                    "💬 Короткий вывод",
                    ai_note,
                ]
                if is_russian(language)
                else [
                    "Position Management",
                    *(f"- {note}" for note in risk.capital_management_notes),
                    "",
                    "💬 Desk Note",
                    ai_note,
                ]
            )
        )
        text = self._join_card_lines(lines)
        return text if text else fallback, model_name

    async def _build_rationale_text(
        self,
        context: PreparedFeatureContext,
        *,
        language: str,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str, str]:
        rationale = context.rationale
        fallback = self._rationale_fallback(context, language=language)
        rationale_terms = self._required_terms("rationale", language)
        await self._report_progress(progress_callback, self._progress_text("rationale_stage", language), 0.84)
        ai_note, model_name = await self._generate_ai_note(
            prompt=premium_signal_rationale(
                prepared_context=self._rationale_prompt_context(context, language=language),
                language=language,
                asset_class=self._asset_class_for_symbol(context.signal.symbol),
            ),
            fallback_text=self._rationale_commentary_fallback(context, language=language),
            min_words=28,
            max_words=80,
            required_terms=rationale_terms,
        )
        ai_note = self._finalize_ai_note(
            ai_note,
            fallback=self._rationale_commentary_fallback(context, language=language),
            required_terms=rationale_terms,
        )
        lines = (
            [
                "🧠 Почему сработал сигнал",
                f"- {rationale.setup_quality}",
                "",
                "📍 Контекст триггера",
                f"- {rationale.summary}",
                "",
                "🔎 Реальные факторы сигнала",
                *(f"- {factor.title}: {factor.detail}" for factor in rationale.factors[:3]),
                "",
                "💡 Почему это стоило отметить",
                f"- {self._reason_value_line(context, language=language)}",
                f"- {self._not_random_line(context, language=language)}",
                "",
                "👀 Что важно дальше",
                *(f"- {note}" for note in rationale.watch_next[:2]),
                "",
                "💬 Короткий вывод",
                ai_note,
            ]
            if is_russian(language)
            else [
                "🧠 Why It Triggered",
                f"- {rationale.setup_quality}",
                "",
                "📍 Trigger Context",
                f"- {rationale.summary}",
                "",
                "🔎 Real Signal Factors",
                *(f"- {factor.title}: {factor.detail}" for factor in rationale.factors[:3]),
                "",
                "💡 Why It Was Worth Flagging",
                f"- {self._reason_value_line(context, language=language)}",
                f"- {self._not_random_line(context, language=language)}",
                "",
                "👀 What Matters Next",
                *(f"- {note}" for note in rationale.watch_next[:2]),
                "",
                "💬 Desk Read",
                ai_note,
            ]
        )
        text = self._join_card_lines(lines)
        return text if text else fallback, model_name

    async def _generate_ai_note(
        self,
        *,
        prompt: str,
        fallback_text: str,
        min_words: int,
        max_words: int,
        required_terms: tuple[str, ...] = (),
    ) -> tuple[str, str]:
        fallback_clean = self._clean_output(fallback_text)
        if not self.settings.ollama_enabled or self.ollama_client is None:
            return fallback_clean, "fallback-template"
        if self.ollama_client.is_cooling_down():
            return fallback_clean, "fallback-cooldown"
        for model_name in self._model_candidates():
            try:
                response = await self.ollama_client.generate(
                    prompt,
                    model_name=model_name,
                    temperature=0.35,
                    timeout_seconds=min(float(self.settings.ollama_timeout_seconds), 20.0),
                    retries=1,
                    base_delay=0.8,
                )
                cleaned = self._clean_output(response)
                self._validate_output(
                    cleaned,
                    min_words=min_words,
                    max_words=max_words,
                    required_terms=required_terms,
                )
                return cleaned, model_name
            except Exception as exc:  # pragma: no cover - runtime dependent
                error_text = self._error_text(exc)
                if "temporarily cooled down" in error_text.lower():
                    LOGGER.info(
                        "Prepared feature AI note is temporarily using fallback. Model=%s Error=%s",
                        model_name,
                        error_text,
                    )
                    break
                LOGGER.warning(
                    "Prepared feature AI note rejected for model %s. Falling back. Error: %s",
                    model_name,
                    error_text,
                )
        return fallback_clean, "fallback-template"

    def _model_candidates(self) -> list[str]:
        models = [self.settings.effective_ollama_analysis_model, self.settings.ollama_model]
        return [model for idx, model in enumerate(models) if model and model not in models[:idx]]

    async def _report_progress(
        self,
        callback: ProgressCallback | None,
        stage_text: str,
        progress: float | None,
    ) -> None:
        if callback is None:
            return
        result = callback(stage_text, progress)
        if inspect.isawaitable(result):
            await result

    def _clean_output(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
        cleaned = re.sub(r"^\s*(reply/comment|main draft|short version|tweet-sized post)\s*:?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^\s*(setup summary|market context|why this matters|what confirms the idea|what weakens it|what to watch next|invalidation ?/? caution|practical trader note|trade framing|confidence drivers|position management|desk note|setup quality|why the alert fired|signal factors|why it was worth flagging|operator read)\s*:?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(" \n\"'")

    def _validate_output(
        self,
        text: str,
        *,
        min_words: int,
        max_words: int,
        required_terms: tuple[str, ...] = (),
    ) -> None:
        if not text:
            raise RuntimeError("empty output")
        lowered = text.lower()
        for phrase in self._banned_phrases:
            if phrase in lowered:
                raise RuntimeError(f"banned phrase detected: {phrase}")
        for fragment in self._generic_note_fragments:
            if fragment in lowered and len(lowered.split()) < max_words * 0.7:
                raise RuntimeError(f"generic filler detected: {fragment}")
        word_count = len(re.findall(r"\b[\w']+\b", text))
        if word_count < min_words or word_count > max_words:
            raise RuntimeError(f"word count {word_count} outside {min_words}-{max_words}")
        if required_terms and sum(1 for term in required_terms if term in lowered) < 2:
            raise RuntimeError("not specific enough to the requested premium card")

    def _analysis_prompt_context(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        signal = context.signal
        if is_russian(language):
            return "\n".join(
                [
                    f"Рынок: {self._market_label(signal.symbol, language=language)}",
                    f"Инструмент: {signal.symbol}",
                    f"Показываемый таймфрейм: {signal.timeframe}",
                    f"Текущий статус: {self._direction_label(signal.direction, language=language)}",
                    f"Закрытие сигнала: {format_price(signal.price)}",
                    f"Текущая рыночная цена: {format_price(float(signal.metadata.get('live_price') or signal.price))}",
                    f"RSI закрытый/текущий: {format_rsi(signal.rsi)} / {format_rsi(float(signal.metadata.get('live_rsi') or signal.rsi))}",
                    f"Оценка: {signal.score}/100",
                    f"24ч объем в котируемой валюте: {format_volume(signal.quote_volume or signal.day_volume)}",
                    f"ATR: {format_price(signal.atr)} ({signal.atr_pct:.2f}%)",
                    f"EMA20 / EMA50: {format_price(signal.ema20)} / {format_price(signal.ema50)}",
                    f"Контекст тренда: {context.rationale.factors[1].detail}",
                    f"Контекст объема: {context.rationale.factors[2].detail}",
                    f"Контекст локации: {context.rationale.factors[3].detail}",
                    f"Подтверждение по текущей свече: {context.rationale.factors[5].detail}",
                    f"Последний результат: {self._followup_context_line(context, language=language) or 'нет'}",
                    f"Что важно дальше: {context.rationale.watch_next[0]}",
                    f"Уровень инвалидации: {format_price(context.risk_plan.invalidation_level)}",
                    f"Кому подходит: {self._trader_fit_line(context, language=language)}",
                    f"Заметка по размеру: {context.risk_plan.capital_management_notes[0]}",
                ]
            )
        return "\n".join(
            [
                f"Market: {self._market_label(signal.symbol, language=language)}",
                f"Symbol: {signal.symbol}",
                f"Displayed timeframe: {signal.timeframe}",
                f"Current status: {self._direction_label(signal.direction, language=language)}",
                f"Signal close: {format_price(signal.price)}",
                f"Current market price: {format_price(float(signal.metadata.get('live_price') or signal.price))}",
                f"RSI closed/live: {format_rsi(signal.rsi)} / {format_rsi(float(signal.metadata.get('live_rsi') or signal.rsi))}",
                f"Score: {signal.score}/100",
                f"24h quote volume: {format_volume(signal.quote_volume or signal.day_volume)}",
                f"ATR: {format_price(signal.atr)} ({signal.atr_pct:.2f}%)",
                f"EMA20 / EMA50: {format_price(signal.ema20)} / {format_price(signal.ema50)}",
                f"Trend note: {context.rationale.factors[1].detail}",
                f"Volume note: {context.rationale.factors[2].detail}",
                f"Location note: {context.rationale.factors[3].detail}",
                f"Live confirmation: {context.rationale.factors[5].detail}",
                f"Latest follow-up: {self._followup_context_line(context, language=language) or 'none'}",
                f"Watch next: {context.rationale.watch_next[0]}",
                f"Invalidation level: {format_price(context.risk_plan.invalidation_level)}",
                f"Trader fit: {self._trader_fit_line(context, language=language)}",
                f"Capital note: {context.risk_plan.capital_management_notes[0]}",
            ]
        )

    def _risk_prompt_context(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        risk = context.risk_plan
        option_lines: list[str] = []
        for option in risk.options:
            if is_russian(language):
                option_lines.append(
                    f"{option.label}: стоп {format_price(option.stop_loss)}, цель {format_price(option.take_profit)}, rr {option.risk_reward:.2f}R, стиль удержания {option.holding_style}, кому подходит {self._option_fit(option.style, context, language=language)}, заметка {option.explanation}"
                )
            else:
                option_lines.append(
                    f"{option.label}: stop {format_price(option.stop_loss)}, target {format_price(option.take_profit)}, rr {option.risk_reward:.2f}R, holding {option.holding_style}, fit {self._option_fit(option.style, context, language=language)}, note {option.explanation}"
                )
        if is_russian(language):
            return "\n".join(
                [
                    f"Рынок: {self._market_label(context.signal.symbol, language=language)}",
                    f"Инструмент: {context.signal.symbol}",
                    f"Таймфрейм: {context.signal.timeframe}",
                    f"Направление: {self._bias_label(risk.bias, language=language)}",
                    f"Уверенность: {risk.confidence_label} ({risk.confidence_score}/100)",
                    f"Базовый вход: {format_price(risk.entry_price)}",
                    f"Значение ATR: {format_price(risk.atr_value)}",
                    f"Структурный уровень: {format_price(risk.structural_level)}",
                    f"Инвалидация: {format_price(risk.invalidation_level)}",
                    *option_lines,
                    *(f"Заметка по капиталу: {note}" for note in risk.capital_management_notes),
                ]
            )
        return "\n".join(
            [
                f"Market: {self._market_label(context.signal.symbol, language=language)}",
                f"Symbol: {context.signal.symbol}",
                f"Timeframe: {context.signal.timeframe}",
                f"Bias: {self._bias_label(risk.bias, language=language)}",
                f"Confidence: {risk.confidence_label} ({risk.confidence_score}/100)",
                f"Reference entry: {format_price(risk.entry_price)}",
                f"ATR value: {format_price(risk.atr_value)}",
                f"Structural level: {format_price(risk.structural_level)}",
                f"Invalidation: {format_price(risk.invalidation_level)}",
                *option_lines,
                *(f"Capital note: {note}" for note in risk.capital_management_notes),
            ]
        )

    def _rationale_prompt_context(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            return "\n".join(
                [
                    f"Рынок: {self._market_label(context.signal.symbol, language=language)}",
                    f"Инструмент: {context.signal.symbol}",
                    f"Таймфрейм: {context.signal.timeframe}",
                    f"Направление: {self._direction_label(context.signal.direction, language=language)}",
                    f"Оценка: {context.signal.score}/100",
                    f"Сводка: {context.rationale.summary}",
                    f"Последний результат: {self._followup_context_line(context, language=language) or 'нет'}",
                    *(f"{factor.title}: {factor.detail}" for factor in context.rationale.factors),
                    *(f"Что важно дальше: {note}" for note in context.rationale.watch_next),
                ]
            )
        return "\n".join(
            [
                f"Market: {self._market_label(context.signal.symbol, language=language)}",
                f"Symbol: {context.signal.symbol}",
                f"Timeframe: {context.signal.timeframe}",
                f"Direction: {self._direction_label(context.signal.direction, language=language)}",
                f"Score: {context.signal.score}/100",
                f"Summary: {context.rationale.summary}",
                f"Latest follow-up: {self._followup_context_line(context, language=language) or 'none'}",
                *(f"{factor.title}: {factor.detail}" for factor in context.rationale.factors),
                *(f"Watch next: {note}" for note in context.rationale.watch_next),
            ]
        )

    def _analysis_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            return self._join_card_lines(
                [
                    "Сводка по сетапу",
                    f"- Статус: {self._direction_label(context.signal.direction, language=language)} на активном таймфрейме {context.signal.timeframe}",
                    f"- Закрытие сигнала: {format_price(context.signal.price)} | Рынок: {format_price(float(context.signal.metadata.get('live_price') or context.signal.price))}",
                    "",
                    "Почему это важно",
                    self._analysis_interpretation_fallback(context, language=language),
                    "",
                    "Что смотреть дальше",
                    f"- {context.rationale.watch_next[0]}",
                ]
            )
        return self._join_card_lines(
            [
                "Setup Summary",
                f"- Status: {self._direction_label(context.signal.direction, language=language)} on the active {context.signal.timeframe} view",
                f"- Signal close: {format_price(context.signal.price)} | Market: {format_price(float(context.signal.metadata.get('live_price') or context.signal.price))}",
                "",
                "Why This Matters",
                self._analysis_interpretation_fallback(context, language=language),
                "",
                "What To Watch Next",
                f"- {context.rationale.watch_next[0]}",
            ]
        )

    def _analysis_interpretation_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.signal.direction == "oversold":
                opening = "Идея на отскок все еще жива, но она усиливается только если покупатели продолжают защищать реакционную зону."
            elif context.signal.direction == "overbought":
                opening = "Идея на охлаждение валидна, но станет чище только если импульс вверх начнет затухать."
            else:
                opening = "Преимущество сейчас мягче, потому что этот таймфрейм уже вернулся ближе к нейтральной зоне."
            return (
                f"{opening} {context.rationale.factors[1].detail} {context.rationale.factors[2].detail} "
                "Если идея верна, следующее движение должно подтвердить структуру, а не провоцировать погоню за ценой. "
                "Если подтверждения не будет, это останется сценарием для наблюдения."
            )
        if context.signal.direction == "oversold":
            opening = "The bounce thesis is still viable, but it only upgrades if buyers keep defending the reaction zone."
        elif context.signal.direction == "overbought":
            opening = "The cooldown thesis is valid, but it only gets cleaner if upside urgency fades and price stops extending."
        else:
            opening = "The edge is softer now because this timeframe has already drifted back toward neutral."
        return (
            f"{opening} {context.rationale.factors[1].detail} {context.rationale.factors[2].detail} "
            "If the thesis is right, the next move should confirm structure rather than force a chase. "
            "If that confirmation does not show up, this stays a watchlist idea."
        )

    def _risk_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        risk = context.risk_plan
        lines = (
            ["Риск-план", f"- Направление: {risk.bias.title()}", f"- Уверенность: {risk.confidence_label} ({risk.confidence_score}/100)"]
            if is_russian(language)
            else ["Trade Framing", f"- Bias: {risk.bias.title()}", f"- Confidence: {risk.confidence_label} ({risk.confidence_score}/100)"]
        )
        for option in risk.options:
            lines.extend(self._render_risk_option(context, option, language=language))
        lines.extend(
            ["Управление позицией", *(f"- {note}" for note in context.risk_plan.capital_management_notes)]
            if is_russian(language)
            else ["Position Management", *(f"- {note}" for note in context.risk_plan.capital_management_notes)]
        )
        return self._join_card_lines(lines)

    def _risk_commentary_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        bias = context.risk_plan.bias
        if is_russian(language):
            return (
                f"Смотри на это как на {bias} сетап с поэтапными выходами, а не как на одну ставку. "
                "Более плотный план подходит для быстрой инвалидизации, а более широкий только с меньшим размером позиции и большим терпением."
            )
        return (
            f"Frame this as a {bias} setup with layered exits, not a one-shot bet. "
            "Use the tighter plan if you want faster invalidation, and only use the wider plan with smaller size and more patience."
        )

    def _rationale_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        lines = (
            [
                "Качество сетапа",
                f"- {context.rationale.setup_quality}",
                "",
                "Почему сработал алерт",
                f"- {context.rationale.summary}",
                "",
                "Факторы сигнала",
                *(f"- {factor.title}: {factor.detail}" for factor in context.rationale.factors[:4]),
            ]
            if is_russian(language)
            else [
                "Setup Quality",
                f"- {context.rationale.setup_quality}",
                "",
                "Why The Alert Fired",
                f"- {context.rationale.summary}",
                "",
                "Signal Factors",
                *(f"- {factor.title}: {factor.detail}" for factor in context.rationale.factors[:4]),
            ]
        )
        return self._join_card_lines(lines)

    def _rationale_commentary_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            return (
                "Это был не просто print по RSI. Триггер mattered, потому что он совпал с трендом, локацией и участием объема. "
                "Именно это отделяет фоновый шум от сетапа, за которым стоит следить."
            )
        return (
            "This was not just an RSI print. The trigger mattered because it lined up with trend, location, and participation context. "
            "That is what separates background noise from a setup worth tracking."
        )

    def _build_fact_payload(
        self,
        signal: AlertSignal,
        alert_record: AlertRecord | None,
        followup_record: FollowUpResultRecord | None,
        risk_plan: RiskPlan,
        rationale: SignalRationale,
        frame: pd.DataFrame,
    ) -> dict[str, Any]:
        latest_row = frame.iloc[-1]
        return {
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_direction": signal.direction,
            "signal_price": signal.price,
            "market_price": signal.metadata.get("live_price"),
            "closed_rsi": signal.rsi,
            "live_rsi": signal.metadata.get("live_rsi"),
            "score": signal.score,
            "quote_volume": signal.quote_volume,
            "day_change_pct": signal.day_change_pct,
            "atr": signal.atr,
            "atr_pct": signal.atr_pct,
            "ema20": signal.ema20,
            "ema50": signal.ema50,
            "volume_ratio": signal.metadata.get("volume_ratio"),
            "candle_close_time": signal.candle_close_time.isoformat(),
            "latest_close_time": latest_row["close_time"].to_pydatetime().isoformat(),
            "alert_context": {
                "alert_id": alert_record.id if alert_record else None,
                "original_timeframe": alert_record.timeframe if alert_record else signal.timeframe,
                "direction": alert_record.direction if alert_record else signal.direction,
                "alert_price": alert_record.alert_price if alert_record else signal.price,
                "alert_rsi": alert_record.alert_rsi if alert_record else signal.rsi,
            },
            "followup_context": {
                "exists": followup_record is not None,
                "stage": followup_record.stage if followup_record else None,
                "move_pct": followup_record.move_pct if followup_record else None,
                "current_rsi": followup_record.current_rsi if followup_record else None,
                "summary": followup_record.summary if followup_record else None,
                "thesis_direction": followup_record.metadata.get("thesis_direction") if followup_record else None,
                "thesis_result_state": followup_record.metadata.get("thesis_result_state") if followup_record else None,
                "favorable_move_pct": followup_record.metadata.get("favorable_move_pct") if followup_record else None,
                "adverse_move_pct": followup_record.metadata.get("adverse_move_pct") if followup_record else None,
            },
            "risk_plan": risk_plan.as_json(),
            "rationale": rationale.as_json(),
        }

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _trend_note(self, signal: AlertSignal) -> str:
        if signal.price < signal.ema20 < signal.ema50:
            return "Price is still below EMA20 and EMA50, so this is working against the near-term trend."
        if signal.price > signal.ema20 > signal.ema50:
            return "Price is above EMA20 and EMA50, so trend structure is supportive rather than hostile."
        return "Trend structure is mixed, so reaction quality matters more than trend alignment alone."

    def _volume_note(self, volume_ratio: Any) -> str:
        if isinstance(volume_ratio, (int, float)):
            return f"Volume is running at roughly {float(volume_ratio):.2f}x the 20-bar average."
        return "Volume is not giving a strong expansion signal right now."

    def _followup_context_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        record = context.followup_record
        if record is None:
            return ""
        stage = record.stage
        state = str(record.metadata.get("thesis_result_state") or "neutral").title()
        if is_russian(language):
            state = {
                "Favorable": "Благоприятно",
                "Adverse": "Негативно",
                "Neutral": "Нейтрально",
            }.get(state, state)
        favorable = record.metadata.get("favorable_move_pct")
        favorable_text = format_percent(float(favorable)) if isinstance(favorable, (int, float)) else format_percent(record.move_pct)
        if is_russian(language):
            return f"{stage} итог: {state} | движение {favorable_text} | RSI сейчас {format_rsi(record.current_rsi)}"
        return f"{stage} result: {state} | move {favorable_text} | RSI now {format_rsi(record.current_rsi)}"

    def _confirmation_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.signal.direction == "oversold":
                return "Идея улучшается, если цена удерживает реакционный минимум, а RSI продолжает выходить из экстремальной зоны."
            if context.signal.direction == "overbought":
                return "Идея улучшается, если цена перестает принимать новые максимумы, а RSI продолжает остывать."
            return "Идея улучшается, если рынок снова соберет более чистое направленное движение из нейтральной зоны."
        if context.signal.direction == "oversold":
            return "The idea improves if price starts holding above the reaction low while RSI keeps recovering out of the extreme zone."
        if context.signal.direction == "overbought":
            return "The idea improves if price stops accepting higher prints while RSI keeps fading out of the extreme zone."
        return "The idea improves if a cleaner directional push rebuilds structure from the current neutral state."

    def _weakening_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.signal.direction == "oversold":
                return "Сетап слабеет, если отскок остается мелким, объем быстро высыхает или цена сразу теряет локальную зону реакции."
            if context.signal.direction == "overbought":
                return "Сетап слабеет, если цена продолжает принимать более высокие уровни, а RSI не охлаждается."
            return "Сетап слабеет, если рынок остается нейтральным и не строит более явный дисбаланс."
        if context.signal.direction == "oversold":
            return "It weakens if the bounce stays shallow, volume dries up quickly, or price loses the local reaction area immediately."
        if context.signal.direction == "overbought":
            return "It weakens if price keeps accepting higher levels and RSI refuses to cool off despite the stretch."
        return "It weakens if the market stays neutral and never rebuilds a cleaner imbalance worth trading."

    def _caution_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.risk_plan.bias == "watchlist":
                return "Это ближе к контексту, чем к сильной уверенности, поэтому полноценная сделка здесь может быть слишком ранней."
            return "Если первая реакция быстро затухает, обычно лучше сократить риск раньше, чем ждать идеального стопа."
        if context.risk_plan.bias == "watchlist":
            return "This is closer to context than conviction, so treating it as a full trade too early would be forcing it."
        return "If the first reaction stalls fast, reducing exposure early is usually cleaner than waiting for a perfect stop-out."

    def _trader_fit_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            score = context.signal.score
            if score >= 85:
                return "Подходит активным трейдерам, которым нужен более чистый momentum или mean-reversion setup."
            if score >= 72:
                return "Подходит трейдерам, которые готовы дождаться подтверждения перед нормальным размером позиции."
            return "Больше подходит для watchlist-first подхода, чем для немедленного входа с высокой уверенностью."
        score = context.signal.score
        if score >= 85:
            return "Fits active traders who want cleaner momentum or mean-reversion structure rather than pure watchlist context."
        if score >= 72:
            return "Fits traders who are comfortable waiting for confirmation before sizing normally."
        return "Fits watchlist-first traders more than immediate high-conviction execution."

    def _reason_value_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.followup_record is not None:
                return f"Сигнал получает дополнительный вес, потому что уже есть сохраненный outcome-контекст из follow-up {context.followup_record.stage}."
            if context.signal.score >= 80:
                return "Сигнал прошел, потому что экстремум, структура и участие объема совпали лучше, чем в обычном шумовом print."
            return "Сигнал прошел, потому что экстремум достаточно реален для наблюдения, а контекст вокруг него не выглядит случайным."
        if context.followup_record is not None:
            return f"The signal has additional weight because there is already stored outcome context from the {context.followup_record.stage} follow-up."
        if context.signal.score >= 80:
            return "The signal passed because extremeness, structure, and participation are lining up better than in a routine board print."
        return "The signal passed because the extreme is real enough to watch and the surrounding context is not random noise."

    def _not_random_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            return (
                f"Алерт опирается не только на RSI: {context.rationale.factors[1].detail} "
                f"{context.rationale.factors[2].detail}"
            )
        return (
            f"The alert is not just about RSI alone: {context.rationale.factors[1].detail} "
            f"{context.rationale.factors[2].detail}"
        )

    def _option_fit(self, style: str, context: PreparedFeatureContext, *, language: str = "en") -> str:
        lowered = style.lower()
        if is_russian(language):
            if lowered == "conservative":
                return "подходит тем, кто хочет плотный риск и быструю обратную связь"
            if lowered == "balanced":
                return "подходит для стандартного swing-плана с запасом по времени"
            if lowered == "aggressive":
                return "подходит тем, кто может уменьшить размер позиции и терпеть более медленное подтверждение"
            return "подходит тем, кто предпочитает терпение, а не форсирование размера"
        if lowered == "conservative":
            return "fits traders who want tight risk and quicker feedback"
        if lowered == "balanced":
            return "fits traders who want a standard swing plan with room to breathe"
        if lowered == "aggressive":
            return "fits traders who can use smaller size and tolerate slower confirmation"
        return "fits traders who are staying patient rather than forcing size"

    def _direction_label(self, direction: str, *, language: str = "en") -> str:
        mapping = (
            {
                "oversold": "Перепроданность",
                "overbought": "Перекупленность",
                "neutral": "Нейтрально",
            }
            if is_russian(language)
            else {
                "oversold": "Oversold",
                "overbought": "Overbought",
                "neutral": "Neutral",
            }
        )
        return mapping.get(str(direction).lower(), str(direction))

    def _bias_label(self, bias: str, *, language: str = "en") -> str:
        mapping = (
            {
                "long": "Лонг",
                "short": "Шорт",
                "watchlist": "Наблюдение",
            }
            if is_russian(language)
            else {
                "long": "Long",
                "short": "Short",
                "watchlist": "Watchlist",
            }
        )
        return mapping.get(str(bias).lower(), str(bias))

    def _trend_note(self, signal: AlertSignal, *, language: str = "en") -> str:
        if is_russian(language):
            if signal.price < signal.ema20 < signal.ema50:
                return "Цена все еще ниже EMA20 и EMA50, поэтому этот сетап идет против ближайшего тренда."
            if signal.price > signal.ema20 > signal.ema50:
                return "Цена выше EMA20 и EMA50, поэтому структура тренда здесь скорее помогает, чем мешает."
            return "Структура тренда смешанная, поэтому качество реакции сейчас важнее, чем одно только совпадение с трендом."
        if signal.price < signal.ema20 < signal.ema50:
            return "Price is still below EMA20 and EMA50, so this is working against the near-term trend."
        if signal.price > signal.ema20 > signal.ema50:
            return "Price is above EMA20 and EMA50, so trend structure is supportive rather than hostile."
        return "Trend structure is mixed, so reaction quality matters more than trend alignment alone."

    def _volume_note(self, volume_ratio: Any, *, language: str = "en") -> str:
        if is_russian(language):
            if isinstance(volume_ratio, (int, float)):
                return f"Объем сейчас около {float(volume_ratio):.2f}x от среднего за 20 свечей."
            return "Объем сейчас не дает сильного сигнала на расширение."
        if isinstance(volume_ratio, (int, float)):
            return f"Volume is running at roughly {float(volume_ratio):.2f}x the 20-bar average."
        return "Volume is not giving a strong expansion signal right now."

    def _risk_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        risk = context.risk_plan
        lines = (
            ["Риск-план", f"- Направление: {self._bias_label(risk.bias, language=language)}", f"- Уверенность: {risk.confidence_label} ({risk.confidence_score}/100)"]
            if is_russian(language)
            else ["Trade Framing", f"- Bias: {self._bias_label(risk.bias, language=language)}", f"- Confidence: {risk.confidence_label} ({risk.confidence_score}/100)"]
        )
        for option in risk.options:
            lines.extend(self._render_risk_option(context, option, language=language))
        lines.extend(
            ["Управление позицией", *(f"- {note}" for note in context.risk_plan.capital_management_notes)]
            if is_russian(language)
            else ["Position Management", *(f"- {note}" for note in context.risk_plan.capital_management_notes)]
        )
        return self._join_card_lines(lines)

    def _risk_commentary_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            opening = (
                "Смотри на это как на сценарий наблюдения с поэтапными решениями, а не как на полноценную ставку."
                if context.risk_plan.bias == "watchlist"
                else "Смотри на это как на сетап с поэтапными выходами, а не как на одну ставку."
            )
            return (
                f"{opening} "
                "Более плотный план подходит для быстрой инвалидации, а более широкий - только с меньшим размером позиции и большим терпением."
            )
        opening = (
            "Frame this as a watchlist scenario with staged decisions, not a full-size bet."
            if context.risk_plan.bias == "watchlist"
            else "Frame this as a setup with layered exits, not a one-shot bet."
        )
        return (
            f"{opening} "
            "Use the tighter plan if you want faster invalidation, and only use the wider plan with smaller size and more patience."
        )

    def _rationale_commentary_fallback(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            return (
                "Это был не просто сигнал по RSI. Триггер стал важным потому, что он совпал с трендом, локацией и участием объема. "
                "Именно это отделяет фоновый шум от сетапа, за которым стоит следить."
            )
        return (
            "This was not just an RSI print. The trigger mattered because it lined up with trend, location, and participation context. "
            "That is what separates background noise from a setup worth tracking."
        )

    def _trader_fit_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        score = context.signal.score
        if is_russian(language):
            if score >= 85:
                return "Подходит активным трейдерам, которым нужен более чистый импульсный или контртрендовый сетап."
            if score >= 72:
                return "Подходит трейдерам, которые готовы дождаться подтверждения перед нормальным размером позиции."
            return "Больше подходит для сценария «сначала наблюдение», чем для немедленного входа с высокой уверенностью."
        if score >= 85:
            return "Fits active traders who want cleaner momentum or mean-reversion structure rather than pure watchlist context."
        if score >= 72:
            return "Fits traders who are comfortable waiting for confirmation before sizing normally."
        return "Fits watchlist-first traders more than immediate high-conviction execution."

    def _reason_value_line(self, context: PreparedFeatureContext, *, language: str = "en") -> str:
        if is_russian(language):
            if context.followup_record is not None:
                return f"Сигнал получает дополнительный вес, потому что уже есть сохраненный контекст результата после этапа {context.followup_record.stage}."
            if context.signal.score >= 80:
                return "Сигнал прошел, потому что экстремум, структура и участие объема совпали лучше, чем в обычном шумовом движении."
            return "Сигнал прошел, потому что экстремум достаточно реален для наблюдения, а контекст вокруг него не выглядит случайным."
        if context.followup_record is not None:
            return f"The signal has additional weight because there is already stored outcome context from the {context.followup_record.stage} follow-up."
        if context.signal.score >= 80:
            return "The signal passed because extremeness, structure, and participation are lining up better than in a routine board print."
        return "The signal passed because the extreme is real enough to watch and the surrounding context is not random noise."

    def _option_fit(self, style: str, context: PreparedFeatureContext, *, language: str = "en") -> str:
        lowered = style.lower()
        if is_russian(language):
            if lowered == "conservative":
                return "подходит тем, кто хочет плотный риск и быструю обратную связь"
            if lowered == "balanced":
                return "подходит для стандартного сценария с запасом по времени"
            if lowered == "aggressive":
                return "подходит тем, кто может уменьшить размер позиции и терпеть более медленное подтверждение"
            return "подходит тем, кто предпочитает терпение, а не форсирование размера"
        if lowered == "conservative":
            return "fits traders who want tight risk and quicker feedback"
        if lowered == "balanced":
            return "fits traders who want a standard swing plan with room to breathe"
        if lowered == "aggressive":
            return "fits traders who can use smaller size and tolerate slower confirmation"
        return "fits traders who are staying patient rather than forcing size"

    def _render_risk_option(self, context: PreparedFeatureContext, option, *, language: str = "en") -> list[str]:
        if is_russian(language):
            label = {
                "conservative": "🛡 Консервативный план",
                "balanced": "⚖️ Сбалансированный план",
                "aggressive": "🚀 Агрессивный план",
            }.get(option.style.lower(), f"{option.label} план")
            return [
                label,
                f"- Вход: работать от {format_price(context.risk_plan.entry_price)} и добавлять размер только если реакция сохраняется",
                f"- Стоп: {format_price(option.stop_loss)}",
                f"- Цель: {format_price(option.take_profit)}",
                f"- Риск / награда: {option.risk_reward:.2f}R",
                f"- Стиль удержания: {option.holding_style} | Кому подходит: {self._option_fit(option.style, context, language=language)}",
                f"- Почему: {option.explanation}",
                "",
            ]
        label = {
            "conservative": "🛡 Conservative Plan",
            "balanced": "⚖️ Balanced Plan",
            "aggressive": "🚀 Aggressive Plan",
        }.get(option.style.lower(), f"{option.label} Plan")
        return [
            label,
            f"- Entry: work from {format_price(context.risk_plan.entry_price)} and only add size if the reaction keeps holding together",
            f"- Stop-loss: {format_price(option.stop_loss)}",
            f"- Take-profit: {format_price(option.take_profit)}",
            f"- Risk / reward: {option.risk_reward:.2f}R",
            f"- Holding style: {option.holding_style} | Fits: {self._option_fit(option.style, context, language=language)}",
            f"- Why: {option.explanation}",
            "",
        ]

    def _join_card_lines(self, lines: list[str]) -> str:
        cleaned_lines = [line.rstrip() for line in lines if line is not None]
        text = "\n".join(cleaned_lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _bullet_if(self, text: str, condition: bool) -> str:
        return f"- {text}" if condition else ""

    def _finalize_ai_note(self, text: str, *, fallback: str, required_terms: tuple[str, ...]) -> str:
        cleaned = self._clean_output(text)
        lowered = cleaned.lower()
        if any(fragment in lowered for fragment in self._generic_note_fragments):
            return self._clean_output(fallback)
        if required_terms and sum(1 for term in required_terms if term in lowered) < 2:
            return self._clean_output(fallback)
        return cleaned

    def _classify_zone(self, rsi: float) -> str:
        if rsi <= self.settings.rsi_oversold:
            return "oversold"
        if rsi >= self.settings.rsi_overbought:
            return "overbought"
        return "neutral"

    def _score_signal(self, row: pd.Series, direction: str) -> int:
        if direction == "oversold":
            threshold_distance = max(self.settings.rsi_oversold - float(row["rsi"]), 0.0)
            trend_score = 12 if row["close"] < row["ema20"] < row["ema50"] else 5
            stretch = max((row["ema20"] - row["close"]) / row["close"], 0.0)
        else:
            threshold_distance = max(float(row["rsi"]) - self.settings.rsi_overbought, 0.0)
            trend_score = 12 if row["close"] > row["ema20"] > row["ema50"] else 5
            stretch = max((row["close"] - row["ema20"]) / row["close"], 0.0)
        extremeness_score = min(threshold_distance * 4.2, 42)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16, 18)
        volatility_score = min(float(row["atr_pct"]) * 600, 16)
        stretch_score = min(stretch * 4000, 14)
        total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score
        return int(max(0, min(round(total), 100)))
