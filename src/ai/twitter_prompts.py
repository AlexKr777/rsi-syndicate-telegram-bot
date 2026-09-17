from __future__ import annotations

from textwrap import dedent


def _global_rules() -> str:
    return dedent(
        """
        Write in English only.
        Write for X/Twitter, not Telegram, not email, not LinkedIn.
        Return only the final post text.
        Return one version only.
        Do not add quotation marks around the post.
        Do not explain the post.
        Do not mention that you are writing a tweet, post, draft, variant, or reply.
        Sound like a real human trader/operator running a serious signal project.
        The post must feel useful first, promotional second.
        Deliver at least one of: idea, edge, proof.
        Be concise, sharp, readable, mobile-friendly, and market-native.
        Avoid robotic phrasing, corporate language, fake guru tone, fake urgency, fake certainty, and hype.
        No "I'm excited".
        No "best regards".
        No "join us".
        No "revolutionizing".
        No "guaranteed profits".
        No "moon", "lambo", or "100x".
        No "here's a tweet-sized post" or other meta lead-ins.
        No labels like "main draft", "short version", or "reply/comment" inside the copy.
        At most two emojis total, and usually zero or one.
        Avoid rocket, gem, siren, brain, sparkle spam, or anything that feels AI-generated.
        No spammy CTA.
        Do not make the post feel like automated crypto noise.
        Prefer a strong opening line, one useful takeaway, and tight structure.
        Use real evidence from the structured context when it sharpens the point.
        If the post is session-level and no chart is attached, do not center it on one coin.
        If follow-up proof is available, prefer that over a raw trigger recap.
        Do not overload numbers unless they matter to the point.
        """
    ).strip()


def twitter_analysis_decision(
    *,
    candidate_type: str,
    prepared_context: str,
    recent_angles: str,
    overused_phrases: str,
    preview_mode: bool,
) -> str:
    preview_text = "PREVIEW MODE is ON. Still keep the same quality standard." if preview_mode else "Normal mode: skip weak drafts."
    return dedent(
        f"""
        {_global_rules()}

        You are the analysis model.
        Decide whether this X/Twitter draft is worth making.

        Candidate type: {candidate_type}
        {preview_text}

        Return exactly these 7 lines:
        Worth Posting: yes or no
        Angle: observation | result | proof | lesson | market context | operator opinion | recap | watchlist
        Value: comma-separated choices from curiosity value | watchlist value | learning value | proof value | decision value
        Hook: one sentence
        Takeaway: one sentence
        Why It Matters: one sentence
        Skip Reason: one short phrase, or "none"

        Rules:
        - choose "no" if the post is not clearly interesting, useful, readable, human, or follow-worthy
        - if there is no clear user value, choose "no"
        - choose "no" if the case is mostly a raw RSI print without proof, context, or a practical takeaway
        - choose "no" if the copy would read like a market report instead of a post worth sharing
        - prefer follow-up-confirmed proof over raw alerts whenever that evidence exists
        - prefer fewer, better posts
        - do not force a draft just because data exists
        - vary angles naturally and avoid repeating overused phrases

        Recent angles:
        {recent_angles}

        Overused phrases to avoid:
        {overused_phrases}

        Structured context:
        {prepared_context}
        """
    ).strip()


