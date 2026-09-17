from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.core.models import AlertSignal, FollowUpResult
from src.core.utils import format_percent, format_price, format_rsi, format_volume
from src.storage.models import AlertRecord, FollowUpResultRecord


@dataclass(slots=True)
class TwitterSignalContext:
    symbol: str
    direction: str
    timeframe: str
    price: float
    rsi: float
    live_price: float | None
    live_rsi: float | None
    score: int
    day_change_pct: float | None
    quote_volume: float | None
    atr_pct: float
    volume_ratio: float | None
    trend_context: str
    volume_context: str
    explanation: str

    def to_prompt_context(self) -> str:
        volume_ratio_text = f"{self.volume_ratio:.2f}x" if self.volume_ratio is not None else "n/a"
        return (
            f"Symbol: {self.symbol}\n"
            f"Direction: {self.direction}\n"
            f"Timeframe: {self.timeframe}\n"
            f"Signal Close: {format_price(self.price)}\n"
            f"RSI(14, closed): {format_rsi(self.rsi)}\n"
            f"Market Price: {format_price(self.live_price) if self.live_price is not None else 'n/a'}\n"
            f"RSI(14, live): {format_rsi(self.live_rsi) if self.live_rsi is not None else 'n/a'}\n"
            f"Score: {self.score}/100\n"
            f"24h Change: {format_percent(self.day_change_pct)}\n"
            f"Quote Volume: {format_volume(self.quote_volume)}\n"
            f"ATR%: {self.atr_pct:.2f}%\n"
            f"Volume Ratio: {volume_ratio_text}\n"
            f"Trend Context: {self.trend_context}\n"
            f"Volume Context: {self.volume_context}\n"
            f"Explanation: {self.explanation}"
        )


@dataclass(slots=True)
class TwitterFollowUpContext:
    symbol: str
    direction: str
    timeframe: str
    stage: str
    score: int
    alert_price: float
    current_price: float
    move_pct: float
    alert_rsi: float
    current_rsi: float
    thesis_direction: str
    favorable_move_pct: float
    adverse_move_pct: float
    thesis_result_state: str
    outcome_label: str
    reaction_quality: str
    day_change_pct: float | None
    quote_volume: float | None
    atr_pct: float
    trend_context: str
    volume_context: str
    alert_context: str
    summary: str

    def to_prompt_context(self) -> str:
        return (
            f"Symbol: {self.symbol}\n"
            f"Direction: {self.direction}\n"
            f"Timeframe: {self.timeframe}\n"
            f"Checkpoint: {self.stage}\n"
            f"Score: {self.score}/100\n"
            f"Alert Price: {format_price(self.alert_price)}\n"
            f"Current Price: {format_price(self.current_price)}\n"
            f"Move Since Alert: {format_percent(self.move_pct)}\n"
            f"RSI Then: {format_rsi(self.alert_rsi)}\n"
            f"RSI Now: {format_rsi(self.current_rsi)}\n"
            f"Thesis Direction: {self.thesis_direction}\n"
            f"Thesis Result State: {self.thesis_result_state}\n"
            f"Favorable Move: {format_percent(self.favorable_move_pct)}\n"
            f"Adverse Move: {format_percent(self.adverse_move_pct)}\n"
            f"Outcome Label: {self.outcome_label}\n"
            f"Reaction Quality: {self.reaction_quality}\n"
            f"24h Change Now: {format_percent(self.day_change_pct)}\n"
            f"Quote Volume: {format_volume(self.quote_volume)}\n"
            f"ATR%: {self.atr_pct:.2f}%\n"
            f"Trend Context: {self.trend_context}\n"
            f"Volume Context: {self.volume_context}\n"
            f"Alert Context: {self.alert_context}\n"
            f"Summary: {self.summary}"
        )


