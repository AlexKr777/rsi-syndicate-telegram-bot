# RSI Analytics Test Module

This folder contains a fully isolated, read-only analytics tool for studying historical RSI signals already stored in the local SQLite database.

It does **not** start the bot, Telegram clients, schedulers, scanners, or any background runtime. It only reads existing data from `data/rsi_alerts.db` and writes reports into `test/output/`.

## What It Analyzes

- Only RSI alerts: `alerts.strategy_key = 'rsi'`
- Raw signal history from:
  - `alerts`
  - `followup_stage_results`
  - `followup_results`
- Follow-up coverage diagnostics:
  - available
  - pending
  - missing overdue
- Performance slices such as:
  - oversold vs overbought
  - 2h / 4h / 8h stages
  - RSI buckets
  - quote volume buckets
  - volume ratio buckets
  - score buckets
  - strong outcomes with `5%+` favorable move
  - combined filters such as `liquidity + RSI`, `liquidity + score`, and `50M+ + score 90+ + RSI`
  - sent-alert / sent-follow-up outcome stats for `@dordo_dordo` if delivery history exists
  - personal delivery windows for `@dordo_dordo` (`last 30d`, `last 90d`, `all time`)
  - personal proxy path stats for `@dordo_dordo`:
    - touched `+5%`
    - went `-5%` against the idea
    - both happened inside the follow-up window
  - available metadata-driven market context features
  - best historical setup combinations

## How To Run

Double-click:

- `test/run_rsi_analytics.bat`

The launcher tries to use:

1. project root `.venv`
2. local `test\.venv`
3. system `python`

By default the `.bat` launcher also tries to send the finished `report.html` to `@dordo_dordo` through the premium bot token from the project environment / `.env`.

If `pandas` is missing, install:

```powershell
pip install -r test\requirements.txt
```

## Generated Files

After a successful run, results are written into `test/output/`:

- `report.md`
- `report.html`
- `overall_stats.csv`
- `validation_checks.csv`
- `stage_stats.csv`
- `best_setups.csv`
- `rsi_buckets.csv`
- `volume_buckets.csv`
- `score_buckets.csv`
- `missing_followups.csv`
- `big_moves_overview.csv`
- `big_moves_by_direction.csv`
- `big_moves_by_stage.csv`
- `dordo_sent_alert_big_moves.csv`
- `dordo_sent_followup_big_moves.csv`
- `liquidity_rsi_combos.csv`
- `score_liquidity_combos.csv`
- `ultra_liquid_score90_rsi.csv`
- `dordo_sent_alert_outcomes.csv`
- `dordo_recent_windows.csv`
- `dordo_rsi_buckets.csv`
- `dordo_score_buckets.csv`
- `dordo_sent_alert_combos.csv`
- `dordo_sent_alert_details.csv`

## Safety Guarantees

- SQLite is opened in **read-only** mode via `mode=ro`
- `PRAGMA query_only = 1` is enabled
- No schema changes
- No `INSERT`, `UPDATE`, `DELETE`
- No imports from the bot entrypoint or runtime services
- No side-effect modules are used
- Telegram delivery is triggered only after a fully successful report build
- Telegram delivery uses the premium bot token (`TELEGRAM_BOT_TOKEN`) and the resolved Telegram user id for `@dordo_dordo`

## Method Notes

- Stage analytics uses raw `followup_stage_results`
- Bucket and metadata studies use the **latest available follow-up per alert** to avoid over-counting one alert across multiple stages
- Missing-overdue logic uses configured stage durations plus a small grace window
- Delivery-history analytics uses `delivered_bot_signals` in read-only mode
- `@dordo_dordo` delivery stats count only rows with `metadata.sent = true`
- The report now includes an automatic `PASS / WARN / FAIL` validation block that cross-checks headline numbers against raw SQLite slices
- Personal `+5% / -5%` path stats are **proxy analytics**, not literal stop/take execution logs
- Without a dedicated candle database, the tool cannot know which happened first inside the move if both `+5%` and `-5%` were touched
- If a field is not present in stored history, the tool reports it as unavailable instead of inventing it

## Known Limitations

- Historical richness depends on what was actually stored in `alerts.metadata_json` and `followup_* .metadata_json`
- Some newer metadata fields may only exist in newer rows, so coverage can be partial
- Requested indicators such as EMA alignment or distance from EMA20 are only analyzed if they truly exist in historical rows
