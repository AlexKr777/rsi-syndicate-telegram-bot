from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.core.utils import escape_html, normalize_symbol
from src.localization import normalize_language
from src.storage.models import FollowUpResultRecord, SignalLifecycleRecord
from src.storage.repository import Repository

_STRATEGY_LABELS = {
    "breakout": ("Breakout", "Пробой"),
    "trend_pullback": ("Trend Pullback", "Откат по тренду"),
    "rsi_bollinger_mr": ("RSI + Bollinger MR", "RSI + Bollinger MR"),
    "rsi_bollinger_touch": ("RSI + Bollinger Touch", "RSI + Bollinger Touch"),
    "vwap": ("VWAP", "VWAP"),
    "false_breakout": ("False Breakout", "Ложный пробой"),
    "rsi": ("RSI", "RSI"),
    "rsi_divergence": ("RSI Divergence", "RSI Divergence"),
    "ekek": ("EKEK", "EKEK"),
    "bollinger": ("Bollinger", "Bollinger"),
    "gold": ("Gold / XAUUSD", "Gold / XAUUSD"),
}

_STATUS_META = {
    "confirmed": {"emoji": "✅", "rank": 2},
    "near_tp": {"emoji": "🎯", "rank": 3},
    "hit_tp": {"emoji": "🏆", "rank": 5},
    "invalidated": {"emoji": "❌", "rank": 4},
    "expired": {"emoji": "⏳", "rank": 1},
}

_STATUS_LABELS = {
    "en": {
        "confirmed": "Confirmed",
        "near_tp": "Near TP",
        "hit_tp": "Hit TP",
        "invalidated": "Invalidated",
        "expired": "Expired",
    },
    "ru": {
        "confirmed": "Подтверждён",
        "near_tp": "Почти TP",
        "hit_tp": "Дошёл до TP",
        "invalidated": "Сломан",
        "expired": "Истёк",
    },
}


@dataclass(frozen=True, slots=True)
class AdminAuditItem:
    signal_id: int
    alert_id: int | None
    strategy_code: str
    symbol: str
    timeframe: str
    event_type: str
    event_at: datetime
    score: float | None
    favorable_move_pct: float
    adverse_move_pct: float
    hidden_strategy: bool
    delivered_alert: bool


@dataclass(frozen=True, slots=True)
class AdminAuditSummary:
    total_created: int
    enabled_strategy_created: int
    hidden_strategy_created: int
    delivered_alerts: int
    confirmed_count: int
    near_tp_count: int
    hit_tp_count: int
    invalidated_count: int
    expired_count: int
    interesting_items: tuple[AdminAuditItem, ...]