@dataclass(slots=True)
class TwitterDailyContext:
    session_date: date
    total_alerts: int
    oversold_count: int
    overbought_count: int
    total_followups: int
    confirmed_followups: int
    failed_followups: int
    average_abs_followup_move_pct: float | None
    top_proof_case: str
    strongest_setups: list[str]
    notable_followups: list[str]
    lesson_points: list[str]
    session_tone: str

    def to_prompt_context(self) -> str:
        strongest = "\n".join(f"- {item}" for item in self.strongest_setups) or "- none"
        followups = "\n".join(f"- {item}" for item in self.notable_followups) or "- none"
        lessons = "\n".join(f"- {item}" for item in self.lesson_points) or "- none"
        return (
            f"Session Date: {self.session_date.isoformat()}\n"
            f"Total Alerts: {self.total_alerts}\n"
            f"Oversold Count: {self.oversold_count}\n"
            f"Overbought Count: {self.overbought_count}\n"
            f"Total Follow-ups: {self.total_followups}\n"
            f"Confirmed Follow-ups: {self.confirmed_followups}\n"
            f"Failed Follow-ups: {self.failed_followups}\n"
            f"Average Absolute Follow-up Move: {format_percent(self.average_abs_followup_move_pct)}\n"
            f"Session Tone: {self.session_tone}\n"
            f"Top Proof Case: {self.top_proof_case}\n"
            f"Strongest Setups:\n{strongest}\n"
            f"Notable Follow-ups:\n{followups}\n"
            f"Lesson Points:\n{lessons}"
        )


def build_signal_context(signal: AlertSignal) -> TwitterSignalContext:
    return TwitterSignalContext(
        symbol=signal.symbol,
        direction=signal.direction,
        timeframe=signal.timeframe,
        price=signal.price,
        rsi=signal.rsi,
        live_price=float(signal.metadata["live_price"]) if isinstance(signal.metadata.get("live_price"), (int, float)) else None,
        live_rsi=float(signal.metadata["live_rsi"]) if isinstance(signal.metadata.get("live_rsi"), (int, float)) else None,
        score=signal.score,
        day_change_pct=signal.day_change_pct,
        quote_volume=signal.quote_volume or signal.day_volume,
        atr_pct=signal.atr_pct,
        volume_ratio=float(signal.metadata["volume_ratio"]) if isinstance(signal.metadata.get("volume_ratio"), (int, float)) else None,
        trend_context=_trend_context(signal),
        volume_context=_volume_context(signal),
        explanation=signal.explanation,
    )


def build_followup_context(signal: AlertSignal, followup: FollowUpResult) -> TwitterFollowUpContext:
    thesis_direction = followup.thesis_direction or (
        "upside bounce"
        if signal.direction == "oversold"
        else "downside cooling"
        if signal.direction == "overbought"
        else "bullish continuation"
        if signal.direction == "long"
        else "bearish continuation"
    )
    favorable_move = followup.favorable_move_pct if followup.favorable_move_pct else _favorable_move_from_direction(signal.direction, followup.move_pct)
    adverse_move = followup.adverse_move_pct if followup.adverse_move_pct else _adverse_move_from_direction(signal.direction, followup.move_pct)
    thesis_result_state = followup.thesis_result_state or _thesis_state_from_direction(signal.direction, followup.move_pct)
    return TwitterFollowUpContext(
        symbol=followup.symbol,
        direction=followup.direction,
        timeframe=followup.timeframe,
        stage=followup.stage,
        score=followup.score,
        alert_price=followup.alert_price,
        current_price=followup.current_price,
        move_pct=followup.move_pct,
        alert_rsi=followup.alert_rsi,
        current_rsi=followup.current_rsi,
        thesis_direction=thesis_direction,
        favorable_move_pct=favorable_move,
        adverse_move_pct=adverse_move,
        thesis_result_state=thesis_result_state,
        outcome_label=_outcome_label(signal.direction, followup.move_pct, thesis_result_state),
        reaction_quality=_reaction_quality(signal.direction, followup.move_pct, followup.alert_rsi, followup.current_rsi, thesis_result_state),
        day_change_pct=followup.metadata.get("24h_change_pct"),
        quote_volume=signal.quote_volume or signal.day_volume,
        atr_pct=signal.atr_pct,
        trend_context=_trend_context(signal),
        volume_context=_volume_context(signal),
        alert_context=signal.explanation,
        summary=followup.summary,
    )


