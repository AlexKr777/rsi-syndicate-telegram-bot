"""Safely mark historical follow-ups without lifecycle data as incomplete.

Run from the repository root:
    .\\.venv\\Scripts\\python.exe -m src.tools.backfill_results_lifecycle --dry-run
    .\\.venv\\Scripts\\python.exe -m src.tools.backfill_results_lifecycle --apply
"""

from __future__ import annotations

import argparse
import asyncio

from src.core.config import get_settings
from src.core.models import AlertSignal
from src.signals.service import SignalLifecycleService
from src.storage.repository import Repository


def _signal_from_alert(alert) -> AlertSignal:
    metadata = {
        **alert.metadata,
        "strategy_key": alert.strategy_key,
        "historical_backfill": True,
        "historical_outcome_incomplete": True,
    }
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
        quote_volume=float(alert.metadata.get("quote_volume") or 0.0) or None,
        last_candle_volume=float(alert.metadata.get("last_candle_volume") or 0.0),
        avg_volume_20=float(alert.metadata.get("avg_volume_20") or 0.0),
        atr=float(alert.metadata.get("atr") or 0.0),
        atr_pct=float(alert.metadata.get("atr_pct") or 0.0),
        ema20=float(alert.metadata.get("ema20") or 0.0),
        ema50=float(alert.metadata.get("ema50") or 0.0),
        score=alert.score,
        explanation=str(alert.metadata.get("explanation") or "Historical follow-up without full candle path."),
        metadata=metadata,
    )


async def _run(*, apply: bool, limit: int) -> dict[str, int]:
    settings = get_settings()
    repository = Repository(str(settings.sqlite_path))
    lifecycle_service = SignalLifecycleService(repository)
    summary = {"candidates": 0, "backfilled_incomplete": 0, "orphans": 0}
    try:
        for followup in await repository.list_followup_results_missing_lifecycle(limit=limit):
            summary["candidates"] += 1
            alert = await repository.get_alert(followup.alert_id)
            if alert is None:
                summary["orphans"] += 1
                continue
            if not apply:
                continue
            record = await lifecycle_service.create_signal(
                signal=_signal_from_alert(alert),
                alert_id=alert.id,
                created_at=alert.alert_sent_at,
                source_type="historical_followup_backfill",
            )
            await lifecycle_service.mark_signal_untrackable(
                record,
                observed_at=followup.observed_at,
                reason="historical_followup_incomplete",
                details={"stage": followup.stage, "backfill": True},
            )
            summary["backfilled_incomplete"] += 1
    finally:
        await repository.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing Results lifecycle rows without inventing outcomes.")
    parser.add_argument("--apply", action="store_true", help="write incomplete lifecycle rows; default is read-only dry run")
    parser.add_argument("--dry-run", action="store_true", help="explicitly keep the command read-only")
    parser.add_argument("--limit", type=int, default=500, help="maximum persisted follow-up rows to inspect")
    arguments = parser.parse_args()
    if arguments.apply and arguments.dry_run:
        parser.error("use either --apply or --dry-run")
    result = asyncio.run(_run(apply=bool(arguments.apply), limit=max(arguments.limit, 1)))
    mode = "applied" if arguments.apply else "dry-run"
    print(f"Results lifecycle backfill ({mode}): {result}")


if __name__ == "__main__":
    main()
