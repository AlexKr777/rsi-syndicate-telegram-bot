# Strategy Research Lab

`strategy_research_lab/` is a fully isolated research and backtesting module for comparing multiple strategies on the existing historical Binance Futures candle cache.

It does not modify the main bot, does not import itself into the production runtime, and reads data only in read-only mode from:

- `../test2/data/futures_research_cache.sqlite`

## Included strategies

1. `double_top_short`
2. `double_bottom_long`
3. `breakdown_short`
4. `oversold_reversal_long`
5. `trend_pullback_long`

## What the module does

- loads 15m historical futures candles in read-only mode
- locally recalculates indicators and analytical buckets
- generates signals for 5 strategies independently
- runs multiple TP/SL scenario types through one execution engine
- calculates PnL in dollars and percent
- builds summary exports and a local Streamlit dashboard

## Isolation guarantees

- nothing in the main bot runtime imports this module
- no production files are edited
- no storage schemas are changed
- no write operations are sent to the source SQLite database
- launches only happen manually through the `.bat` files in this folder

## Install dependencies

Recommended:

```powershell
cd strategy_research_lab
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

The launchers also try fallbacks if `.venv` is missing, but the clean setup is a local `.venv` in this folder.

## Run backtests

```powershell
.\run_backtests.bat
```

This generates outputs in:

- `output/exports/`
- `output/reports/`
- `output/charts/`

## Run dashboard

```powershell
.\run_dashboard.bat
```

The dashboard opens in the browser automatically and reads only exported CSV files plus the candle cache in read-only mode for the trade viewer.

## Configuration

Main settings live in `config.yaml`:

- `data_source`
- `money_model`
- `execution`
- `filters`
- `scenarios`
- `dashboard`
- `export`
- `strategies.*`

## TP/SL scenario types

The module supports:

- fixed `%` stop / `%` take
- ATR-based stop with `R`-multiple take
- structural stop plus `R`-multiple take
- structural stop plus measured-move target where the strategy provides it

## Ambiguous candle handling

If both TP and SL are touched inside the same 15m candle:

- `pessimistic`: count as `STOP`
- `optimistic`: count as `TAKE`
- `skip_ambiguous`: mark `AMBIGUOUS`

Default is `pessimistic`.

## OPEN and AMBIGUOUS

- `OPEN`: the trade never reached TP or SL in the available history window, so it stays unresolved
- `AMBIGUOUS`: both TP and SL were touched in the same candle and the selected ambiguous policy says to skip it

Both remain visible in reports. They are not converted into fake time exits.

## Money model

By default:

- starting capital = `100000`
- fixed stake per trade = `100`
- leverage = `1`
- fees = `0`
- slippage = `0`

The dashboard recalculates balance and PnL from the filtered trade set using the configured fixed stake model.

## Limitations

- data source is 15m OHLCV only, so intra-candle order between TP and SL is unknown
- no funding, open interest, order book, liquidation, or trade-tape data is used
- unresolved `OPEN` trades contribute `0` realized PnL until they are closed
- current module uses historical candles already cached by the isolated `test2` workflow

## What was intentionally not touched

- main bot runtime
- trading execution
- Telegram bot logic
- existing DB schemas
- existing production commands
- existing historical-data pipelines