class AdminMonitoringService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def build_summary(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str,
        content_kind: str,
        enabled_strategy_keys: tuple[str, ...],
        start: datetime,
        end: datetime,
        signal_limit: int = 400,
        item_limit: int = 5,
    ) -> AdminAuditSummary:
        recent_signals = await self.repository.list_recent_tracked_signals(since=start, limit=signal_limit)
        delivered = await self.repository.list_delivered_signals(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            content_kind=content_kind,
            since=start,
            limit=max(signal_limit * 2, 200),
        )
        delivered_alert_ids = {
            int(record.alert_id)
            for record in delivered
            if record.alert_id is not None
            and record.message_kind == "alert"
            and bool(record.metadata.get("sent", True))
        }
        followups = await self.repository.list_followup_results_between(
            start=start,
            end=end,
            limit=max(signal_limit * 2, 200),
        )
        followups_by_alert_id: dict[int, FollowUpResultRecord] = {}
        for followup in followups:
            current = followups_by_alert_id.get(followup.alert_id)
            if current is None or followup.observed_at > current.observed_at:
                followups_by_alert_id[followup.alert_id] = followup

        enabled = set(enabled_strategy_keys)
        created_records = [record for record in recent_signals if start <= record.created_at < end]
        enabled_created = [record for record in created_records if record.strategy_code in enabled]
        hidden_created = [record for record in created_records if record.strategy_code not in enabled]

        interesting_items: list[AdminAuditItem] = []
        for record in recent_signals:
            event_type, event_at = self._latest_interesting_event(record, start=start, end=end)
            if event_type is None or event_at is None:
                continue
            followup = followups_by_alert_id.get(int(record.alert_id or 0))
            interesting_items.append(
                AdminAuditItem(
                    signal_id=record.signal_id,
                    alert_id=record.alert_id,
                    strategy_code=record.strategy_code,
                    symbol=normalize_symbol(record.symbol),
                    timeframe=record.timeframe,
                    event_type=event_type,
                    event_at=event_at,
                    score=record.confidence_score,
                    favorable_move_pct=float(followup.metadata.get("favorable_move_pct") or 0.0) if followup is not None else 0.0,
                    adverse_move_pct=float(followup.metadata.get("adverse_move_pct") or 0.0) if followup is not None else 0.0,
                    hidden_strategy=record.strategy_code not in enabled,
                    delivered_alert=record.alert_id in delivered_alert_ids if record.alert_id is not None else False,
                )
            )
        interesting_items.sort(key=self._item_rank, reverse=True)

        return AdminAuditSummary(
            total_created=len(created_records),
            enabled_strategy_created=len(enabled_created),
            hidden_strategy_created=len(hidden_created),
            delivered_alerts=len(delivered_alert_ids),
            confirmed_count=sum(1 for record in recent_signals if record.confirmed_at is not None and start <= record.confirmed_at < end),
            near_tp_count=sum(1 for record in recent_signals if record.near_tp_at is not None and start <= record.near_tp_at < end),
            hit_tp_count=sum(1 for record in recent_signals if record.hit_tp_at is not None and start <= record.hit_tp_at < end),
            invalidated_count=sum(1 for record in recent_signals if record.invalidated_at is not None and start <= record.invalidated_at < end),
            expired_count=sum(1 for record in recent_signals if record.expired_at is not None and start <= record.expired_at < end),
            interesting_items=tuple(interesting_items[:item_limit]),
        )

    def select_digest_items(
        self,
        summary: AdminAuditSummary,
        *,
        limit: int = 3,
    ) -> tuple[AdminAuditItem, ...]:
        selected: list[AdminAuditItem] = []
        for item in summary.interesting_items:
            if not self._is_digest_worthy(item):
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
        return tuple(selected)

    def render_status_block(self, summary: AdminAuditSummary, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        is_ru = language == "ru"
        title = "👑 Мониторинг admin" if is_ru else "👑 Admin Monitor"
        intro = (
            "Сводка по всему системному потоку за 24 часа, включая стратегии, которые сейчас выключены в твоём личном наборе."
            if is_ru
            else "A 24h view of the full system stream, including strategies that are currently disabled in your personal setup."
        )
        lines = [
            f"<b>{escape_html(title)}</b>",
            "",
            escape_html(intro),
            "",
            f"{'Создано сигналов' if is_ru else 'Signals created'}: <b>{summary.total_created}</b>",
            f"{'По включённым стратегиям' if is_ru else 'On enabled strategies'}: <b>{summary.enabled_strategy_created}</b>",
            f"{'По выключенным стратегиям' if is_ru else 'On disabled strategies'}: <b>{summary.hidden_strategy_created}</b>",
            f"{'Доставлено тебе alert-карт' if is_ru else 'Alerts delivered to you'}: <b>{summary.delivered_alerts}</b>",
            "",
            f"{'TP' if is_ru else 'Hit TP'}: <b>{summary.hit_tp_count}</b>  |  {'SL / сломан' if is_ru else 'Invalidated'}: <b>{summary.invalidated_count}</b>",
            f"{'Подтверждён' if is_ru else 'Confirmed'}: <b>{summary.confirmed_count}</b>  |  {'Почти TP' if is_ru else 'Near TP'}: <b>{summary.near_tp_count}</b>  |  {'Истёк' if is_ru else 'Expired'}: <b>{summary.expired_count}</b>",
        ]
        if summary.interesting_items:
            lines.extend(
                [
                    "",
                    escape_html("Что сейчас интереснее всего:" if is_ru else "Most interesting right now:"),
                ]
            )
            for item in summary.interesting_items[:3]:
                lines.append(self._render_item_line(item, language_code=language_code))
        else:
            lines.extend(
                [
                    "",
                    escape_html(
                        "Пока нет сильных lifecycle-обновлений по общему потоку."
                        if is_ru
                        else "No meaningful lifecycle shifts have appeared in the broader stream yet."
                    ),
                ]
            )
        return "\n".join(lines)

    def render_digest(
        self,
        items: tuple[AdminAuditItem, ...],
        *,
        language_code: str = "en",
    ) -> str:
        language = normalize_language(language_code)
        is_ru = language == "ru"
        lines = [
            f"<b>{escape_html('👑 Admin Flow Digest' if not is_ru else '👑 Сводка admin-потока')}</b>",
            "",
            escape_html(
                "Интересные движения по follow-up и статусам со всего потока, включая стратегии, которые у тебя сейчас выключены."
                if is_ru
                else "Interesting follow-up and lifecycle movement across the full stream, including strategies that are currently disabled in your setup."
            ),
        ]
        for item in items:
            lines.extend(["", self._render_item_line(item, language_code=language_code)])
        lines.extend(
            [
                "",
                escape_html(
                    "Срез специально отфильтрован по самым полезным изменениям, чтобы не засорять чат."
                    if is_ru
                    else "This digest is filtered to the most useful changes so it stays low-noise."
                ),
            ]
        )
        return "\n".join(lines)

    def _latest_interesting_event(
        self,
        record: SignalLifecycleRecord,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[str | None, datetime | None]:
        candidates = [
            ("confirmed", record.confirmed_at),
            ("near_tp", record.near_tp_at),
            ("hit_tp", record.hit_tp_at),
            ("invalidated", record.invalidated_at),
            ("expired", record.expired_at),
        ]
        recent = [(event_type, event_at) for event_type, event_at in candidates if event_at is not None and start <= event_at < end]
        if not recent:
            return None, None
        recent.sort(key=lambda item: (item[1].timestamp(), int(_STATUS_META[item[0]]["rank"])))
        return recent[-1]

    def _item_rank(self, item: AdminAuditItem) -> tuple[int, int, float, float, float]:
        hidden_bonus = 1 if item.hidden_strategy else 0
        severity = int(_STATUS_META[item.event_type]["rank"])
        move = item.adverse_move_pct if item.event_type == "invalidated" else item.favorable_move_pct
        score = float(item.score or 0.0)
        return (hidden_bonus, severity, move, score, item.event_at.timestamp())

    def _is_digest_worthy(self, item: AdminAuditItem) -> bool:
        if item.event_type in {"hit_tp", "invalidated"}:
            return True
        if item.hidden_strategy and item.event_type in {"near_tp", "confirmed"}:
            return True
        if item.event_type == "near_tp" and item.favorable_move_pct >= 5.0:
            return True
        return item.event_type == "confirmed" and item.favorable_move_pct >= 3.0 and float(item.score or 0.0) >= 86.0

    def _render_item_line(self, item: AdminAuditItem, *, language_code: str) -> str:
        language = normalize_language(language_code)
        is_ru = language == "ru"
        strategy_name = _STRATEGY_LABELS.get(item.strategy_code, (item.strategy_code.replace("_", " ").title(), item.strategy_code.replace("_", " ").title()))[1 if is_ru else 0]
        status_label = _STATUS_LABELS[language].get(item.event_type, item.event_type)
        emoji = str(_STATUS_META[item.event_type]["emoji"])
        if item.event_type == "invalidated":
            move_label = (
                f"adverse {item.adverse_move_pct:.1f}%"
                if not is_ru
                else f"против хода {item.adverse_move_pct:.1f}%"
            )
        else:
            move_label = (
                f"favorable {item.favorable_move_pct:.1f}%"
                if not is_ru
                else f"по сценарию {item.favorable_move_pct:.1f}%"
            )
        tag = ""
        if item.hidden_strategy:
            tag = "disabled in your setup" if not is_ru else "стратегия выключена у тебя"
        elif not item.delivered_alert:
            tag = "not sent to your feed" if not is_ru else "в ленту не отправлялся"
        suffix = f" | {tag}" if tag else ""
        return (
            f"• {emoji} <b>{escape_html(item.symbol)}</b> | "
            f"{escape_html(strategy_name)} | "
            f"{escape_html(status_label)} | "
            f"{escape_html(move_label)}{escape_html(suffix)}"
        )