def build_daily_context(
    session_date: date,
    alerts: list[AlertRecord],
    followups: list[FollowUpResultRecord],
) -> TwitterDailyContext:
    oversold_count = sum(1 for alert in alerts if alert.direction == "oversold")
    overbought_count = sum(1 for alert in alerts if alert.direction == "overbought")
    strongest_setups = [
        (
            f"{alert.symbol} {alert.direction} score {alert.score}/100, "
            f"RSI {format_rsi(alert.alert_rsi)}, price {format_price(alert.alert_price)}"
        )
        for alert in alerts[:5]
    ] 

    sorted_followups = sorted(followups, key=_followup_rank_key, reverse=True)
    confirmed_followups = sum(
        1
        for item in followups
        if _followup_thesis_state(item) == "favorable"
    )
    failed_followups = max(0, len(followups) - confirmed_followups)
    average_abs_followup_move_pct = (
        sum(abs(item.move_pct) for item in followups) / len(followups)
        if followups
        else None
    )
    notable_followups = [
        (
            f"{item.symbol} {item.stage} { _followup_thesis_state(item) } case: "
            f"{format_percent(_followup_favorable_move(item) if _followup_thesis_state(item) == 'favorable' else item.move_pct)} move, "
            f"RSI {format_rsi(item.alert_rsi)} -> {format_rsi(item.current_rsi)}"
        )
        for item in sorted_followups[:5]
    ]

    lessons: list[str] = []
    if oversold_count > overbought_count:
        lessons.append("Oversold signals outnumbered overbought ones, so the session leaned toward dip-stress and bounce watch.")
    elif overbought_count > oversold_count:
        lessons.append("Overbought signals dominated, which points to broader stretch and possible fade conditions.")
    else:
        lessons.append("The board stayed fairly balanced between oversold and overbought extremes.")

    if sorted_followups:
        best = sorted_followups[0]
        lessons.append(
            f"The clearest follow-up came from {best.symbol} at {best.stage}, with a {format_percent(_followup_favorable_move(best) if _followup_thesis_state(best) == 'favorable' else best.move_pct)} move after the signal."
        )
        worst = sorted_followups[-1]
        lessons.append(
            f"Not every setup followed through cleanly. {worst.symbol} is a reminder to judge the reaction, not just the trigger."
        )

    session_tone = _session_tone(oversold_count, overbought_count, sorted_followups)
    return TwitterDailyContext(
        session_date=session_date,
        total_alerts=len(alerts),
        oversold_count=oversold_count,
        overbought_count=overbought_count,
        total_followups=len(followups),
        confirmed_followups=confirmed_followups,
        failed_followups=failed_followups,
        average_abs_followup_move_pct=average_abs_followup_move_pct,
        top_proof_case=notable_followups[0] if notable_followups else "none",
        strongest_setups=strongest_setups,
        notable_followups=notable_followups,
        lesson_points=lessons,
        session_tone=session_tone,
    )


def _trend_context(signal: AlertSignal) -> str:
    if signal.direction in {"oversold", "long"}:
        if signal.price < signal.ema20 < signal.ema50:
            return "short-term downtrend stretch"
        if signal.price < signal.ema20:
            return "below fast trend but not fully aligned" if signal.direction == "oversold" else "bullish trigger against soft trend context"
        return "countertrend oversold print" if signal.direction == "oversold" else "bullish continuation structure"
    if signal.price > signal.ema20 > signal.ema50:
        return "short-term uptrend stretch"
    if signal.price > signal.ema20:
        return "above fast trend but not fully aligned" if signal.direction == "overbought" else "bearish trigger against firm trend context"
    return "countertrend overbought print" if signal.direction == "overbought" else "bearish continuation structure"


def _volume_context(signal: AlertSignal) -> str:
    volume_ratio = signal.metadata.get("volume_ratio")
    if volume_ratio is None:
        return "volume context unavailable"
    if volume_ratio >= 1.8:
        return "clear volume expansion"
    if volume_ratio >= 1.2:
        return "volume running above average"
    return "volume close to normal"


def _outcome_label(direction: str, move_pct: float, thesis_state: str | None = None) -> str:
    state = thesis_state or _thesis_state_from_direction(direction, move_pct)
    if direction == "oversold":
        if state == "favorable":
            return "bounce follow-through"
        if state == "neutral":
            return "bounce still needs confirmation"
        return "bounce failed to show up"
    if direction == "long":
        if state == "favorable":
            return "long continuation followed through"
        if state == "neutral":
            return "long continuation still needs confirmation"
        return "long trigger failed to hold"
    if direction == "short":
        if state == "favorable":
            return "short continuation followed through"
        if state == "neutral":
            return "short continuation still needs confirmation"
        return "short trigger failed to hold"
    if state == "favorable":
        return "pullback followed through"
    if state == "neutral":
        return "cooling move still needs confirmation"
    return "momentum stayed stronger than the signal alone implied"


