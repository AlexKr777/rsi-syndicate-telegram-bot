from __future__ import annotations

from datetime import datetime
from textwrap import dedent

from src.core.models import AlertSignal, FollowUpResult
from src.localization import is_russian, normalize_language
from src.core.utils import format_percent, format_price, format_rsi, format_volume, utc_now


def _global_rules(language: str = "en", *, asset_class: str = "crypto") -> str:
    normalized_language = normalize_language(language)
    language_rule = "Write in Russian only." if is_russian(normalized_language) else "Write in English only."
    normalized_asset = str(asset_class or "crypto").strip().lower()
    if normalized_asset == "gold":
        market_rule = "Stay inside gold / XAUUSD market context only."
        cross_market_rule = (
            "Do not describe this instrument as a coin, token, altcoin, or Binance futures pair unless that is explicitly provided in the context."
        )
    else:
        market_rule = "Stay inside crypto and crypto futures context only."
        cross_market_rule = (
            "Never mention forex, stocks, commodities, or non-crypto instruments unless they are explicitly provided in the context."
        )
    return dedent(
        """
        {language_rule}
        {market_rule}
        {cross_market_rule}
        Write for Telegram, not email, not LinkedIn, not a corporate landing page.
        Sound like a real trader or operator who respects the reader's time.
        Keep the tone calm, sharp, useful, market-native, and human.
        No "I'm excited".
        No "I'm glad you're here".
        No "let me tell you".
        No "best regards".
        No "I'm your community manager".
        No "join us".
        No "revolutionizing your trading".
        No "trading experience".
        No fake warmth, no motivational filler, no assistant-style phrasing.
        No hype language, no fake urgency, no exaggerated confidence.
        Avoid hashtags, long intros, marketing slogans, and generic AI phrasing.
        Use plain text only.
        Keep paragraphs short and mobile-friendly.
        One tasteful emoji is acceptable if it feels natural. Zero is also fine.
        """
    ).format(
        language_rule=language_rule,
        market_rule=market_rule,
        cross_market_rule=cross_market_rule,
    ).strip()


def _startup_context(now: datetime | None = None) -> str:
    timestamp = (now or utc_now()).strftime("%Y-%m-%d %H:%M UTC")
    return f"Current timestamp: {timestamp}"


def _signal_context(signal: AlertSignal) -> str:
    official_market_price = (
        f"\nOfficial Binance Futures Market Price: {format_price(float(signal.metadata['live_price']))}"
        if isinstance(signal.metadata.get("live_price"), (int, float))
        else ""
    )
    return dedent(
        f"""
        Symbol: {signal.symbol}
        Direction: {signal.direction}
        Timeframe: {signal.timeframe}
        Price: {format_price(signal.price)}
        {official_market_price}
        RSI(14): {format_rsi(signal.rsi)}
        24h Change: {format_percent(signal.day_change_pct)}
        24h Volume: {format_volume(signal.quote_volume or signal.day_volume)}
        Internal Score: {signal.score}/100
        Explanation: {signal.explanation}
        """
    ).strip()


def _followup_context(signal: AlertSignal, followup: FollowUpResult) -> str:
    return dedent(
        f"""
        Original alert:
        {_signal_context(signal)}

        Follow-up:
        Official Binance Futures Current Price: {format_price(followup.current_price)}
        Current RSI: {format_rsi(followup.current_rsi)}
        Move Since Alert: {format_percent(followup.move_pct)}
        Follow-up Summary: {followup.summary}
        """
    ).strip()


def public_startup_post(now: datetime | None = None) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a PUBLIC startup post.
        Style target: short launch note from a serious market operator.
        Focus: crypto is noisy, scanning hundreds of charts takes time, this channel exists to filter noise and surface cleaner setups with context.
        Tone: confident, useful, restrained, human.
        Hard length target: 60 to 110 words.
        Structure: 2 or 3 short paragraphs. No greeting line. No sign-off.

        Context:
        {_startup_context(now)}
        """
    ).strip()


def pro_startup_post(now: datetime | None = None) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a PRO startup post.
        Style target: short signal-desk note.
        Focus: stronger filtering, faster delivery, cleaner setups, less noise.
        Tone: direct, serious, selective, slightly cold, non-corporate.
        Hard length target: 50 to 90 words.
        Structure: 2 compact paragraphs max.
        Hard rules: no invitation language, no "join", no sales angle, no grand claims, no welcome-script tone.

        Context:
        {_startup_context(now)}
        """
    ).strip()


