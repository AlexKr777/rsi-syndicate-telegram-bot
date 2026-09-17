from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThesisResult:
    thesis_direction: str
    favorable_move_pct: float
    adverse_move_pct: float
    thesis_result_state: str


def thesis_direction_for_signal(direction: str) -> str:
    if direction == "long":
        return "long_continuation"
    if direction == "short":
        return "short_continuation"
    if direction == "oversold":
        return "upside_reaction"
    if direction == "overbought":
        return "downside_cooling"
    return "neutral"


def evaluate_thesis_result(direction: str, move_pct: float, *, neutral_tolerance: float = 0.15) -> ThesisResult:
    if direction in {"oversold", "long"}:
        favorable = max(move_pct, 0.0)
        adverse = max(-move_pct, 0.0)
    elif direction in {"overbought", "short"}:
        favorable = max(-move_pct, 0.0)
        adverse = max(move_pct, 0.0)
    else:
        favorable = 0.0
        adverse = 0.0

    if favorable > neutral_tolerance and favorable >= adverse:
        state = "favorable"
    elif adverse > neutral_tolerance and adverse > favorable:
        state = "adverse"
    else:
        state = "neutral"

    return ThesisResult(
        thesis_direction=thesis_direction_for_signal(direction),
        favorable_move_pct=favorable,
        adverse_move_pct=adverse,
        thesis_result_state=state,
    )