def _session_tone(
    oversold_count: int,
    overbought_count: int,
    followups: list[FollowUpResultRecord],
) -> str:
    if not followups:
        if oversold_count > overbought_count:
            return "soft tape with repeated dip-stress"
        if overbought_count > oversold_count:
            return "stretched tape with repeated upside extension"
        return "mixed tape without a single dominant theme"

    avg_move = sum(item.move_pct for item in followups) / len(followups)
    if oversold_count > overbought_count and avg_move >= 0:
        return "dip-buying responses showed up more often than clean continuation lower"
    if overbought_count > oversold_count and avg_move <= 0:
        return "fades and cooling moves showed up more often than fresh squeeze follow-through"
    return "mixed tape where signal quality depended more on reaction quality than on the trigger itself"


def _reaction_quality(direction: str, move_pct: float, alert_rsi: float, current_rsi: float, thesis_state: str | None = None) -> str:
    state = thesis_state or _thesis_state_from_direction(direction, move_pct)
    rsi_shift = current_rsi - alert_rsi
    if direction == "oversold":
        if state == "favorable" and (move_pct >= 2 or (move_pct >= 1 and rsi_shift >= 10)):
            return "clear bounce follow-through"
        if state == "favorable":
            return "partial bounce, still needs confirmation"
        return "failed bounce so far"
    if direction == "long":
        if state == "favorable" and (move_pct >= 2 or (move_pct >= 1 and rsi_shift >= 5)):
            return "clean long continuation"
        if state == "favorable":
            return "positive continuation, but not decisive yet"
        return "long setup failed to gain traction"
    if direction == "short":
        if state == "favorable" and (move_pct <= -2 or (move_pct <= -1 and rsi_shift <= -5)):
            return "clean short continuation"
        if state == "favorable":
            return "negative continuation, but not decisive yet"
        return "short setup failed to gain traction"

    if state == "favorable" and (move_pct <= -2 or (move_pct <= -1 and rsi_shift <= -10)):
        return "clean fade follow-through"
    if state == "favorable":
        return "cooling move, but not decisive yet"
    return "momentum stayed stronger than the signal alone implied"


def _thesis_state_from_direction(direction: str, move_pct: float) -> str:
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


def _favorable_move_from_direction(direction: str, move_pct: float) -> float:
    if direction in {"oversold", "long"}:
        return max(move_pct, 0.0)
    return max(-move_pct, 0.0)


def _adverse_move_from_direction(direction: str, move_pct: float) -> float:
    if direction in {"oversold", "long"}:
        return max(-move_pct, 0.0)
    return max(move_pct, 0.0)


def _followup_thesis_state(record: FollowUpResultRecord) -> str:
    state = str(record.metadata.get("thesis_result_state") or "").strip().lower()
    if state in {"favorable", "adverse", "neutral"}:
        return state
    return _thesis_state_from_direction(record.direction, record.move_pct)


def _followup_favorable_move(record: FollowUpResultRecord) -> float:
    value = record.metadata.get("favorable_move_pct")
    if isinstance(value, (int, float)):
        return float(value)
    return _favorable_move_from_direction(record.direction, record.move_pct)


def _followup_stage_bonus(stage: str) -> float:
    return {
        "2h": 0.8,
        "4h": 1.4,
        "6h": 1.8,
        "8h": 2.0,
    }.get(stage.lower(), 1.0)


def _followup_rank_key(record: FollowUpResultRecord) -> float:
    state = _followup_thesis_state(record)
    favorable_move = _followup_favorable_move(record)
    rsi_recovery = abs(record.current_rsi - record.alert_rsi)
    base = favorable_move * 14.0 + min(rsi_recovery, 20.0) * 0.9 + (record.score / 10.0)
    if state == "favorable":
        base += 22.0
    elif state == "neutral":
        base += 4.0
    else:
        base -= 8.0
    return base + _followup_stage_bonus(record.stage)