def lab_startup_post(now: datetime | None = None) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a LAB startup post.
        Style target: internal operator note.
        Focus: monitoring live, alerts live, charts live, follow-ups live, AI live.
        Tone: practical, short, calm, technical.
        Hard length target: 30 to 70 words.
        Structure: one compact block. No generic system-check language.

        Context:
        {_startup_context(now)}
        """
    ).strip()


def community_startup_post(now: datetime | None = None) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a COMMUNITY startup post.
        Style target: natural chat opener from a real trader.
        Focus: invite discussion around setups, market behavior, and observations.
        Tone: relaxed, sharp, human, Telegram-native.
        Hard length target: 35 to 80 words.
        Structure: 2 to 5 short lines, not a moderator script. One concrete observation. A question is optional, not required. No mini-article.

        Context:
        {_startup_context(now)}
        """
    ).strip()


def public_alert_post(signal: AlertSignal) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a PUBLIC alert post.
        Style target: short market insight or best-setup note.
        Focus: one useful takeaway, one reason this stands out, and what matters next.
        Tone: useful, calm, credible, concise.
        Hard length target: 40 to 90 words.
        Structure: 1 or 2 short paragraphs.
        Hard rules: do not repeat channel mission statements, do not talk about filtering noise unless it is directly relevant to the setup.

        Market context:
        {_signal_context(signal)}
        """
    ).strip()


def pro_alert_post(signal: AlertSignal) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a PRO alert post.
        Style target: sharp desk note.
        Focus: why this is cleaner than average, what lines up, and why it deserves attention now.
        Tone: concise, direct, premium, non-promotional.
        Hard length target: 30 to 70 words.
        Structure: 1 or 2 compact paragraphs.
        Hard rules: no invitation language, no "join", no sales copy, no hype, no startup-like copy.

        Market context:
        {_signal_context(signal)}
        """
    ).strip()