def summarize_followup(
    direction: str,
    *,
    stage: str,
    market_move_pct: float,
    candle_move_pct: float,
    current_rsi: float,
    alert_rsi: float,
    language: str = "en",
) -> str:
    thesis = evaluate_thesis_result(direction, market_move_pct)
    is_russian = str(language or "en").strip().lower().startswith("ru")
    stage_prefix = f"{stage} проверка: " if is_russian else f"{stage} check: "

    if direction == "long":
        if thesis.thesis_result_state == "favorable":
            if market_move_pct >= 1.0:
                return stage_prefix + (
                    "лонговый сценарий развивается: цена держится выше триггера и продолжает движение вверх."
                    if is_russian
                    else "the long thesis is developing: price is holding above the trigger and extending higher."
                )
            return stage_prefix + (
                "лонговый сценарий подтверждается, но импульс пока еще ранний."
                if is_russian
                else "the long thesis is confirmed, but the move still looks early."
            )
        if thesis.thesis_result_state == "adverse":
            return stage_prefix + (
                "лонговый сценарий пока не держится: цена ушла ниже триггерной зоны и давит вниз."
                if is_russian
                else "the long thesis is not holding for now: price slipped back below the trigger zone and is pressing lower."
            )
        return stage_prefix + (
            "лонговый сценарий пока смешанный: есть реакция, но без явного продолжения."
            if is_russian
            else "the long thesis is still mixed: there is a reaction, but no clear follow-through yet."
        )

    if direction == "short":
        if thesis.thesis_result_state == "favorable":
            if market_move_pct <= -1.0:
                return stage_prefix + (
                    "шортовый сценарий развивается: цена держится ниже триггера и продолжает снижение."
                    if is_russian
                    else "the short thesis is developing: price is holding below the trigger and extending lower."
                )
            return stage_prefix + (
                "шортовый сценарий подтверждается, но движение пока еще раннее."
                if is_russian
                else "the short thesis is confirmed, but the move still looks early."
            )
        if thesis.thesis_result_state == "adverse":
            return stage_prefix + (
                "шортовый сценарий пока ломается: цена вернулась выше триггерной зоны и восстанавливается."
                if is_russian
                else "the short thesis is failing for now: price reclaimed the trigger zone and is recovering."
            )
        return stage_prefix + (
            "шортовый сценарий пока смешанный: есть охлаждение, но без явного продолжения."
            if is_russian
            else "the short thesis is still mixed: there is some cooling, but no clear follow-through yet."
        )

    if direction == "oversold":
        if thesis.thesis_result_state == "favorable":
            if candle_move_pct > 0 and market_move_pct <= 0.5 and current_rsi > alert_rsi:
                if is_russian:
                    return stage_prefix + "после сигнала перепроданности цена отскочила и RSI восстановился, но в live-рынке значительная часть этой реакции уже ослабла."
                return stage_prefix + "price bounced after the oversold signal and RSI recovered, but much of that reaction has already faded in the live market."
            if current_rsi >= alert_rsi + 8:
                if is_russian:
                    return stage_prefix + "сценарий отскока пока отрабатывает: цена выше уровня сигнала, а RSI заметно восстановился от экстремума."
                return stage_prefix + "the bounce thesis is working so far: price is higher than the signal level and RSI has recovered clearly from the extreme."
            if is_russian:
                return stage_prefix + "цена движется в ожидаемую сторону отскока, но восстановление пока выглядит ранним, а не полностью подтвержденным."
            return stage_prefix + "price is moving in the expected bounce direction, but the recovery still looks early rather than fully confirmed."
        if thesis.thesis_result_state == "adverse":
            if current_rsi < alert_rsi:
                if is_russian:
                    return stage_prefix + "сценарий отскока пока ломается: после сигнала перепроданности цена осталась слабой, а RSI ушел еще ниже вместо восстановления."
                return stage_prefix + "the bounce thesis is failing for now: price stayed weak after the oversold signal and RSI slipped further instead of recovering."
            if is_russian:
                return stage_prefix + "цена пошла против сценария перепроданности, поэтому поведение больше похоже на продолжающееся давление вниз, чем на рабочий отскок."
            return stage_prefix + "price moved against the oversold thesis, so this still behaves more like ongoing downside pressure than a usable bounce."
        if is_russian:
            return stage_prefix + "сигнал перепроданности пока не дал достаточно продолжения, поэтому это все еще больше контекст для watchlist, чем подтверждение."
        return stage_prefix + "the oversold signal has not produced enough follow-through yet, so this still looks more like watchlist context than proof."

    if direction == "overbought":
        if thesis.thesis_result_state == "favorable":
            if candle_move_pct < 0 and market_move_pct >= -0.5 and current_rsi < alert_rsi:
                if is_russian:
                    return stage_prefix + "после сигнала перекупленности цена остыла и RSI нормализовался, но live-рынок уже успел частично откатить это движение."
                return stage_prefix + "price cooled off after the overbought signal and RSI normalized, but the live market has already retraced part of that move."
            if current_rsi <= alert_rsi - 8:
                if is_russian:
                    return stage_prefix + "сценарий охлаждения пока работает: цена ниже уровня сигнала, а RSI заметно отошел от экстремума."
                return stage_prefix + "the cooling thesis is working so far: price is lower than the signal level and RSI has backed away clearly from the extreme."
            if is_russian:
                return stage_prefix + "цена реагирует в ожидаемую сторону охлаждения, но снижение пока выглядит ранним, а не полностью подтвержденным."
            return stage_prefix + "price is reacting in the expected cooling direction, but the fade still looks early rather than fully confirmed."
        if thesis.thesis_result_state == "adverse":
            if current_rsi > alert_rsi:
                if is_russian:
                    return stage_prefix + "сценарий охлаждения пока ломается: после сигнала перекупленности цена продолжила рост, а RSI остался растянутым вместо ослабления."
                return stage_prefix + "the cooling thesis is failing for now: price kept pushing after the overbought signal and RSI stayed stretched instead of easing."
            if is_russian:
                return stage_prefix + "цена пошла против сценария перекупленности, поэтому импульс оказался сильнее, чем предполагал один только сигнал."
            return stage_prefix + "price moved against the overbought thesis, so momentum stayed stronger than the signal alone implied."
        if is_russian:
            return stage_prefix + "сигнал перекупленности пока не дал достаточно продолжения, поэтому это все еще больше контекст для watchlist, чем подтверждение."
        return stage_prefix + "the overbought signal has not produced enough follow-through yet, so this still looks more like watchlist context than proof."

    if is_russian:
        return stage_prefix + "сигнал вернулся в нейтральную зону, поэтому follow-up сейчас скорее контекстный, чем направленный."
    return stage_prefix + "the signal is back in neutral territory, so the follow-up is more contextual than directional."
