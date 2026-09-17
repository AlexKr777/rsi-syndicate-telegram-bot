# Double Top Short Backtesting

Autonomous module for backtesting a SHORT strategy on the double top pattern.

This folder is fully isolated from the main bot:
- it is not imported by the main runtime
- it does not change the bot's trading logic
- it reads market data only from the existing local candle cache in `test2/data/futures_research_cache.sqlite`
- SQLite access is read-only

## What this module does

- loads 15m Binance Futures candles from the local project cache
- rebuilds indicators on top of candles:
  - RSI
  - ATR / ATR %
  - EMA20 / EMA50
  - avg volume 20
  - volume ratio
  - rolling 24h quote volume
  - candle body / wick metrics
  - bot-like score
- detects double top patterns
- opens SHORT only after confirmed neckline breakdown
- backtests multiple TP / SL scenarios
- marks unresolved trades as `OPEN`
- handles `TP and SL inside the same candle` according to config
- exports trades and aggregated reports
- launches a local Streamlit dashboard

## Source of data

Primary source:
- `../test2/data/futures_research_cache.sqlite`

Tables read:
- `symbol_catalog`
- `futures_klines`

The module opens SQLite in `mode=ro`, so it cannot write back into the existing candle cache.

## Default TP / SL scenarios

- `SL 2% / TP 5%`
- `SL 2% / TP 10%`
- `SL 5% / TP 5%`
- `SL 5% / TP 10%`

## Double top logic

Default structural rules:
- local pivot highs and lows
- two peaks must be close to each other
- there must be a valley between peaks
- neckline = valley low
- entry = close of the candle that confirms breakout below the neckline

Main config knobs:
- `pivot_lookback_left`
- `pivot_lookback_right`
- `max_peak_diff_pct`
- `max_peak_diff_atr_multiple`
- `min_bars_between_peaks`
- `max_bars_between_peaks`
- `min_valley_depth_pct`
- `max_breakout_bars_after_second_peak`
- `breakout_confirmation_mode`

## OPEN / AMBIGUOUS meaning

- `OPEN`
  - after entry, neither TP nor SL was reached in the remaining available historical candles
  - there is no artificial time exit

- `AMBIGUOUS`
  - TP and SL were both touched inside the same 15m candle
  - exact order is unknown from OHLCV only

Ambiguous policy is controlled by config:
- `pessimistic`
- `optimistic`
- `skip_ambiguous`

Default: `pessimistic`

## Installation

Recommended isolated setup inside this folder:

```powershell
cd backtesting_double_top
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run backtest

Double-click:
- `run_backtest.bat`

Or terminal:

```powershell
cd backtesting_double_top
.venv\Scripts\python.exe -m app.main --config config.yaml
```

## Run dashboard

Double-click:
- `run_dashboard.bat`

Or terminal:

```powershell
cd backtesting_double_top
.venv\Scripts\streamlit.exe run app/dashboard.py
```

## Output structure

- `output/reports/`
  - `summary.md`
  - `run_metadata.json`
- `output/exports/`
  - `patterns.csv`
  - `trades.csv`
  - `scenario_summary.csv`
  - `symbol_summary.csv`
  - `month_summary.csv`
  - `week_summary.csv`
  - bucket summaries
- `output/charts/`
  - reserved for future static exports

## Config sections

- `data_source`
- `pattern_detection`
- `filters`
- `strategy`
- `dashboard`
- `export`

## Limitations

- data is 15m OHLCV, not tick data
- exact order of TP / SL inside the same candle is unknown
- indicators are rebuilt locally on the candle cache, not pulled from the production bot runtime
- the dashboard depends on previously exported CSV files from the backtest run

## What this module does not touch

- main bot runtime
- Telegram delivery
- existing prod configs
- trading execution
- scheduler / scanners / service startup
- existing project databases and schemas