def community_alert_post(signal: AlertSignal) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Task: write a COMMUNITY alert post.
        Style target: real trader dropping an observation into chat.
        Focus: what just happened and one simple chat-native reaction.
        Tone: natural, short, conversational.
        Hard length target: 12 to 45 words.
        Structure: 2 to 5 short lines. One concrete observation. A question is optional and only if it feels natural. No essay.
        Hard rules: keep it crypto-native, chat-like, and short enough to feel like a real room opener.
        If you mention a price, use the exact official Binance Futures market price from context and label it clearly.
        If the price is not needed, do not mention it at all.

        Market context:
        {_signal_context(signal)}
        """
    ).strip()


def lab_internal_summary(signal: AlertSignal, followup: FollowUpResult | None = None) -> str:
    context = _signal_context(signal) if followup is None else _followup_context(signal, followup)
    scope = "alert" if followup is None else "follow-up"
    return dedent(
        f"""
        {_global_rules()}

        Task: write a LAB internal {scope} note.
        Style target: internal ops update.
        Focus: what happened in one compact summary.
        Tone: short, factual, human.
        Hard length target: 12 to 40 words.
        Structure: one compact block, ideally one or two sentences.

        Context:
        {context}
        """
    ).strip()


def followup_summary_post(channel_kind: str, signal: AlertSignal, followup: FollowUpResult) -> str:
    audience_map = {
        "public": "PUBLIC follow-up note",
        "pro": "PRO follow-up note",
        "results": "RESULTS proof post",
        "community": "COMMUNITY follow-up note",
        "lab": "LAB follow-up note",
    }
    guidance_map = {
        "public": "Explain how price and RSI changed after the alert in a clean, educational way.",
        "pro": "Summarize outcome quality in a direct desk-style tone with zero promotional language.",
        "results": "Frame this as a clean proof/result case: what happened after the signal, why the move was favorable or adverse to the thesis, and what the chart proves.",
        "community": "Keep it short and conversational, like a trader dropping a quick follow-up into chat. A question is optional and should not appear by default. If you mention a price, use the exact official Binance Futures current price from context.",
        "lab": "Keep it practical and internal.",
    }
    length_map = {
        "public": "35 to 85 words",
        "pro": "25 to 70 words",
        "results": "30 to 80 words",
        "community": "12 to 45 words",
        "lab": "12 to 40 words",
    }
    return dedent(
        f"""
        {_global_rules()}

        Task: write a {audience_map[channel_kind]}.
        Focus: {guidance_map[channel_kind]}
        Avoid victory-lap language and avoid assistant-style explanation.
        Hard length target: {length_map[channel_kind]}.

        Context:
        {_followup_context(signal, followup)}
        """
    ).strip()


def coin_alert_analysis(*, prepared_context: str, language: str = "en", asset_class: str = "crypto") -> str:
    return dedent(
        f"""
        {_global_rules(language, asset_class=asset_class)}

        Task: write a market analysis reply for a Telegram alert button.
        Audience: a trader who tapped "AI Analysis" under an alert.
        Goal: explain whether the setup looks worth watching, whether it looks actionable yet, what looks weak or interesting, and what matters next.
        Tone: calm, practical, human, market-aware.
        Hard rules:
        - do not promise profit
        - do not say definitely buy or definitely short
        - do not pretend certainty
        - do not use hype or fake urgency
        - do not sound robotic or corporate
        - write the final answer only in {"Russian" if is_russian(language) else "English"}
        - use short paragraphs
        - keep it readable on mobile
        - no debug info
        - no markdown fences

        Preferred structure:
        1. one short paragraph describing the current condition
        2. one short paragraph saying whether this looks weak / normal / stronger and whether it is worth watching yet
        3. one short paragraph describing what matters next

        Target length: 70 to 150 words.

        Context:
        {prepared_context}
        """
    ).strip()


def premium_signal_analysis(
    *,
    prepared_context: str,
    language: str = "en",
    asset_class: str = "crypto",
) -> str:
    return dedent(
        f"""
        {_global_rules(language, asset_class=asset_class)}

        Task: write the premium trader note for an AI Analysis card.
        Important: the card already contains the hard facts. Do not repeat the whole alert in longer form.
        Use the provided facts to explain the edge, the weakness, and the next decision point.
        Important: all factual numbers already come from the system. Do not invent any prices, RSI values, stops, targets, probabilities, or levels.
        Your job is interpretation only.
        Tone: calm, sharp, practical, asset-specific, desk-style, premium.
        Hard rules:
        - no hype
        - no certainty
        - no financial-advice phrasing
        - no filler
        - no motivational language
        - no vague \"watch price action\" filler
        - no markdown fences
        - no headers
        - no bullet list
        - keep it readable on mobile
        - 35 to 70 words
        - 3 to 4 short sentences max
        - every sentence must add a concrete decision-useful point
        - refer to concrete context, not generic market commentary
        - sentence 1: what the setup is saying now
        - sentence 2: what supports it most
        - sentence 3: what weakens or invalidates it
        - optional sentence 4: who it fits or what to watch next

        Cover:
        1. what the setup is really saying now
        2. what supports it vs what weakens it
        3. what would confirm or invalidate it next

        Context:
        {prepared_context}
        """
    ).strip()


def premium_risk_commentary(
    *,
    prepared_context: str,
    language: str = "en",
    asset_class: str = "crypto",
) -> str:
    return dedent(
        f"""
        {_global_rules(language, asset_class=asset_class)}

        Task: write the premium trader note for a Risk Management card.
        Goal: explain how to use the provided stop-loss / take-profit variants without inventing any new numbers.
        Important: use only the levels and facts already in the context. Do not invent probabilities or exact win rates.
        Tone: professional, practical, concise, premium.
        Hard rules:
        - 28 to 60 words
        - 2 to 4 short sentences
        - no hype
        - no fake certainty
        - no generic \"manage risk accordingly\" filler
        - no markdown fences
        - no headers
        - focus on trade-offs, position sizing, invalidation, and which variant fits which trader
        - do not re-list every number already shown in the card
        - make the note feel like a desk comment, not a blog paragraph
        - sentence 1 should say how to frame the trade
        - sentence 2 should explain variant choice
        - optional sentence 3 or 4 can cover sizing / partials / invalidation

        Context:
        {prepared_context}
        """
    ).strip()


def premium_signal_rationale(
    *,
    prepared_context: str,
    language: str = "en",
    asset_class: str = "crypto",
) -> str:
    return dedent(
        f"""
        {_global_rules(language, asset_class=asset_class)}

        Task: write the premium trader note for a Signal Reason card.
        Goal: explain why this setup earned attention and why it was more than random noise, using only the real factors already provided.
        Important: do not invent percentages, correlations, or performance claims.
        Tone: practical, sharp, non-hyped, clear, premium.
        Hard rules:
        - 28 to 60 words
        - 2 to 4 short sentences
        - no marketing language
        - no certainty
        - no fake precision
        - do not repeat the alert in longer form
        - explain why the trigger mattered here, not just that RSI was high or low
        - no markdown fences
        - no headers
        - make it sound like a real operator explaining the trigger, not a chatbot summary
        - sentence 1 should explain the trigger
        - sentence 2 should explain the context around it
        - optional sentence 3 should explain why it was worth tracking

        Context:
        {prepared_context}
        """
    ).strip()