def twitter_best_setup_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a best-setup post for X/Twitter.",
        focus="Explain why this specific setup is cleaner than average right now. Make the hook feel native to a fast market feed, not like a report.",
        structure="One sharp hook, one short explanation, one takeaway. Use the signal context to explain why this matters now, not how RSI works.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_followup_result_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a follow-up result post for X/Twitter.",
        focus="Show what happened after the alert in a grounded, trust-building way. Lead with the before -> after proof and explain what a trader should learn from it.",
        structure="Open with the result, then compress the lesson. Sound calm and credible. No victory lap, no chest-beating.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_market_insight_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a market-insight post for X/Twitter.",
        focus="Summarize one useful session read that actually changes how a trader should filter the board.",
        structure="Open with the readable condition, then turn it into a decision-quality takeaway. Keep it session-level unless a chart is attached.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_operator_opinion_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write an operator-opinion post for X/Twitter.",
        focus="Sound like a real human operator giving one market thought grounded in the collected data.",
        structure="Use a personal but disciplined tone. One opinion, one reason, one takeaway. No motivational filler.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_chart_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a chart-first post for X/Twitter.",
        focus="Let the chart and the takeaway work together. The caption should add the lesson the eye might miss, not repeat the obvious candles.",
        structure="One chart implication, one reason it matters, one takeaway. If there is follow-up proof, make that the center of gravity.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_daily_recap_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a daily recap post for X/Twitter.",
        focus="Give a short end-of-day narrative only if the session produced a real lesson or proof case.",
        structure="Make it read like a trader's close note, not a report. One clear close note, one lesson.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_daily_stats_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a daily stats post for X/Twitter.",
        focus="Use stats only if they support a useful takeaway or proof read. Never dump counts without interpretation.",
        structure="Lead with the takeaway, then use only the numbers that make that point stronger.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_fomo_or_missed_move_post(*, prepared_context: str, analysis_summary: str, include_soft_promo: bool, preview_mode: bool) -> str:
    return _writer_prompt(
        task="Write a missed-move / proof-style post for X/Twitter.",
        focus="Create curiosity and proof without sounding manipulative or chest-beating. The point is to show what the follow-up proved.",
        structure="Start with the move or outcome, then explain why the market response mattered more than the trigger itself.",
        prepared_context=prepared_context,
        analysis_summary=analysis_summary,
        include_soft_promo=include_soft_promo,
        preview_mode=preview_mode,
    )


def twitter_short_variant(*, prepared_context: str, analysis_summary: str, preview_mode: bool) -> str:
    preview_text = "This is PREVIEW MODE." if preview_mode else "This is normal mode."
    return dedent(
        f"""
        {_global_rules()}

        Write one shorter X/Twitter variant of the same idea.
        Goal: quicker, punchier, still useful.
        Length target: 12 to 45 words.
        Return only the shorter post text.
        {preview_text}

        Analysis summary:
        {analysis_summary}

        Structured context:
        {prepared_context}
        """
    ).strip()


def twitter_reply_comment(*, prepared_context: str, analysis_summary: str, preview_mode: bool) -> str:
    preview_text = "This is PREVIEW MODE." if preview_mode else "This is normal mode."
    return dedent(
        f"""
        {_global_rules()}

        Write one optional reply/comment line for the post.
        Goal: add one extra useful thought in a natural way.
        Length target: 8 to 28 words.
        Return only the reply text.
        {preview_text}

        Analysis summary:
        {analysis_summary}

        Structured context:
        {prepared_context}
        """
    ).strip()


def twitter_rewrite_for_diversity(
    *,
    existing_text: str,
    prepared_context: str,
    analysis_summary: str,
    avoid_phrases: str,
    recent_openings: str,
) -> str:
    return dedent(
        f"""
        {_global_rules()}

        Rewrite this X/Twitter draft once so it feels less repetitive.

        Rules:
        - keep the same core point
        - use a different opening style
        - change sentence rhythm and framing
        - avoid these phrases: {avoid_phrases}
        - avoid openings similar to: {recent_openings}
        - return only the rewritten post text
        - do not make it longer or more corporate

        Analysis summary:
        {analysis_summary}

        Structured context:
        {prepared_context}

        Draft to rewrite:
        {existing_text}
        """
    ).strip()


def _writer_prompt(
    *,
    task: str,
    focus: str,
    structure: str,
    prepared_context: str,
    analysis_summary: str,
    include_soft_promo: bool,
    preview_mode: bool,
) -> str:
    preview_text = "PREVIEW MODE is ON. Keep the same quality standard." if preview_mode else "Normal mode."
    promo_text = "Soft promo is allowed, but only lightly and only after useful content." if include_soft_promo else "Do not include product promotion."
    return dedent(
        f"""
        {_global_rules()}

        {task}
        Focus: {focus}
        Structure: {structure}
        Preferred length: 1 to 4 short lines, usually 35 to 90 words.
        {promo_text}
        {preview_text}

        Analysis summary:
        {analysis_summary}

        Structured context:
        {prepared_context}
        """
    ).strip()
